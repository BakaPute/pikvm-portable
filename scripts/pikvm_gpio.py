"""GPIO18 only: non-exclusive, read-only BCM2837 level sampling.

Never request a gpiochip line, configure a pin, or fall back to /dev/mem.
Unrecognised hardware/driver keeps the existing pinctrl reader.
"""
import mmap
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

VALIDATION = Path('/run/pikvm-oled/gpio18-validation.json')


def boot_id():
    value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value):
        raise Unavailable('Current boot identity is not confirmed')
    return value


def read_validation(platform, path=None):
    path = path or VALIDATION
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_size > 4096 or
            (hasattr(os,'geteuid') and (info.st_uid != 0 or info.st_mode & 0o077))):
        raise Unavailable('GPIO18 validation file is not private and root-owned')
    record = json.loads(path.read_text())
    try:
        valid = (record.get('schema') == 1 and record.get('config') == 'ip --' and
                 record.get('platform') == platform and record.get('boot_id') == boot_id() and
                 0 <= time.monotonic()-record['at'] <= 86400 and
                 record.get('low_pairs',0) >= 2 and record.get('high_pairs',0) >= 2 and
                 record.get('cycles',0) >= 2 and record.get('valid') is True)
    except (KeyError,TypeError,AttributeError):
        valid = False
    if not valid:
        raise Unavailable('GPIO18 ip -- needs a successful LOW/HIGH validation on this boot/platform')
    return record


class Unavailable(RuntimeError):
    pass


def pinctrl_state():
    result = subprocess.run(['pinctrl', 'get', '18'], capture_output=True,
                            text=True, timeout=.3)
    if result.returncode:
        raise Unavailable('pinctrl get 18 failed')
    match = re.fullmatch(r'\s*18:\s+ip\s+(pd|--)\s*\|\s*(hi|lo)\s*(?://[^\r\n]*)?\s*', result.stdout)
    if not match:
        raise Unavailable('GPIO18 configuration is not a recognised input profile')
    return {'config':'ip '+match[1], 'level':match[2] == 'hi'}


def pinctrl_sample():
    state = pinctrl_state()
    if state['config'] == 'ip --':
        validate_board()  # This exact board/profile was physically verified by the user.
    return state['level']


def state_of(sample):
    value = sample()
    # Boolean sources remain useful for injected test fixtures; production uses pinctrl_state.
    if value is True or value is False:
        return {'config':'ip pd','level':value}
    if not isinstance(value,dict) or value.get('config') not in ('ip pd','ip --') or type(value.get('level')) is not bool:
        raise Unavailable('Unrecognised GPIO18 sample')
    return value


def compare_pair(reader, sample):
    before = reader.read()
    state = state_of(sample)
    after = reader.read()
    if before != after:
        return state, False  # An edge straddled the read; it is not validation evidence.
    if before is not state['level']:
        raise Unavailable('GPIO18 pinctrl/MMIO levels diverge')
    return state, True


def validate_board(compatible=Path('/proc/device-tree/compatible')):
    board = compatible.read_bytes().split(b'\0')
    if b'raspberrypi,model-zero-2-w' not in board or b'brcm,bcm2837' not in board:
        raise Unavailable('Only Raspberry Pi Zero 2 W / BCM2837 is supported')


def dt_cells(path):
    with path.open('rb') as file:
        raw = file.read(4097)
    if not raw or len(raw) > 4096 or len(raw) % 4:
        raise Unavailable('Invalid DT cells: '+str(path))
    return [int.from_bytes(raw[i:i+4],'big') for i in range(0,len(raw),4)]


def cell_count(path):
    values = dt_cells(path)
    if len(values) != 1 or values[0] not in (1,2):
        raise Unavailable('Unsupported DT cell count: '+str(path))
    return values[0]


def cell_number(cells):
    value = 0
    for cell in cells:value = (value << 32) | cell
    return value


