"""RC11 policy, persistence and authenticated API. Synthetic files only."""
import base64
import asyncio
import contextlib
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import pikvm_config as config
from pikvm_settings import Settings
import test_portable_os as integration
from test_oled import script
import pikvm_oled as oled
from PIL import Image


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'settings.json';self.store=config.Store(self.path)

    def write_private(self,value):
        self.path.write_text(value);self.path.chmod(0o600)

    def test_defaults_and_both_numeric_boundaries(self):
        self.assertFalse(config.defaults()['idle_enabled'])
        config.validate(config.defaults())
        for key,spec in config.FIELDS.items():
            if spec['minimum'] is None:continue
            for number in (spec['minimum']-1,spec['maximum']+1,True,1.1,'2'):
                values=config.defaults();values[key]=number
                with self.subTest(key=key,value=number),self.assertRaises(config.ConfigError):config.validate(values)

    def test_strict_schema_rejects_unknown_commands_and_paths(self):
        for key,value in [('gpio17',False),('shell','reboot'),('theme','pink'),('iso_favorite','../escape'),('iso_favorite','/root'),('iso_favorite','a//b'),('kvm_order',['share']),('oled_pages',[]),('kvm_hidden',['poweroff'])]:
            values=config.defaults();values[key]=value
            with self.subTest(key=key),self.assertRaises(config.ConfigError):config.validate(values)

    def test_duplicate_pages_and_all_disabled_and_thresholds(self):
        for mutate in (lambda v:v['oled_pages'].__setitem__(1,copy.deepcopy(v['oled_pages'][0])),
                       lambda v:[p.update(enabled=False) for p in v['oled_pages']],
                       lambda v:v.update(battery_low=10,battery_critical=20),
                       lambda v:v.update(idle_first_seconds=3600,idle_shutdown_seconds=60)):
            values=config.defaults();mutate(values)
            with self.assertRaises(config.ConfigError):config.validate(values)

    def test_noop_and_history_are_bounded_and_revision_checked(self):
        values=config.defaults();first=self.store.save(values,0)
        self.assertEqual(first['revision'],0);self.assertFalse(self.path.exists())
        for i in range(25):
            values['oled_contrast']=i
            result=self.store.save(values,i)
        self.assertEqual(result['revision'],25);self.assertEqual(len(result['history']),20)
        with self.assertRaises(config.ConfigError):self.store.save(values,0)
        self.assertNotIn('password',self.path.read_text())

    def test_repeated_full_resets_cannot_grow_beyond_reader_limit(self):
        for i in range(30):
            result=self.store.save(config.defaults(),i,True,reset=True)
            self.assertTrue(result['healthy']);self.assertLessEqual(self.path.stat().st_size,config.MAX_BYTES)

    def test_sensitive_changes_and_reset_need_confirmation(self):
        values=config.defaults();values['idle_enabled']=True
        with self.assertRaises(config.ConfigError):self.store.save(values,0)
        self.store.save(values,0,True)
        self.assertTrue(self.store.read()['values']['idle_enabled'])
        self.store.save(config.defaults(),1,True,reset=True)
        self.assertFalse(self.store.read()['values']['idle_enabled'])

    def test_interrupted_write_preserves_previous_file_and_cleans_temp(self):
        values=config.defaults();values['theme']='light';self.store.save(values,0)
        before=self.path.read_bytes();values['theme']='dark'
        with patch.object(config.os,'replace',side_effect=OSError('synthetic interruption')):
            with self.assertRaises(OSError):self.store.save(values,1)
        self.assertEqual(before,self.path.read_bytes());self.assertFalse(list(self.path.parent.glob('.settings-*')))

    def test_corruption_uses_safe_defaults_and_explicit_recovery(self):
        for raw in ('{broken','[]','{"schema_version":999}',json.dumps({'schema_version':1,'values':{'shell':'shutdown'}})):
            self.write_private(raw)
            document=self.store.read();self.assertFalse(document['healthy']);self.assertFalse(document['values']['idle_enabled'])
            with self.assertRaises(config.ConfigError):self.store.save(config.defaults(),'corrupt')
        self.store.save(config.defaults(),'corrupt',True,reset=True)
        self.assertTrue(self.store.read()['healthy'])

    def test_safe_migration_and_future_schema_rejection(self):
        self.write_private('{"schema_version":0,"theme":"light"}')
        self.assertEqual(self.store.read()['values']['theme'],'light');self.assertFalse(self.store.read()['values']['idle_enabled'])
        self.store.save(self.store.read()['values'],0)
        self.write_private('{"schema_version":0,"theme":"light","command":"anything"}')
        self.assertFalse(self.store.read()['healthy'])

    def test_concurrent_instances_only_one_revision_wins(self):
        barrier=threading.Barrier(8);results=[]
        def writer(i):
            values=config.defaults();values['oled_contrast']=i
            barrier.wait()
            try:config.Store(self.path).save(values,0);results.append('ok')
            except config.ConfigError:results.append('conflict')
        threads=[threading.Thread(target=writer,args=(i,)) for i in range(8)]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertEqual(results.count('ok'),1);self.assertEqual(results.count('conflict'),7)

    def test_pst_root_resolves_from_fstab_without_assuming_msd_path(self):
        fstab=Path(self.temp.name)/'fstab';fstab.write_text('LABEL=PST /var/lib/kvmd/pst ext4 ro,X-kvmd.pst-root=/var/lib/kvmd/pst/data 0 0\n')
        self.assertEqual(config.pst_path(fstab),Path('/var/lib/kvmd/pst/data/portable-os/settings.json'))
        fstab.write_text('LABEL=PIPST /var/lib/kvmd/pst ext4 ro,X-kvmd.pst-user=kvmd-pst 0 2\n')
        self.assertEqual(config.pst_path(fstab),Path('/var/lib/kvmd/pst/portable-os/settings.json'))
        fstab.write_text('LABEL=MSD /var/lib/kvmd/msd ext4 rw 0 0\n')
        with self.assertRaises(config.ConfigError):config.pst_path(fstab)

    def test_production_write_requires_pst_and_never_falls_back_to_root(self):
        with patch.object(config,'pst_path',side_effect=config.ConfigError('PST absent',503)):
            doc=config.Configuration().read();self.assertFalse(doc['healthy'])
        with patch.dict(sys.modules,{'kvmd.apps':None}):
            with self.assertRaises(config.ConfigError):config.Configuration().save(config.defaults(),0,True,True)


