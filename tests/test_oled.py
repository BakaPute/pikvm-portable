"""OLED rendering, logical input and safety. No real GPIO, I2C or commands."""
import base64
import contextlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pikvm_oled as oled
from test_portable_install import portable
from test_portable_os import api


def script(name):
    loader = importlib.machinery.SourceFileLoader('oled_test_' + name.replace('-', '_'), str(ROOT / 'scripts' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


menu, status = script('pikvm-button-menu'), script('pikvm-oled-custom')


def event(frame_id, expires):
    return {'id': frame_id, 'expires': expires, 'done': threading.Event(), 'error': None}


class FrameTests(unittest.TestCase):
    def test_ssd1306_configuration_is_exactly_i2c_3c_128_by_64(self):
        serial, device = Mock(), Mock()
        with patch.dict(sys.modules, {'luma.core.interface.serial': Mock(i2c=serial),
                                      'luma.oled.device': Mock(ssd1306=device)}):
            self.assertIs(oled.physical_device(), device.return_value)
        serial.assert_called_once_with(port=1, address=0x3C)
        device.assert_called_once_with(serial.return_value, width=128, height=64)

    def test_disconnect_and_reconnect_keep_latest_pixels_and_retry_every_30_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [0.0]
            first, restored = Mock(), Mock()
            factory = Mock(side_effect=[first, OSError('still absent'), restored])
            device = oled.MirrorDevice('status', path=Path(directory) / 'oled/frame.json', factory=factory,
                                       clock=lambda: now[0], background=False)
            image = Image.new('1', (128, 64))
            device.display(image); self.assertTrue(device.output._attempt())
            self.assertEqual(device.physical, 'connected')
            first.display.side_effect = OSError('unplugged')
            now[0] = 1; image.putpixel((1, 2), 255)
            device.display(image); device.output._attempt()
            self.assertEqual(device.physical, 'disconnected')
            now[0] = 30; image.putpixel((127, 63), 255)
            device.display(image)
            self.assertFalse(device.output._attempt()); self.assertEqual(factory.call_count, 1)
            now[0] = 31; device.output._attempt()  # reconnect still fails
            self.assertEqual(factory.call_count, 2)
            now[0] = 60; self.assertFalse(device.output._attempt())
            now[0] = 61; device.output._attempt()  # retry with NO further render
            self.assertEqual(device.physical, 'connected')
            self.assertEqual(restored.display.call_args.args[0].tobytes(), image.tobytes())
            device.display(image)
            data = oled.read_frame(device.path, clock=lambda: now[0])
            self.assertEqual(data['physical'], 'connected')
            self.assertEqual(base64.b64decode(data['pixels']), image.tobytes())

    def test_blocked_factory_and_display_never_block_virtual_rendering_or_queue_frames(self):
        for blocked_call in ('factory', 'display'):
            with self.subTest(blocked_call=blocked_call), tempfile.TemporaryDirectory() as directory:
                entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
                now, output = [0.0], []
                class Driver:
                    def display(self, image):
                        if blocked_call == 'display' and not release.is_set():
                            entered.set(); release.wait(5)
                        output.append(image.tobytes()); delivered.set()
                def factory():
                    if blocked_call == 'factory':
                        entered.set(); release.wait(5)
                    return Driver()
                device = oled.MirrorDevice('status', path=Path(directory) / 'oled/frame.json',
                                           factory=factory, clock=lambda: now[0])
                try:
                    device.display(Image.new('1', (128, 64)))
                    self.assertTrue(entered.wait(1))
                    started = time.perf_counter()
                    for index in range(20):
                        now[0] += 1
                        latest = Image.new('1', (128, 64)); latest.putpixel((index, 2), 255)
                        device.display(latest)
                    self.assertLess(time.perf_counter() - started, 1, 'Rendering must not wait for blocked I2C')
                    self.assertEqual(base64.b64decode(oled.read_frame(device.path, clock=lambda: now[0])['pixels']), latest.tobytes())
                    worker = device.output.thread
                    self.assertTrue(worker.is_alive())
                    self.assertEqual(device.output.generation, 21)
                    release.set()
                    deadline = time.monotonic() + 2
                    while (not output or output[-1] != latest.tobytes()) and time.monotonic() < deadline:
                        delivered.wait(.01); delivered.clear()
                    self.assertEqual(output[-1], latest.tobytes())
                    self.assertIs(device.output.thread, worker)
                finally:
                    release.set(); device.close()

    def test_actual_service_entry_loop_survives_missing_i2c_without_process_restart(self):
        # Windows has no systemd. Run the real service main loop in one child
        # process and replace only telemetry and the physical driver.
        harness = '''
import sys,importlib.machinery,importlib.util
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'scripts'))
import pikvm_oled as oled
oled.FRAME=Path(sys.argv[2])
class DeviceNotFoundError(Exception):pass
def absent():raise DeviceNotFoundError('I2C device not found on address: 0x3C')
oled.physical_device=absent
loader=importlib.machinery.SourceFileLoader('oled_service',str(root/'scripts/pikvm-oled-custom'))
spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
module.battery=lambda:(82,3.95)
module.battery_charging=lambda:False
module.wifi=lambda:('fixture',-50)
module.ip_address=lambda:'192.0.2.1'
module.transfer_info=lambda:{}
module.main()
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oled/frame.json'
            process = subprocess.Popen([sys.executable, '-B', '-c', harness, str(ROOT), str(path)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                timestamps = set(); deadline = time.monotonic() + 8
                while len(timestamps) < 3 and time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), 'Service main loop exited on an I2C error')
                    try:
                        data = oled.read_frame(path); timestamps.add(data['monotonic'])
                        self.assertEqual(data['physical'], 'disconnected')
                    except oled.OledError:
                        pass
                    time.sleep(.05)
                self.assertEqual(len(timestamps), 3)
                self.assertIsNone(process.poll())
            finally:
                process.terminate(); stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(stderr, b'', 'Missing hardware must not leak a service traceback')

    def test_exact_pixels_shared_with_physical_and_without_i2c(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oled/frame.json'
            physical = Mock()
            device = oled.MirrorDevice('menu', path=path, factory=lambda: physical, background=False)
            image = Image.new('1', (128, 64)); image.putpixel((33, 12), 255)
            device.set_context(screen='menu', selection=2)
            device.display(image)
            device.output._attempt(); device.publish(image, force=True)
            data = oled.read_frame(path)
            self.assertEqual(base64.b64decode(data['pixels']), physical.display.call_args.args[0].tobytes())
            self.assertEqual(data['context'], {'screen': 'menu', 'selection': 2})
            self.assertEqual(data['physical'], 'connected')
            factory = Mock(side_effect=OSError('No I2C device'))
            headless = oled.MirrorDevice('status', path=path, factory=factory, background=False)
            headless.display(image); headless.display(image)
            headless.output._attempt()
            self.assertEqual(oled.read_frame(path)['physical'], 'disconnected')
            self.assertEqual(factory.call_count, 1, 'Absent I2C is retried at most every 30 seconds')
            self.assertEqual(base64.b64decode(oled.read_frame(path)['pixels']), image.tobytes())

    def test_real_status_and_menu_renderers_publish_same_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oled/frame.json'
            physical = Mock()
            device = oled.MirrorDevice('menu', path=path, factory=lambda: physical, background=False)
            with patch.object(menu, 'DEVICE', device):
                menu.draw_menu(0)
                device.output._attempt()
                first = oled.read_frame(path)
                self.assertEqual(first['context']['selection'], 0)
                self.assertEqual(base64.b64decode(first['pixels']), physical.display.call_args.args[0].tobytes())
                device.published = float('-inf')
                with patch.object(menu, 'current_ssid', return_value='Test network'), patch.object(menu, 'wifi_password', return_value='test only'):
                    menu.draw_menu(1)
                device.output._attempt()
                second = oled.read_frame(path)
                self.assertEqual(second['context']['selection'], 1)
                self.assertNotEqual(first['pixels'], second['pixels'])
            device.published = float('-inf')
            with patch.object(status, 'battery', return_value=(82, 3.95)), patch.object(status, 'battery_charging', return_value=False), \
                 patch.object(status, 'wifi', return_value=('Test network', -50)), patch.object(status, 'ip_address', return_value='192.0.2.1'):
                status.page_main(device, 10)
            device.output._attempt()
            self.assertEqual(base64.b64decode(oled.read_frame(path)['pixels']), physical.display.call_args.args[0].tobytes())

    def test_stale_or_invalid_frame_is_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oled/frame.json'
            device = oled.MirrorDevice('menu', path=path, factory=lambda: Mock(), clock=lambda: 10, background=False)
            device.display(Image.new('1', (128, 64)))
            with self.assertRaisesRegex(oled.OledError, 'périmé'):
                oled.read_frame(path, clock=lambda: 26)
            path.write_text('{}')
            with self.assertRaises(oled.OledError):
                oled.read_frame(path)


class InputTests(unittest.TestCase):
    def test_socket_protocol_handles_fragmentation_and_bounds_messages(self):
        left, right = socket.socketpair()
        with left, right:
            left.settimeout(1)
            def send():
                right.sendall(b'{"action":')
                right.sendall(b'"short"}\n')
            worker = threading.Thread(target=send); worker.start()
            self.assertEqual(oled.receive_json(left, 1024), {'action': 'short'})
            worker.join()
            right.sendall(b'x' * 1026 + b'\n')
            with self.assertRaises(ValueError): oled.receive_json(left, 1024)

    def test_local_peer_must_be_root_in_production(self):
        connection = Mock()
        with patch.object(oled.socket, 'SO_PEERCRED', 17, create=True):
            connection.getsockopt.return_value = struct.pack('3i', 100, 0, 0)
            oled.authorize_local(connection)
            connection.getsockopt.return_value = struct.pack('3i', 100, 1000, 1000)
            with self.assertRaises(oled.OledError) as error: oled.authorize_local(connection)
            self.assertEqual(error.exception.status, 403)

    def test_virtual_duration_never_becomes_long_even_with_slow_render_or_physical_overlap(self):
        now = [10.0]
        button = oled.LogicalButton(clock=lambda: now[0], frame_reader=lambda: {'id': 'a' * 64})
        button.pending = event('a' * 64, 11)
        self.assertTrue(button.poll(False))
        token = button.start()
        now[0] = 50  # Arbitrarily slow scheduler/frame rendering.
        self.assertFalse(button.poll(True))
        self.assertFalse(button.poll(True), 'Physical overlap waits for release')
        self.assertEqual(button.duration(token), .1)
        with self.assertRaises(oled.OledError):
            button.require_physical()
        self.assertFalse(button.poll(False))
        self.assertTrue(button.poll(True))
        real_token = button.start(); now[0] += 5
        self.assertEqual(button.duration(real_token), 5)
        self.assertEqual(button.duration(token), .1, 'Original virtual token stays short forever')
        button.require_physical()

    def test_expired_or_changed_frame_requests_are_not_replayed(self):
        button = oled.LogicalButton(clock=lambda: 20, frame_reader=lambda: {'id': 'b' * 64})
        for item in (event('a' * 64, 21), event('b' * 64, 19)):
            button.pending = item
            self.assertFalse(button.poll(False))
            self.assertIsNotNone(item['error'])
            self.assertTrue(item['done'].is_set())
        self.assertIsNone(button.pending)

    def test_physical_press_and_double_click_are_rejected(self):
        button = oled.LogicalButton(frame_reader=lambda: {'id': 'a' * 64})
        button.poll(True)
        with self.assertRaises(oled.OledError): button.submit('a' * 64)
        button.poll(False); button.last_short = time.monotonic()
        with self.assertRaises(oled.OledError) as error: button.submit('a' * 64)
        self.assertEqual(error.exception.status, 429)

    def test_actual_menu_short_path_cycles_without_any_long_action(self):
        now = [10.0]
        button = oled.LogicalButton(clock=lambda: now[0], frame_reader=lambda: {'id': 'a' * 64})
        selections = []
        def draw(index, held=0):
            if not selections or selections[-1] != index:
                selections.append(index)
                if len(selections) < 5:
                    button.pending = event('a' * 64, now[0] + 1)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(menu, 'INPUT', button))
            stack.enter_context(patch.object(menu, 'physical_button_down', return_value=False))
            stack.enter_context(patch.object(menu, 'get_device'))
            stack.enter_context(patch.object(menu, 'draw_menu', side_effect=draw))
            stack.enter_context(patch.object(menu.time, 'monotonic', side_effect=lambda: now[0]))
            stack.enter_context(patch.object(menu.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)))
            commands = stack.enter_context(patch.object(menu.subprocess, 'run'))
            dangerous = [stack.enter_context(patch.object(menu, name)) for name in
                         ('poweroff', 'restart_pikvm', 'hotspot_toggle', 'run_iso_manager', 'delete_image')]
            menu.run_menu()
            self.assertEqual(selections, [0, 1, 2, 3, 0])
            for operation in dangerous: operation.assert_not_called()
            for call in commands.call_args_list:
                self.assertEqual(call.args[0][0], 'systemctl')
                self.assertEqual(call.args[0][-1], menu.OLED_SERVICE)

    def test_sensitive_functions_have_secondary_origin_guard(self):
        button = oled.LogicalButton(); button.origin = 'virtual'
        with patch.object(menu, 'INPUT', button), patch.object(menu, 'message'), patch.object(menu.subprocess, 'run') as run, patch.object(menu.subprocess, 'Popen') as popen:
            for function, args in ((menu.poweroff, ()), (menu.restart_pikvm, ()),
                                   (menu.hotspot_toggle, (True,)), (menu.delete_image, (Path('/unused'),))):
                result = function(*args)
                self.assertTrue(result is False or (isinstance(result,tuple) and result[0] is False))
            run.assert_not_called(); popen.assert_not_called()

    def test_short_cancels_real_iso_confirmation_and_leaves_rescue_power_without_shutdown(self):
        for action in ('iso', 'rescue-power'):
            with self.subTest(action=action), contextlib.ExitStack() as stack:
                now = [10.0]
                button = oled.LogicalButton(clock=lambda: now[0], frame_reader=lambda: {'id': 'a' * 64})
                button.pending = event('a' * 64, 11)
                stack.enter_context(patch.object(menu, 'INPUT', button))
                stack.enter_context(patch.object(menu, 'physical_button_down', return_value=False))
                stack.enter_context(patch.object(menu.time, 'monotonic', side_effect=lambda: now[0]))
                stack.enter_context(patch.object(menu.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)))
                power = stack.enter_context(patch.object(menu, 'poweroff'))
                restart = stack.enter_context(patch.object(menu, 'restart_pikvm'))
                # Rendering stalls for ten seconds, greater than every hold threshold.
                draw = lambda *args: now.__setitem__(0, now[0] + 10)
                stack.enter_context(patch.object(menu, 'draw_iso_confirm', side_effect=draw))
                stack.enter_context(patch.object(menu, 'draw_rescue_power', side_effect=draw))
                stack.enter_context(patch.object(menu, 'HOTSPOT_STATE', Mock(exists=lambda: True)))
                if action == 'iso':
                    self.assertFalse(menu.confirm_delete(Path('fixture.iso')))
                else:
                    menu.run_rescue_power()
                power.assert_not_called(); restart.assert_not_called()

    @unittest.skipUnless(hasattr(socket, 'AF_UNIX'), 'Unix sockets unavailable')
    def test_local_ipc_consumes_one_short_and_rejects_long_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oled/button.sock'
            button = oled.LogicalButton(frame_reader=lambda: {'id': 'a' * 64})
            button.poll(False)
            with button.listen(path, allowed_uid=os.getuid() if hasattr(os, 'getuid') else 0):
                self.assertTrue(oled.ping(path)['ready'])
                self.assertIsNone(button.pending, 'Health checks never inject input')
                result = []
                worker = threading.Thread(target=lambda: result.append(oled.request_short('a' * 64, path)))
                worker.start()
                for _ in range(100):
                    if button.pending: break
                    time.sleep(.005)
                self.assertTrue(button.poll(False)); worker.join(timeout=2)
                self.assertEqual(result, [{'accepted': True, 'action': 'short'}])
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(2); client.connect(str(path))
                    client.sendall(b'{"action":"long","frame_id":"bad","duration":5}\n')
                    self.assertFalse(oled.receive_json(client, 4096)['ok'])


class InstallTests(unittest.TestCase):
    def test_readiness_rejects_a_frame_left_over_from_before_the_update(self):
        module = Mock()
        module.read_frame.return_value = {'monotonic': 20}
        module.OledError = oled.OledError
        with patch.object(portable, 'load', return_value=module), \
             patch.object(portable.time, 'monotonic', side_effect=[0, 0, 2]), patch.object(portable.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'non prêt'):
                portable.wait_oled_ready(Mock(), observed_after=30, timeout=1)
        module.ping.assert_not_called()

    def test_dead_button_service_disables_web_input_even_if_socket_remains(self):
        backend = api.SystemBackend()
        with patch.object(oled, 'read_frame', return_value={'id': 'a' * 64}), \
             patch.object(oled, 'button_status', return_value={'ready':False}), \
             patch.object(backend, 'services', side_effect=AssertionError('No service command in frame hot path')):
            self.assertFalse(backend.oled()['button_available'])

    def test_unknown_local_changes_are_preserved_and_reinstall_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('pikvm-oled-custom', 'pikvm-button-menu'):
                (root / name).write_bytes((ROOT / 'scripts' / name).read_bytes())
            library = root / 'lib'; library.mkdir()
            shared = library / 'pikvm_oled.py'
            shared.write_bytes((ROOT / 'scripts/pikvm_oled.py').read_bytes())
            with patch.object(portable, 'BIN', root), patch.object(portable, 'LIB', library), \
                 patch.object(portable, 'preflight_journal', return_value=Mock()):
                portable.oled_preflight(); portable.oled_preflight()
                shared.write_bytes(b'# unreviewed local library fix\n')
                with self.assertRaisesRegex(RuntimeError, 'locaux'):
                    portable.oled_preflight()
                self.assertEqual(shared.read_bytes(), b'# unreviewed local library fix\n')
                shared.write_bytes((ROOT / 'scripts/pikvm_oled.py').read_bytes())
                target = root / 'pikvm-oled-custom'; target.write_bytes(b'# local Python fix\n')
                with self.assertRaisesRegex(RuntimeError, 'locaux'):
                    portable.oled_preflight()
                self.assertEqual(target.read_bytes(), b'# local Python fix\n')

    def test_button_service_has_no_gpio_write_and_payload_preserves_power_startup(self):
        source = (ROOT / 'scripts/pikvm-button-menu').read_text(encoding='utf-8')
        self.assertNotIn('"pinctrl", "set"', source)
        self.assertNotIn('button_setup()', source)
        self.assertNotIn('GPIO17', source)
        mapping = portable.file_map()
        self.assertIn(Path('/usr/local/lib/pikvm-portable/pikvm_oled.py'), mapping)
        self.assertNotIn(Path('/usr/local/bin/pikvm-power-hold-startup'), mapping)
        self.assertIn('"$REPO/scripts/pikvm_oled.py"', (ROOT / 'install.sh').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
