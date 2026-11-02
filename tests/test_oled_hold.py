"""Held input and slow-I/O regressions. No GPIO, systemd or target access."""
import threading
import time
import subprocess
import tempfile
import sys
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test_oled as fixtures

oled, menu, api = fixtures.oled, fixtures.menu, fixtures.api


class HoldTests(unittest.TestCase):
    def make(self, context=None):
        self.now = 10.0
        self.frame = {'id':'c'*64,'control_id':'b'*64,'context':context or {'screen':'menu','selection':1}}
        self.button = oled.LogicalButton(clock=lambda:self.now,frame_reader=lambda:self.frame)
        self.button.poll(False)
        self.start = {'action':'start','owner':'d'*64,'gesture_id':'a'*32,'control_id':'b'*64,'permit':''}

    def update(self, action, **kwargs):
        return self.button.remote({'action':action,'owner':'d'*64,'gesture_id':'a'*32,**kwargs})

    def test_real_variable_duration_and_release_not_fixed_short(self):
        for duration in (.1,2,5,8.7):
            with self.subTest(duration=duration):
                self.make(); self.button.remote(self.start)
                self.assertTrue(self.button.poll(False)); token=self.button.start()
                for step in range(1,int(duration*10)+1):
                    self.now=10+step/10
                    self.update('keep'); self.assertTrue(self.button.poll(False))
                self.now=10+duration; self.update('stop')
                self.assertFalse(self.button.poll(False))
                self.assertAlmostEqual(self.button.duration(token),duration)
                self.assertFalse(self.button.cancelled(token))

    def test_cancel_focus_loss_and_expired_lease_never_become_click_or_long_action(self):
        for action in ('cancel','lease'):
            self.make();self.button.remote(self.start);self.button.poll(False);token=self.button.start()
            self.now+=.5
            if action=='cancel':self.update('cancel')
            else:self.now+=.4
            self.assertFalse(self.button.poll(False))
            self.assertTrue(self.button.cancelled(token));self.assertEqual(self.button.duration(token),0)
            self.assertFalse(self.button.sensitive('power'))

    def test_release_before_start_only_produces_short_and_cancel_before_start_produces_none(self):
        for action in ('stop','cancel'):
            self.make(); self.update(action)
            self.now+=.1;self.button.remote(self.start)
            pressed=self.button.poll(False)
            self.assertEqual(pressed,action=='stop')
            token=self.button.start()
            self.assertFalse(self.button.poll(False))
            self.assertEqual(self.button.cancelled(token),action=='cancel')
            self.assertLess(self.button.duration(token),.8)

    def test_session_ownership_and_client_duration_are_enforced(self):
        self.make();self.button.remote(self.start)
        with self.assertRaises(oled.OledError) as error:
            self.button.remote({'action':'stop','owner':'e'*64,'gesture_id':'a'*32})
        self.assertEqual(error.exception.status,403)
        with self.assertRaises(oled.OledError):self.update('keep',duration=5)

    def test_sensitive_actions_need_explicit_matching_screen_permission(self):
        self.make({'screen':'menu','selection':0})
        self.button.remote(self.start);self.button.poll(False)
        self.assertFalse(self.button.sensitive('power'))
        self.make({'screen':'menu','selection':0})
        self.button.remote({**self.start,'permit':'power'});self.button.poll(False)
        self.button.start()
        self.assertTrue(self.button.sensitive('power'));self.assertFalse(self.button.sensitive('delete'))
        self.update('cancel');self.assertFalse(self.button.sensitive('power'))
        self.make({'screen':'menu','selection':1})
        with self.assertRaises(oled.OledError):self.button.remote({**self.start,'permit':'power'})

    def test_uncertain_physical_sample_cancels_until_release(self):
        self.make(); self.button.poll(True);token=self.button.start();self.now+=2
        self.assertFalse(self.button.poll(None));self.assertTrue(self.button.cancelled(token))
        self.assertFalse(self.button.poll(True))
        self.button.poll(False);self.assertTrue(self.button.poll(True))

    def test_a_new_permission_cannot_authorize_the_previous_gesture(self):
        self.make({'screen':'menu','selection':0});self.button.remote(self.start)
        self.button.poll(False);self.button.start();self.update('stop');self.button.poll(False)
        self.now+=.2;self.button.poll(False)
        self.button.remote({**self.start,'gesture_id':'f'*32,'permit':'power'})
        self.assertFalse(self.button.sensitive('power'))
        self.button.poll(False);self.button.start()
        self.assertTrue(self.button.sensitive('power'))

    def test_cancelled_real_menu_does_not_advance_selection(self):
        self.make();self.button.remote(self.start)
        selections=[]
        def draw(index,held=0):
            selections.append(index)
            if self.button.hold and self.button.hold['consumed']:
                self.update('cancel')
        with patch.object(menu,'INPUT',self.button),patch.object(menu,'physical_button_down',return_value=False), \
             patch.object(menu,'get_device'),patch.object(menu,'draw_menu',side_effect=draw), \
             patch.object(menu.time,'monotonic',side_effect=lambda:self.now), \
             patch.object(menu.time,'sleep',side_effect=lambda delay:setattr(self,'now',self.now+delay)), \
             patch.object(menu.subprocess,'run'):
            menu.run_menu()
        self.assertEqual(set(selections),{0})

    def test_five_second_hold_reaches_existing_power_menu_threshold(self):
        self.make({'screen':'menu','selection':0});self.button.remote({**self.start,'permit':'power'})
        def sleep(delay):
            self.now+=delay
            self.update('keep')
        with patch.object(menu,'INPUT',self.button),patch.object(menu,'physical_button_down',return_value=False), \
             patch.object(menu,'get_device'),patch.object(menu,'draw_menu'), \
             patch.object(menu.time,'monotonic',side_effect=lambda:self.now),patch.object(menu.time,'sleep',side_effect=sleep), \
             patch.object(menu.subprocess,'run'),patch.object(menu,'poweroff') as power:
            menu.run_menu()
            power.assert_called_once()
        self.assertGreaterEqual(self.button.duration(self.button.start()),5)


