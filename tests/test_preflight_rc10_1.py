"""Slow/low-resource probes on isolated fixtures, never real Pi memory pressure."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch

from test_portable_preflight import checks
from test_portable_install import portable

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('isolated_probe', ROOT/'scripts/pikvm_preflight_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def sample(available=45056, stalled=0, oom=0, headroom=None):
    return {'memory_kib': {'MemAvailable': available, 'SwapTotal': 0},
            'psi': {'memory': {'some': {'total': stalled, 'avg10': 10.0}}},
            'vmstat': {'oom_kill': oom},
            'cgroups': [{'path': '/test', 'headroom_kib': headroom, 'events': {'oom_kill': oom}}],
            'child': {'cpu_ticks': 1, 'State': 'R', 'VmRSS': '8192 kB', 'wchan': '0'}}


class ResourceTests(unittest.TestCase):
    def test_passive_proc_and_cgroup_ancestor_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc, group = root/'proc', root/'cgroup'
            (proc/'self').mkdir(parents=True)
            (proc/'pressure').mkdir()
            (proc/'meminfo').write_text('MemTotal: 398336 kB\nMemAvailable: 45056 kB\nSwapTotal: 0 kB\n')
            (proc/'vmstat').write_text('oom_kill 2\npgmajfault 19\npgscan_direct 8\n')
            (proc/'self/cgroup').write_text('0::/leaf\n')
            for kind in ('cpu','memory','io'):
                (proc/'pressure'/kind).write_text('some avg10=12.50 avg60=5 avg300=1 total=234567\nfull avg10=1.0 avg60=0 avg300=0 total=100000\n')
            (group/'leaf').mkdir(parents=True)
            for path, limit in ((group, '67108864'), (group/'leaf', 'max')):
                (path/'memory.current').write_text('33554432')
                (path/'memory.max').write_text(limit)
                (path/'memory.events').write_text('oom 1\noom_kill 2\n')
            with patch.object(checks, 'PROC', proc), patch.object(checks, 'CGROUP', group), \
                 patch.object(checks.subprocess, 'run', side_effect=AssertionError('No diagnostic subprocess')):
                result = checks.resources(123)
            self.assertEqual(result['memory_kib']['MemAvailable'], 45056)
            self.assertEqual(result['psi']['memory']['some']['total'], 234567)
            self.assertEqual(result['vmstat']['pgmajfault'], 19)
            self.assertEqual([c['headroom_kib'] for c in result['cgroups']], [None, 32768])
            self.assertIn('unavailable', result['child'])

    def test_missing_resources_never_invent_pressure_or_a_grace(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(checks, 'PROC', Path(directory)):
            result = checks.resources()
        self.assertEqual(result['memory_kib'], {})
        self.assertTrue(all(value is None for value in result['psi'].values()))
        self.assertEqual(checks.pressure_evidence(result, result), [])

    def test_counter_reset_and_historical_oom_are_not_new_events(self):
        self.assertEqual(checks.pressure_evidence(sample(stalled=999999), sample(stalled=0)), [])
        self.assertFalse(checks.oom_observed(sample(oom=4), sample(oom=4)))
        self.assertTrue(checks.oom_observed(sample(oom=4), sample(oom=5)))


class SlowCommandTests(unittest.TestCase):
    def journal(self, directory):
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        return checks.Journal(directory)

    def test_very_low_memory_or_cgroup_headroom_refuses_before_launch(self):
        for resources in (sample(available=8192), sample(headroom=8192)):
            with self.subTest(resources=resources), tempfile.TemporaryDirectory() as directory:
                journal = self.journal(directory)
                with patch.object(checks, 'resources', return_value=resources), patch.object(checks.subprocess, 'Popen') as spawn:
                    with self.assertRaises(checks.PreflightError) as caught:
                        journal.step('python-kvmd-imports', ['not-executed'], .3)
                    self.assertEqual(caught.exception.category, 'RESOURCE_PRESSURE')
                    spawn.assert_not_called()
                self.assertIn('admission refused', journal.path.read_text())
                self.assertTrue((journal.directory/'resources.jsonl').is_file())

    def test_slow_import_under_measured_pressure_succeeds_only_after_exit(self):
        began = time.monotonic()
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            with patch.object(checks, 'resources', side_effect=lambda *_: sample(stalled=int((time.monotonic()-began)*1000000))), \
                 patch.object(checks, 'IMPORT_GRACE', 2):
                result = journal.step('python-kvmd-imports', [sys.executable, '-u', '-c',
                    'import time; print("PROBE BEGIN import=fake",flush=True); time.sleep(.7); print("PROBE COMPLETE",flush=True)'], .5)
            self.assertIn('PROBE COMPLETE', result)
            log = journal.path.read_text()
            self.assertEqual(log.count('PRESSURE_GRACE'), 1)
            self.assertIn('OK python-kvmd-imports', log)
            self.assertIn('TIMEOUT_DETAIL', log)

    def test_slow_without_pressure_gets_no_arbitrary_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            with patch.object(checks, 'resources', return_value=sample()), patch.object(checks, 'IMPORT_GRACE', 10):
                with self.assertRaises(checks.PreflightError) as caught:
                    journal.step('python-kvmd-imports', [sys.executable, '-u', '-c', 'import time; print("BEGIN",flush=True); time.sleep(30)'], .5)
            self.assertEqual(caught.exception.category, 'TIMEOUT_INCONCLUSIVE')
            self.assertNotIn('PRESSURE_GRACE', journal.path.read_text())

    def test_complete_output_without_exit_is_failure_even_under_pressure(self):
        began = time.monotonic()
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            with patch.object(checks, 'resources', side_effect=lambda *_: sample(stalled=int((time.monotonic()-began)*1000000))), \
                 patch.object(checks, 'IMPORT_GRACE', .4):
                with self.assertRaises(checks.PreflightError):
                    journal.step('python-kvmd-imports', [sys.executable, '-u', '-c',
                        'import time; print("PROBE COMPLETE",flush=True); time.sleep(30)'], .5)
            log = journal.path.read_text()
            self.assertEqual(log.count('PRESSURE_GRACE'), 1)
            self.assertIn('TIMEOUT python-kvmd-imports', log)
            self.assertIn('PROBE COMPLETE', log)
            self.assertNotIn('OK python-kvmd-imports', log)

    def test_full_drive_output_without_exit_never_passes_or_gets_import_grace(self):
        began = time.monotonic()
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            with patch.object(checks, 'resources', side_effect=lambda *_: sample(stalled=int((time.monotonic()-began)*1000000))):
                with self.assertRaises(checks.PreflightError):
                    journal.step('drive1-read', [sys.executable, '-u', '-c',
                        'import time; print("LUN_READ_COMPLETE",flush=True); time.sleep(30)'], .5)
            self.assertNotIn('PRESSURE_GRACE', journal.path.read_text())
            self.assertIn('LUN_READ_COMPLETE', next(journal.directory.glob('*.stdout')).read_text())

    def test_nonzero_import_is_not_retried_or_ignored_under_pressure(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            with patch.object(checks, 'resources', return_value=sample(stalled=999999)):
                with self.assertRaisesRegex(checks.PreflightError, 'code 7'):
                    journal.step('python-kvmd-imports', [sys.executable, '-c', 'raise SystemExit(7)'], 5)
            self.assertNotIn('PRESSURE_GRACE', journal.path.read_text())

    def test_successful_exit_during_new_oom_is_not_a_healthy_system(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            with patch.object(checks, 'resources', side_effect=[sample(), sample(oom=1)]):
                with self.assertRaises(checks.PreflightError) as caught:
                    journal.step('python-kvmd-imports', [sys.executable, '-c', 'pass'], 5)
            self.assertEqual(caught.exception.category, 'RESOURCE_PRESSURE')

    def test_cleanup_failure_preserves_original_timeout_and_child_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            original = journal.cleanup
            def cleanup(process):
                original(process)  # Never leave a real child running in the test.
                raise RuntimeError('simulated cleanup uncertainty')
            with patch.object(checks, 'resources', return_value=sample()), patch.object(journal, 'cleanup', side_effect=cleanup):
                with self.assertRaises(checks.PreflightError) as caught:
                    journal.step('fake-drive-read', [sys.executable, '-u', '-c', 'import time; print("partial",flush=True); time.sleep(30)'], .5)
            self.assertEqual(caught.exception.category, 'CLEANUP_FAILED')
            log = journal.path.read_text()
            self.assertIn('TIMEOUT fake-drive-read', log)
            self.assertIn('simulated cleanup uncertainty', log)
            self.assertIn('partial', log)

    @unittest.skipIf(os.name == 'nt', 'RLIMIT_AS requires Linux')
    def test_child_memory_limit_error_is_failure_without_host_oom(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = self.journal(directory)
            with patch.object(checks, 'resources', return_value=sample()):
                with self.assertRaises(checks.PreflightError):
                    journal.step('limited-child', [sys.executable, '-c',
                        'import resource; resource.setrlimit(resource.RLIMIT_AS,(64*1024**2,64*1024**2)); bytearray(128*1024**2)'], 5)
            self.assertIn('MemoryError', next(journal.directory.glob('*.stderr')).read_text())


class WorkerAndStartupTests(unittest.TestCase):
    def test_worker_memory_checkpoint_records_rss_and_peak_without_extra_imports(self):
        with patch('builtins.open', mock_open(read_data='VmRSS: 8123 kB\nVmHWM: 9012 kB\n')):
            self.assertEqual(probe.memory_report(), ' rss_kib=8123 hwm_kib=9012')
        with patch('builtins.open', side_effect=FileNotFoundError()):
            self.assertIn('unknown', probe.memory_report())

    def test_check_does_not_load_the_unused_rollback_helper(self):
        journal = Mock()
        journal.phase.side_effect = lambda *_: contextlib.nullcontext()
        with patch.object(portable.os, 'geteuid', return_value=0, create=True), \
             patch.object(sys, 'argv', ['installer','check']), patch.object(portable, 'preflight'), \
             patch.object(portable, 'preflight_journal', return_value=journal), \
             patch.object(portable, 'policy_preflight', return_value=(b'',False)), \
             patch.object(portable, 'helper', side_effect=AssertionError('Unused helper loaded')), \
             contextlib.redirect_stdout(io.StringIO()):
            portable.main()

    def test_zero_exit_with_incomplete_import_protocol_is_not_success(self):
        journal = Mock()
        journal.step.return_value = 'PROBE COMPLETE group=runtime\n'
        with self.assertRaises(checks.PreflightError) as caught:
            checks.import_probe(journal, 'python-kvmd-imports', 'runtime', ROOT/'scripts')
        self.assertEqual(caught.exception.category, 'PROBE_INCOMPLETE')

    def test_import_probe_preserves_config_validation_without_running_otgmsd(self):
        names = []
        init = Mock(return_value=SimpleNamespace(config=SimpleNamespace(kvmd=SimpleNamespace(msd=SimpleNamespace(type='otg')))))
        def fake_import(name, **_):
            names.append(name)
            return SimpleNamespace(__version__='4.213', FileHandler=object, init=init)
        output = io.StringIO()
        with patch.object(probe, 'EXPECTED_PYTHON', sys.version_info[:3]), \
             patch('builtins.__import__', side_effect=fake_import), contextlib.redirect_stdout(output):
            probe.run_group('runtime')
            probe.run_group('pillow')
        self.assertEqual(tuple(names), probe.GROUPS['runtime'] + ('kvmd.apps',) + probe.GROUPS['pillow'])
        init.assert_called_once_with(cli_logging=True, load_msd=True, test_args=['--'])
        self.assertFalse(any('otgmsd' in name for name in names))
        self.assertEqual(output.getvalue().count('PROBE COMPLETE'), 2)

    def test_non_otg_configuration_cannot_pass(self):
        init = Mock(return_value=SimpleNamespace(config=SimpleNamespace(kvmd=SimpleNamespace(msd=SimpleNamespace(type='disabled')))))
        def fake_import(name, **_):
            return SimpleNamespace(__version__='4.213', FileHandler=object, init=init)
        with patch.object(probe, 'EXPECTED_PYTHON', sys.version_info[:3]), \
             patch('builtins.__import__', side_effect=fake_import), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'otg'):
                probe.run_group('runtime')

    def test_import_failure_keeps_last_checkpoint_and_no_complete_marker(self):
        output = io.StringIO()
        with patch.object(probe, 'EXPECTED_PYTHON', sys.version_info[:3]), \
             patch('builtins.__import__', side_effect=ImportError('injected bad module')), contextlib.redirect_stdout(output):
            with self.assertRaises(ImportError):
                probe.run_group('pillow')
        self.assertIn('PROBE BEGIN import=PIL.Image', output.getvalue())
        self.assertNotIn('PROBE COMPLETE', output.getvalue())

    def test_installer_cold_start_does_not_preload_http_ssl_html_or_ast(self):
        code = ('import importlib.machinery,importlib.util,sys,json; '
                'loader=importlib.machinery.SourceFileLoader("cold_installer",sys.argv[1]); '
                'spec=importlib.util.spec_from_loader(loader.name,loader); '
                'module=importlib.util.module_from_spec(spec); loader.exec_module(module); '
                'print(json.dumps([n for n in ("http.client","ssl","html.parser","ast","aiohttp","PIL") if n in sys.modules]))')
        result = subprocess.run([sys.executable,'-I','-B','-c',code,str(ROOT/'scripts/pikvm-portable-install')],
                                capture_output=True,text=True,timeout=15,check=True)
        self.assertEqual(json.loads(result.stdout), [])

    def test_packaged_worker_paths_match_installed_supervisor(self):
        mapping = portable.file_map()
        for name in ('pikvm_preflight_probe.py','pikvm-portable-drive-check.sh'):
            self.assertIn(portable.LIB/name, mapping)


class DriveShellTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        lun = root/'lun'
        lun.mkdir()
        for name, value in {'file':'', 'cdrom':'0','ro':'0','removable':'1','nofua':'0'}.items():
            (lun/name).write_text(value+'\n', encoding='utf-8', newline='\n')
        source = (ROOT/'scripts/pikvm-portable-drive-check.sh').read_text()
        source = source.replace('lun=/sys/kernel/config/usb_gadget/kvmd/functions/mass_storage.usb1/lun.0',
                                'lun="$DRIVE_FIXTURE"')
        script = root/'drive.sh'
        script.write_text(source, encoding='utf-8', newline='\n')
        return lun, script

    def run_shell(self, script, lun):
        bash = shutil.which('bash') if os.name != 'nt' else 'C:/Program Files/Git/bin/bash.exe'
        if not bash or not Path(bash).is_file():
            self.skipTest('bash unavailable')
        return subprocess.run([bash,str(script)], env={**os.environ,'DRIVE_FIXTURE':lun.as_posix()},
                              capture_output=True,text=True,timeout=10)

    def test_empty_drive_read_only_and_missing_malformed_attached_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            lun, script = self.fixture(directory)
            before = {p.name:p.read_bytes() for p in lun.iterdir()}
            result = self.run_shell(script,lun)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('file_empty=1',result.stdout)
            self.assertIn('LUN_READ_COMPLETE',result.stdout)
            self.assertEqual({p.name:p.read_bytes() for p in lun.iterdir()},before)
            (lun/'file').write_bytes(b'')  # configfs may return zero bytes, not LF.
            self.assertEqual(self.run_shell(script,lun).returncode,0)
            (lun/'file').write_bytes(before['file'])
            for name, value in [('file','/private/user.iso'), ('ro','unknown'), ('removable','0'), ('file','\x00'), ('ro','0\x00')]:
                with self.subTest(name=name):
                    (lun/name).write_text(value)
                    result = self.run_shell(script,lun)
                    self.assertNotEqual(result.returncode,0)
                    self.assertNotIn('LUN_READ_COMPLETE',result.stdout)
                    (lun/name).write_bytes(before[name])
            (lun/'file').unlink()
            result = self.run_shell(script,lun)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('LUN_READ_ERROR',result.stderr)

    def test_configuration_change_between_observations_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            lun, script = self.fixture(directory)
            source = script.read_text().replace('second=$(snapshot)', 'printf 1 > "$lun/ro"\nsecond=$(snapshot)')
            script.write_text(source,encoding='utf-8',newline='\n')
            result = self.run_shell(script,lun)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('LUN_CHANGED',result.stderr)


if __name__ == '__main__':
    unittest.main()
