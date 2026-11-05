"""Readable native layouts, canonical monochrome pixels and RC12 preference migration."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from PIL import Image,ImageChops
from test_oled_rc12 import SAMPLE,ROOT
import pikvm_config as config
import pikvm_oled_ui as ui
import pikvm_oled as oled
from pikvm_oled_nav import preview_navigation
from pikvm_settings import Settings
from types import SimpleNamespace
from test_portable_install import portable


class LayoutTests(unittest.TestCase):
    def assert_layout(self,surface):
        self.assertEqual(surface.image.size,(128,64));self.assertEqual(surface.image.mode,'1')
        for i,a in enumerate(surface.text_regions):
            self.assertTrue(0<=a[0]<=a[2]<=128 and 0<=a[1]<=a[3]<=64,a)
            for b in surface.text_regions[i+1:]:
                self.assertFalse(max(a[0],b[0])<min(a[2],b[2]) and max(a[1],b[1])<min(a[3],b[3]),(a,b))

    def test_all_pages_both_profiles_values_unknown_long_and_animation_phases(self):
        extreme={**SAMPLE,'ssid':'École / réseau très long '*30,'ip':'2001:db8:'+'abcd:'*15,'uptime':'123 jours 23 heures 59 minutes'}
        for style in ('readable','compact'):
            values={**config.defaults(),'oled_style':style}
            for page in config.PAGES:
                for data in (SAMPLE,{},extreme):
                    for phase in (0,2,20):
                        with self.subTest(style=style,page=page,phase=phase):self.assert_layout(ui.render_status(page,data,values,8,phase))

    def test_system_readable_values_are_large_and_secondary_information_has_its_own_page(self):
        values=config.defaults();frame=ui.render_status('system',SAMPLE,values)
        values_runs=[r for r in frame.text_runs if r['text'] in ('17%','62%','43 °C')]
        self.assertEqual(len(values_runs),3);self.assertTrue(all(r['size']>=14 and not r['elided'] for r in values_runs))
        self.assertFalse(any('disponible' in r['text'] or '1h 25m'==r['text'] for r in frame.text_runs))
        detail=ui.render_status('system_details',SAMPLE,values)
        self.assertTrue(any(r['text']=='148 Mio' and r['size']>=14 for r in detail.text_runs))

    def test_all_menus_confirmations_errors_idle_and_progress_bounds(self):
        screens=('menu','power','wifi','network','iso-root','iso','iso-action','iso-info','iso-connect-confirm','iso-eject-confirm','power-confirm','network-confirm','working','message')
        for style in ('readable','compact'):
            values={**config.defaults(),'oled_style':style}
            for screen in screens:
                with self.subTest(style=style,screen=screen):self.assert_layout(preview_navigation(screen,values))
            for progress in (None,0,.5,1,2):
                frame=ui.render_message('Erreur / notification',['API indisponible','Réessayer plus tard'],values,'Clic : retour',progress=progress)
                self.assert_layout(frame)
            self.assert_layout(ui.render_idle('screen',values));self.assertIsNone(ui.render_idle('off',values).image.getbbox())

    def test_selected_long_iso_has_visible_overflow_and_scrolling_can_be_disabled(self):
        items=[{'name':'Été / '+'Nom ISO avec espaces '*25,'icon':'disc'} for _ in range(100)]
        for style in ('readable','compact'):
            values={**config.defaults(),'oled_style':style};moving=ui.render_list('Dossiers ISO',items,99,values,phase=3)
            self.assertTrue(moving.animated);self.assertTrue(any(r['elided'] for r in moving.text_runs))
            disabled={**values,'oled_animations':False};first=ui.render_list('ISO',items,99,disabled,phase=0);second=ui.render_list('ISO',items,99,disabled,phase=4)
            self.assertEqual(first.image.tobytes(),second.image.tobytes());self.assertFalse(first.animated);self.assert_layout(first)

    def test_pixel_packing_matches_all_drawn_bars_icons_and_selection(self):
        values={**config.defaults(),'oled_style':'compact'}
        for frame in (ui.render_status('system',SAMPLE,values),preview_navigation('iso',values)):
            decoded=Image.frombytes('1',(128,64),frame.image.tobytes())
            for y in range(64):
                for x in range(128):self.assertEqual(bool(decoded.getpixel((x,y))),bool(frame.image.getpixel((x,y))))
        full=ui.Surface(values);full.bar(3,20,100,10,1)
        self.assertEqual(Image.frombytes('1',(128,64),full.image.tobytes()).getpixel((10,24)),255)

    def test_qr_has_four_quiet_modules_without_interpolation(self):
        for modules in (21,25,29,56):
            qr=Image.new('1',(modules,modules),0)
            frame=ui.render_qr(qr,'Exemple',config.defaults());pane=frame.image.crop((0,0,64,64)).convert('L')
            box=ImageChops.invert(pane).getbbox();factor=(box[2]-box[0])//modules
            self.assertGreaterEqual(box[0],factor*4);self.assertGreaterEqual(64-box[2],factor*4)

    def test_large_combining_input_never_draws_half_a_glyph(self):
        frame=ui.Surface(config.defaults());frame.text('e'+'\u0301'*80,3,20,122,size=12,h=12)
        self.assert_layout(frame);self.assertTrue(any(r['elided'] for r in frame.text_runs) or not frame.text_runs)

    def test_previews_and_optional_physical_output_share_exact_bits_in_both_modes(self):
        settings=Settings(SimpleNamespace(),Path('unused'))
        with tempfile.TemporaryDirectory(dir=ROOT/'private') as directory:
            physical=Mock();device=oled.MirrorDevice('status',path=Path(directory)/'oled/frame.json',factory=lambda:physical,background=False)
            for style in ('readable','compact'):
                values={**config.defaults(),'oled_style':style}
                for page in config.PAGES:
                    preview=settings.preview({'values':values,'page':page})
                    image=Image.frombytes('1',(128,64),base64.b64decode(preview['pixels']))
                    device.display(image);device.output._attempt();device.publish(device.output.latest,force=True)
                    self.assertEqual(physical.display.call_args.args[0].tobytes(),base64.b64decode(oled.read_frame(device.path)['pixels']))
            device.close()


class PreferenceTests(unittest.TestCase):
    def test_rc12_compact_preferences_and_order_are_preserved_without_a_write(self):
        old=json.loads((ROOT/'tests/fixtures/rc12-settings.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory(dir=ROOT/'private') as directory:
            target=Path(directory)/'settings.json';target.write_text(json.dumps(old),encoding='utf-8');target.chmod(0o600);raw=target.read_bytes()
            current=config.Store(target).read()
            self.assertTrue(current['healthy']);self.assertEqual(current['migrated_from'],2);self.assertEqual(current['revision'],9)
            self.assertEqual(current['values']['oled_pages'][:6],old['values']['oled_pages']);self.assertEqual(current['values']['oled_style'],'compact')
            self.assertFalse(any(p['enabled'] for p in current['values']['oled_pages'][6:]));self.assertEqual(target.read_bytes(),raw)
            old['values']['oled_style']='detailed';self.assertEqual(config.migrate_rc12(old['values'])['oled_style'],'readable')
            self.assertEqual(config.defaults()['oled_style'],'readable')

    def test_rc12_snapshot_restores_exact_original_preferences_after_rc121_save(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'private') as directory:
            root=Path(directory);target=root/'settings.json';raw=(ROOT/'tests/fixtures/rc12-settings.json').read_bytes();target.write_bytes(raw);target.chmod(0o600)
            backup=root/'backup';backup.mkdir();h=portable.helper()
            with patch.object(portable,'preferences_module',return_value=config),patch.object(config,'pst_path',return_value=target),patch.object(config,'pst_commit',side_effect=lambda writer:writer(target)):
                metadata=portable.snapshot_preferences(h,backup);manifest={'files':[],'portable_preferences':metadata}
                (backup/'manifest.json').write_text(json.dumps(manifest));portable.verify_backup(h,backup)
                state=config.Store(target).read();state['values']['oled_style']='readable';config.Store(target).save(state['values'],9)
                self.assertEqual(json.loads(target.read_text())['schema_version'],3)
                portable.restore_preferences(h,backup,manifest);self.assertEqual(target.read_bytes(),raw)

    def test_extra_pages_are_selectable_in_order_and_keep_individual_duration(self):
        values=config.defaults();values['oled_start']='system_details';values['oled_pages'][3]['seconds']=7
        config.validate(values);rotation=config.PageRotation()
        self.assertEqual(rotation.choose(values,0),('system_details',7));self.assertEqual(rotation.choose(values,7)[0],'network')
        self.assertEqual(rotation.choose(values,7,request='next')[0],'network_details')


if __name__=='__main__':unittest.main()
