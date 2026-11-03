"""Read-only compatibility gate: individual deadlines and persistent diagnostics.

Only stdlib imports; do not import logging before checking its integrity.
"""
import contextlib
import datetime
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time


PROC = Path('/proc')
CGROUP = Path('/sys/fs/cgroup')
IMPORT_GRACE = 30  # Once only, after measured contention + observable progress.
MIN_IMPORT_HEADROOM_KIB = 24 * 1024
IMPORT_STEPS = {'python-kvmd-imports', 'pillow-imports'}


class PreflightError(RuntimeError):
    def __init__(self, message, category='CHECK_FAILED'):
        super().__init__(category + ': ' + message)
        self.category = category


def small_text(path, limit=65536):
    with path.open('rb') as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Diagnostic file too large: ' + str(path))
    return data.decode('utf-8', errors='replace')


def process_snapshot(pid):
    result = {'pid': pid}
    try:
        for line in small_text(PROC / str(pid) / 'status').splitlines():
            key, _, value = line.partition(':')
            if key in ('State', 'VmRSS', 'VmHWM', 'VmSwap', 'Threads'):
                result[key] = value.strip()
        fields = small_text(PROC / str(pid) / 'stat').rsplit(')', 1)[1].split()
        result.update(cpu_ticks=int(fields[11])+int(fields[12]), major_faults=int(fields[9]))
        result['wchan'] = small_text(PROC / str(pid) / 'wchan', 4096).strip()
    except (OSError, ValueError, IndexError) as error:
        result['unavailable'] = type(error).__name__
    return result


