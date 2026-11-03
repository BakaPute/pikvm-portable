"""RC gates, recovery contracts and installer readiness; no device access."""
import io
import hashlib
import json
from pathlib import Path
import tempfile
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_portable_install import portable


ROOT = Path(__file__).resolve().parents[1]


class CandidateTests(unittest.TestCase):
    def test_candidate_bundle_is_deterministic_and_contains_no_device_data(self):
        loader = portable.load('portable_package_test', ROOT / 'scripts/pikvm-portable-package.py')
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first.tar.gz', Path(directory) / 'second.tar.gz'
            self.assertEqual(loader.build(first), loader.build(second))
            with tarfile.open(first) as archive:
                names = archive.getnames()
                prefix = loader.RELEASE + '/'
                manifest = archive.extractfile(prefix + 'MANIFEST.sha256').read().decode()
                entries = {name: checksum for checksum, name in
                           (line.split('  ', 1) for line in manifest.splitlines())}
                for entry in archive.getmembers():
                    self.assertTrue(entry.isfile())
                    self.assertTrue(entry.name.startswith(prefix))
                    self.assertNotIn('..', Path(entry.name).parts)
                    relative = entry.name[len(prefix):]
                    if relative != 'MANIFEST.sha256':
                        self.assertEqual(hashlib.sha256(archive.extractfile(entry).read()).hexdigest(), entries[relative])
                for path in ('scripts/pikvm_transfer.py', 'scripts/wifi-wizard-api',
                             'scripts/pikvm-share-api', 'scripts/pikvm-python-integrity.sh'):
                    self.assertIn(path, entries)
            self.assertNotIn(b'\r', first.with_name(first.name + '.sha256').read_bytes())
            self.assertTrue(any(name.endswith('/MANIFEST.sha256') for name in names))
            self.assertFalse(any('/private/' in name or name.endswith('.img') or '.git/' in name for name in names))

    def test_unauthenticated_success_is_never_considered_ready(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"ok":true}'
        response.getheader.return_value = 'PiKVM-Portable-OS'
        h = SimpleNamespace(service_state=lambda: {'active': True})
        with patch.object(portable.http.client, 'HTTPConnection', return_value=connection), \
             patch.object(portable.time, 'monotonic', side_effect=[0, 0, 2]), patch.object(portable.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'non prête'):
                portable.wait_ready(h, timeout=1)

    def test_ready_requires_new_service_identity_auth_challenge_and_active_unit(self):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 401
        response.read.return_value = b'{"ok":false}'
        response.getheader.return_value = 'PiKVM-Portable-OS Python/3.14'
        h = SimpleNamespace(service_state=lambda: {'active': True})
        with patch.object(portable.http.client, 'HTTPConnection', return_value=connection):
            portable.wait_ready(h)
        connection.close.assert_called_once()

    def test_modified_backup_is_rejected_before_stopping_any_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '0').write_bytes(b'modified')
            (root / 'manifest.json').write_text(json.dumps({'files': [
                {'exists': True, 'file': '0', 'sha256': '0' * 64}]}))
            h = portable.helper()
            with patch.object(h, 'run') as command:
                with self.assertRaisesRegex(RuntimeError, 'aucun service arrêté'):
                    portable.restore(h, root)
            command.assert_not_called()

    def test_deployment_vendors_its_own_rollback_helper_and_compatibility_gate(self):
        mapping = portable.file_map()
        self.assertIn(portable.LIB / 'installer.py', mapping)
        self.assertIn(portable.LIB / 'preflight.sh', mapping)
        self.assertNotIn(Path('/usr/lib/python3.14/logging/__init__.py'), mapping)
        self.assertFalse(any(str(path).endswith('.img') for path in mapping))

    def test_repair_has_no_global_upgrade_or_signature_bypass(self):
        source = (ROOT / 'scripts/pikvm-python-logging-repair.sh').read_text()
        self.assertIn('pacman-key --verify', source)
        self.assertIn('--authorized', source)
        self.assertIn('mtree_hash "$DB/mtree"', source)
        self.assertNotIn('pacman -S', source)
        self.assertNotIn('SigLevel', source)
        self.assertNotIn('mkfs', source)
        self.assertNotIn('systemctl restart', source)
        self.assertNotRegex(source.split('if [[ "$action" == inspect ]]')[0], r'(?m)^\s*(/usr/bin/)?python3\s')

    def test_logging_integrity_gate_precedes_python_and_usb_commands(self):
        source = (ROOT / 'scripts/pikvm_preflight.py').read_text()
        self.assertLess(source.index('sha256sum'), source.index("journal.step('python-kvmd-imports'"))
        self.assertLess(source.index('sha256sum'), source.index('kvmd-otgmsd'))
        self.assertNotIn('--set-', source)
        self.assertNotIn('pinctrl set', source)


if __name__ == '__main__':
    unittest.main()
