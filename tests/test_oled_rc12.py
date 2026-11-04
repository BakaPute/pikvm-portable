"""Native 128x64 UI, text bounds, RC11 migration and bounded render work."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import pikvm_config as config
import pikvm_oled_ui as ui
import pikvm_oled as oled
from test_oled import script
from pikvm_settings import Settings
from types import SimpleNamespace

SAMPLE={'percent':82,'voltage':3.94,'charging':False,'cpu':17,'ram':62,'available_mb':148,
        'temperature':43,'uptime':'1h 25m','ip':'192.168.168.99','ssid':'Atelier réseau / un SSID extrêmement long pour vérifier le défilement',
        'dbm':-56,'connected':True,'usb':'OK','kvm':True,'hdmi':'1920x1080',
        'drives':{'0':{'known':True,'attached':True,'cdrom':True},'1':{'known':True,'attached':False,'cdrom':False}},
        'state':'importing','current':'Un très long fichier avec espaces et accents éèà.iso','free':8.2}


class ComponentTests(unittest.TestCase):
    def test_every_status_is_exact_monochrome_and_text_stays_in_reserved_bounds(self):
        for page in config.PAGES:
            for phase in (0,1,3,10,100):
                with self.subTest(page=page,phase=phase):
                    surface=ui.render_status(page,SAMPLE,config.defaults(),10,phase)
                    self.assertEqual(surface.image.size,(128,64));self.assertEqual(surface.image.mode,'1')
                    self.assertEqual(len(surface.image.tobytes()),1024)
                    self.assertIsNotNone(surface.image.getbbox())
                    for x,y,right,bottom in surface.text_regions:
                        self.assertTrue(0<=x<=right<=128);self.assertTrue(0<=y<=bottom<=64)

    def test_no_text_regions_overlap_on_normal_status_layouts(self):
        for page in config.PAGES:
            surface=ui.render_status(page,SAMPLE,config.defaults(),10)
            for i,a in enumerate(surface.text_regions):
                for b in surface.text_regions[i+1:]:
                    self.assertFalse(max(a[0],b[0])<min(a[2],b[2]) and max(a[1],b[1])<min(a[3],b[3]),(page,a,b))

    def test_unknown_telemetry_is_not_a_zero_or_a_crash(self):
        for page in config.PAGES:
            surface=ui.render_status(page,{},config.defaults())
            self.assertIsNotNone(surface.image.getbbox())
        self.assertEqual(ui.percent(None),'--');self.assertEqual(ui.percent(float('nan')),'--')
        self.assertEqual(ui.percent('82'),'--');self.assertEqual(ui.percent(True),'--')

    def test_fit_uses_pixel_width_with_accents_and_unbounded_input_is_bounded(self):
        for value in ('éèàÉ Wi-Fi 100%', 'W'*5000, '汉字'*100, 'foo\nbar\tname.iso'):
            result=ui.fit(value,40)
            self.assertLessEqual(ui.width(result),40);self.assertLessEqual(len(ui.clean(value)),256)
            self.assertNotIn('\n',result)

    def test_monochrome_metrics_match_the_actual_raster_and_keep_the_last_glyph(self):
        from PIL import ImageDraw
        for value in ('Batterie','Repos','Système','Pi Zero 2 W','Wi-Fi connecté'):
            reference=Image.new('1',(300,40));f=ui.font(9,True);box=f.getbbox(value,mode='1')
            ImageDraw.Draw(reference).text((-box[0],-box[1]),value,font=f,fill=1)
            raster=ui.text_mask(value,9,True)
            self.assertEqual(raster.getbbox(),reference.getbbox())
            self.assertEqual(raster.tobytes(),reference.crop((0,0,raster.width,raster.height)).tobytes())

    def test_marquee_only_when_necessary_and_both_animation_switches_work(self):
        values=config.defaults()
        frames=[ui.render_status('network',SAMPLE,values,10,phase) for phase in (0,3)]
        self.assertTrue(all(s.animated for s in frames));self.assertNotEqual(frames[0].image.tobytes(),frames[1].image.tobytes())
        for key in ('animations','oled_animations'):
            disabled={**values,key:False}
            a=ui.render_status('network',SAMPLE,disabled,10,0);b=ui.render_status('network',SAMPLE,disabled,10,3)
            self.assertFalse(a.animated);self.assertEqual(a.image.tobytes(),b.image.tobytes())
        self.assertFalse(ui.render_status('battery',SAMPLE,values).animated)

    def test_selected_long_list_is_bounded_and_accessible_in_three_rows(self):
        items=[{'name':f'Dossier {i} '+'W'*200,'icon':'folder' if i%2 else 'disc'} for i in range(1000)]
        for index in (0,1,500,999):
            frame=ui.render_list('ISO / une longue arborescence',items,index,config.defaults(),'1 suivant · 2 ouvrir',phase=2)
            self.assertTrue(frame.animated);self.assertEqual(frame.image.size,(128,64))
            self.assertLessEqual(len(frame.text_regions),6)
        self.assertIsNotNone(ui.render_list('ISO',[],0,config.defaults()).image.getbbox())

    def test_clipping_and_caches_have_fixed_memory_bounds(self):
        for i in range(1200):ui.text_mask('Étiquette '+str(i));ui.bounds('Mesure '+str(i))
        self.assertLessEqual(ui.text_mask.cache_info().currsize,64);self.assertLessEqual(ui.bounds.cache_info().currsize,1024)
        with self.assertRaises(ValueError):ui.Surface().bar(120,40,20,5,.5)

    def test_qr_does_not_crop_modules_or_interpolate_and_rejects_dense_qr(self):
        qr=Image.new('1',(29,29),1);qr.putpixel((0,0),0)
        scene=ui.render_qr(qr,'Exemple Wi-Fi',config.defaults())
        self.assertTrue(scene.image.getpixel((0,0)))
        with self.assertRaises(ValueError):ui.render_qr(Image.new('1',(61,61)),'Wi-Fi',config.defaults())

    def test_style_visible_preferences_and_idle_frames_are_real_render_changes(self):
        values=config.defaults();first=ui.render_status('main',SAMPLE,values).image.tobytes()
        for key,value in (('oled_style','detailed'),('oled_alignment','right'),('oled_show_ip',False),('oled_show_battery',False),('oled_show_ssid',False)):
            self.assertNotEqual(first,ui.render_status('main',SAMPLE,{**values,key:value}).image.tobytes(),key)
        self.assertIsNone(ui.render_idle('off',values).image.getbbox())
        self.assertIsNotNone(ui.render_idle('screen',values).image.getbbox())


class MigrationTests(unittest.TestCase):
    def test_rc11_order_duration_visibility_revision_and_preferences_are_preserved(self):
        raw=json.loads((ROOT/'tests/fixtures/rc11-settings.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json';path.write_text(json.dumps(raw));path.chmod(0o600)
            before=path.read_bytes();store=config.Store(path);loaded=store.read()
            self.assertTrue(loaded['healthy']);self.assertEqual(loaded['schema_version'],2);self.assertEqual(loaded['revision'],7)
            self.assertEqual(loaded['values']['oled_pages'][:4],raw['values']['oled_pages'])
            self.assertFalse(any(p['enabled'] for p in loaded['values']['oled_pages'] if p['id'] in ('network','usb')))
            self.assertEqual(loaded['values']['theme'],'light');self.assertFalse(loaded['values']['idle_enabled'])
            self.assertEqual(path.read_bytes(),before,'Reading RO preferences must not persist a migration')
            values=loaded['values'];values['oled_style']='detailed';saved=store.save(values,7)
            self.assertTrue(saved['healthy']);self.assertEqual(saved['revision'],8)

    def test_unknown_rc11_fields_are_not_silently_imported(self):
        raw=json.loads((ROOT/'tests/fixtures/rc11-settings.json').read_text(encoding='utf-8'))['values']
        for key in ('gpio18','command','oled_animations'):
            with self.assertRaises(config.ConfigError):config.migrate_rc11({**raw,key:'untrusted'})

    def test_page_remaining_uses_the_new_page_duration_and_initial_page(self):
        values=config.defaults();values['oled_pages'][0]['seconds']=2;values['oled_pages'][1]['seconds']=15
        rotation=config.PageRotation();self.assertEqual(rotation.choose(values,0),('main',2))
        self.assertEqual(rotation.choose(values,2),('battery',15))


class ProducerTests(unittest.TestCase):
    def test_absent_luma_init_closes_every_bus_and_does_not_retain_atexit_closures(self):
        import gc,weakref
        registry=Mock();core=SimpleNamespace(atexit=registry);buses=[];references=[]
        class Partial:
            def cleanup(self):pass
        def serial(**_):
            bus=Mock();buses.append(bus);return bus
        def absent(*args,**kwargs):
            device=Partial();references.append(weakref.ref(device))
            core.atexit.register(lambda:device.cleanup())
            raise OSError('SSD1306 absent')
        with patch.dict(sys.modules,{'luma.core.interface.serial':Mock(i2c=serial),'luma.oled.device':Mock(ssd1306=absent),'luma.core.device':core}):
            for _ in range(100):
                with self.assertRaises(OSError):oled.physical_device()
        gc.collect();self.assertTrue(all(ref() is None for ref in references))
        self.assertIs(core.atexit,registry);registry.register.assert_not_called()
        for bus in buses:bus.cleanup.assert_called_once()

    def test_disconnect_closes_the_owned_bus_in_the_worker(self):
        physical=Mock();physical.display.side_effect=OSError('disconnected')
        output=oled.PhysicalOutput(lambda:physical,background=False)
        output.offer(Image.new('1',(128,64)));output._attempt()
        physical._portable_release.assert_called_once();self.assertIsNone(output.device)

    def test_staged_benchmark_ignores_an_old_module_on_pythonpath(self):
        import os,subprocess
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'pikvm_config.py';path.write_text("raise RuntimeError('old installed RC11 must not be imported')",encoding='utf-8')
            env={**os.environ,'PYTHONPATH':directory}
            result=subprocess.run([sys.executable,'-B',str(ROOT/'scripts/pikvm-oled-benchmark.py'),'--iterations','1'],env=env,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('iso-action',json.loads(result.stdout)['scenes'])

    def test_status_pixels_match_the_optional_device_and_web_frame_exactly(self):
        status=script('pikvm-oled-custom')
        with tempfile.TemporaryDirectory() as directory:
            physical=Mock();device=oled.MirrorDevice('status',path=Path(directory)/'oled/frame.json',factory=lambda:physical,background=False)
            for name in ('page_battery','page_network','page_usb'):
                with patch.object(status,'battery',return_value=(82,3.94)),patch.object(status,'battery_charging',return_value=False), \
                     patch.object(status,'network_info',return_value=SAMPLE),patch.object(status,'drive_info',return_value=SAMPLE['drives']),patch.object(status,'usb_state',return_value='OK'):
                    getattr(status,name)(device,10)
                device.output._attempt();device.publish(device.output.latest,force=True)
                self.assertEqual(base64.b64decode(oled.read_frame(device.path)['pixels']),physical.display.call_args.args[0].tobytes())

    def test_menu_skips_rendering_unchanged_frames(self):
        from oled_nav_fixtures import Harness
        status=script('pikvm-oled-custom');h=Harness();h.nav.change('menu')
        device=SimpleNamespace(set_context=Mock(),display=Mock(),refresh=Mock())
        with patch.object(status,'render_navigation',wraps=status.render_navigation) as draw:
            status.display_navigation(device,h.nav.snapshot(),h.values,h.now)
            status.display_navigation(device,h.nav.snapshot(),h.values,h.now)
        self.assertEqual(draw.call_count,1);device.refresh.assert_called_once()

    def test_api_preview_all_pages_share_the_native_renderer(self):
        settings=Settings(SimpleNamespace(),Path('unused-test-preferences'))
        with patch('subprocess.run',side_effect=AssertionError('Preview must not read hardware')):
            for page in config.PAGES:
                preview=settings.preview({'values':config.defaults(),'page':page})
                self.assertEqual(len(base64.b64decode(preview['pixels'])),1024)
                self.assertTrue(preview['synthetic'])


if __name__=='__main__':unittest.main()