def dt_region(node, dtroot):
    """Translate a single direct soc child; never guess cell widths or addresses."""
    soc = dtroot/'soc'
    if node.parent != soc or b'simple-bus' not in (soc/'compatible').read_bytes().split(b'\0'):
        raise Unavailable('Unsupported DT bus topology: '+str(node))
    for entry in (soc,node):
        status = entry/'status'
        if status.exists() and status.read_bytes().rstrip(b'\0') not in (b'ok',b'okay'):
            raise Unavailable('Disabled DT node: '+str(entry))
    address = cell_count(soc/'#address-cells')
    size = cell_count(soc/'#size-cells')
    parent = cell_count(dtroot/'#address-cells')
    reg = dt_cells(node/'reg')
    if len(reg) != address+size:
        raise Unavailable('Exactly one DT register window required: '+str(node/'reg'))
    bus, length = cell_number(reg[:address]), cell_number(reg[address:])
    if length <= 0 or bus+length > 1 << (32*address):
        raise Unavailable('Invalid DT register extent: '+str(node/'reg'))
    ranges = dt_cells(soc/'ranges')
    stride = address+parent+size
    if len(ranges) % stride:
        raise Unavailable('Malformed DT soc/ranges')
    hits = []
    for i in range(0,len(ranges),stride):
        row = ranges[i:i+stride]
        child = cell_number(row[:address]);cpu = cell_number(row[address:address+parent])
        span = cell_number(row[address+parent:])
        if span <= 0 or child+span > 1 << (32*address) or cpu+span > 1 << (32*parent):
            raise Unavailable('Invalid DT soc/ranges extent')
        if child < bus+length and bus < child+span:
            if not (child <= bus and bus+length <= child+span):
                raise Unavailable('DT soc/ranges partially overlaps the register window')
            hits.append({'child':child,'cpu':cpu,'range_size':span,'physical':cpu+bus-child})
    if len(hits) != 1:
        raise Unavailable('DT soc/ranges must translate the complete window exactly once')
    return {'bus':bus,**hits[0],'size':length}


def validate_binding(entry, driver_dir, sysroot, dtroot):
    platform = entry.resolve(strict=True)
    expected = sysroot/'devices/platform/soc/3f200000.gpiomem'
    if platform != expected:
        raise Unavailable('Unexpected platform link target: '+str(platform))
    if (platform/'driver').resolve(strict=True) != driver_dir:
        raise Unavailable('Platform driver backlink is inconsistent: '+str(platform/'driver'))
    node = (platform/'of_node').resolve(strict=True)
    if not node.is_relative_to(dtroot) or (node/'compatible').read_bytes().split(b'\0') != [b'brcm,bcm2835-gpiomem',b'']:
        raise Unavailable('Platform of_node is not the recognised legacy gpiomem binding')
    gpio = dtroot/'soc/gpio@7e200000'
    if (gpio/'compatible').read_bytes().split(b'\0') != [b'brcm,bcm2835-gpio',b'']:
        raise Unavailable('GPIO controller compatible is not BCM2835')
    control = dt_region(gpio,dtroot)
    memory = dt_region(node,dtroot)
    if (control['bus'],control['physical'],control['size']) != (0x7E200000,0x3F200000,0xB4):
        raise Unavailable('GPIO DT reg/ranges do not describe BCM2837 GPIO at 0x3f200000')
    if memory['bus'] != control['bus'] or memory['physical'] != control['physical'] or memory['size'] not in (0xB4,0x1000):
        raise Unavailable('gpiomem DT reg/ranges do not map the validated GPIO registers')
    resource = platform/'resource'
    try:
        rows = resource.read_text().splitlines()
    except FileNotFoundError:
        if resource.is_symlink():raise Unavailable('Dangling resource link')
        rows = None
    if rows is not None:
        if len(rows) != 1:
            raise Unavailable('Ambiguous sysfs resource window')
        try:start,end,flags = (int(value,16) for value in rows[0].split())
        except ValueError:raise Unavailable('Malformed sysfs resource window') from None
        if start != memory['physical'] or end != start+memory['size']-1 or not flags & 0x200:
            raise Unavailable('sysfs resource contradicts DT reg/ranges')
    return {'platform':str(platform),'driver':str(driver_dir),'of_node':str(node),
            'basis':'device-tree+sysfs-links','resource_present':rows is not None,
            'gpio_region':control,'gpiomem_region':memory}


