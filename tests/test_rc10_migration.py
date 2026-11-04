"""Migration gates, literal shell bootstrap and complete nginx configurations."""
import contextlib
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_portable_install import portable
from test_portable_preflight import checks

ROOT = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def test_share_power_guard_patch_is_narrow_idempotent_and_rejects_unknown_body(self):
        source = '''# compatibility fix stays here
class Controller:
    def operation(self):
        if not self.lock.acquire(blocking=False):
            raise ShareError('busy')
        yield
'''
        result = portable.share_power_policy(source)
        self.assertIn('# compatibility fix stays here', result)
        self.assertIn('pikvm-poweroff-requested', result)
        self.assertEqual(portable.share_power_policy(result), result)
        with self.assertRaisesRegex(RuntimeError, 'inconnue'):
            portable.share_power_policy(source.replace('        if not self.lock.acquire', '        # unknown custom wrapper\n        if not self.lock.acquire'))

    def test_legacy_bootstrap_refuses_implicit_hardware_update(self):
        bash = shutil.which('bash') if os.name != 'nt' else 'C:/Program Files/Git/bin/bash.exe'
        if not bash or not Path(bash).is_file():
            self.skipTest('bash unavailable')
        result = subprocess.run([bash, str(ROOT/'install.sh')], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--initial-hardware-setup', result.stderr)
        self.assertNotIn('Maintient', result.stdout)

    def test_share_server_patch_preserves_local_compatibility_text_and_refuses_unknown_class(self):
        legacy = '''# local Python compatibility fix retained verbatim
class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = False
    block_on_close = True
    request_queue_size = 8

LOCAL_FIX = 'unchanged'
'''
        result = portable.bounded_share_policy(legacy)
        self.assertIn('# local Python compatibility fix retained verbatim', result)
        self.assertIn("LOCAL_FIX = 'unchanged'", result)
        self.assertIn('BoundedSemaphore(8)', result)
        self.assertEqual(portable.bounded_share_policy(result), result)
        with self.assertRaisesRegex(RuntimeError, 'locaux'):
            portable.bounded_share_policy(legacy.replace('request_queue_size = 8', 'request_queue_size = 17'))

    def test_unknown_local_legacy_fix_is_refused_and_matching_candidate_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'installed'
            source = 'scripts/pikvm-usb-transfer'
            candidate = (ROOT / source).read_bytes()
            old = b'known old version'
            evidence = {'files': {source: str(path)}, 'baselines': {str(path): hashlib.sha256(old).hexdigest()}}
            fake = SimpleNamespace(observe=lambda: {'busy': False, 'drive': {'known': True, 'image': ''}})
            with patch.object(portable, 'storage_sources', return_value=evidence), \
                 patch.object(portable, 'load', return_value=fake):
                path.write_bytes(old)
                portable.storage_preflight()
                path.write_bytes(candidate)
                portable.storage_preflight()
                portable.storage_preflight()
                path.write_bytes(b'unreviewed Python compatibility fix')
                with self.assertRaisesRegex(RuntimeError, 'Correctif local inconnu'):
                    portable.storage_preflight()
                self.assertEqual(path.read_bytes(), b'unreviewed Python compatibility fix')

    def test_update_mapping_and_archive_exclude_all_user_data_and_power_services(self):
        mapping = portable.file_map()
        for path in mapping:
            self.assertFalse(str(path).startswith('/var/lib/kvmd/msd'))
            self.assertNotIn('power-hold', str(path))
            self.assertNotIn('auto-shutdown', str(path))
        for name in ('pikvm-usb-transfer', 'pikvm-image-folders', 'wifi-wizard-api'):
            self.assertIn(Path('/usr/local/bin') / name, mapping)
        self.assertIn(portable.LIB / 'pikvm_transfer.py', mapping)

    def test_low_space_refuses_update_before_stopping_or_snapshotting(self):
        helper = portable.helper()
        with tempfile.TemporaryDirectory() as directory, patch.object(helper,'BACKUPS',Path(directory)/'backups'), \
             patch.object(portable, 'oled_preflight'), \
             patch.object(portable, 'policy_preflight', return_value=(b'', False)), \
             patch.object(portable.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
             patch.object(helper, 'snapshot') as snapshot, patch.object(helper, 'run') as commands:
            with self.assertRaisesRegex(RuntimeError, 'aucun service arrêté'):
                portable.install(helper)
            snapshot.assert_not_called()
            commands.assert_not_called()

    def test_copyreg_bad_checksum_stops_before_any_import_or_drive_command(self):
        journal = Mock()
        journal.phase.side_effect = lambda _: contextlib.nullcontext()
        outputs = {'package-python': 'python 3.14.7-1', 'package-kvmd': 'kvmd 4.213-1',
                   'logging-baseline': 'a'*64, 'logging-sha256': 'a'*64+'  file',
                   'copyreg-baseline': 'b'*64, 'copyreg-sha256': 'c'*64+'  file'}
        journal.step.side_effect = lambda name, *args: outputs.get(name, '')
        with patch.object(checks.Path, 'is_file', return_value=True), patch.object(checks.Path, 'is_symlink', return_value=False):
            with self.assertRaisesRegex(checks.PreflightError, 'copyreg checksum mismatch'):
                checks.compatibility(journal)
        calls = [call.args[0] for call in journal.step.call_args_list]
        self.assertNotIn('python-kvmd-imports', calls)
        self.assertNotIn('drive1-read', calls)

    def test_shell_bootstrap_detects_binary_copyreg_without_running_python(self):
        bash = shutil.which('bash') if os.name != 'nt' else 'C:/Program Files/Git/bin/bash.exe'
        if not bash or not Path(bash).is_file():
            self.skipTest('bash unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            members = ['usr/lib/python3.14/copyreg.py', 'usr/lib/python3.14/logging/__init__.py']
            mtree = []
            for member in members:
                target = root / member
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'known correct Python module\n')
                mtree.append('./' + member + ' sha256digest=' + hashlib.sha256(target.read_bytes()).hexdigest())
            metadata = root / 'mtree.gz'
            metadata.write_bytes(gzip.compress('\n'.join(mtree).encode()))
            source = (ROOT / 'scripts/pikvm-python-integrity.sh').read_text()
            # Only a test copy gets redirected to fixtures; production has no
            # environment override that could bypass its system file checks.
            source = source.replace('mtree=/var/lib/pacman/local/python-3.14.7-1/mtree',
                                    'mtree="$INTEGRITY_FIXTURE_ROOT/mtree.gz"')
            source = source.replace('"/$member"', '"$INTEGRITY_FIXTURE_ROOT/$member"')
            script = root / 'fixture.sh'
            script.write_text(source, encoding='utf-8', newline='\n')
            env = {**os.environ, 'INTEGRITY_FIXTURE_ROOT': root.as_posix()}
            result = subprocess.run([bash, str(script)], env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            (root / members[0]).write_bytes(b'\x8e\xa9\x76\xa8')
            result = subprocess.run([bash, str(script)], env=env, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Integrity FAIL usr/lib/python3.14/copyreg.py', result.stderr)
            self.assertEqual((root / members[0]).read_bytes(), b'\x8e\xa9\x76\xa8')


if __name__ == '__main__':
    unittest.main()