def resources(pid=None):
    """Small passive /proc reads only. Never ps/systemctl, drop_caches or swap."""
    result = {'time': time.time(), 'memory_kib': {}, 'psi': {}, 'vmstat': {}, 'cgroups': []}
    try:
        for line in small_text(PROC / 'meminfo').splitlines():
            key, _, raw = line.partition(':')
            values = raw.split()
            if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree', 'Cached', 'SReclaimable'):
                if len(values) == 2 and values[0].isdigit() and values[1] == 'kB':
                    result['memory_kib'][key] = int(values[0])
    except (OSError, ValueError) as error:
        result['memory_unavailable'] = type(error).__name__
    for kind in ('cpu', 'memory', 'io'):
        try:
            values = {}
            for line in small_text(PROC / 'pressure' / kind, 4096).splitlines():
                parts = line.split()
                fields = dict(part.split('=', 1) for part in parts[1:])
                values[parts[0]] = {'total': int(fields['total']), 'avg10': float(fields['avg10'])}
            result['psi'][kind] = values
        except (OSError, ValueError, KeyError, IndexError):
            result['psi'][kind] = None
    try:
        for line in small_text(PROC / 'vmstat').splitlines():
            key, value = line.split()
            if key in ('oom_kill', 'pgmajfault', 'pswpin', 'pswpout') or key.startswith(('allocstall', 'pgscan', 'pgsteal')):
                result['vmstat'][key] = int(value)
    except (OSError, ValueError):
        result['vmstat_unavailable'] = True
    try:
        own = next(line[3:] for line in small_text(PROC / 'self/cgroup').splitlines() if line.startswith('0::'))
        relative = Path(own.lstrip('/'))
        if '..' in relative.parts:
            raise ValueError('Invalid cgroup path')
        directory = CGROUP / relative
        # Include ancestor limits; memory.max in the leaf alone is insufficient.
        while directory.is_relative_to(CGROUP):
            entry = {'path': str(directory)}
            try:
                current = int(small_text(directory / 'memory.current', 4096))
                limit = small_text(directory / 'memory.max', 4096).strip()
                entry.update(current_bytes=current, max_bytes=int(limit) if limit != 'max' else None)
                entry['headroom_kib'] = max(0, (int(limit)-current)//1024) if limit != 'max' else None
                entry['events'] = dict((k, int(v)) for k, v in
                    (line.split() for line in small_text(directory / 'memory.events', 4096).splitlines()))
            except (OSError, ValueError):
                entry['unavailable'] = True
            result['cgroups'].append(entry)
            if directory == CGROUP:
                break
            directory = directory.parent
    except (OSError, ValueError, StopIteration):
        result['cgroup_unavailable'] = True
    result['supervisor'] = process_snapshot(os.getpid())
    if pid is not None:
        result['child'] = process_snapshot(pid)
        try:
            children = small_text(PROC / str(pid) / 'task' / str(pid) / 'children', 4096).split()
            result['children'] = [process_snapshot(int(child)) for child in children[:8]]
        except (OSError, ValueError):
            result['children_unavailable'] = True
    return result


def counter_increased(before, after, key):
    return key in before and key in after and after[key] > before[key]


def oom_observed(before, after):
    if counter_increased(before.get('vmstat', {}), after.get('vmstat', {}), 'oom_kill'):
        return True
    previous = {entry['path']: entry for entry in before.get('cgroups', [])}
    return any(counter_increased(previous.get(entry['path'], {}).get('events', {}),
                                 entry.get('events', {}), 'oom_kill') for entry in after.get('cgroups', []))


def pressure_evidence(before, after):
    evidence = []
    for kind in ('memory', 'io', 'cpu'):
        old, new = before.get('psi', {}).get(kind) or {}, after.get('psi', {}).get(kind) or {}
        for scope in ('some', 'full'):
            a, b = old.get(scope, {}).get('total'), new.get(scope, {}).get('total')
            if a is not None and b is not None and b - a >= 100000:
                evidence.append(f'{kind}.{scope} stalled_us={b-a}')
    return evidence


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

    def sample(self, name, event, pid=None):
        snapshot = resources(pid)
        with (self.directory / 'resources.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps({'step': name, 'event': event, **snapshot}, separators=(',', ':')) + '\n')
        return snapshot

    def detail(self, name, process, out, err, before):
        snapshot = self.sample(name, 'timeout', process.pid)
        def tail(path):
            with path.open('rb') as handle:
                handle.seek(max(0, path.stat().st_size - 4096))
                return handle.read(4096).decode('utf-8', errors='replace')
        self.write('TIMEOUT_DETAIL ' + json.dumps({'step': name, 'child': snapshot.get('child'),
                   'children': snapshot.get('children'),
                   'memory_kib': snapshot.get('memory_kib'), 'pressure': pressure_evidence(before, snapshot),
                   'oom_observed': oom_observed(before, snapshot), 'stdout_tail': tail(out),
                   'stderr_tail': tail(err)}, ensure_ascii=True))
        return snapshot

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
        baseline = self.sample(name, 'before')
        if name in IMPORT_STEPS:
            available = baseline.get('memory_kib', {}).get('MemAvailable')
            limits = [entry['headroom_kib'] for entry in baseline.get('cgroups', [])
                      if entry.get('headroom_kib') is not None]
            if ((available is not None and available < MIN_IMPORT_HEADROOM_KIB) or
                    (limits and min(limits) < MIN_IMPORT_HEADROOM_KIB)):
                self.write(f'RESOURCE_PRESSURE {name} admission refused available_kib={available} cgroup_headroom_kib={limits}')
                self.write(f'FAIL {name} category=RESOURCE_PRESSURE before launch')
                raise PreflightError('Marge mémoire insuffisante avant imports ; aucune commande lourde lancée ; journal ' + str(self.path), 'RESOURCE_PRESSURE')
        process = None
        extended = False
        try:
            with out.open('xb') as stdout, err.open('xb') as stderr:
                options = {'start_new_session': True} if os.name == 'posix' else {
                    'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
                process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=stdout,
                                           stderr=stderr, env={**os.environ, 'LC_ALL': 'C'}, **options)
                deadline, sampled = began + timeout, began
                try:
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            self.write(f'DEADLINE {name} pid={process.pid} elapsed={time.monotonic()-began:.3f}s')
                            current = self.detail(name, process, out, err, baseline)
                            evidence = pressure_evidence(baseline, current)
                            child = current.get('child', {})
                            progress = out.stat().st_size > 0 or child.get('cpu_ticks', 0) > 0 or child.get('major_faults', 0) > 0
                            if (name in IMPORT_STEPS and not extended and evidence and progress
                                    and not oom_observed(baseline, current)):
                                extended = True
                                deadline = began + timeout + IMPORT_GRACE
                                self.write(f'PRESSURE_GRACE {name} extra={IMPORT_GRACE}s hard_limit={timeout+IMPORT_GRACE}s evidence={evidence}')
                                continue
                            self.write(f'TIMEOUT {name} pid={process.pid} elapsed={time.monotonic()-began:.3f}s extended={extended}')
                            category = 'RESOURCE_PRESSURE' if evidence or oom_observed(baseline, current) else 'TIMEOUT_INCONCLUSIVE'
                            raise PreflightError(f'{name}: délai {deadline-began:g}s dépassé ; commande {shlex.join(map(str,args))} ; état non validé, pas une preuve de corruption ; journal {self.path}', category)
                        try:
                            code = process.wait(timeout=min(1.0, remaining))
                            break
                        except subprocess.TimeoutExpired:
                            if out.stat().st_size > 65536 or err.stat().st_size > 65536:
                                raise PreflightError(f'{name}: sortie excessive ; fichiers conservés')
                            if time.monotonic() - sampled >= 5:
                                current = self.sample(name, 'waiting', process.pid)
                                self.write(f'WAIT {name} pid={process.pid} elapsed={time.monotonic()-began:.3f}s state={current.get("child",{}).get("State")} rss={current.get("child",{}).get("VmRSS")}')
                                sampled = time.monotonic()
                    current = self.sample(name, 'exit', process.pid)
                    if code:
                        with err.open('rb') as stderr_tail:
                            stderr_tail.seek(max(0, err.stat().st_size - 4096))
                            allocation_failure = b'MemoryError' in stderr_tail.read(4096)
                        category = 'RESOURCE_PRESSURE' if allocation_failure or oom_observed(baseline, current) else 'CHECK_FAILED'
                        raise PreflightError(f'{name}: code {code} ; stderr {err} ; journal {self.path}', category)
                    if oom_observed(baseline, current):
                        raise PreflightError(f'{name}: OOM observé pendant le contrôle ; stabilité non validée ; journal {self.path}', 'RESOURCE_PRESSURE')
                except BaseException as error:
                    # Never replace the original timeout diagnostic by a cleanup error.
                    try:
                        self.cleanup(process)
                    except Exception as cleanup_error:
                        self.write(f'CLEANUP FAILED pid={process.pid} error={cleanup_error}')
                        raise PreflightError(str(error) + f' ; arrêt enfants non confirmé pid={process.pid} : {cleanup_error}', 'CLEANUP_FAILED') from error
                    raise
            if out.stat().st_size > 65536 or err.stat().st_size > 65536:
                raise PreflightError(f'{name}: sortie excessive ; fichiers conservés')
            result = out.read_text(encoding='utf-8', errors='replace')
        except BaseException as error:
            self.write(f'FAIL {name} elapsed={time.monotonic()-began:.3f}s error={error}')
            raise
        self.write(f'OK {name} elapsed={time.monotonic()-began:.3f}s pressure_grace={extended}')
        return result


def import_probe(journal, name, group, here):
    # The worker must both finish ALL checks and exit normally; neither a partial
    # stdout nor exit(0) from an imported module is a validation of the group.
    groups = {'runtime': ('copyreg','logging','asyncio','ssl','aiohttp','mako','kvmd'),
              'pillow': ('PIL.Image','PIL.ImageDraw','PIL.ImageFont')}
    args = ['/usr/bin/python3', '-I', '-B', '-u', str(here / 'pikvm_preflight_probe.py'), group]
    result = journal.step(name, args, 15)
    records = [line for line in result.splitlines() if line.startswith('PROBE ')]
    expected = [prefix + module + suffix for module in groups[group]
                for prefix, suffix in (('PROBE BEGIN import=', ''), ('PROBE OK import=', ' elapsed='))]
    if group == 'runtime':
        expected += ['PROBE BEGIN config=msd', 'PROBE OK config=msd']
    if (len(records) != len(expected)+1 or records[-1] != 'PROBE COMPLETE group=' + group or
            any(not line.startswith(prefix) for line, prefix in zip(records, expected))):
        journal.write('FAIL ' + name + ' category=PROBE_INCOMPLETE')
        raise PreflightError(name + ': import probe incomplete; normal exit alone is insufficient', 'PROBE_INCOMPLETE')


def compatibility(journal):
    python = journal.step('package-python', ['pacman', '-Q', 'python'], 10).strip()
    kvmd = journal.step('package-kvmd', ['pacman', '-Q', 'kvmd'], 10).strip()
    with journal.phase('package-versions'):
        if python != 'python 3.14.7-1':
            raise PreflightError('Candidate targets exactly Python 3.14.7-1; manual compatibility review required.')
        if not (kvmd == 'kvmd 4.213' or kvmd.startswith('kvmd 4.213-')):
            raise PreflightError('Candidate targets KVMD 4.213.')
    mtree = Path('/var/lib/pacman/local/python-3.14.7-1/mtree')
    for label, member in (('logging', 'logging/__init__.py'), ('copyreg', 'copyreg.py')):
        target = Path('/usr/lib/python3.14') / member
        with journal.phase(label + '-metadata'):
            if not target.is_file() or target.is_symlink() or not mtree.is_file():
                raise PreflightError(label + ' or package metadata unavailable.')
        expected = journal.step(label + '-baseline', ['bash', '-o', 'pipefail', '-c',
            'gzip -dc "$1" | awk -v target="$2" \'$1 == target {for(i=2;i<=NF;i++) if($i ~ /^sha256digest=/) {sub(/^sha256digest=/,"",$i); print $i}}\'',
            'preflight-mtree', str(mtree), './usr/lib/python3.14/' + member], 10).strip()
        actual = journal.step(label + '-sha256', ['sha256sum', str(target)], 10).split()
        with journal.phase(label + '-integrity'):
            if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
                raise PreflightError(label + ' baseline hash unavailable.')
            if not actual or actual[0] != expected:
                raise PreflightError(label + ' checksum mismatch: repair before migration.', 'INTEGRITY_FAILED')
    here = Path(__file__).resolve().parent
    # Separate processes keep peak RSS at max(runtime, Pillow), not their sum.
    import_probe(journal, 'python-kvmd-imports', 'runtime', here)
    import_probe(journal, 'pillow-imports', 'pillow', here)
    result = journal.step('drive1-read', ['/bin/sh', str(here / 'pikvm-portable-drive-check.sh')], 10)
    with journal.phase('drive1-observation'):
        lines = result.splitlines()
        fields = dict(line.split('=', 1) for line in lines if '=' in line)
        if (len(lines) != 6 or lines[-1] != 'LUN_READ_COMPLETE' or
                set(fields) != {'file_empty','cdrom','ro','removable','nofua'} or
                fields['file_empty'] != '1' or fields['removable'] != '1' or
                any(fields[key] not in ('0','1') for key in ('cdrom','ro','nofua'))):
            raise PreflightError('Drive 1 unknown/incomplete observation; no state accepted.', 'HARDWARE_UNKNOWN')
    journal.step('nginx-syntax', ['nginx', '-t', '-p', '/etc/kvmd/nginx', '-c',
        '/run/kvmd/nginx.conf', '-g', 'pid /run/kvmd/nginx.pid; user kvmd-nginx; error_log stderr;'], 15)
    for service in ('kvmd.service', 'kvmd-nginx.service'):
        journal.step(service, ['systemctl', 'is-active', '--quiet', service], 10)
    journal.write('COMPATIBILITY OK: Python, logging, copyreg, KVMD, Drive 1 read, nginx, services')


if __name__ == '__main__':
    journal = Journal()
    try:
        compatibility(journal)
    except Exception as error:
        raise SystemExit('PRECHECK FAILED: ' + str(error))