class OledPreferenceTests(unittest.TestCase):
    def test_disabled_pages_order_and_individual_duration(self):
        values=config.defaults();values['oled_pages'][0],values['oled_pages'][1]=values['oled_pages'][1],values['oled_pages'][0]
        values['oled_start']='battery'
        values['oled_pages'][0]['seconds']=5
        for page in values['oled_pages']:
            if page['id'] in ('system','network','usb'):page['enabled']=False
        rotation=config.PageRotation();self.assertEqual(rotation.choose(values,0)[0],'battery')
        self.assertEqual(rotation.choose(values,4)[0],'battery');self.assertEqual(rotation.choose(values,5)[0],'main')
        self.assertEqual(rotation.choose(values,15)[0],'battery')

    def test_conditional_alert_priorities_return_and_critical_cannot_hide(self):
        values=config.defaults();values['oled_pages'][-1]['enabled']=False
        rotation=config.PageRotation()
        self.assertEqual(rotation.choose(values,0,True,15,critical_transfer=True)[0],'transfer')
        self.assertEqual(rotation.choose(values,6,True,50)[0],'main')
        self.assertEqual(rotation.choose(values,7,True,5)[0],'battery')
        values['oled_transfer_priority']=5;values['oled_low_priority']=1
        self.assertEqual(config.PageRotation().choose(values,0,True,15)[0],'battery')

    def test_permanent_page_and_logical_next_request(self):
        values=config.defaults();values.update(oled_auto=False,oled_fixed='system')
        for page in values['oled_pages']:
            if page['id'] in ('network','usb'):page['enabled']=False
        rotation=config.PageRotation();self.assertEqual(rotation.choose(values,0)[0],'system')
        self.assertEqual(rotation.choose(values,100,request='next')[0],'main')
        self.assertEqual(rotation.choose(values,105)[0],'main')
        self.assertEqual(rotation.choose(values,111)[0],'system')

    def test_rotation_exact_pixels_and_contrast_in_async_physical_output(self):
        with tempfile.TemporaryDirectory() as directory:
            physical=Mock();device=oled.MirrorDevice('status',path=Path(directory)/'oled/frame.json',factory=lambda:physical,background=False)
            image=Image.new('1',(128,64));image.putpixel((0,0),255)
            values=config.defaults();values.update(oled_rotation='180',oled_contrast=42)
            with patch.object(oled.READER,'get',return_value=values):device.display(image)
            device.output._attempt()
            result=oled.read_frame(device.path);raw=base64.b64decode(result['pixels'])
            self.assertEqual(raw,physical.display.call_args.args[0].tobytes());self.assertTrue(raw[-1]&1)
            physical.contrast.assert_called_with(42)

    def test_button_customization_does_not_change_gesture_or_gpio_reader(self):
        from oled_nav_fixtures import Harness
        h=Harness();h.values['button_menu_timeout']=25;h.nav.change('menu');h.now+=24;h.nav.tick()
        self.assertEqual(h.nav.screen,'menu');h.now+=2;h.nav.tick();self.assertEqual(h.nav.screen,'status')
        from pikvm_gpio import pinctrl_sample
        from test_oled import menu
        self.assertIs(menu.pinctrl_sample,pinctrl_sample)

    def test_status_short_customization_long_menu_and_cancelled_gpio(self):
        from oled_nav_fixtures import Harness
        for action in ('menu','battery','next'):
            h=Harness();h.values['button_short']=action;h.click()
            if action=='menu':self.assertEqual(h.nav.screen,'menu')
            else:h.backend.status_page.assert_called_with(action)
            h=Harness();h.values['button_short']=action;h.step(True);h.wait(.1,True);h.step(None);h.wait(.5)
            h.backend.status_page.assert_not_called();self.assertEqual(h.nav.screen,'status')


