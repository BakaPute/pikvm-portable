#!/usr/bin/env python3
"""Build a deterministic, allowlisted Portable OS candidate. No device access."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parent.parent
RELEASE = 'pikvm-portable-os-0.2.0-rc.11'
FILES = ('docs/portable-os-rc11.md', 'scripts/pikvm-portable-rc11-diagnose.sh', 'scripts/pikvm_config.py', 'scripts/pikvm_settings.py', 'scripts/pikvm_activity.py', 'docs/portable-os-rc10.2.md', 'scripts/pikvm_preflight_probe.py', 'scripts/pikvm-portable-drive-check.sh',
         'docs/performance/rc10.1-startup-local.json',
         'docs/portable-os-rc10.1.md', 'scripts/pikvm-hotspot', 'docs/performance/rc10-local.json', 'scripts/pikvm_transfer.py', 'scripts/pikvm-usb-transfer',
         'scripts/pikvm-python-integrity.sh',
         'scripts/pikvm-image-folders', 'scripts/wifi-wizard-api',
         'scripts/pikvm-share-api',
         'scripts/pikvm-portable-report', 'scripts/pikvm-storage-baselines.json',
         'docs/portable-os-rc10-audit.md',
         'web/share/js/usb-transfer.js', 'web/share/js/drive-folders.js', 'web/share/js/power-control.js',
         'web/extras/image-manager/app.js', 'web/extras/image-manager/index.html',
         'web/extras/wifi-wizard/index.html',
         'kvmd-extras/wifi-wizard/nginx.ctx-server.conf',
         'kvmd-extras/wifi-wizard/nginx.ctx-http.conf',
         'kvmd-extras/image-manager/nginx.ctx-http.conf',
         'kvmd-extras/image-manager/nginx.ctx-server.conf', 'install-portable-os.sh', 'systemd/pikvm-portable-api.service',
         'scripts/pikvm-portable-api', 'scripts/pikvm-portable-install',
         'scripts/pikvm-share-install', 'scripts/pikvm-portable-preflight.sh',
         'scripts/pikvm_preflight.py', 'docs/portable-os-rc6-preflight.md',
         'scripts/pikvm-portable-perf', 'docs/portable-os-rc7.md',
         'scripts/pikvm_gpio.py', 'docs/portable-os-rc8.md',
         'docs/portable-os-rc8-gpio-profile.md',
         'docs/portable-os-rc8-sysfs.md',
         'docs/portable-os-rc9.md',
         'docs/portable-os-rc9.1.md',
         'docs/performance/rc6-local.json', 'docs/performance/rc7-local.json',
         'scripts/pikvm-python-logging-repair.sh', 'scripts/pikvm-portable-diagnose.sh',
         'scripts/pikvm-share-windows-diagnose.ps1', 'scripts/pikvm-portable-package.py',
         'scripts/pikvm_oled.py', 'scripts/pikvm-oled-custom', 'scripts/pikvm-button-menu',
         'scripts/pikvm-oled-baselines.json', 'docs/portable-os-oled.md', 'docs/portable-os-rc4.md', 'docs/portable-os-rc5.md', 'docs/portable-os-rc6.md',
         'docs/portable-os-rc1.md', 'docs/portable-os-rc2.md', 'docs/portable-os.md')


def payload():
    result = {}
    for relative in FILES:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('Release source missing or symbolic: ' + relative)
        result[relative] = path.read_bytes()
    for relative in ('web/legacy', 'web/extras/portable-os', 'kvmd-extras/portable-os'):
        for path in sorted((ROOT / relative).rglob('*')):
            parts = path.relative_to(ROOT / relative).parts
            if (path.is_file() and not path.is_symlink() and
                    path.suffix in {'.js', '.css', '.svg', '.html', '.json', '.conf', '.yaml'} and
                    not any(part.startswith('.') or part == 'node_modules' for part in parts)):
                result[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    result['MANIFEST.sha256'] = ''.join(hashlib.sha256(content).hexdigest() + '  ' + name + '\n'
                                      for name, content in sorted(result.items())).encode()
    return result


def build(output):
    contents = payload()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('wb') as file, gzip.GzipFile(filename='', fileobj=file, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, content in sorted(contents.items()):
                info = tarfile.TarInfo(RELEASE + '/' + name)
                info.size, info.mtime, info.uid, info.gid = len(content), 0, 0, 0
                info.mode = 0o755 if name.startswith('scripts/') or name.endswith('.sh') else 0o644
                archive.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + '.sha256').write_text(digest + '  ' + output.name + '\n',
                                                       encoding='utf-8', newline='\n')
    return digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'private' / (RELEASE + '.tar.gz'))
    options = parser.parse_args()
    print(str(options.output) + '\nSHA256 ' + build(options.output))
