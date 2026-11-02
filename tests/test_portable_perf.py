"""RC7 bounded deduplication, freshness, and passive Linux parser regressions."""
import copy
import contextlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from test_oled import oled, ROOT, api, status

loader=importlib.machinery.SourceFileLoader('perf_sampler',str(ROOT/'scripts/pikvm-portable-perf'))
spec=importlib.util.spec_from_loader(loader.name,loader)
sampler=importlib.util.module_from_spec(spec);loader.exec_module(sampler)


class PerfTests(unittest.TestCase):
    def test_status_redraws_on_real_countdown_or_cache_change_and_refreshes_between(self):
        now=[100.0];ticks=[0];draws=[]
        class Finished(Exception):pass
        class Cache:
            revision=0
            def wrap(self,reader,*args,**kwargs):return reader
        cache=Cache();device=Mock()
        def page(device,remaining):draws.append((remaining,cache.revision))
        def sleep(delay):
            ticks[0]+=1;now[0]=100+ticks[0]*.1
            if ticks[0]==5:cache.revision=1
            if ticks[0]>=100:raise Finished()
        with patch.object(status,'AsyncCache',return_value=cache),patch.object(status,'MirrorDevice',return_value=device), \
             patch.object(status,'transfer_info',return_value={}),patch.object(status,'page_main',page), \
             patch.object(status.time,'monotonic',side_effect=lambda:now[0]),patch.object(status.time,'sleep',side_effect=sleep):
            with self.assertRaises(Finished):status.main()
        self.assertEqual({remaining for remaining,_ in draws},set(range(1,11)))
        self.assertIn((10,1),draws,'Telemetry changes must be visible before the next second')
        self.assertLessEqual(len(draws),12);self.assertGreater(device.refresh.call_count,80)

    def test_identical_pixels_offer_once_but_changed_context_and_freshness_still_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            now=[100.0];driver=Mock()
            device=oled.MirrorDevice('status',path=Path(directory)/'oled/frame.json',
                factory=lambda:driver,clock=lambda:now[0],background=False)
            image=Image.new('1',(128,64))
            for i in range(300):
                now[0]=100+i*.1
                device.display(image);device.output._attempt()
            self.assertEqual(driver.display.call_count,1)
            self.assertEqual(device.output.generation,1)
            frame=oled.read_frame(device.path,clock=lambda:now[0])
            self.assertLessEqual(frame['age'],1)
            old_control=frame['control_id'];old_pixels=frame['pixel_id']
            now[0]+=1;device.set_context(screen='menu');device.display(image)
            frame=oled.read_frame(device.path,clock=lambda:now[0])
            self.assertNotEqual(old_control,frame['control_id']);self.assertEqual(old_pixels,frame['pixel_id'])
            now[0]+=16
            with self.assertRaises(oled.OledError):oled.read_frame(device.path,clock=lambda:now[0])
            device.close()

    def test_conditional_response_keeps_fresh_metadata_and_fails_on_stale_frame(self):
        frame={'pixel_id':'a'*64,'pixels':'encoded','context':{'remaining':2},'id':'b'*64}
        with patch.object(oled,'read_frame',return_value=frame),patch.object(oled,'button_status',return_value={'ready':True}):
            backend=api.SystemBackend()
            small=backend.oled(pixels_id='a'*64)
            self.assertNotIn('pixels',small);self.assertTrue(small['pixels_unchanged'])
            self.assertEqual(small['context']['remaining'],2)
            self.assertIn('pixels',backend.oled(pixels_id='c'*64))
            self.assertIn('pixels',frame,'Do not mutate shared frame data')
        with patch.object(oled,'read_frame',side_effect=oled.OledError('stale')):
            with self.assertRaises(oled.OledError):backend.oled(pixels_id='a'*64)

    def test_legacy_frame_without_pixel_identifier_is_always_complete(self):
        with patch.object(oled,'read_frame',return_value={'pixels':'legacy'}),patch.object(oled,'button_status',return_value={'ready':False}):
            self.assertEqual(api.SystemBackend().oled(pixels_id='a'*64)['pixels'],'legacy')

    def test_linux_stat_parser_handles_parentheses_and_pid_reuse_deltas(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);p=root/'42';p.mkdir()
            (p/'cgroup').write_text('0::/system.slice/pikvm-button-menu.service\n')
            # Fields 3..22, utime=10 stime=20 starttime=99.
            values=['S']+['0']*19;values[11]='10';values[12]='20';values[19]='99'
            (p/'stat').write_text('42 (odd ) worker) '+' '.join(values))
            (p/'status').write_text('VmRSS: 100 kB\nThreads: 2\n')
            (p/'io').write_text('read_bytes: 12\nwrite_bytes: 5\n')
            (p/'smaps_rollup').write_text('Pss: 90 kB\n')
            current=sampler.sample(root)
            self.assertEqual(current['processes'][0]['pss_kib'],90)
            self.assertEqual(current['processes'][0]['name'],'odd ) worker')
            previous=copy.deepcopy(current);current['monotonic']=previous['monotonic']+2
            current['processes'][0]['ticks']+=100
            sampler.compare(current,previous,100)
            self.assertEqual(current['processes'][0]['cpu_percent_one_core'],50)
            current['processes'][0]['start']+=1
            sampler.compare(current,previous,100)
            self.assertIsNone(current['processes'][0]['cpu_percent_one_core'])

    def test_sampler_has_no_subprocess_or_device_access(self):
        source=(ROOT/'scripts/pikvm-portable-perf').read_text()
        self.assertNotIn('import subprocess',source)
        self.assertNotIn('/dev/i2c',source);self.assertNotIn('pinctrl',source)