def validate_platform(compatible=Path('/proc/device-tree/compatible'),
                      sysroot=Path('/sys'), device=Path('/dev/gpiomem')):
    validate_board(compatible)
    dtroot = compatible.parent.resolve(strict=True)
    sysroot = sysroot.resolve(strict=True)
    info = device.lstat()
    if not stat.S_ISCHR(info.st_mode):
        raise Unavailable('/dev/gpiomem must be an ordinary character device')
    devno = f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'
    classes = []
    for name in ('gpiomem','bcm2835-gpiomem'):
        try:directory = (sysroot/'class'/name/'gpiomem').resolve(strict=True)
        except FileNotFoundError:continue
        if not directory.is_relative_to(sysroot/'devices'):
            raise Unavailable('gpiomem class target is outside sysfs devices')
        if (directory/'dev').read_text().strip() != devno:
            raise Unavailable('gpiomem device number contradicts sysfs class')
        classes.append(directory)
    if len(classes) != 1 or (sysroot/'dev/char'/devno).resolve(strict=True) != classes[0]:
        raise Unavailable('gpiomem class and /sys/dev/char identity are not unique and consistent')
    uevent = classes[0]/'uevent'
    if uevent.exists():
        values = dict(line.split('=',1) for line in uevent.read_text().splitlines() if '=' in line)
        if values.get('DEVNAME') != 'gpiomem' or values.get('MAJOR') != devno.split(':')[0] or values.get('MINOR') != devno.split(':')[1]:
            raise Unavailable('gpiomem uevent identity is inconsistent')
    matches = []
    for driver in ('rpi-gpiomem','gpiomem-bcm2835'):
        directory = sysroot/'bus/platform/drivers'/driver
        for entry in sorted(directory.glob('*.gpiomem')):
            matches.append(validate_binding(entry,directory,sysroot,dtroot))
    if len(matches) != 1:
        raise Unavailable('A unique BCM2837 GPIO register window was not confirmed')
    return {'device':str(device),'devno':devno,'class_device':str(classes[0]),**matches[0]}


