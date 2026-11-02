"""Portable OS security/USB/policy tests. No PiKVM access or real system commands."""
import contextlib
import http.client
import importlib.machinery
import importlib.util
import io
import json
import re
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(ROOT / 'scripts' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


api = load('pikvm-portable-api')
installer = load('pikvm-portable-install')


class PolicyTests(unittest.TestCase):
    def test_narrow_patch_preserves_python_fixes_and_is_idempotent(self):
        source = '''# Custom Python 3.14 compatibility fix retained
import asyncio
class Backend:
    def release(self):
        if True:
            command([
                'systemctl', 'start', AUTO_SERVICE,
            ])
        self.lease.unlink(missing_ok=True)
'''
        result = installer.manual_shutdown_policy(source)
        self.assertIn('# Custom Python 3.14 compatibility fix retained\nimport asyncio', result)
        self.assertNotIn("'systemctl', 'start'", result)
        self.assertIn('self.lease.unlink(missing_ok=True)', result)
        self.assertEqual(result, installer.manual_shutdown_policy(result))

    def test_historical_lease_never_restarts_disabled_auto_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = api.share.LinuxBackend()
            backend.lease = Path(directory) / 'lease.json'
            backend.lease.write_text('{"auto_active": true}')
            with patch.object(api.share, 'storage_lock', return_value=contextlib.nullcontext()), \
                 patch.object(api.share, 'command') as command:
                backend.release()
            command.assert_not_called()
            self.assertFalse(backend.lease.exists())

    def test_unknown_shell_restart_is_rejected_instead_of_overwriting_local_fixes(self):
        with self.assertRaisesRegex(RuntimeError, 'non reconnu'):
            installer.manual_shutdown_policy('run("systemctl start pikvm-auto-shutdown.service", shell=True)\n')

    def test_no_gpio_or_gadget_writes_in_integration(self):
        source = (ROOT / 'scripts/pikvm-portable-api').read_text()
        self.assertNotIn('pinctrl', source)
        self.assertNotIn('kvmd-otgmsd', source)
        self.assertNotIn('mkfs', source)

    def test_legacy_installer_also_preserves_manual_shutdown_policy(self):
        source = (ROOT / 'install.sh').read_text()
        self.assertIsNone(re.search(r'^\s*systemctl\s+(enable|start|restart)\s+.*pikvm-auto-shutdown', source, re.M))


class DiagnosticTests(unittest.TestCase):
    def test_usb_attributes_and_unknown_windows_mount_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gadget = root / 'gadget'
            controllers = root / 'controllers'
            (gadget / 'configs').mkdir(parents=True)
            lun = gadget / 'functions/mass_storage.usb1/lun.0'
            lun.mkdir(parents=True)
            for name, value in {'file': '/image', 'cdrom': '0', 'ro': '0', 'removable': '1', 'nofua': '0'}.items():
                (lun / name).write_text(value)
            (gadget / 'UDC').write_text('controller.0')
            (controllers / 'controller.0').mkdir(parents=True)
            (controllers / 'controller.0/state').write_text('configured')
            result = api.SystemBackend(gadget, controllers).usb()
            self.assertTrue(result['host_configured'])
            self.assertEqual(result['drives']['1']['attributes']['file'], '/image')
            self.assertIsNone(result['windows']['mounted'])
            self.assertIsNone(result['windows']['drive_letter'])
            self.assertFalse(result['drives']['0']['present'])

    def test_log_unit_injection_rejected_before_any_command(self):
        with patch.object(api, 'run') as command:
            with self.assertRaises(api.share.ShareError):
                api.SystemBackend().logs('kvmd.service; reboot')
        command.assert_not_called()

    def test_password_token_and_hotspot_pass_are_masked(self):
        for value in ('password=abc', 'PASS : abc', 'auth_token=abc', 'Authorization: Basic xyz', 'psk=xyz'):
            self.assertNotIn('abc', api.redact(value))
            self.assertIn('masquée', api.redact(value))
        self.assertEqual(api.redact('Normal device information'), 'Normal device information')

    def test_hotspot_only_uses_existing_script_and_does_not_return_its_password(self):
        with patch.object(api, 'run', return_value='PASS : should never be returned') as command:
            result = api.SystemBackend().hotspot(True)
        self.assertNotIn('PASS', json.dumps(result))
        self.assertEqual(command.call_args.args[0], ['/usr/local/bin/pikvm-hotspot', 'on'])


class IntegrationAuthTests(unittest.TestCase):
    def setUp(self):
        self.server = api.share.Server(('127.0.0.1', 0), api.Handler)
        self.server.backend = type('Backend', (), {'status': lambda self: {'safe': True},
            'usb': lambda self: {}, 'logs': lambda self, unit: {}, 'hotspot': lambda self, enabled: {'requested': enabled},
            'oled': lambda self: {'source': 'menu'}, 'oled_short': lambda self, frame_id: {'accepted': True},
            'oled_event': lambda self, data, owner: {'accepted': True}})()
        self.server.action_lock = threading.Lock()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        original = api.share.authenticate
        self.auth = patch.object(api.share, 'authenticate', side_effect=lambda headers:
            original(headers, lambda token=None: 200 if token == 'a' * 64 else 401))
        self.auth.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.auth.stop()

    def request(self, path, post=None, auth=True, csrf=True):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        headers = {'Cookie': 'auth_token=' + 'a' * 64} if auth else {}
        if post is not None:
            headers['Content-Type'] = 'application/json'
            if csrf:
                headers['X-Pikvm-Share'] = '1'
        # Send this small fixture request as one packet. The zero-latency mocked
        # auth can otherwise close HTTP/1.0 before http.client sends its body,
        # producing a Windows TCP reset instead of the intended denial response.
        body = json.dumps(post).encode() if post is not None else b''
        headers.update({'Host': 'localhost', 'Content-Length': str(len(body))})
        request = ('POST' if post is not None else 'GET') + ' /extras/portable-os/api/' + path + ' HTTP/1.0\r\n'
        request += ''.join(name + ': ' + value + '\r\n' for name, value in headers.items()) + '\r\n'
        connection.connect()
        connection.sock.sendall(request.encode() + body)
        response = http.client.HTTPResponse(connection.sock)
        response.begin()
        status = response.status
        response.read()
        connection.close()
        return status

    def test_all_read_routes_require_native_session(self):
        for path in ('status', 'usb', 'logs?unit=kvmd.service', 'oled'):
            self.assertEqual(self.request(path, auth=False), 401)
        self.assertEqual(self.request('status'), 200)

    def test_oled_short_requires_auth_csrf_and_exact_short_action(self):
        short = {'action': 'short', 'frame_id': 'a' * 64}
        self.assertEqual(self.request('oled/short', short, auth=False), 401)
        self.assertEqual(self.request('oled/short', short, csrf=False), 403)
        self.assertEqual(self.request('oled/short', {'action': 'long', 'frame_id': 'a' * 64}), 400)
        self.assertEqual(self.request('oled/short', {**short, 'duration': 5}), 400)
        self.assertEqual(self.request('oled/short', short), 200)

    def test_held_button_requires_auth_csrf_and_forbids_owner_or_duration_forgery(self):
        start = {'action':'start','gesture_id':'a'*32,'control_id':'b'*64,'permit':''}
        self.assertEqual(self.request('oled/button',start,auth=False),401)
        self.assertEqual(self.request('oled/button',start,csrf=False),403)
        self.assertEqual(self.request('oled/button',{**start,'owner':'fake'}),400)
        self.assertEqual(self.request('oled/button',{**start,'duration':5}),400)
        self.assertEqual(self.request('oled/button',start),200)

    def test_network_change_requires_session_csrf_and_explicit_confirmation(self):
        self.assertEqual(self.request('hotspot', {'enabled': True}, auth=False), 401)
        self.assertEqual(self.request('hotspot', {'enabled': True}, csrf=False), 403)
        self.assertEqual(self.request('hotspot', {'enabled': True}), 400)
        self.assertEqual(self.request('hotspot', {'enabled': True, 'confirmed': True}), 200)


if __name__ == '__main__':
    unittest.main()
