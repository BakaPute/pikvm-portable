"""Read-only compatibility gate: individual deadlines and persistent diagnostics.

Only stdlib imports; do not import logging before checking its integrity.
"""
import contextlib
import datetime
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time


class PreflightError(RuntimeError):
    pass


class Journal:
    def compatibility(self):
        compatibility(self)

    def __init__(self, parent=None):
        self.directory = Path(tempfile.mkdtemp(prefix='pikvm-portable-preflight-', dir=parent))
        self.path = self.directory / 'steps.log'
        self.serial = 0
        self.write('JOURNAL ' + str(self.path))

    def write(self, message):
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds')
        line = stamp + ' ' + message + '\n'
        with self.path.open('a', encoding='utf-8') as output:
            output.write(line)
            output.flush()
        print(line, end='', file=sys.stderr, flush=True)

    @contextlib.contextmanager
    def phase(self, name):
        began = time.monotonic()
        self.write('BEGIN ' + name)
        try:
            yield
        except BaseException as error:
            self.write(f'FAIL {name} elapsed={time.monotonic()-began:.3f}s error={error}')
            raise
        else:
            self.write(f'OK {name} elapsed={time.monotonic()-began:.3f}s')

    def cleanup(self, process):
        """Kill only the group created for this check, including lingering children."""
        if os.name == 'posix':
            self.write(f'CLEANUP TERM group={process.pid}')
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(1)
            # Always KILL the group, even if its leader exited on TERM.
            self.write(f'CLEANUP KILL group={process.pid}')
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
        else:
            # Local Windows tests only; the Pi uses isolated POSIX groups.
            self.write(f'CLEANUP Windows process tree pid={process.pid}')
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            process.wait(timeout=2)
        self.write(f'CLEANUP complete pid={process.pid}')

    def step(self, name, args, timeout):
        self.serial += 1
        prefix = self.directory / f'{self.serial:02d}-{name}'
        out, err = Path(str(prefix) + '.stdout'), Path(str(prefix) + '.stderr')
        began = time.monotonic()
        self.write(f'BEGIN {name} timeout={timeout}s command={shlex.join(map(str,args))} stdout={out} stderr={err}')
        try:
            with out.open('xb') as stdout, err.open('xb') as stderr:
                options = {'start_new_session': True} if os.name == 'posix' else {
                    'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
                process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=stdout,
                                           stderr=stderr, env={**os.environ, 'LC_ALL': 'C'}, **options)
                try:
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Record before cleanup: useful even if cleanup itself fails.
                    self.write(f'TIMEOUT {name} pid={process.pid} elapsed={time.monotonic()-began:.3f}s')
                    self.cleanup(process)
                    raise PreflightError(f'{name}: délai {timeout}s dépassé ; commande {shlex.join(map(str,args))} ; journal {self.path}') from None
                except BaseException:
                    self.cleanup(process)
                    raise
            if code:
                raise PreflightError(f'{name}: code {code} ; stderr {err} ; journal {self.path}')
            # Checks have small stdout. Never collect unlimited output in RAM.
            if out.stat().st_size > 65536:
                raise PreflightError(f'{name}: sortie excessive ; fichier conservé : {out}')
            result = out.read_text(encoding='utf-8', errors='replace')
        except BaseException as error:
            self.write(f'FAIL {name} elapsed={time.monotonic()-began:.3f}s error={error}')
            raise
        self.write(f'OK {name} elapsed={time.monotonic()-began:.3f}s')
        return result


def compatibility(journal):
    python = journal.step('package-python', ['pacman', '-Q', 'python'], 10).strip()
    kvmd = journal.step('package-kvmd', ['pacman', '-Q', 'kvmd'], 10).strip()
    with journal.phase('package-versions'):
        if python != 'python 3.14.7-1':
            raise PreflightError('Candidate targets exactly Python 3.14.7-1; manual compatibility review required.')
        if not (kvmd == 'kvmd 4.213' or kvmd.startswith('kvmd 4.213-')):
            raise PreflightError('Candidate targets KVMD 4.213.')
    target = Path('/usr/lib/python3.14/logging/__init__.py')
    mtree = Path('/var/lib/pacman/local/python-3.14.7-1/mtree')
    with journal.phase('logging-metadata'):
        if not target.is_file() or target.is_symlink() or not mtree.is_file():
            raise PreflightError('logging or package metadata unavailable.')
    expected = journal.step('logging-baseline', ['bash', '-o', 'pipefail', '-c',
        'gzip -dc "$1" | awk \'$1 == "./usr/lib/python3.14/logging/__init__.py" {for(i=2;i<=NF;i++) if($i ~ /^sha256digest=/) {sub(/^sha256digest=/,"",$i); print $i}}\'',
        'preflight-mtree', str(mtree)], 10).strip()
    actual = journal.step('logging-sha256', ['sha256sum', str(target)], 10).split()
    with journal.phase('logging-integrity'):
        if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise PreflightError('logging baseline hash unavailable.')
        if not actual or actual[0] != expected:
            raise PreflightError('logging checksum mismatch: repair before migration.')
    journal.step('python-kvmd-imports', ['/usr/bin/python3', '-I', '-B', '-c',
        'import sys,logging,asyncio,ssl,aiohttp,mako,kvmd; assert sys.version_info[:2] == (3,14); assert kvmd.__version__ == "4.213"; assert hasattr(logging,"FileHandler")'], 15)
    journal.step('drive1-read', ['kvmd-otgmsd', '-i', '1'], 20)
    journal.step('nginx-syntax', ['nginx', '-t', '-p', '/etc/kvmd/nginx', '-c',
        '/run/kvmd/nginx.conf', '-g', 'pid /run/kvmd/nginx.pid; user kvmd-nginx; error_log stderr;'], 15)
    for service in ('kvmd.service', 'kvmd-nginx.service'):
        journal.step(service, ['systemctl', 'is-active', '--quiet', service], 10)
    journal.write('COMPATIBILITY OK: Python, logging, KVMD, Drive 1 read, nginx, services')


if __name__ == '__main__':
    journal = Journal()
    try:
        compatibility(journal)
    except Exception as error:
        raise SystemExit('PRECHECK FAILED: ' + str(error))
