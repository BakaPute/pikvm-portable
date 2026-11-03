"""Synthetic storage, injected crashes and mocked hardware; never connects to Pi."""
import contextlib
import hashlib
import http.client
import importlib.machinery
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pikvm_transfer as transfer


def load(name):
    loader = importlib.machinery.SourceFileLoader('recovery_' + name.replace('-', '_'), str(ROOT / 'scripts' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


usb = load('pikvm-usb-transfer')
folders = load('pikvm-image-folders')
wifi = load('wifi-wizard-api')


class StorageFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'source'
        self.src.mkdir()
        self.dest = self.root / 'destination'
        self.dest.mkdir()
        self.image = self.dest / '.USB-TRANSFER.img'
        self.image.write_bytes(b'backup source never touched')
        self.source = self.src / 'Windows français avec espaces.iso'
        self.source.write_bytes(bytes(range(256)) * 8192)
        self.target = self.dest / self.source.name
        self.journal = transfer.ImportJournal(self.dest)

    def assert_preserved(self):
        self.assertEqual(self.image.read_bytes(), b'backup source never touched')
        self.assertEqual(self.source.read_bytes(), bytes(range(256)) * 8192)


class ImportTests(StorageFixture):
    def test_copy_hash_no_overwrite_source_preserved_and_idempotent_retry(self):
        self.journal.copy(self.source, self.target)
        inode = self.target.stat().st_ino
        again = transfer.ImportJournal(self.dest)
        again.copy(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.target.stat().st_ino, inode)
        self.assertEqual(list(self.dest.glob('*.iso')), [self.target])
        self.assertFalse(list(self.dest.glob('.__usbimport-*.part')))
        self.assert_preserved()

    def test_existing_recovered_iso_is_verified_and_never_overwritten(self):
        self.target.write_bytes(self.source.read_bytes())
        inode = self.target.stat().st_ino
        self.journal.copy(self.source, self.target)
        self.assertEqual(self.target.stat().st_ino, inode)
        self.assert_preserved()

    def test_conflicting_iso_is_refused_and_preserved(self):
        self.target.write_bytes(b'existing user data')
        with self.assertRaisesRegex(RuntimeError, 'différente'):
            self.journal.copy(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b'existing user data')
        self.assert_preserved()

    def test_interrupted_partial_is_retained_quarantined_explicitly_then_retry(self):
        with self.assertRaises(InterruptedError):
            self.journal.copy(self.source, self.target, Mock(side_effect=InterruptedError('network lost')))
        self.assertFalse(self.target.exists())
        partial = next(self.dest.glob('.__usbimport-*.part'))
        saved = partial.read_bytes()
        journal = transfer.ImportJournal(self.dest)
        with self.assertRaisesRegex(RuntimeError, 'partielle'):
            journal.copy(self.source, self.target)
        journal.recover_partial(self.source.name)
        self.assertEqual(next(self.dest.glob('.usbimport-retained-*')).read_bytes(), saved)
        journal.copy(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assert_preserved()

    def test_crash_after_full_copy_before_verification_recovers_without_recopier(self):
        original = transfer.digest
        original_open = Path.open
        with patch.object(transfer, 'digest', side_effect=InterruptedError('crash before verification')):
            with self.assertRaises(InterruptedError):
                self.journal.copy(self.source, self.target)
        with patch.object(transfer.Path, 'open', autospec=True, side_effect=lambda p, *a, **k: self.fail('unexpected write')
                          if a and a[0] == 'xb' and p.name.endswith('.part') else original_open(p, *a, **k)):
            transfer.ImportJournal(self.dest).copy(self.source, self.target)
        self.assertEqual(original(self.target), original(self.source))

    def test_crash_at_every_durable_copy_checkpoint_can_recover(self):
        # planned, verified, published, done. SIGKILL equivalent: no cleanup hook.
        for checkpoint in range(1, 5):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / self.source.name
                journal = transfer.ImportJournal(root)
                save = journal.save
                count = [0]
                def crash(stage, **extra):
                    save(stage, **extra)
                    count[0] += 1
                    if count[0] == checkpoint:
                        raise InterruptedError('simulated power loss')
                with patch.object(journal, 'save', side_effect=crash):
                    with self.assertRaises(InterruptedError):
                        journal.copy(self.source, target)
                transfer.ImportJournal(root).copy(self.source, target)
                self.assertEqual(target.read_bytes(), self.source.read_bytes())
                self.assertFalse(list(root.glob('.__usbimport-*.part')))
        self.assert_preserved()

    def test_write_or_sync_failure_keeps_source_and_no_false_publication(self):
        for fault in (OSError(28, 'disk full'), PermissionError('denied'), OSError(5, 'I/O')):
            with self.subTest(fault=fault), patch.object(transfer.os, 'fsync', side_effect=fault):
                with self.assertRaises(OSError):
                    self.journal.copy(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.assert_preserved()

    def test_insufficient_space_is_checked_before_copy(self):
        with patch.object(transfer.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(RuntimeError, 'Espace'):
                self.journal.copy(self.source, self.target)
        self.assertFalse(list(self.dest.glob('.__usbimport-*.part')))
        self.assert_preserved()

    def test_data_fsync_failure_is_retried_before_recovered_publication(self):
        original = transfer.os.fsync
        failed = [False]
        def fail_data(fd):
            if not failed[0] and os.fstat(fd).st_size == self.source.stat().st_size:
                failed[0] = True
                raise OSError('data fsync failed')
            return original(fd)
        with patch.object(transfer.os, 'fsync', side_effect=fail_data):
            with self.assertRaises(OSError):
                self.journal.copy(self.source, self.target)
        self.assertFalse(self.target.exists())
        self.assertTrue(list(self.dest.glob('.__usbimport-*.part')))
        with patch.object(transfer.os, 'fsync', wraps=original) as sync:
            transfer.ImportJournal(self.dest).copy(self.source, self.target)
            self.assertGreaterEqual(sync.call_count, 3)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assert_preserved()

    def test_truncated_corrupted_temp_is_not_published(self):
        with patch.object(transfer, 'digest', return_value='0'*64):
            with self.assertRaisesRegex(RuntimeError, 'partielle'):
                self.journal.copy(self.source, self.target)
        self.assertFalse(self.target.exists())
        self.assertTrue(list(self.dest.glob('.__usbimport-*.part')))
        self.assert_preserved()

    def test_publication_collision_does_not_replace_external_writer(self):
        link = transfer.os.link
        def collide(source, dest):
            dest.write_bytes(b'concurrent KVMD upload')
            return link(source, dest)
        with patch.object(transfer.os, 'link', side_effect=collide):
            with self.assertRaises(FileExistsError):
                self.journal.copy(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b'concurrent KVMD upload')
        self.assertTrue(list(self.dest.glob('.__usbimport-*.part')))
        self.assert_preserved()

    def test_source_changed_during_copy_refused(self):
        def change(*_):
            os.utime(self.source, ns=(1, 1))
        with self.assertRaisesRegex(RuntimeError, 'changé'):
            self.journal.copy(self.source, self.target, change)
        self.assertFalse(self.target.exists())

    def test_journal_corrupt_or_traversal_cannot_publish_or_remove_anything(self):
        self.journal.path.write_text('{corrupt')
        with self.assertRaises(ValueError):
            transfer.ImportJournal(self.dest)
        self.journal.path.unlink()
        self.journal.copy(self.source, self.target)
        self.journal.data['files'][self.source.name]['temp'] = '../outside.part'
        with self.assertRaisesRegex(RuntimeError, 'invalide'):
            self.journal.copy(self.source, self.target)
        self.assert_preserved()

    @unittest.skipIf(os.name == 'nt', 'Windows symlink permission not assumed')
    def test_symlink_sources_and_destinations_are_refused(self):
        link = self.src / 'link.iso'
        link.symlink_to(self.source)
        with self.assertRaises(RuntimeError):
            self.journal.copy(link, self.target)
        self.target.symlink_to(self.source)
        with self.assertRaises(RuntimeError):
            self.journal.copy(self.source, self.target)

    def test_xz_output_verified_and_truncated_archive_retained(self):
        source = self.src / 'compressed.iso.xz'
        source.write_bytes(lzma.compress(self.source.read_bytes(), preset=1))
        target = self.dest / 'compressed.iso'
        self.journal.copy(source, target)
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        broken = self.src / 'broken.iso.xz'
        broken.write_bytes(source.read_bytes()[:20])
        with self.assertRaises((RuntimeError, lzma.LZMAError)):
            self.journal.copy(broken, self.dest / 'broken.iso')
        self.assertTrue(broken.exists())
        self.assertFalse((self.dest / 'broken.iso').exists())

    def test_native_orphan_link_report_and_library_are_not_globally_blocked(self):
        self.target.write_bytes(self.source.read_bytes())
        orphan = self.dest / '.__usbimport-old.part'
        os.link(self.target, orphan)
        lun = self.root / 'lun'
        lun.write_text('')
        with patch.object(folders, 'ROOT', self.dest), patch.object(folders, 'LUN', lun), \
             patch.object(folders, 'transfer_active', return_value=False):
            folders.check_idle()
        report = transfer.recovery_report(self.dest)
        self.assertEqual(report['temporary_files'][0]['links'], 2)
        self.assertEqual(orphan.read_bytes(), self.target.read_bytes())
        transfer.recover_link(self.dest, orphan.name, self.target.name)
        transfer.recover_link(self.dest, orphan.name, self.target.name)
        self.assertFalse(orphan.exists())
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        (self.dest / '.__active.incomplete').touch()
        with patch.object(folders, 'ROOT', self.dest), patch.object(folders, 'LUN', lun), \
             patch.object(folders, 'transfer_active', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'Upload'):
                folders.check_idle()


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lun = self.root / 'functions/mass_storage.usb0/lun.0'
        self.lun.mkdir(parents=True)
        for name, value in [('file', ''), ('cdrom', '1'), ('ro', '1')]:
            (self.lun / name).write_text(value)
        (self.root / 'UDC').write_text('configured')
        self.state = self.root / 'state.json'
        self.state.write_text('{"state":"connected"}')
        for name, value in {'GADGET': self.root, 'STATE': self.state, 'JOURNAL': self.root/'journal',
                            'IMAGE': self.root/'source.img'}.items():
            self.enterContext(patch.object(transfer, name, value))
        self.busy = self.enterContext(patch.object(transfer, 'busy', return_value=False))

    def test_stale_connected_and_configured_controller_are_not_media(self):
        with patch.object(subprocess, 'run', side_effect=AssertionError('status must not spawn')):
            for _ in range(100):
                status = wifi.usb_transfer_status()
                self.assertEqual(status['state'], 'ready')
                self.assertTrue(status['drive']['usb_connected'])
                self.assertFalse(status['drive']['transfer_active'])
        self.assertEqual(json.loads(self.state.read_text())['state'], 'connected')

    def test_missing_hardware_is_unknown_and_blocks_all_mutation(self):
        (self.lun / 'file').unlink()
        self.assertEqual(transfer.observe()['state'], 'unknown')
        with self.assertRaisesRegex(RuntimeError, 'inconnu'):
            usb.ensure_detached()
        with self.assertRaisesRegex(RuntimeError, 'inconnu'):
            folders.transfer_active()

    def test_interrupted_state_after_writer_disappears_and_after_reboot(self):
        self.state.write_text('{"state":"importing"}')
        self.assertEqual(transfer.observe()['state'], 'interrupted')
        self.busy.return_value = True
        self.assertEqual(transfer.observe()['state'], 'importing')
        self.busy.return_value = False
        self.state.unlink()
        transfer.JOURNAL.write_text('{"stage":"importing"}')
        self.assertEqual(transfer.observe()['state'], 'interrupted')

    def test_corrupt_state_is_diagnosed_without_trusting_old_value(self):
        self.state.write_text('{broken')
        status = transfer.observe()
        self.assertEqual(status['state'], 'ready')
        self.assertTrue(status['errors'])

    def test_repeated_stop_is_noop_and_never_ejects_media(self):
        with patch.object(usb, 'write_state'), patch.object(usb, 'run') as commands:
            usb.command_stop()
            usb.command_stop()
            commands.assert_not_called()
            (self.lun / 'file').write_text(str(transfer.IMAGE))
            with self.assertRaisesRegex(RuntimeError, 'Éjecter'):
                usb.command_stop()
            with self.assertRaisesRegex(RuntimeError, 'Éjecter'):
                usb.command_import()
            commands.assert_not_called()

    def test_reset_never_deletes_or_formats_source(self):
        with patch.object(usb, 'create_image') as create, patch.object(usb, 'run') as commands:
            with self.assertRaisesRegex(RuntimeError, 'désactivée'):
                usb.command_reset()
            create.assert_not_called()
            commands.assert_not_called()

    def test_start_refuses_unconfirmed_usb_reset_or_drive1_usage(self):
        transfer.IMAGE.write_bytes(b'retained source')
        other = self.root / 'other.img'
        other.write_bytes(b'SHARE data')
        lun1 = self.root / 'functions/mass_storage.usb1/lun.0/file'
        lun1.parent.mkdir(parents=True)
        lun1.write_text('')
        with patch.object(usb, 'IMAGE', transfer.IMAGE), patch.object(usb, 'LUN', self.lun), \
             patch.object(usb, 'UDC_FILE', self.root/'UDC'), patch.object(usb, 'ensure_no_local_access'), \
             patch.object(usb, 'ensure_idle_storage'), patch.object(usb, 'remount') as remount, \
             patch.object(usb, 'write_state'), patch.object(usb, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'allow-usb-reset'):
                usb.command_start()
            lun1.write_text(str(other))
            with self.assertRaisesRegex(RuntimeError, 'lecteur USB'):
                usb.command_start(True)
            self.assertEqual((self.root/'UDC').read_text(), 'configured')
            self.assertEqual(lun1.read_text(), str(other))
            run.assert_not_called()
            remount.assert_not_called()
        self.assertEqual(transfer.IMAGE.read_bytes(), b'retained source')

    def test_import_refuses_source_attached_to_drive1(self):
        transfer.IMAGE.write_bytes(b'retained source')
        lun1 = self.root / 'functions/mass_storage.usb1/lun.0/file'
        lun1.parent.mkdir(parents=True)
        lun1.write_text(str(transfer.IMAGE))
        with patch.object(usb, 'IMAGE', transfer.IMAGE), patch.object(usb, 'run') as commands:
            with self.assertRaisesRegex(RuntimeError, 'autre LUN'):
                usb.ensure_detached()
            commands.assert_not_called()


class FolderMutationTests(StorageFixture):
    def test_root_subfolder_unicode_spaces_move_back_and_directory_lifecycle(self):
        self.target.write_bytes(self.source.read_bytes())
        lun = self.root / 'lun'
        lun.write_text('')
        with patch.object(folders, 'ROOT', self.dest), patch.object(folders, 'LUN', lun), \
             patch.object(folders, 'transfer_active', return_value=False), patch.object(folders, 'run'):
            folders.execute('mkdir', {'name':'Dossier français', 'parent':''})
            folders.execute('mkdir', {'name':'Sous dossier', 'parent':'Dossier français'})
            result = folders.execute('move_file', {'source':self.target.name, 'folder':'Dossier français/Sous dossier'})
            self.assertEqual(result['path'], 'Dossier français/Sous dossier/' + self.target.name)
            self.assertFalse(self.target.exists())
            folders.execute('move_file', {'source':result['path'], 'folder':''})
            self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
            folders.execute('rename_file', {'source':self.target.name, 'name':'Renommée avec espaces.iso'})
            self.assertEqual((self.dest/'Renommée avec espaces.iso').read_bytes(), self.source.read_bytes())
            folders.execute('rmdir', {'path':'Dossier français/Sous dossier'})
            folders.execute('rename_dir', {'path':'Dossier français', 'name':'Vide'})
            folders.execute('rmdir', {'path':'Vide'})
            self.assertFalse((self.dest/'Vide').exists())
        self.assert_preserved()

    def test_collision_path_traversal_and_nonempty_directory_are_refused(self):
        self.target.write_bytes(b'existing')
        with patch.object(folders, 'ROOT', self.dest), patch.object(folders, 'check_idle'), patch.object(folders, 'run'):
            for bad in ('../escape', '/absolute', '.USB-TRANSFER.img', 'a\\b'):
                with self.assertRaises(ValueError):
                    folders.execute('mkdir', {'name':bad})
            (self.dest/'folder').mkdir()
            (self.dest/'folder'/'keep').write_bytes(b'preserve')
            with self.assertRaises(OSError):
                folders.execute('rmdir', {'path':'folder'})
            with self.assertRaises(FileExistsError):
                folders.execute('mkdir', {'name':'folder'})
        self.assertEqual(self.target.read_bytes(), b'existing')
        self.assert_preserved()


class LifecycleTests(StorageFixture):
    def test_privileged_children_inherit_storage_locks(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ('ok', None)
        with patch.object(transfer, 'LOCK_FDS', {102, 101}), patch.object(usb.subprocess, 'Popen', return_value=process) as spawn:
            usb.run(['fake helper'], capture=True)
        self.assertEqual(spawn.call_args.kwargs['pass_fds'], (101, 102))

    @unittest.skipIf(os.name == 'nt', 'Inherited flock after parent exit requires Linux')
    def test_child_holds_lock_after_parent_disappears(self):
        lock = self.root / 'lock'
        process = None
        try:
            with transfer.exclusive(lock):
                process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                           pass_fds=tuple(transfer.LOCK_FDS))
            self.assertTrue(transfer.busy(lock), 'Child must retain the same open file description')
        finally:
            if process:
                process.terminate()
                process.wait(timeout=5)
        self.assertFalse(transfer.busy(lock))

    def test_full_import_twice_no_global_usb_reset_no_source_recreation(self):
        with patch.object(usb, 'IMAGE', self.image), patch.object(usb, 'MOUNT', self.src), \
             patch.object(usb, 'ensure_detached'), patch.object(usb, 'ensure_idle_storage'), \
             patch.object(usb, 'ensure_no_local_access'), patch.object(usb, 'attach_image', return_value='/dev/loop99'), \
             patch.object(usb, 'remount') as remount, patch.object(usb, 'run') as run, \
             patch.object(usb, 'write_state') as state, patch.object(usb, 'create_image', side_effect=AssertionError('source destruction')):
            usb.command_import()
            usb.command_import()
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(state.call_args.args[0], 'done')
        self.assertEqual(remount.call_args.args, ('ro',))
        self.assertTrue(all(c.args[0][0] in ('mount', 'umount', 'losetup', 'fsck.exfat') for c in run.call_args_list))
        self.assert_preserved()

    def test_failed_unmount_does_not_detach_loop_or_report_success(self):
        def command(args, **_):
            if args[0] == 'umount':
                raise RuntimeError('busy mount')
        with patch.object(usb, 'IMAGE', self.image), patch.object(usb, 'MOUNT', self.src), \
             patch.object(usb, 'ensure_detached'), patch.object(usb, 'ensure_idle_storage'), \
             patch.object(usb, 'ensure_no_local_access'), patch.object(usb, 'attach_image', return_value='/dev/loop99'), \
             patch.object(usb, 'remount'), patch.object(usb, 'run', side_effect=command) as run, \
             patch.object(usb, 'write_state') as state:
            with self.assertRaisesRegex(RuntimeError, 'busy mount'):
                usb.command_import()
        self.assertFalse(any(c.args[0][:2] == ['losetup', '-d'] for c in run.call_args_list))
        self.assertEqual(state.call_args.args[0], 'error')
        self.assert_preserved()

    def test_prepare_existing_is_non_destructive_and_create_is_exclusive(self):
        with patch.object(usb, 'IMAGE', self.image), patch.object(usb, 'ensure_detached'), \
             patch.object(usb, 'ensure_no_local_access'), patch.object(usb, 'write_state'), \
             patch.object(usb, 'run') as run:
            usb.command_prepare()
            with self.assertRaises(FileExistsError):
                usb.create_image()
            run.assert_not_called()
        self.assert_preserved()

    def test_child_group_killed_even_when_leader_exits(self):
        proc = Mock(pid=123456)
        proc.communicate.side_effect = [subprocess.TimeoutExpired('fake', .1), ('', '')]
        proc.returncode = -15
        with patch.object(usb.subprocess, 'Popen', return_value=proc), \
             patch.object(usb.os, 'killpg', create=True) as kill, patch.object(usb.time, 'sleep'), \
             patch.object(usb.signal, 'SIGKILL', 9, create=True):
            with self.assertRaisesRegex(RuntimeError, 'Délai'):
                usb.run(['fake'], timeout=.1)
        self.assertEqual([c.args[1] for c in kill.call_args_list], [usb.signal.SIGTERM, 9])

    @unittest.skipIf(os.name == 'nt', 'Real flock requires Linux; CI scenario prepared')
    def test_concurrent_writer_and_stale_unlocked_file(self):
        lock = self.root / 'lock'
        with transfer.exclusive(lock):
            self.assertTrue(transfer.busy(lock))
            with self.assertRaisesRegex(RuntimeError, 'déjà'):
                with transfer.exclusive(lock):
                    self.fail('second writer entered')
        with transfer.exclusive(lock):
            pass  # Existing lock file is never mistaken for an active writer.


class AuthAndConcurrencyTests(unittest.TestCase):
    def test_share_and_portable_limit_worker_admission_without_unbounded_threads(self):
        auth = load('pikvm-share-api')
        with auth.Server(('127.0.0.1', 0), auth.Handler) as server:
            for _ in range(8):
                self.assertTrue(server.slots.acquire(blocking=False))
            with patch.object(server, 'shutdown_request') as close:
                server.process_request('fake ninth connection', ('127.0.0.1', 1))
                close.assert_called_once_with('fake ninth connection')
            for _ in range(8):
                server.slots.release()

    def test_wifi_auth_and_csrf_reuse_real_share_rules(self):
        auth = load('pikvm-share-api')
        with patch.object(wifi, 'AUTH', auth):
            for missing in ({}, {'Cookie': 'auth_token=' + 'a'*64}):
                with patch.object(auth, 'authenticate', side_effect=auth.ShareError('denied', 401)):
                    with self.assertRaises(auth.ShareError):
                        wifi.authorize(missing, True)
            with patch.object(auth, 'authenticate'):
                with self.assertRaises(auth.ShareError):
                    wifi.authorize({}, True)
                with self.assertRaises(auth.ShareError):
                    wifi.authorize({'X-Pikvm-Share':'1', 'Origin':'https://other', 'X-Share-Origin':'https://pi'}, True)
                wifi.authorize({'X-Pikvm-Share':'1', 'Origin':'https://pi', 'X-Share-Origin':'https://pi'}, True)

    def test_long_request_does_not_block_status_and_unauthenticated_mutation_refused(self):
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set()
            release.wait(3)
            return {}
        with wifi.ReuseTCPServer(('127.0.0.1', 0), wifi.Handler) as server, \
             patch.object(wifi, 'authorize'), patch.object(wifi, 'wifi_status', side_effect=slow), \
             patch.object(wifi, 'usb_transfer_status', return_value={'state': 'ready'}):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def request_slow():
                conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                try:
                    conn.request('GET', '/api/status')
                    conn.getresponse().read()
                finally:
                    conn.close()
            worker = threading.Thread(target=request_slow)
            worker.start()
            self.assertTrue(entered.wait(2))
            conn = http.client.HTTPConnection(*server.server_address, timeout=2)
            try:
                conn.request('GET', '/api/usb-transfer/status')
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())['transfer']['state'], 'ready')
                with patch.object(wifi, 'authorize', side_effect=SimpleDenied('denied')), \
                     patch.object(wifi, 'usb_transfer_run') as mutation:
                    conn.close()
                    conn = http.client.HTTPConnection(*server.server_address, timeout=2)
                    conn.request('POST', '/api/usb-transfer/start', '{}')
                    response = conn.getresponse()
                    self.assertEqual(response.status, 401)
                    response.read()
                    mutation.assert_not_called()
            finally:
                conn.close()
                release.set()
                worker.join(5)
                server.shutdown()
                thread.join(5)


class SimpleDenied(Exception):
    status = 401


class WifiPersistenceTests(unittest.TestCase):
    def test_priority_injection_and_invalid_credentials_are_refused(self):
        for value in ('10\npsk=evil', '1;systemctl poweroff', '10000', 'nan'):
            with self.assertRaises(ValueError):
                wifi.checked_priority(value)
        self.assertEqual(wifi.checked_priority('-20'), '-20')
        for ssid, password in [('bad\nssid', 'eightchars'), ('x'*33, 'eightchars'), ('ok', 'short')]:
            with patch.object(wifi, 'run') as command:
                with self.assertRaises(ValueError):
                    wifi.generate_network(ssid, password)
                command.assert_not_called()

    def test_password_sent_on_stdin_never_in_command_arguments(self):
        with patch.object(wifi, 'run', return_value=SimpleNamespace(returncode=0)) as command:
            wifi.generate_network('Test SSID', 'secret-example')
        self.assertEqual(command.call_args.args[0], ['wpa_passphrase', 'Test SSID'])
        self.assertEqual(command.call_args.kwargs['input_text'], 'secret-example\n')

    def test_atomic_config_and_unique_durable_private_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wifi.conf'
            path.write_text('original config\n')
            with patch.object(wifi, 'CONF', path):
                first, second = Path(wifi.backup_conf()), Path(wifi.backup_conf())
                self.assertNotEqual(first, second)
                wifi.write_conf(['new config'])
                self.assertEqual(path.read_text(), 'new config\n')
                self.assertEqual(first.read_text(), 'original config\n')
                with patch.object(wifi.os, 'fsync', side_effect=OSError('EIO')):
                    with self.assertRaises(OSError):
                        wifi.write_conf(['corrupt candidate'])
                self.assertEqual(path.read_text(), 'new config\n')

    def test_failed_wifi_restart_is_not_reported_as_success(self):
        with patch.object(wifi, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, 'échoué'):
                wifi.restart_wifi_service()


class PowerStorageTests(unittest.TestCase):
    def test_queued_poweroff_blocks_new_custom_storage_until_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(transfer, 'POWER_MARKER', root/'marker'), \
                 patch.object(transfer, 'STORAGE_LOCK', root/'lock'), \
                 patch.object(transfer, 'exclusive', return_value=contextlib.nullcontext()), \
                 patch.object(transfer, 'require_idle_for_power') as check:
                transfer.reserve_poweroff()
                check.assert_called_once()
                with self.assertRaisesRegex(RuntimeError, 'Arrêt demandé'):
                    transfer.require_not_stopping()
                self.assertEqual(json.loads((root/'marker').read_text())['reason'], 'explicit-poweroff')

    def test_backend_power_guard_blocks_busy_unknown_lease_and_either_drive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in (0, 1):
                file = root / f'functions/mass_storage.usb{index}/lun.0/file'
                file.parent.mkdir(parents=True)
                file.write_text('')
            lease = root / 'lease'
            state = {'state': 'ready', 'busy': False}
            with patch.object(transfer, 'GADGET', root), patch.object(transfer, 'ROOT', root), \
                 patch.object(transfer, 'SHARE_LEASE', lease), patch.object(transfer, 'observe', return_value=state):
                transfer.require_idle_for_power()
                for key, value in [('busy', True), ('state', 'unknown')]:
                    old = state[key]
                    state[key] = value
                    with self.assertRaises(RuntimeError):
                        transfer.require_idle_for_power()
                    state[key] = old
                lease.touch()
                with self.assertRaises(RuntimeError):
                    transfer.require_idle_for_power()
                lease.unlink()
                for index in (0, 1):
                    file = root / f'functions/mass_storage.usb{index}/lun.0/file'
                    file.write_text('live.iso')
                    with self.assertRaises(RuntimeError):
                        transfer.require_idle_for_power()
                    file.write_text('')


if __name__ == '__main__':
    unittest.main()
