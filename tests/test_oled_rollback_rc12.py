"""RC11 preference bytes survive schema migration and repeated rollback."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import pikvm_config as config
from test_portable_install import portable,ROOT


class PreferenceRollbackTests(unittest.TestCase):
    def test_rc11_snapshot_restore_is_byte_exact_lease_protected_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'pst/portable-os/settings.json';target.parent.mkdir(parents=True)
            original=(ROOT/'tests/fixtures/rc11-settings.json').read_bytes();target.write_bytes(original);target.chmod(0o600)
            backup=root/'backup';backup.mkdir();h=portable.helper()
            with patch.object(portable,'preferences_module',return_value=config),patch.object(config,'pst_path',return_value=target), \
                 patch.object(config,'pst_commit',side_effect=lambda writer:writer(target)) as lease:
                metadata=portable.snapshot_preferences(h,backup)
                manifest={'files':[],'portable_preferences':metadata};(backup/'manifest.json').write_text(json.dumps(manifest))
                portable.verify_backup(h,backup)
                migrated=config.Store(target).read();migrated['values']['oled_style']='detailed';config.Store(target).save(migrated['values'],7)
                self.assertEqual(json.loads(target.read_text())['schema_version'],2)
                portable.restore_preferences(h,backup,manifest);self.assertEqual(target.read_bytes(),original)
                self.assertTrue((backup/'preferences-before-restore.json').is_file())
                portable.restore_preferences(h,backup,manifest);lease.assert_called_once()
                (backup/'preferences.json').write_bytes(b'corrupt')
                with patch.object(h,'run') as run,self.assertRaises(RuntimeError):portable.restore(h,backup)
                run.assert_not_called();self.assertEqual(target.read_bytes(),original)

    def test_denied_lease_never_writes_and_absent_preference_restores_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'settings.json';h=portable.helper()
            with patch.object(portable,'preferences_module',return_value=config),patch.object(config,'pst_path',return_value=target):
                metadata=portable.snapshot_preferences(h,root);manifest={'portable_preferences':metadata}
                values=config.defaults();values['theme']='light';config.Store(target).save(values,0)
                before=target.read_bytes()
                with patch.object(config,'pst_commit',side_effect=config.ConfigError('denied')),self.assertRaises(config.ConfigError):
                    portable.restore_preferences(h,root,manifest)
                self.assertEqual(target.read_bytes(),before)
                with patch.object(config,'pst_commit',side_effect=lambda writer:writer(target)):
                    portable.restore_preferences(h,root,manifest);self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