class ReadOnlyLevel:
    """One open/map; only reads GPFSEL1 (GPIO18 mode) and GPLEV0 bit18."""
    def __init__(self, device=Path('/dev/gpiomem')):
        self.fd = None
        self.mapping = None
        self.words = None
        self.failure = None
        self.check_at = 0
        self.check_sample = None
        self.expected_config = None
        if sys.byteorder != 'little':
            raise Unavailable('Only little-endian BCM2837 userspace is supported')
        self.platform = validate_platform(device=device)
        try:
            self.fd = os.open(device, os.O_RDONLY | getattr(os,'O_CLOEXEC',0) |
                              getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_SYNC',0))
            info = os.fstat(self.fd)
            if not stat.S_ISCHR(info.st_mode) or f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}' != self.platform['devno']:
                raise Unavailable('gpiomem identity changed while opening')
            self.mapping = mmap.mmap(self.fd,4096,access=mmap.ACCESS_READ,offset=0)
            self.words = memoryview(self.mapping).cast('I')
            self.read()
        except BaseException:
            self.close()
            raise

    def read(self):
        if self.failure:
            raise Unavailable(self.failure)
        if self.check_sample is not None and time.monotonic()-self.check_at > 2:
            raise Unavailable('GPIO18 periodic verification is stale')
        if self.mapping is None:
            raise Unavailable('GPIO mapping closed')
        if (self.words[0x04 // 4] >> 24) & 7:
            raise Unavailable('GPIO18 is no longer an input')
        return bool(self.words[0x34 // 4] & (1 << 18))

    def configure_check(self, sample, config):
        self.check_sample, self.expected_config = sample, config
        self.check_at = time.monotonic()

    def check(self):
        # Invoked by the EXISTING heartbeat thread, never the 40ms sampling path.
        if self.check_sample and not self.failure and time.monotonic()-self.check_at >= 1:
            try:
                state, stable = compare_pair(self,self.check_sample)
                if state['config'] != self.expected_config:
                    raise Unavailable('GPIO18 configuration changed after validation')
                self.check_at = time.monotonic()
            except (OSError,ValueError,Unavailable,subprocess.SubprocessError) as error:
                self.failure = str(error)[:160]
        return {'config':self.expected_config,'failure':self.failure}

    def close(self):
        if self.words is not None:
            self.words.release();self.words = None
        if self.mapping is not None:
            self.mapping.close();self.mapping = None
        if self.fd is not None:
            os.close(self.fd);self.fd = None


def select_reader(fallback, factory=ReadOnlyLevel, sample=pinctrl_state):
    reader = None
    try:
        before = state_of(sample)
        reader = factory()
        mapped = reader.read()
        after = state_of(sample)
        if before != after or before['level'] is not mapped:
            raise Unavailable('GPIO18 changed during cross-check; retry with button released')
        if before['config'] == 'ip --':
            read_validation(reader.platform)
        reader.configure_check(sample,before['config'])
        return reader.read, reader, {'backend':'gpiomem-readonly','interval_ms':40,'config':before['config']}
    except (OSError, ValueError, Unavailable, subprocess.SubprocessError) as error:
        if reader is not None:
            reader.close()
        return fallback, None, {'backend':'pinctrl','interval_ms':40,'reason':str(error)[:200]}


def compare_controlled(seconds=30, save=False, factory=ReadOnlyLevel, sample=pinctrl_state):
    if save:
        # A failed re-validation must not leave an older success authorising activation.
        VALIDATION.unlink(missing_ok=True)
    reader = factory()
    config = None; low = high = cycles = 0; phase = 0
    end = time.monotonic()+seconds
    try:
        while time.monotonic() < end:
            state, stable = compare_pair(reader,sample)
            if config is None:config = state['config']
            if state['config'] != config:
                raise Unavailable('GPIO18 configuration changed during comparison')
            if stable:
                if state['level']:
                    high += 1
                    if phase == 1:phase = 2
                else:
                    low += 1
                    if phase == 2:cycles += 1
                    phase = 1
            time.sleep(.05)
        record = {'schema':1,'config':config,'platform':reader.platform,'boot_id':boot_id(),
                  'at':time.monotonic(),'low_pairs':low,'high_pairs':high,'cycles':cycles,
                  'valid':low >= 2 and high >= 2 and cycles >= 2}
        if not record['valid']:
            raise Unavailable('Two complete LOW/HIGH/LOW presses and stable pairs in both states are required')
        if save:
            from pikvm_oled import private_directory
            private_directory(VALIDATION.parent)
            temporary = VALIDATION.with_name('.gpio18-validation-'+str(os.getpid()))
            fd = os.open(temporary,os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'w') as file:json.dump(record,file)
            os.replace(temporary,VALIDATION)
        return record
    finally:
        reader.close()


def inspect_hardware():
    """Bounded, passive evidence retained even when fast-reader selection fails."""
    dtroot = Path('/proc/device-tree')
    properties = {}
    def property_info(path):
        try:
            with path.open('rb') as file:raw = file.read(4097)
            return {'hex':raw[:4096].hex(),'truncated':len(raw)>4096}
        except OSError as error:return {'error':str(error)}
    for name in ('compatible','#address-cells','soc/compatible','soc/#address-cells',
                 'soc/#size-cells','soc/ranges','soc/gpio@7e200000/compatible','soc/gpio@7e200000/reg'):
        properties[name] = property_info(dtroot/name)
    bindings = []
    for driver in ('rpi-gpiomem','gpiomem-bcm2835'):
        for entry in sorted((Path('/sys/bus/platform/drivers')/driver).glob('*.gpiomem')):
            record = {'entry':str(entry)}
            try:
                platform = entry.resolve(strict=True)
                record.update(platform=str(platform),driver=str((platform/'driver').resolve(strict=True)))
                node = (platform/'of_node').resolve(strict=True)
                record['of_node'] = str(node)
                if node.is_relative_to(dtroot.resolve(strict=True)):
                    record['properties'] = {name:property_info(node/name) for name in ('compatible','reg','status')}
                record['resource_present'] = (platform/'resource').exists()
            except OSError as error:record['error'] = str(error)
            bindings.append(record)
    try:validation = validate_platform()
    except (OSError,ValueError,Unavailable) as error:validation = {'error':str(error)}
    return {'device_tree':properties,'bindings':bindings,'platform_validation':validation}


def diagnose():
    """Passive feature probe; no line requests or service changes."""
    import importlib.metadata
    import platform
    try:version = importlib.metadata.version('gpiod')
    except importlib.metadata.PackageNotFoundError:version = None
    read, resource, result = select_reader(lambda:None)
    try:
        return {**result,'kernel':platform.release(),'gpiod_python_version':version,
                'sample':read() if resource else None,
                'validation':resource.platform if resource else None,
                'hardware':inspect_hardware(),
                'event_backend_enabled':False,
                'note':'No GPIO request, configuration, write or module loading performed.'}
    finally:
        if resource:resource.close()


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--diagnose',action='store_true')
    group.add_argument('--compare',action='store_true')
    parser.add_argument('--seconds',type=int,default=30)
    parser.add_argument('--save-validation',action='store_true')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120 or (args.save_validation and not args.compare):parser.error('comparison: 5..120 seconds; save requires --compare')
    if args.compare:print('Deux appuis courts contrôlés, avec relâchement entre eux. Ne pas maintenir le bouton.',file=sys.stderr)
    try:print(json.dumps(compare_controlled(args.seconds,args.save_validation) if args.compare else diagnose(),indent=2))
    except (OSError,ValueError,Unavailable,subprocess.SubprocessError) as error:raise SystemExit('GPIO18 validation failed: '+str(error))
