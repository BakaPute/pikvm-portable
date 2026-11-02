"""RC8 GPIO fixtures only: never open a real device or request a GPIO line."""
import contextlib
import mmap
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from test_oled import oled, menu
import pikvm_gpio as gpio


class GpioTests(unittest.TestCase):
    def test_mapping_is_read_only_and_gpio18_level_and_mode_are_exact(self):
        registers=bytearray(4096)
        info=Mock(st_mode=stat.S_IFCHR,st_rdev=0)
        # A real ACCESS_READ map of a fixture also verifies writes are rejected.
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'registers';path.write_bytes(registers)
            with path.open('rb') as file, contextlib.closing(mmap.mmap(file.fileno(),4096,access=mmap.ACCESS_READ)) as mapping:
                with patch.object(gpio,'validate_platform',return_value={'devno':'0:0'}), \
                     patch.object(gpio.os,'open',return_value=123) as opening, \
                     patch.object(gpio.os,'fstat',return_value=info),patch.object(gpio.os,'close') as close, \
                     patch.object(gpio.os,'major',return_value=0,create=True),patch.object(gpio.os,'minor',return_value=0,create=True), \
                     patch.object(gpio.mmap,'mmap',return_value=mapping) as mapper:
                    reader=gpio.ReadOnlyLevel()
                    self.assertTrue(reader.words.readonly)
                    self.assertFalse(reader.read())
                    flags=opening.call_args.args[1]
                    self.assertEqual(flags & getattr(os,'O_ACCMODE',3),os.O_RDONLY)
                    self.assertEqual(mapper.call_args.kwargs['access'],mmap.ACCESS_READ)
                    with self.assertRaises(TypeError):mapping[0:4]=b'\0'*4
                    reader.close();reader.close();close.assert_called_once_with(123)
        reader=gpio.ReadOnlyLevel.__new__(gpio.ReadOnlyLevel);reader.mapping=registers
        reader.words=memoryview(registers).cast('I')
        struct.pack_into('<I',registers,0x34,1<<17)
        self.assertFalse(reader.read(),'GPIO17 must not be used as the button')
        struct.pack_into('<I',registers,0x34,1<<18);self.assertTrue(reader.read())
        struct.pack_into('<I',registers,0x04,1<<24)
        with self.assertRaises(gpio.Unavailable):reader.read()

    def test_platform_validation_rejects_unknown_board_and_non_device(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);compat=root/'compatible';device=root/'gpiomem';device.write_bytes(b'')
            compat.write_bytes(b'raspberrypi,model-5-b\0brcm,bcm2712\0')
            with self.assertRaises(gpio.Unavailable):gpio.validate_platform(compat,root,device)
            compat.write_bytes(b'raspberrypi,model-zero-2-w\0brcm,bcm2837\0')
            with self.assertRaises(gpio.Unavailable):gpio.validate_platform(compat,root,device)

    def test_exact_driver_window_and_device_identity_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);compat=root/'compatible'
            compat.write_bytes(b'raspberrypi,model-zero-2-w\0brcm,bcm2837\0')
            dev=root/'class/gpiomem/gpiomem/dev';dev.parent.mkdir(parents=True);dev.write_text('0:0')
            platform=root/'bus/platform/drivers/rpi-gpiomem/3f200000.gpiomem'
            (platform/'of_node').mkdir(parents=True)
            (platform/'of_node/compatible').write_bytes(b'brcm,bcm2835-gpiomem\0')
            (platform/'resource').write_text('0x3f200000 0x3f200fff 0x200\n')
            with patch.object(gpio.Path,'lstat',return_value=Mock(st_mode=stat.S_IFCHR,st_rdev=0)), \
                 patch.object(gpio.os,'major',return_value=0,create=True),patch.object(gpio.os,'minor',return_value=0,create=True):
                self.assertEqual(gpio.validate_platform(compat,root)['devno'],'0:0')
                (platform/'resource').write_text('0x7e200000 0x7e200fff 0x200\n')
                with self.assertRaises(gpio.Unavailable):gpio.validate_platform(compat,root)
    def test_cross_check_selects_persistent_reader_without_subprocesses_per_sample(self):
        device=Mock();device.read.return_value=False;sample=Mock(return_value=False)
        fallback=Mock()
        read,resource,status=gpio.select_reader(fallback,factory=lambda:device,sample=sample)
        for _ in range(750):self.assertFalse(read())
        self.assertEqual(status['backend'],'gpiomem-readonly')
        self.assertIs(resource,device);self.assertEqual(sample.call_count,2);fallback.assert_not_called()

    def test_unavailable_or_changing_hardware_never_takes_exclusive_control(self):
        for failure in (PermissionError('denied'),gpio.Unavailable('unknown driver'),subprocess.TimeoutExpired('pinctrl',.3)):
            fallback=Mock(return_value=None)
            read,resource,status=gpio.select_reader(fallback,factory=Mock(side_effect=failure),sample=lambda:False)
            self.assertIs(read,fallback);self.assertIsNone(resource);self.assertEqual(status['backend'],'pinctrl')
        device=Mock();device.read.return_value=True
        read,resource,status=gpio.select_reader(lambda:None,factory=lambda:device,sample=lambda:False)
        self.assertIsNone(resource);device.close.assert_called_once()

    def test_pinctrl_failure_and_unexpected_bias_do_not_become_a_press(self):
        for code,value in [(1,'18: ip pd | hi'),(0,'18: op dh | hi'),(0,'18: ip pu | hi'),(0,'garbage hi')]:
            with patch.object(gpio.subprocess,'run',return_value=Mock(returncode=code,stdout=value)):
                with self.assertRaises(gpio.Unavailable):gpio.pinctrl_sample()
        with patch.object(gpio.subprocess,'run',return_value=Mock(returncode=0,stdout='18: ip pd | hi // GPIO18 = input')):
            self.assertTrue(gpio.pinctrl_sample())

    def sampler(self):
        with patch.object(oled.threading.Thread,'start'):
            return oled.ButtonReader(lambda:False)

    def test_short_gpio_error_is_latched_until_consumer_observes_it(self):
        reader=self.sampler();reader.update(True);self.assertTrue(reader.read())
        reader.update(None);reader.update(True)
        self.assertIsNone(reader.read());self.assertTrue(reader.read())
        self.assertEqual(reader.status()['errors'],1)

    def test_sampling_gap_cannot_be_hidden_by_a_fresh_high_after_recovery(self):
        reader=self.sampler()
        with patch.object(oled.time,'monotonic',return_value=10):reader.update(True)
        with patch.object(oled.time,'monotonic',return_value=10.5):
            reader.update(True)
            self.assertIsNone(reader.read());self.assertTrue(reader.read())
            self.assertEqual(reader.status()['errors'],1)

    def test_physical_holds_and_release_after_2_3_5_seconds(self):
        for seconds in (.12,2,3,5):
            with self.subTest(seconds=seconds):
                now=[10.0];reader=self.sampler();button=oled.LogicalButton(clock=lambda:now[0])
                reader.update(False);button.poll(reader.read());reader.update(True)
                self.assertTrue(button.poll(reader.read()));token=button.start()
                for _ in range(round(seconds/.04)):
                    now[0]+=.04;reader.update(True);self.assertTrue(button.poll(reader.read()))
                reader.update(False);self.assertFalse(button.poll(reader.read()))
                self.assertFalse(button.cancelled(token));self.assertAlmostEqual(button.duration(token),seconds,delta=.021)

    def test_gpio_loss_cancels_physical_hold_and_requires_release(self):
        now=[10.0];reader=self.sampler();button=oled.LogicalButton(clock=lambda:now[0])
        reader.update(True);button.poll(reader.read());token=button.start();now[0]+=4.9
        reader.update(None);reader.update(True)
        self.assertFalse(button.poll(reader.read()));self.assertTrue(button.cancelled(token))
        self.assertEqual(button.duration(token),0);self.assertFalse(button.sensitive('power'))
        self.assertFalse(button.poll(reader.read()))
        reader.update(False);button.poll(reader.read());reader.update(True);self.assertTrue(button.poll(reader.read()))

    def test_simultaneous_physical_press_cancels_virtual_hold_without_origin_conversion(self):
        now=[10.0];button=oled.LogicalButton(clock=lambda:now[0],frame_reader=lambda:{'control_id':'b'*64,'context':{}})
        button.poll(False)
        button.remote({'action':'start','owner':'d'*64,'gesture_id':'a'*32,'control_id':'b'*64,'permit':''})
        button.poll(False);token=button.start();now[0]+=.2
        self.assertFalse(button.poll(True));self.assertTrue(button.cancelled(token));self.assertEqual(token[1],'remote')
        self.assertFalse(button.sensitive('power'));self.assertFalse(button.poll(True))
        button.poll(False);self.assertTrue(button.poll(True))

    def test_gpio_absence_does_not_extend_or_cancel_a_healthy_virtual_lease(self):
        now=[10.0];button=oled.LogicalButton(clock=lambda:now[0],frame_reader=lambda:{'control_id':'b'*64,'context':{}})
        identity={'owner':'d'*64,'gesture_id':'a'*32}
        button.remote({**identity,'action':'start','control_id':'b'*64,'permit':''});button.poll(None);token=button.start()
        for _ in range(25):
            now[0]+=.2;button.remote({**identity,'action':'keep'});self.assertTrue(button.poll(None))
        self.assertAlmostEqual(button.duration(token),5)
        now[0]+=.81;self.assertFalse(button.poll(None));self.assertTrue(button.cancelled(token))

    def test_existing_press_debounce_rejects_a_single_high_sample(self):
        now=[10.0];values=iter([True,False,False,False,False,False])
        def sleep(delay):now[0]+=delay
        with patch.object(menu,'button_down',side_effect=lambda:next(values,False)), \
             patch.object(menu.time,'monotonic',side_effect=lambda:now[0]),patch.object(menu.time,'sleep',side_effect=sleep):
            self.assertFalse(menu.wait_press_until(10.15))

    def test_sampler_closes_device_after_thread_has_stopped(self):
        resource=Mock();reader=oled.ButtonReader(lambda:False,resource=resource)
        reader.close();self.assertFalse(reader.thread.is_alive());resource.close.assert_called_once()
