"""Bounded prechecks: no hardware commands, real stalled child processes."""
import contextlib
import importlib.util
import io
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from test_portable_install import portable

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preflight_tests', ROOT/'scripts/pikvm_preflight.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def probe_output(group):
    names = ('copyreg','logging','asyncio','ssl','aiohttp','mako','kvmd') if group == 'runtime' else ('PIL.Image','PIL.ImageDraw','PIL.ImageFont')
    config = 'PROBE BEGIN config=msd\nPROBE OK config=msd\n' if group == 'runtime' else ''
    return ''.join('PROBE BEGIN import=' + name + '\nPROBE OK import=' + name + ' elapsed=0.001s\n' for name in names) + config + 'PROBE COMPLETE group=' + group + '\n'


class PreflightTests(unittest.TestCase):
    def journal(self, directory):
        # Keep test output concise; the durable files remain under the test root.
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.enterContext(patch.object(checks, 'resources', return_value={
            'memory_kib': {'MemAvailable': 131072}, 'psi': {}, 'vmstat': {}, 'cgroups': []}))
        return checks.Journal(directory)

    def test_intermittent_drive_imports_and_systemctl_fail_closed_then_pass_on_a_new_run(self):
        for name in ('drive1-read', 'python-kvmd-imports', 'kvmd.service'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                marker=Path(directory)/'once'
                code=('import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); '
                      'existed=p.exists(); p.write_text("seen"); '
                      'print("starting simulated check",flush=True); '
                      'print("partial diagnostic",file=sys.stderr,flush=True); '
                      'time.sleep(0 if existed else 60)')
                args=[sys.executable,'-I','-B','-c',code,str(marker)]
                first=self.journal(directory)
                began=time.monotonic()
                with self.assertRaisesRegex(checks.PreflightError, name):
                    first.step(name,args,.6)
                self.assertLess(time.monotonic()-began,10)
                log=first.path.read_text()
                self.assertIn('TIMEOUT '+name,log); self.assertIn('command=',log)
                self.assertIn('timeout=0.6s',log); self.assertIn('elapsed=',log)
                self.assertIn('starting simulated check',next(first.directory.glob('*.stdout')).read_text())
                self.assertIn('partial diagnostic',next(first.directory.glob('*.stderr')).read_text())
                # No automatic retry. A separate explicit invocation gets its own log.
                second=self.journal(directory)
                self.assertIn('starting simulated check',second.step(name,args,5))
                self.assertNotEqual(first.path,second.path)
                self.assertIn('TIMEOUT',first.path.read_text())

    def test_timeout_stops_a_grandchild_even_when_group_leader_exits_on_term(self):
        with tempfile.TemporaryDirectory() as directory:
            beat=Path(directory)/'child-heartbeat'
            # A separate script avoids shell quoting and contains no device access.
            script=Path(directory)/'child.py'
            script.write_text('import signal,time,pathlib,sys\n'
                'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                'p=pathlib.Path(sys.argv[1])\n'
                'while True:\n p.write_text(str(time.monotonic()))\n time.sleep(.05)\n')
            parent=('import subprocess,sys,time; '
                    'subprocess.Popen([sys.executable,"-B",sys.argv[1],sys.argv[2]]); time.sleep(60)')
            journal=self.journal(directory)
            with self.assertRaises(checks.PreflightError):
                journal.step('tree',[sys.executable,'-B','-c',parent,str(script),str(beat)],1)
            self.assertTrue(beat.exists(),'Grandchild must run before the timeout')
            last=beat.read_text();time.sleep(.3)
            self.assertEqual(beat.read_text(),last,'Timed-out descendants must stop')

    def test_posix_cleanup_always_kills_the_group_after_leader_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=self.journal(directory);process=Mock(pid=123456)
            with patch.object(checks.os,'name','posix'), patch.object(checks.os,'killpg',create=True) as kill, \
                 patch.object(checks.time,'sleep'):
                # SIGKILL may be absent on Windows; supply its POSIX number for this mock.
                with patch.object(checks.signal,'SIGKILL',9,create=True):
                    journal.cleanup(process)
            self.assertEqual([call.args for call in kill.call_args_list],[(123456,signal.SIGTERM),(123456,9)])
            process.wait.assert_called_once_with(timeout=2)

    def test_nonzero_status_and_partial_diagnostics_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=self.journal(directory)
            with self.assertRaisesRegex(checks.PreflightError,'code 7'):
                journal.step('inactive-service',[sys.executable,'-c','import sys; print("inactive",file=sys.stderr);sys.exit(7)'],5)
            self.assertIn('inactive',next(journal.directory.glob('*.stderr')).read_text())
            self.assertNotIn('OK inactive-service',journal.path.read_text())

    def test_all_original_checks_and_per_command_budgets_are_retained(self):
        journal=Mock();journal.phase.side_effect=lambda name:contextlib.nullcontext()
        outputs={'package-python':'python 3.14.7-1\n','package-kvmd':'kvmd 4.213-1\n',
                 'logging-baseline':'a'*64,'logging-sha256':'a'*64+'  file',
                 'copyreg-baseline':'a'*64,'copyreg-sha256':'a'*64+'  file',
                 'python-kvmd-imports':probe_output('runtime'), 'pillow-imports':probe_output('pillow'),
                 'drive1-read':'file_empty=1\ncdrom=0\nro=0\nremovable=1\nnofua=0\nLUN_READ_COMPLETE\n'}
        journal.step.side_effect=lambda name,args,timeout:outputs.get(name,'')
        with patch.object(checks.Path,'is_file',return_value=True),patch.object(checks.Path,'is_symlink',return_value=False):
            checks.compatibility(journal)
        commands={call.args[0]:call.args[1:] for call in journal.step.call_args_list}
        self.assertEqual(commands['drive1-read'][0][0], '/bin/sh')
        self.assertTrue(commands['drive1-read'][0][1].endswith('pikvm-portable-drive-check.sh'))
        self.assertEqual(commands['drive1-read'][1],10)
        self.assertEqual(commands['python-kvmd-imports'][1],15)
        self.assertEqual(commands['kvmd.service'],(['systemctl','is-active','--quiet','kvmd.service'],10))
        self.assertIn('nginx-syntax',commands);self.assertIn('kvmd-nginx.service',commands)
        self.assertEqual(len(commands),12)

    def test_failed_check_never_continues_to_later_commands(self):
        journal=Mock();journal.step.side_effect=checks.PreflightError('blocked pacman')
        with self.assertRaises(checks.PreflightError):checks.compatibility(journal)
        journal.step.assert_called_once()

    def test_import_drive_or_systemctl_timeout_stops_the_entire_gate(self):
        order=['package-python','package-kvmd','logging-baseline','logging-sha256','copyreg-baseline','copyreg-sha256',
               'python-kvmd-imports','pillow-imports','drive1-read','nginx-syntax','kvmd.service','kvmd-nginx.service']
        for fault in ('python-kvmd-imports','drive1-read','kvmd.service'):
            with self.subTest(fault=fault):
                journal=Mock();journal.phase.side_effect=lambda name:contextlib.nullcontext()
                def step(name,args,timeout):
                    if name==fault:raise checks.PreflightError('TIMEOUT '+name)
                    return {'package-python':'python 3.14.7-1','package-kvmd':'kvmd 4.213-1',
                            'logging-baseline':'a'*64,'logging-sha256':'a'*64+'  file',
                 'copyreg-baseline':'a'*64,'copyreg-sha256':'a'*64+'  file',
                 'python-kvmd-imports':probe_output('runtime'), 'pillow-imports':probe_output('pillow'),
                 'drive1-read':'file_empty=1\ncdrom=0\nro=0\nremovable=1\nnofua=0\nLUN_READ_COMPLETE\n'}.get(name,'')
                journal.step.side_effect=step
                with patch.object(checks.Path,'is_file',return_value=True),patch.object(checks.Path,'is_symlink',return_value=False):
                    with self.assertRaisesRegex(checks.PreflightError,fault):checks.compatibility(journal)
                self.assertEqual([c.args[0] for c in journal.step.call_args_list],order[:order.index(fault)+1])

    def test_installer_uses_same_supervisor_and_stops_before_oled_on_failure(self):
        journal=Mock();journal.compatibility.side_effect=checks.PreflightError('blocked imports')
        with patch.object(portable,'preflight_journal',return_value=journal), \
             patch.object(portable,'navigation_preflight') as navigation,patch.object(portable,'oled_preflight') as oled:
            with self.assertRaises(checks.PreflightError):portable.preflight()
            navigation.assert_not_called();oled.assert_not_called()

    def test_no_shared_services_or_gpio_are_mutated_by_oled_health_check(self):
        journal=Mock()
        with patch.object(portable,'preflight_journal',return_value=journal), \
             patch.object(portable.Path,'is_file',return_value=True), \
             patch.object(portable.Path,'is_symlink',return_value=False), \
             patch.object(portable.Path,'exists',return_value=False), \
             patch.object(portable.Path,'read_bytes',return_value=b'same'):
            portable.oled_preflight()
        self.assertEqual(journal.step.call_args_list[0].args,
            ('power-hold-active',['systemctl','is-active','--quiet','pikvm-power-hold.service'],10))
        self.assertEqual(len(journal.step.call_args_list),1, 'Pillow is checked once in compatibility, not again during install')

    def test_wrapper_and_installed_payload_keep_the_shared_supervisor(self):
        source=(ROOT/'scripts/pikvm-portable-preflight.sh').read_text()
        self.assertIn('exec /usr/bin/python3 -I -B',source)
        self.assertIn('pikvm_preflight.py',source)
        self.assertIn(portable.LIB/'pikvm_preflight.py',portable.file_map())
