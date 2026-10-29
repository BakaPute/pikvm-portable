"""Safe stdlib tests: no real image, Linux mounts, GPIO or PiKVM connection."""
import contextlib
import errno
from email.message import Message
import http.client
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(ROOT / 'scripts' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


api = load('pikvm-share-api')
installer = load('pikvm-share-install')


class FakeBackend:
    def __init__(self, root):
        self.mount = root
        self.attached = False
        self.mounted = False
        self.lease = None
        self.events = []
        self.fail_unmount = False
        self.fail_mount = False

    def validate_image(self):
        pass

    def lease_read(self):
        return self.lease

    def drive(self):
        return 'image' if self.attached else ''

    def ensure_unmounted(self):
        if self.mounted:
            raise api.ShareError('Already mounted')

    def mounted_owned(self, lease):
        if not self.mounted or not lease:
            raise api.ShareError('Not owned')

    def reserve(self):
        self.events.append('reserve')
        self.lease = {'loop': 'fake', 'auto_active': True}

    def release(self):
        self.events.append('release')
        self.lease = None

    def mount_image(self):
        if self.attached:
            raise AssertionError('Concurrent exFAT access')
        self.events.append('mount')
        if self.fail_mount:
            raise api.ShareError('Dirty volume')
        self.mounted = True

    def unmount_image(self):
        self.events.append('unmount')
        if self.attached or self.fail_unmount:
            raise api.ShareError('Busy')
        self.mounted = False

    def attach(self):
        if self.mounted:
            raise AssertionError('Concurrent exFAT access')
        self.events.append('attach')
        self.attached = True


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = FakeBackend(self.root)
        self.control = api.Controller(self.backend)
        self.commands = patch.object(api, 'command', return_value='').start()
        self.addCleanup(patch.stopall)

    def web(self):
        self.control.web(True)

    def test_web_requires_explicit_ejection_confirmation(self):
        for value in (False, None, 1, 'true'):
            with self.assertRaises(api.ShareError):
                self.control.web(value)
        self.assertEqual(self.backend.events, [])

    def test_attached_usb_cannot_mount_even_if_confirmed(self):
        self.backend.attached = True
        with self.assertRaises(api.ShareError):
            self.web()
        self.assertFalse(self.backend.mounted)
        self.assertEqual(self.backend.events, [])

    def test_web_unmounts_before_usb_attach(self):
        self.web()
        self.control.usb()
        self.assertEqual(self.backend.events, ['reserve', 'mount', 'unmount', 'attach'])
        self.assertFalse(self.backend.mounted)
        self.assertIsNotNone(self.backend.lease)

    def test_busy_unmount_prevents_attach_and_requires_recovery(self):
        self.web()
        self.backend.fail_unmount = True
        with self.assertRaises(api.ShareError):
            self.control.usb()
        self.assertFalse(self.backend.attached)
        self.assertNotIn('attach', self.backend.events)
        self.assertEqual(self.control.mode, 'error')
        self.backend.fail_unmount = False
        self.control.recover()
        self.assertEqual(self.control.mode, 'detached')
        self.assertIsNone(self.backend.lease)

    def test_dirty_image_keeps_recovery_reservation(self):
        self.backend.fail_mount = True
        with self.assertRaises(api.ShareError):
            self.web()
        self.assertEqual(self.control.mode, 'error')
        self.assertIsNotNone(self.backend.lease)
        with self.assertRaises(api.ShareError):
            self.control.usb()

    def test_restart_never_assumes_old_mount_is_safe(self):
        self.web()
        restarted = api.Controller(self.backend)
        self.assertEqual(restarted.mode, 'error')
        with self.assertRaises(api.ShareError):
            restarted.files('')
        restarted.recover()
        self.assertFalse(self.backend.mounted)

    def test_concurrent_operation_is_rejected(self):
        with self.control.operation():
            with self.assertRaises(api.ShareError) as error:
                with self.control.operation():
                    pass
        self.assertEqual(error.exception.status, 423)

    def test_unexpected_usb_reconnection_blocks_reads(self):
        self.web()
        self.backend.attached = True
        with self.assertRaises(api.ShareError):
            self.control.files('')
        self.assertEqual(self.control.mode, 'error')

    def test_lost_mount_enters_error_and_can_recover(self):
        self.web()
        self.backend.mounted = False
        with self.assertRaises(api.ShareError):
            self.control.files('')
        self.assertEqual(self.control.mode, 'error')
        self.control.recover()
        self.assertEqual(self.control.mode, 'detached')

    def test_file_operations_and_nonempty_directory(self):
        self.web()
        self.control.mutate('mkdir', {'name': 'Données'})
        self.control.mutate('create-file', {'parent': 'Données', 'name': 'vide.txt'})
        self.control.mutate('rename', {'path': 'Données/vide.txt', 'name': 'été.txt'})
        self.assertEqual(self.control.files('Données')['items'][0]['name'], 'été.txt')
        with self.assertRaises(OSError):
            self.control.mutate('delete', {'path': 'Données'})
        self.control.mutate('delete', {'path': 'Données/été.txt'})
        self.control.mutate('delete', {'path': 'Données'})
        self.assertFalse((self.root / 'Données').exists())

    def test_case_collision_never_overwrites(self):
        self.web()
        (self.root / 'File.txt').write_text('original')
        with self.assertRaises(api.ShareError):
            self.control.mutate('create-file', {'name': 'file.TXT'})
        self.assertEqual((self.root / 'File.txt').read_text(), 'original')

    def test_upload_order_size_owner_finish_and_mode_lock(self):
        self.web()
        upload = self.control.begin_upload({'name': 'test.bin', 'size': 4}, 'owner')['id']
        for owner, offset, data in [('other', 0, b'ab'), ('owner', 2, b'ab'), ('owner', 0, b'12345')]:
            with self.assertRaises(api.ShareError):
                self.control.upload_chunk(upload, owner, offset, data)
        with self.assertRaises(api.ShareError):
            self.control.usb()
        # An active import is a normal conflict, preserving the valid Web session.
        self.assertFalse(self.backend.attached)
        self.assertEqual(self.control.mode, 'web')
        self.assertEqual(self.control.upload_chunk(upload, 'owner', 0, b'ab')['offset'], 2)
        with self.assertRaises(api.ShareError):
            self.control.finish_upload(upload, 'owner')
        self.control.upload_chunk(upload, 'owner', 2, b'cd')
        self.control.finish_upload(upload, 'owner')
        self.assertEqual((self.root / 'test.bin').read_bytes(), b'abcd')

    def test_upload_cancel_and_expiration(self):
        self.web()
        ident = self.control.begin_upload({'name': 'a', 'size': 5}, 'owner')['id']
        temp = self.control.uploads[ident]['temp']
        self.control.cancel_upload(ident, 'owner')
        self.assertFalse(temp.exists())
        ident = self.control.begin_upload({'name': 'b', 'size': 0}, 'owner')['id']
        self.control.uploads[ident]['updated'] -= 1000
        self.control.expire_uploads()
        self.assertFalse(self.control.uploads)

    def test_upload_disk_full_removes_unpublished_partial(self):
        self.web()
        ident = self.control.begin_upload({'name': 'full.bin', 'size': 4}, 'owner')['id']
        temp = self.control.uploads[ident]['temp']
        with patch.object(Path, 'open', side_effect=OSError(errno.ENOSPC, 'full')):
            with self.assertRaises(OSError):
                self.control.upload_chunk(ident, 'owner', 0, b'abcd')
        self.assertNotIn(ident, self.control.uploads)
        self.assertFalse(temp.exists())
        self.assertFalse((self.root / 'full.bin').exists())

    def test_insufficient_space_rejected_before_upload_file_creation(self):
        self.web()
        with patch.object(api.os, 'statvfs', create=True,
                          return_value=SimpleNamespace(f_bavail=1024**2, f_frsize=1)):
            with self.assertRaises(api.ShareError) as error:
                self.control.begin_upload({'name': 'too-big', 'size': 1}, 'owner')
        self.assertEqual(error.exception.status, 507)
        self.assertFalse(list(self.root.iterdir()))

    def test_zero_byte_upload_and_hidden_files(self):
        self.web()
        ident = self.control.begin_upload({'name': '.hidden', 'size': 0}, 'owner')['id']
        self.assertFalse(self.control.files('')['items'])
        self.control.finish_upload(ident, 'owner')
        self.assertEqual(self.control.files('')['items'][0]['size'], 0)

    def test_parent_rename_blocked_during_upload(self):
        self.web()
        self.control.mutate('mkdir', {'name': 'dir'})
        self.control.begin_upload({'parent': 'dir', 'name': 'a', 'size': 0}, 'owner')
        with self.assertRaises(api.ShareError):
            self.control.mutate('rename', {'path': 'dir', 'name': 'other'})


class PathTests(unittest.TestCase):
    def test_invalid_exfat_names(self):
        for name in ('', '.', '..', '../x', '/etc', 'a\\b', 'a:b', 'x\x00', 'x\n',
                     'a.', 'a ', 'CON.txt', 'LPT1', api.TEMP_PREFIX + 'x', 'x' * 256):
            with self.subTest(name=name), self.assertRaises(api.ShareError):
                api.safe_name(name)

    def test_valid_unicode_and_hidden_names(self):
        for name in ('école.txt', '.hidden', '日本語', 'test file.txt'):
            self.assertEqual(api.safe_name(name), name)

    def test_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value in ('../x', '/etc/passwd', 'a//b', 'a/./b', 'a/../b', ''):
                with self.subTest(value=value), self.assertRaises(api.ShareError):
                    api.safe_path(root, value)
            self.assertEqual(api.safe_path(root, '', True), root)


def headers(**values):
    message = Message()
    for key, value in values.items():
        message[key.replace('_', '-')] = value
    return message


class AuthTests(unittest.TestCase):
    def test_missing_invalid_and_expired_session(self):
        for value in ('', 'other=x', 'auth_token=short'):
            with self.assertRaises(api.ShareError):
                api.authenticate(headers(Cookie=value), lambda token=None: 401)
        with self.assertRaises(api.ShareError):
            api.authenticate(headers(Cookie='auth_token=' + 'a' * 64), lambda token=None: 403)

    def test_valid_session_and_disabled_auth_rejected(self):
        cookie = headers(Cookie='auth_token=' + 'a' * 64)
        self.assertEqual(len(api.authenticate(cookie, lambda token=None: 200 if token else 401)), 64)
        with self.assertRaises(api.ShareError) as error:
            api.authenticate(cookie, lambda token=None: 200)
        self.assertEqual(error.exception.status, 503)

    def test_csrf(self):
        for values in ({}, {'X_Pikvm_Share': '1', 'Origin': 'null'},
                       {'X_Pikvm_Share': '1', 'Origin': 'https://evil', 'X_Share_Origin': 'https://pikvm'},
                       {'X_Pikvm_Share': '1', 'Sec_Fetch_Site': 'cross-site'}):
            with self.assertRaises(api.ShareError):
                api.check_csrf(headers(**values))
        api.check_csrf(headers(X_Pikvm_Share='1', Origin='https://pikvm', X_Share_Origin='https://pikvm'))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = FakeBackend(Path(self.temp.name))
        self.server = api.Server(('127.0.0.1', 0), api.Handler)
        self.server.controller = api.Controller(self.backend)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        original_auth = api.authenticate
        self.auth_patch = patch.object(api, 'authenticate', side_effect=lambda h:
            original_auth(h, lambda token=None: 200 if token == 'a' * 64 else 401))
        self.auth_patch.start()
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.auth_patch.stop()

    def request(self, action, method='GET', body=None, authenticated=True, extra=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        request_headers = {'Cookie': 'auth_token=' + 'a' * 64} if authenticated else {}
        if method == 'POST':
            request_headers.update({'Content-Type': 'application/json', 'X-Pikvm-Share': '1'})
        request_headers.update(extra or {})
        connection.request(method, '/extras/pikvm-share/api/' + action,
                           body if isinstance(body, bytes) else json.dumps(body) if body is not None else None,
                           request_headers)
        response = connection.getresponse()
        status, values, payload = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, values, payload

    def test_every_read_route_requires_auth(self):
        for route in ('status', 'files', 'download?path=test'):
            self.assertEqual(self.request(route, authenticated=False)[0], 401)

    def test_mutation_requires_auth_and_csrf_before_controller(self):
        for route in ('mode/web', 'mode/usb', 'recover', 'mkdir', 'delete', 'upload/begin'):
            self.assertEqual(self.request(route, 'POST', {}, authenticated=False)[0], 401)
        self.assertEqual(self.request('mode/web', 'POST', {'ejected': True},
                                      extra={'X-Pikvm-Share': ''})[0], 403)
        self.assertFalse(self.backend.events)

    def test_http_web_switch_listing_download_sandbox_and_error(self):
        with patch.object(api, 'command', return_value=''):
            self.assertEqual(self.request('mode/web', 'POST', {'ejected': True})[0], 200)
            self.assertEqual(self.request('create-file', 'POST', {'name': 'x.html'})[0], 200)
            path = self.backend.mount / 'x.html'
            path.write_bytes(b'<script>bad()</script>')
            status, values, data = self.request('download?path=x.html')
            self.assertEqual(status, 200)
            self.assertEqual(data, path.read_bytes())
            self.assertTrue(values['Content-Disposition'].startswith('attachment;'))
            self.assertIn('sandbox', values['Content-Security-Policy'])
            self.assertEqual(values['Content-Type'], 'application/octet-stream')
            self.assertEqual(self.request('files?path=../etc')[0], 400)
            self.assertEqual(self.request('unknown')[0], 404)

    def test_preflight_never_enables_cors(self):
        status, values, _ = self.request('mode/web', 'OPTIONS')
        self.assertEqual(status, 501)
        self.assertNotIn('Access-Control-Allow-Origin', values)

    def test_full_upload_protocol_over_http(self):
        with patch.object(api, 'command', return_value=''):
            self.assertEqual(self.request('mode/web', 'POST', {'ejected': True})[0], 200)
            status, _, body = self.request('upload/begin', 'POST', {'name': 'upload.bin', 'size': 4})
            self.assertEqual(status, 200)
            ident = json.loads(body)['result']['id']
            self.assertEqual(self.request('upload/chunk?id=' + ident + '&offset=0', 'POST', b'abcd',
                extra={'Content-Type': 'application/octet-stream'})[0], 200)
            self.assertEqual(self.request('upload/finish', 'POST', {'id': ident})[0], 200)
            self.assertEqual(self.request('download?path=upload.bin')[2], b'abcd')

    def test_invalid_json_and_oversized_body(self):
        self.assertEqual(self.request('mode/web', 'POST', b'{')[0], 400)
        self.assertEqual(self.request('mode/web', 'POST', b'',
                                      extra={'Content-Length': str(2 * 1024**2)})[0], 413)


class NativeSafetyTests(unittest.TestCase):
    def test_original_helper_keeps_required_basename(self):
        self.assertEqual(Path(api.ORIGINAL_HELPER).name, 'kvmd-helper-otgmsd-remount')
        self.assertIn(api.ORIGINAL_HELPER, (ROOT / 'scripts/pikvm-share-remount').read_text())

    def test_drive_one_other_image_and_share_on_drive_zero_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lun = root / 'lun'
            lun.mkdir()
            (lun / 'removable').write_text('1')
            image, other = root / 'share', root / 'other'
            image.touch()
            other.touch()
            backend = api.LinuxBackend()
            backend.image = image
            with patch.object(api, 'LUN', lun):
                for values in ({str(lun / 'file'): str(other)},
                               {str(lun / 'file'): '', '/drive0/file': str(image)}):
                    with patch.object(backend, 'luns', return_value=values), self.assertRaises(api.ShareError):
                        backend.drive()

    def test_mount_offline_fsck_precedes_mount_and_only_n_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = api.LinuxBackend()
            backend.mount = Path(directory) / 'mnt'
            lease = {'loop': None, 'device': None}
            events = []
            def run(args, **kwargs):
                events.append(args)
                if args[0] == 'losetup':
                    return '/dev/loop7'
                if args[0] == 'lsblk':
                    return json.dumps({'blockdevices': [{'name': '/dev/loop7', 'children': []}]})
                return ''
            probe = type('Probe', (), {'returncode': 0, 'stdout': 'exfat\n'})
            with patch.object(backend, 'lease_read', return_value=lease), \
                 patch.object(backend, 'lease_write'), patch.object(backend, 'validate_image'), \
                 patch.object(backend, 'drive', return_value=''), patch.object(backend, 'ensure_unmounted'), \
                 patch.object(backend, 'mounted_owned'), patch.object(api, 'command', side_effect=run), \
                 patch.object(api.subprocess, 'run', return_value=probe):
                backend.mount_image()
            fsck = next(i for i, args in enumerate(events) if args[0] == 'fsck.exfat')
            mount = next(i for i, args in enumerate(events) if args[0] == 'mount')
            self.assertLess(fsck, mount)
            self.assertEqual(events[fsck], ['fsck.exfat', '-n', '/dev/loop7'])
            self.assertNotIn('mkfs.exfat', [args[0] for args in events])

    def test_busy_native_umount_never_detaches_loop(self):
        backend = api.LinuxBackend()
        def run(args, **kwargs):
            if args[0] == 'umount':
                raise api.ShareError('Busy')
            return ''
        with patch.object(backend, 'lease_read', return_value={'loop': '/dev/loop7'}), \
             patch.object(backend, 'drive', return_value=''), patch.object(backend, 'loops', return_value=['/dev/loop7']), \
             patch.object(backend, 'is_mounted', return_value=True), patch.object(backend, 'mounted_owned'), \
             patch.object(api.os, 'walk', return_value=[]), patch.object(api, 'command', side_effect=run) as commands:
            with self.assertRaises(api.ShareError):
                backend.unmount_image()
        self.assertFalse(any(args.args[0][0] == 'losetup' for args in commands.call_args_list))

    def test_remount_guard_defers_only_ro_and_preserves_args(self):
        if api.fcntl is None:
            with patch.dict('sys.modules', {'fcntl': Mock()}):
                guard = load('pikvm-share-remount')
        else:
            guard = load('pikvm-share-remount')
        fake_file = Mock()
        with patch.object(guard.os, 'open', return_value=55), \
             patch.object(guard.os, 'O_NOFOLLOW', 0, create=True), \
             patch.object(guard.os, 'fdopen', return_value=contextlib.nullcontext(fake_file)), \
             patch.object(guard.fcntl, 'flock'), \
             patch.object(guard, 'LEASE') as lease, patch.object(guard.subprocess, 'run') as process:
            lease.exists.return_value = True
            with patch.object(guard.sys, 'argv', ['helper', 'ro']):
                self.assertEqual(guard.main(), 0)
            process.assert_not_called()
            process.return_value.returncode = 0
            with patch.object(guard.sys, 'argv', ['helper', 'rw']):
                self.assertEqual(guard.main(), 0)
            process.assert_called_once_with([guard.ORIGINAL, 'rw'], check=False)

    def test_installer_rolls_back_original_helper_and_web_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / 'kvmd-helper-otgmsd-remount'
            target = root / 'web.html'
            source = root / 'new.html'
            original = root / 'native' / helper.name
            helper.write_bytes(b'installed native with compatibility fixes')
            target.write_bytes(b'existing web integration')
            source.write_bytes(b'new share page')
            fake = type('Module', (), {'ORIGINAL_HELPER': str(original)})
            mapping = {helper: (ROOT / 'scripts/pikvm-share-remount', 0o755), target: (source, 0o644)}
            with patch.object(installer, 'check'), patch.object(installer, 'helper_path', return_value=helper), \
                 patch.object(installer, 'file_map', return_value=mapping), \
                 patch.object(installer, 'BACKUPS', root / 'backups'), \
                 patch.object(installer, 'service_state', return_value={'active': False, 'enabled': False}), \
                 patch.object(installer, 'offline', return_value=contextlib.nullcontext()), \
                 patch.object(installer, 'assert_idle'), patch.object(installer, 'run', return_value=''), \
                 patch.object(installer.subprocess, 'run'), \
                 patch.object(installer.os, 'chown', create=True), \
                 patch.object(installer, 'reload_nginx'), \
                 patch.object(installer, 'nginx_config', side_effect=RuntimeError('invalid nginx')), \
                 patch('sys.stdout', new_callable=io.StringIO):
                with self.assertRaises(RuntimeError):
                    installer.install(fake)
            self.assertEqual(helper.read_bytes(), b'installed native with compatibility fixes')
            self.assertEqual(target.read_bytes(), b'existing web integration')
            self.assertFalse(original.exists())

    def test_backend_attach_is_explicit_drive_one(self):
        backend = api.LinuxBackend()
        with patch.object(backend, 'validate_image'), patch.object(backend, 'ensure_unmounted'), \
             patch.object(backend, 'drive', side_effect=['', str(api.IMAGE)]), \
             patch.object(api, 'command', return_value='') as run:
            backend.attach()
        args = run.call_args.args[0]
        self.assertEqual(args[:3], ['kvmd-otgmsd', '-i', '1'])
        self.assertNotIn('--eject', args)

    def test_no_loop_created_when_drive_attached(self):
        backend = api.LinuxBackend()
        with patch.object(backend, 'lease_read', return_value={}), patch.object(backend, 'validate_image'), \
             patch.object(backend, 'drive', return_value=str(api.IMAGE)), \
             patch.object(api, 'command') as run:
            with self.assertRaises(api.ShareError):
                backend.mount_image()
        run.assert_not_called()

    def test_symlink_names_are_blocked_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'target').mkdir()
            try:
                (root / 'link').symlink_to(root / 'target', target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation requires Windows developer mode')
            with self.assertRaises(api.ShareError):
                api.safe_path(root, 'link/x')

    def test_all_new_scripts_and_diagnostic_use_lf(self):
        paths = list((ROOT / 'scripts').glob('pikvm-share-*')) + [ROOT / 'install-share.sh']
        for path in paths:
            self.assertNotIn(b'\r', path.read_bytes(), str(path))

    def test_installer_backup_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, dest = root / 'source', root / 'dest'
            source.write_bytes(b'image')
            fake = type('Module', (), {'IMAGE': root / 'msd' / 'image', 'SIZE': 5})
            value = installer.copy_image(fake, source, dest)
            self.assertEqual(installer.digest(dest), value)
            with self.assertRaises(RuntimeError):
                installer.copy_image(fake, source, dest)


if __name__ == '__main__':
    unittest.main()
