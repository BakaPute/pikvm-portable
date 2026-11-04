"""Renderer handoff/heartbeat regressions, without hardware or service changes."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from test_oled_hold import oled


class ControllerTests(unittest.TestCase):
    def test_control_heartbeat_is_fresh_while_renderer_poll_is_stale(self):
        now=[100.0]
        button=oled.LogicalButton(clock=lambda:now[0])
        button.last_poll=10
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'oled/button.json';button.heartbeat=path
            button.publish_heartbeat()
            with patch.object(oled,'BUTTON_HEARTBEAT',path),patch.object(oled,'SOCKET',Mock(is_socket=lambda:True)), \
                 patch.object(oled.time,'monotonic',return_value=now[0]):
                status=oled.button_status()
                self.assertFalse(status['ready']);self.assertEqual(status['poll_age_ms'],90000)

    def test_five_second_hold_survives_missing_frames_with_real_keep_renewals(self):
        now=[10.0];frame={'control_id':'b'*64,'context':{'screen':'menu','selection':1}}
        button=oled.LogicalButton(clock=lambda:now[0],frame_reader=lambda:frame)
        button.poll(False)
        identity={'owner':'d'*64,'gesture_id':'a'*32}
        button.remote({**identity,'action':'start','control_id':'b'*64,'permit':''})
        self.assertTrue(button.poll(False));token=button.start()
        button.frame_reader=Mock(side_effect=oled.OledError('Frame producer unavailable'))
        for step in range(1,26):
            now[0]=10+step*.2;button.remote({**identity,'action':'keep'})
            self.assertTrue(button.poll(False));self.assertFalse(button.cancelled(token))
        button.remote({**identity,'action':'stop'});self.assertFalse(button.poll(False))
        self.assertAlmostEqual(button.duration(token),5)
        button.frame_reader.assert_not_called()

    def test_renderer_handoff_cancels_queued_input_for_a_different_menu(self):
        now=[10.0];frame={'control_id':'b'*64,'context':{'screen':'status'}}
        button=oled.LogicalButton(clock=lambda:now[0],frame_reader=lambda:frame)
        button.remote({'owner':'d'*64,'gesture_id':'a'*32,'action':'start','control_id':'b'*64,'permit':''})
        frame['control_id']='c'*64
        self.assertFalse(button.poll(False));self.assertTrue(button.hold['cancelled'])

    def test_no_frame_failure_can_extend_a_lost_lease(self):
        now=[10.0];button=oled.LogicalButton(clock=lambda:now[0],frame_reader=lambda:{'control_id':'b'*64,'context':{}})
        identity={'owner':'d'*64,'gesture_id':'a'*32}
        button.remote({**identity,'action':'start','control_id':'b'*64,'permit':''});button.poll(False);token=button.start()
        now[0]+=.81
        self.assertFalse(button.poll(False));self.assertTrue(button.cancelled(token))
        with self.assertRaises(oled.OledError):button.remote({**identity,'action':'keep'})

    def test_queued_input_waits_for_the_same_control_after_producer_handoff(self):
        now=[10.0];frame={'control_id':'b'*64,'context':{'screen':'status'}}
        button=oled.LogicalButton(clock=lambda:now[0],frame_reader=lambda:frame)
        identity={'owner':'d'*64,'gesture_id':'a'*32}
        button.remote({**identity,'action':'start','control_id':'b'*64,'permit':''})
        button.frame_reader=Mock(side_effect=oled.OledError('Producer switching'))
        self.assertFalse(button.poll(False));self.assertFalse(button.hold['consumed'])
        now[0]+=.2;button.remote({**identity,'action':'keep'})
        button.frame_reader=lambda:frame
        self.assertTrue(button.poll(False));self.assertTrue(button.hold['consumed'])
