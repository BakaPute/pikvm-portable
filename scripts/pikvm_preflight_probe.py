"""Isolated imports/configuration check; never starts KVMD or writes hardware."""
import sys
import time

EXPECTED_PYTHON = (3, 14, 7)
GROUPS = {
    'runtime': ('copyreg', 'logging', 'asyncio', 'ssl', 'aiohttp', 'mako', 'kvmd'),
    'pillow': ('PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont'),
}


def memory_report():
    try:
        values = {}
        with open('/proc/self/status') as handle:
            for line in handle:
                key, _, value = line.partition(':')
                if key in ('VmRSS', 'VmHWM'):
                    values[key] = value.split()[0]
        return ' rss_kib=' + values.get('VmRSS', 'unknown') + ' hwm_kib=' + values.get('VmHWM', 'unknown')
    except OSError:
        return ' rss_kib=unknown hwm_kib=unknown'


def run_group(group):
    if sys.version_info[:3] != EXPECTED_PYTHON:
        raise RuntimeError('Python version incompatible: ' + str(sys.version_info[:3]))
    for name in GROUPS[group]:
        began = time.monotonic()
        print('PROBE BEGIN import=' + name, flush=True)
        module = __import__(name, fromlist=['__name__'])
        if name == 'kvmd' and module.__version__ != '4.213':
            raise RuntimeError('KVMD version incompatible')
        if name == 'logging' and not hasattr(module, 'FileHandler'):
            raise RuntimeError('logging.FileHandler absent')
        print(f'PROBE OK import={name} elapsed={time.monotonic()-began:.3f}s' + memory_report(), flush=True)
    if group == 'runtime':
        # Preserve the CLI's implicit schema/MSD-type check, without another
        # interpreter or executing otgmsd.main(). KVMD 4.213 init only reads and
        # validates configuration/plugin options; it does not start a service.
        print('PROBE BEGIN config=msd', flush=True)
        apps = __import__('kvmd.apps', fromlist=['init'])
        initialized = apps.init(cli_logging=True, load_msd=True, test_args=['--'])
        if initialized.config.kvmd.msd.type != 'otg':
            raise RuntimeError('KVMD MSD must use the otg plugin')
        print('PROBE OK config=msd' + memory_report(), flush=True)
    print('PROBE COMPLETE group=' + group, flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in GROUPS:
        raise SystemExit('Usage: pikvm_preflight_probe.py runtime|pillow')
    run_group(sys.argv[1])
