"""GPIO18 only: non-exclusive, read-only BCM2837 level sampling.

Never request a gpiochip line, configure a pin, or fall back to /dev/mem.
Unrecognised hardware/driver keeps the existing pinctrl reader.
"""
import mmap
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


class Unavailable(RuntimeError):
    pass


def pinctrl_sample():
    result = subprocess.run(['pinctrl', 'get', '18'], capture_output=True,
                            text=True, timeout=.3)
    if result.returncode:
        raise Unavailable('pinctrl get 18 failed')
    # Require the existing input / pull-down configuration. Never repair it here.
    match = re.search(r'^\s*18:\s+ip\s+pd\s*\|\s*(hi|lo)\b', result.stdout, re.M)
    if not match:
        raise Unavailable('GPIO18 input/pull-down configuration not confirmed')
    return match[1] == 'hi'


def validate_platform(compatible=Path('/proc/device-tree/compatible'),
                      sysroot=Path('/sys'), device=Path('/dev/gpiomem')):
    board = compatible.read_bytes().split(b'\0')
    if b'raspberrypi,model-zero-2-w' not in board or b'brcm,bcm2837' not in board:
        raise Unavailable('Only Raspberry Pi Zero 2 W / BCM2837 is supported')
    info = device.lstat()
    if not stat.S_ISCHR(info.st_mode):
        raise Unavailable('/dev/gpiomem must be an ordinary character device')
    devno = f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'
    classes = [sysroot/'class'/name/'gpiomem/dev' for name in ('gpiomem','bcm2835-gpiomem')]
    if not any(path.is_file() and path.read_text().strip() == devno for path in classes):
        raise Unavailable('gpiomem device number not confirmed by sysfs')
    matches = []
    for driver in ('rpi-gpiomem','gpiomem-bcm2835'):
        for entry in (sysroot/'bus/platform/drivers'/driver).glob('*'):
            node = entry/'of_node/compatible'
            if not node.is_file() or b'brcm,bcm2835-gpiomem' not in node.read_bytes().split(b'\0'):
                continue
            ranges = (entry/'resource').read_text().splitlines()
            if len(ranges) != 1:
                continue
            start, end, flags = (int(value,16) for value in ranges[0].split())
            if start == 0x3F200000 and end == 0x3F200FFF and flags & 0x200:
                matches.append(str(entry))
    if len(matches) != 1:
        raise Unavailable('A unique BCM2837 GPIO register window was not confirmed')
    return {'device':str(device),'devno':devno,'platform':matches[0]}


class ReadOnlyLevel:
    """One open/map; only reads GPFSEL1 (GPIO18 mode) and GPLEV0 bit18."""
    def __init__(self, device=Path('/dev/gpiomem')):
        self.fd = None
        self.mapping = None
        self.words = None
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
        if self.mapping is None:
            raise Unavailable('GPIO mapping closed')
        if (self.words[0x04 // 4] >> 24) & 7:
            raise Unavailable('GPIO18 is no longer an input')
        return bool(self.words[0x34 // 4] & (1 << 18))

    def close(self):
        if self.words is not None:
            self.words.release();self.words = None
        if self.mapping is not None:
            self.mapping.close();self.mapping = None
        if self.fd is not None:
            os.close(self.fd);self.fd = None


def select_reader(fallback, factory=ReadOnlyLevel, sample=pinctrl_sample):
    reader = None
    try:
        before = sample()
        reader = factory()
        mapped = reader.read()
        after = sample()
        if before is not mapped or after is not mapped:
            raise Unavailable('GPIO18 changed during cross-check; retry with button released')
        return reader.read, reader, {'backend':'gpiomem-readonly','interval_ms':40}
    except (OSError, ValueError, Unavailable, subprocess.SubprocessError) as error:
        if reader is not None:
            reader.close()
        return fallback, None, {'backend':'pinctrl','interval_ms':40,'reason':str(error)[:200]}


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
                'event_backend_enabled':False,
                'note':'No GPIO request, configuration, write or module loading performed.'}
    finally:
        if resource:resource.close()


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnose',action='store_true',required=True)
    parser.parse_args()
    print(json.dumps(diagnose(),indent=2))