class PstHandoverTests(unittest.TestCase):
    def make_client(self,failures,after_yield=False):
        calls=[]
        class Refused(Exception):pass
        @contextlib.asynccontextmanager
        async def writable():
            calls.append(True)
            if len(calls)<=failures:raise Refused('Write is not allowed')
            yield '/synthetic/pst/portable-os'
            if after_yield:raise Refused('Lease lost after writer')
        return lambda:SimpleNamespace(writable=writable),Refused,calls

    def test_ro_transition_is_reacquired_before_any_writer_runs(self):
        factory,refused,calls=self.make_client(2);writer=Mock(return_value='saved');delays=[]
        async def sleep(delay):delays.append(delay)
        result=asyncio.run(config.pst_write(factory,writer,refused,sleep))
        self.assertEqual(result,'saved');self.assertEqual(len(calls),3);writer.assert_called_once();self.assertEqual(delays,[.1,.2])

    def test_persistent_denial_is_bounded_and_fail_closed(self):
        factory,refused,calls=self.make_client(100);writer=Mock()
        async def sleep(_):pass
        with self.assertRaises(refused):asyncio.run(config.pst_write(factory,writer,refused,sleep))
        self.assertEqual(len(calls),7);writer.assert_not_called()

    def test_error_after_writer_never_replays_a_potential_commit(self):
        factory,refused,calls=self.make_client(0,after_yield=True);writer=Mock()
        with self.assertRaises(refused):asyncio.run(config.pst_write(factory,writer,refused))
        self.assertEqual(len(calls),1);writer.assert_called_once()

    def test_validation_or_io_errors_are_not_retried(self):
        for error in (config.ConfigError('path mismatch'),OSError('synthetic write failure')):
            factory,refused,calls=self.make_client(0);writer=Mock(side_effect=error)
            with self.assertRaises(type(error)):asyncio.run(config.pst_write(factory,writer,refused))
            self.assertEqual(len(calls),1)