class FluidityTests(unittest.TestCase):
    def test_iso_counter_uses_display_cache_without_scanning_the_disk_in_draw(self):
        with patch.object(menu,'DISPLAY_IMAGES',Mock(return_value=None)), \
             patch.object(menu,'image_files',side_effect=AssertionError('disk scan in render')), \
             patch.object(menu,'usb_transfer_busy',return_value=False),patch.object(menu,'get_device'),patch.object(menu,'show'):
            menu.draw_iso_page()

    def test_native_countdown_keeps_each_second_while_telemetry_blocks_four_seconds(self):
        harness='''
import sys,time,importlib.machinery,importlib.util
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'scripts'))
import pikvm_oled as oled
oled.FRAME=Path(sys.argv[2]);oled.physical_device=lambda:None
loader=importlib.machinery.SourceFileLoader('status',str(root/'scripts/pikvm-oled-custom'))
spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
module.battery=lambda:(time.sleep(4) or (82,3.95))
module.battery_charging=lambda:False
module.wifi=lambda:('fixture',-50)
module.ip_address=lambda:'192.0.2.1'
module.transfer_info=lambda:{}
module.main()
'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'oled/frame.json'
            process=subprocess.Popen([sys.executable,'-B','-c',harness,str(fixtures.ROOT),str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                values=[];deadline=time.monotonic()+5
                while len(values)<3 and time.monotonic()<deadline:
                    self.assertIsNone(process.poll())
                    try:
                        context=oled.read_frame(path)['context']
                        # Windows can reject atomic replacement while this test
                        # holds an ordinary read handle. Linux /run supports it.
                        if context.get('screen')=='error':
                            self.assertTrue(os.name=='nt' and context.get('error_type')=='PermissionError',context)
                            time.sleep(.02)
                            continue
                        value=context['remaining']
                        if not values or values[-1]!=value:values.append(value)
                    except oled.OledError:pass
                    time.sleep(.02)
                self.assertEqual(values[:3],[10,9,8])
            finally:
                process.terminate();process.communicate(timeout=5)
    def test_blocked_telemetry_returns_immediately_and_has_bounded_pending_work(self):
        entered,release=threading.Event(),threading.Event()
        def slow():entered.set();release.wait(3);return 42
        cache=oled.AsyncCache(workers=1)
        try:
            read=cache.wrap(slow,default='unknown',interval=1)
            self.assertEqual(read(),'unknown');self.assertTrue(entered.wait(1))
            started=time.perf_counter()
            for _ in range(1000):self.assertEqual(read(),'unknown')
            self.assertLess(time.perf_counter()-started,.5)
            self.assertLessEqual(len(cache.items),32);self.assertEqual(len(cache.queue),0)
            release.set();deadline=time.monotonic()+1
            while read()!='42' and time.monotonic()<deadline:
                if read()==42:break
                time.sleep(.005)
            self.assertEqual(read(),42)
        finally:release.set();cache.close()

    def test_frame_api_never_waits_on_system_services_or_input_socket(self):
        backend=api.SystemBackend()
        with patch.object(oled,'read_frame',return_value={'id':'a'*64}),patch.object(oled,'button_status',return_value={'ready':True}), \
             patch.object(backend,'services',side_effect=AssertionError('service lock used')), \
             patch.object(oled,'ping',side_effect=AssertionError('socket roundtrip used')):
            self.assertTrue(backend.oled()['button_available'])

    def test_power_arming_refuses_attached_or_unknown_media(self):
        backend=api.SystemBackend()
        with patch.object(backend,'usb',return_value={'drives':{'0':{'attributes':{'file':'disk.iso'}},'1':{'attributes':{'file':''}}}}), \
             patch.object(oled,'request_event') as send:
            with self.assertRaises(oled.OledError):backend.oled_event({'action':'start','permit':'power'},'a'*64)
            send.assert_not_called()