class IdlePolicyTests(unittest.TestCase):
    def setUp(self):
        self.now=0;self.engine=config.IdleEngine(clock=lambda:self.now);self.values=config.defaults();self.values['idle_enabled']=True
        self.safe=dict.fromkeys(('drive0','drive1','transfer','share','storage','install','ssh'),False)

    def test_multiple_activity_sources_and_disabled_sources(self):
        self.now=200;self.engine.activity('web',self.values);self.now=250
        self.assertEqual(self.engine.evaluate(self.values,self.safe)['elapsed'],50)
        self.values['activity_mouse']=False;self.engine.activity('mouse',self.values)
        self.assertEqual(self.engine.evaluate(self.values,self.safe)['source'],'web')
        self.engine.activity('button',self.values);self.assertEqual(self.engine.evaluate(self.values,self.safe)['elapsed'],0)
        with self.assertRaises(config.ConfigError):self.engine.activity('ssh_keystroke',self.values)

    def test_critical_inhibitors_cannot_be_disabled_and_unknown_is_blocked(self):
        self.now=2000
        for key in self.safe:
            for value in (True,None):
                result=self.engine.evaluate(self.values,{**self.safe,key:value})
                self.assertTrue(result['inhibitors']);self.assertFalse(result['shutdown_allowed']);self.assertFalse(result['simulation_would_allow'])

    def test_safe_simulation_never_executes_shutdown(self):
        self.now=2000;result=self.engine.evaluate(self.values,self.safe)
        self.assertTrue(result['simulation_would_allow']);self.assertFalse(result['shutdown_allowed'])
        self.assertIn('non activable',result['reason'])

    def test_kvm_presence_lease_is_separate_from_activity(self):
        self.now=1700;self.engine.presence();self.now=1710
        result=self.engine.evaluate(self.values,self.safe)
        self.assertEqual(result['elapsed'],1710);self.assertTrue(result['inhibitors'])
        self.now=1730;self.assertFalse(self.engine.evaluate(self.values,self.safe)['inhibitors'])

    def test_warning_first_action_and_service_restart_are_safe(self):
        self.values['idle_action']='off';self.now=1750
        result=self.engine.evaluate(self.values,self.safe);self.assertTrue(result['warning']);self.assertEqual(result['action'],'off')
        restarted=config.IdleEngine(clock=lambda:self.now);self.assertEqual(restarted.evaluate(self.values,self.safe)['elapsed'],0)
        self.values['idle_enabled']=False;self.assertEqual(self.engine.evaluate(self.values,self.safe)['action'],'none')


class ConfigApiTests(unittest.TestCase):
    cleanup=integration.IntegrationAuthTests.cleanup
    request=integration.IntegrationAuthTests.request
    def setUp(self):
        integration.IntegrationAuthTests.setUp(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.server.backend.settings=Settings(self.server.backend,Path(self.temp.name)/'settings.json')

    def test_all_new_routes_require_authentication_and_csrf(self):
        for route in ('settings','settings/current','settings/export','idle','report','integrity'):
            self.assertEqual(self.request(route,auth=False),401)
        for route in ('settings/apply','settings/reset','settings/import','activity','idle/simulate'):
            self.assertEqual(self.request(route,{},auth=False),401);self.assertEqual(self.request(route,{},csrf=False),403)

    def test_strict_valid_apply_and_conflict(self):
        self.assertEqual(self.request('settings'),200)
        values=config.defaults();values['theme']='light'
        payload={'values':values,'expected_revision':0,'confirmed':False}
        self.assertEqual(self.request('settings/apply',payload),200)
        self.assertEqual(self.request('settings/apply',payload),409)
        self.assertEqual(self.request('settings/apply',{**payload,'shell':'reboot'}),400)

    def test_import_export_and_secret_fields_are_rejected(self):
        settings=self.server.backend.settings;document=settings.export()
        self.assertEqual(set(document),{'format','schema_version','values'})
        self.assertEqual(self.request('settings/export'),200)
        document['values']['password']='secret'
        self.assertEqual(self.request('settings/import',{'expected_revision':0,'confirmed':True,'config':document}),400)

    def test_preview_uses_real_renderers_without_hardware_or_persistence(self):
        settings=self.server.backend.settings
        for page in config.PAGES:
            frame=settings.preview({'values':config.defaults(),'page':page})
            self.assertEqual(len(base64.b64decode(frame['pixels'])),1024);self.assertTrue(frame['synthetic'])
        self.assertFalse(settings.configuration.store().path.exists())
        values=config.defaults();values['oled_rotation']='180'
        normal=settings.preview({'values':config.defaults(),'page':'main'})
        rotated=settings.preview({'values':values,'page':'main'})
        self.assertNotEqual(normal['pixels'],rotated['pixels'])
        self.assertEqual(self.request('settings/preview',{'values':values,'page':'main'},csrf=False),403)

    def test_simulation_and_unknown_activity_do_not_trigger_commands(self):
        with patch.object(integration.api,'run') as command:
            self.assertEqual(self.request('idle/simulate',{'elapsed':2000,'evidence':dict.fromkeys(('drive0','drive1','transfer','share','storage','install','ssh'),False)}),200)
            self.assertEqual(self.request('activity',{'source':'keyboard'}),200)
            self.assertEqual(self.request('activity',{'source':'ssh'}),400)
        command.assert_not_called()


if __name__=='__main__':unittest.main()
