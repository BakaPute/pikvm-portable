"""Gestures, single framebuffer producer and native ISO adapter safety."""
import contextlib
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from oled_nav_fixtures import Harness,Worker
from pikvm_gestures import Gestures,Permit,Gesture
from pikvm_oled_nav import Navigation,NavigationReader,render_navigation,preview_navigation,Worker as ActionWorker
from pikvm_iso import Library,NativeMsd,visible
import pikvm_transfer as transfer
from test_oled import script,oled


class GestureTests(unittest.TestCase):
    def test_bounce_only_advances_once_and_sub_debounce_noise_never_clicks(self):
        h=Harness();h.nav.change('menu')
        for down,delay in [(True,.01),(False,.01),(True,.01),(True,.04),(True,.1),(False,.01),(True,.01),(False,.01)]:h.step(down,delay)
        h.wait(.5);self.assertEqual(h.nav.index,1)
        h=Harness();h.step(True,.01);h.step(False,.01);h.wait(.5)
        h.backend.status_page.assert_not_called()

    def test_double_opens_without_dispatching_pending_single(self):
        h=Harness();h.nav.change('menu')
        h.step(True);h.wait(.1,True);h.step(False);h.wait(.08)
        h.step(True);h.wait(.1,True);h.step(False);events=h.wait(.08)
        self.assertEqual([e.kind for e in events],['double']);self.assertEqual(h.nav.screen,'power')
        self.assertEqual(h.nav.index,0);h.wait(.6);self.assertEqual(h.nav.index,0)

    def test_boundaries_release_debounce_cannot_extend_a_hold(self):
        for duration,kind in [(1.19,'single'),(1.2,'hold'),(2.,'hold'),(3.,'hold'),(5.,'hold')]:
            h=Harness();events=h.hold(duration);events+=h.wait(.5)
            self.assertEqual([e.kind for e in events],[kind],duration)
            self.assertAlmostEqual(events[0].duration,duration,places=6)

    def test_context_change_owner_change_and_second_hold_discard_pending_single(self):
        for change in ('context','hold'):
            h=Harness();h.nav.change('menu');h.step(True);h.wait(.1,True);h.step(False);h.wait(.08)
            if change=='context':h.nav.change('wifi');h.wait(.5);self.assertEqual(h.nav.index,0)
            else:h.hold(1.3);h.wait(.5);self.assertEqual(h.nav.screen,'status')
        engine=Gestures(debounce=0)
        engine.feed(True,0,origin='remote',owner='a',context=1);engine.feed(False,.1,origin='remote',owner='a',context=1)
        engine.feed(True,.2,origin='remote',owner='b',context=1)
        self.assertEqual(engine.feed(False,.3,origin='remote',owner='b',context=1),[])
        self.assertEqual(engine.feed(False,.7,origin='remote',owner='b',context=1)[0].kind,'single')

    def test_gpio_loss_and_scheduler_stall_never_become_long_actions(self):
        for fault in (None,'stall'):
            h=Harness();h.nav.operation='shutdown';h.nav.change('power-confirm')
            h.step(True);h.wait(4.8,True)
            h.step(None if fault is None else True,seconds=.02 if fault is None else 1)
            h.wait(.4,True);h.wait(.5,False)
            self.assertIsNone(h.worker.task);h.backend.sensitive.assert_not_called()

    def test_three_seconds_home_never_powers_off_from_a_normal_menu(self):
        h=Harness();h.nav.change('menu');h.hold(5)
        self.assertEqual(h.nav.screen,'status');self.assertIsNone(h.worker.task)
        h.backend.sensitive.assert_not_called()

    def test_power_thresholds_only_after_separate_confirmation_and_permission(self):
        for operation,threshold in [('restart',2),('shutdown',5),('hotspot',5)]:
            for duration,allowed,executes in [(threshold-.01,True,False),(threshold,False,False),(threshold,True,True)]:
                h=Harness();h.nav.operation=operation;h.nav.change('network-confirm' if operation=='hotspot' else 'power-confirm')
                h.gesture('hold',duration,lambda _:allowed)
                self.assertEqual(h.worker.task is not None,executes,(operation,duration,allowed))
                if executes:h.finish();h.backend.sensitive.assert_called_once()
        permit=Permit('power',10);permit.consume('power',11)
        with self.assertRaises(RuntimeError):permit.consume('power',11)
        with self.assertRaises(RuntimeError):Permit('power',0).consume('power',3)

    def test_virtual_double_and_overlap_use_real_logical_transport_and_800ms_lease(self):
        h=Harness();h.nav.change('menu');h.frame['context']=h.nav.context()
        for n in range(2):
            identity={'owner':'c'*64,'gesture_id':str(n)*32}
            h.button.remote({**identity,'action':'start','control_id':'b'*64,'permit':''})
            h.step(False);h.wait(.06);h.button.remote({**identity,'action':'stop'});h.step(False);h.wait(.06)
        self.assertEqual(h.nav.screen,'power');self.assertIsNone(h.worker.task)
        h=Harness();h.nav.change('menu');h.frame['context']=h.nav.context()
        identity={'owner':'c'*64,'gesture_id':'1'*32}
        h.button.remote({**identity,'action':'start','control_id':'b'*64,'permit':''});h.step(False)
        h.step(True);h.wait(.8,True);h.wait(.5)
        self.assertEqual(h.nav.index,0);self.assertIsNone(h.worker.task)

    def test_stale_navigation_context_rejected_before_remote_start(self):
        h=Harness();h.nav.change('menu')
        with self.assertRaises(oled.OledError):
            h.button.remote({'action':'start','owner':'c'*64,'gesture_id':'1'*32,'control_id':'b'*64,'permit':''})


class NavigationTests(unittest.TestCase):
    def test_hierarchical_iso_open_select_confirm_cd_flash_eject_and_no_delete(self):
        h=Harness();h.nav.change('menu')
        state={'drive':{'connected':False}}
        h.backend.library.side_effect=lambda folder,scope:(state,[{'name':'Retour','kind':'back'},{'name':'Linux' if not folder else 'Debian test.iso','kind':'folder' if not folder else 'file','path':'Linux' if not folder else 'Linux/Debian test.iso','complete':True,'size':123}])
        h.select('iso');self.assertEqual(h.nav.screen,'working');h.backend.connect.assert_not_called();h.finish()
        h.select('browse');h.finish();h.select('folder');h.finish()
        self.assertEqual(h.nav.folder,'Linux');h.select('file');self.assertEqual(h.nav.screen,'iso-action')
        h.select('info');self.assertEqual(h.nav.screen,'iso-info');h.gesture('single')
        for mode in ('cdrom','flash'):
            h.nav.change('iso-action');h.select(mode);h.backend.connect.assert_not_called();h.backend.connect.return_value={'drive':{'connected':True}}
            h.gesture();h.finish();h.backend.connect.assert_called_once_with('Linux/Debian test.iso',mode=='cdrom');h.backend.connect.reset_mock()
        h.nav.msd={'drive':{'connected':True}};h.nav.change('iso-root');h.select('eject');h.backend.eject.assert_not_called()
        h.backend.eject.return_value=state;h.gesture();h.finish();h.backend.eject.assert_called_once_with(True)
        self.assertFalse(any('delete' in str(row) for row in h.nav.items()))

    def test_favorites_recent_and_favorite_action_use_worker_without_auto_connection(self):
        h=Harness();h.nav.change('iso-root');h.backend.library.return_value=({},[{'kind':'back','name':'Retour'}])
        for scope in ('favorites','recent'):
            h.nav.change('iso-root');h.select(scope);h.finish();h.backend.library.assert_called_with('',scope)
        h.nav.target='Linux/test.iso';h.nav.change('iso-action');h.select('favorite');h.finish()
        h.backend.favorite.assert_called_once_with('Linux/test.iso');h.backend.connect.assert_not_called()

    def test_worker_errors_and_timeouts_never_replay_and_late_result_does_not_steal_home(self):
        h=Harness();h.backend.library.side_effect=RuntimeError('API indisponible');h.nav.refresh_library();h.finish()
        self.assertEqual(h.nav.screen,'message');self.assertIn('API indisponible',h.nav.error)
        h.backend.library.side_effect=None;h.backend.library.return_value=({},[])
        h.nav.refresh_library();h.gesture('hold',3);self.assertEqual(h.nav.screen,'status');h.finish();self.assertEqual(h.nav.screen,'status')
        h.nav.change('menu');h.now+=61;h.nav.tick();self.assertEqual(h.nav.screen,'status')

    def test_slow_worker_is_bounded_and_never_blocks_navigation(self):
        import threading
        release=threading.Event();started=threading.Event();worker=ActionWorker()
        def slow():started.set();release.wait(2);return 1
        try:
            self.assertTrue(worker.submit(slow));self.assertTrue(started.wait(1))
            before=time.perf_counter()
            for _ in range(1000):self.assertIsNone(worker.poll());self.assertFalse(worker.submit(slow))
            self.assertLess(time.perf_counter()-before,.5)
        finally:release.set();worker.close()

    def test_small_navigation_model_reader_requires_fresh_controller_and_matching_pid(self):
        h=Harness();h.nav.change('iso');h.nav.entries=[{'name':'long '*100,'kind':'file'} for _ in range(4000)];h.nav.index=2500
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'oled/nav.json';h.nav.publish=Navigation.publish.__get__(h.nav);h.nav.publish(path)
            self.assertLess(path.stat().st_size,8192);reader=NavigationReader(path)
            self.assertIsNone(reader.read({'ready':False}));self.assertIsNone(reader.read({'ready':True,'pid':0}))
            model=reader.read({'ready':True,'pid':__import__('os').getpid()});self.assertEqual(model['count'],4000)
            frame=render_navigation(model,h.values);self.assertEqual(frame.image.size,(128,64))


class IsoTests(unittest.TestCase):
    def state(self,connected=False):
        return {'enabled':True,'online':True,'busy':False,'drive':{'connected':connected,'image':{'name':'Linux/Debian test.iso'},'cdrom':True,'rw':False},
                'storage':{'uploading':None,'downloading':False,'images':{'Linux/Debian test.iso':{'complete':True,'size':123},'Windows/Win11/test.iso':{'complete':True},'.USB-TRANSFER.img':{'complete':True}}}}
    def test_tree_native_paths_root_deep_and_hidden_container_excluded(self):
        library=Library();state=self.state()
        self.assertEqual([r['name'] for r in library.entries(state)],['Retour','Linux','Windows'])
        self.assertEqual(library.entries(state,'Linux')[1]['name'],'Debian test.iso')
        self.assertEqual(library.entries(state,'Windows')[1]['path'],'Windows/Win11')
        for name in ('/a.iso','../a.iso','.USB-TRANSFER.img','x/../a.iso','x\\a.iso','x//a.iso','lost+found/a.iso'):
            self.assertFalse(visible(name),name)
    def test_native_connect_modes_and_eject_use_only_whitelisted_api_with_fresh_guards(self):
        for cdrom in (True,False):
            with tempfile.TemporaryDirectory() as directory,contextlib.ExitStack() as stack:
                root=Path(directory);(root/'Linux').mkdir();(root/'Linux/Debian test.iso').write_bytes(b'synthetic')
                native=Mock();state=self.state();selected=copy.deepcopy(state);selected['drive']['cdrom']=cdrom
                observation={'busy':True,'drive':{'known':True,'image':'','transfer_active':False}}
                final=copy.deepcopy(selected);final['drive']['connected']=True
                replies=iter([state,{},selected,{},final])
                def request(method,path,params=None):
                    if path=='/msd/set_connected':observation['drive']['image']=str(root/'Linux/Debian test.iso') if params['connected'] else ''
                    return next(replies)
                native.request.side_effect=request
                stack.enter_context(patch.object(transfer,'observe',return_value=observation));stack.enter_context(patch.object(transfer,'require_not_stopping'))
                stack.enter_context(patch.object(transfer,'exclusive',side_effect=lambda _:contextlib.nullcontext()))
                library=Library(root,native);library.connect('Linux/Debian test.iso',cdrom)
                posts=[call.args for call in native.request.call_args_list if call.args[0]=='POST']
                self.assertEqual(posts,[('POST','/msd/set_params',{'image':'Linux/Debian test.iso','cdrom':int(cdrom),'rw':0}),('POST','/msd/set_connected',{'connected':1})])
                native.reset_mock();replies=iter([self.state(True),{},self.state()])
                observation['drive']['image']=str(root/'Linux/Debian test.iso')
                with self.assertRaises(RuntimeError):library.eject(False)
                self.assertEqual(native.request.call_count,0);library.eject(True)
                self.assertIn(unittest.mock.call('POST','/msd/set_connected',{'connected':0}),native.request.call_args_list)
    def test_unknown_busy_upload_transfer_or_mismatched_media_fail_closed(self):
        library=Library();observation={'busy':False,'drive':{'known':True,'image':'','transfer_active':False}}
        for field,value in [('online',False),('enabled',False),('busy',True)]:
            state=self.state();state[field]=value
            with patch.object(transfer,'observe',return_value=observation),self.assertRaises(RuntimeError):library.guard(state)
        for state,obs in [(self.state(),{'busy':None}), (self.state(),{'busy':False,'drive':{'known':False}}),
                          (self.state(True),observation),({**self.state(),'storage':{'uploading':True,'downloading':False}},observation)]:
            with patch.object(transfer,'observe',return_value=obs),self.assertRaises(RuntimeError):library.guard(state)
        for method,path in [('POST','/msd/reset'),('DELETE','/msd'),('POST','/hid/reset')]:
            with self.assertRaises(RuntimeError):NativeMsd().request(method,path)
    def test_params_failure_or_disagreement_never_connects(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.ExitStack() as stack:
            root=Path(directory);(root/'Linux').mkdir();(root/'Linux/Debian test.iso').write_bytes(b'synthetic')
            native=Mock();native.request.side_effect=[self.state(),{}, {**self.state(),'drive':{'connected':False,'image':{'name':'other.iso'},'rw':False,'cdrom':True}}]
            stack.enter_context(patch.object(transfer,'exclusive',side_effect=lambda _:contextlib.nullcontext()))
            stack.enter_context(patch.object(transfer,'observe',return_value={'busy':True,'drive':{'known':True,'image':'','transfer_active':False}}))
            stack.enter_context(patch.object(transfer,'require_not_stopping'))
            with self.assertRaises(RuntimeError):Library(root,native).connect('Linux/Debian test.iso',True)
            self.assertFalse(any(c.args[1]=='/msd/set_connected' for c in native.request.call_args_list))


class BackendTests(unittest.TestCase):
    def test_favorites_toggle_persist_and_recent_is_bounded_without_touching_images(self):
        from pikvm_config import Configuration
        backend=script('pikvm-button-menu').Backend()
        with tempfile.TemporaryDirectory() as directory:
            backend.preferences=Configuration(Path(directory)/'settings.json');backend.iso=Mock()
            backend.favorite('Linux/test.iso');self.assertEqual(backend.preferences.read()['values']['iso_favorites'],['Linux/test.iso'])
            backend.favorite('Linux/test.iso');self.assertEqual(backend.preferences.read()['values']['iso_favorites'],[])
            for index in range(15):backend.remember('iso_recent',f'Linux/Test {index}.iso')
            recent=backend.preferences.read()['values']['iso_recent'];self.assertEqual(len(recent),12);self.assertEqual(recent[0],'Linux/Test 14.iso')
            backend.iso.connect.assert_not_called();backend.iso.eject.assert_not_called()

    def test_failed_history_write_does_not_replay_a_successful_native_connection(self):
        backend=script('pikvm-button-menu').Backend();backend.iso=Mock();backend.iso.connect.return_value={'drive':{'connected':True}}
        backend.remember=Mock(side_effect=RuntimeError('PST denied'))
        result=backend.connect('Linux/test.iso',True)
        self.assertTrue(result['drive']['connected']);self.assertIn('historique',result['portable_notice']);backend.iso.connect.assert_called_once()

    def test_hotspot_qr_uses_real_setting_names_and_sends_secret_only_on_stdin(self):
        from PIL import Image
        menu=script('pikvm-button-menu');backend=menu.Backend()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);active=root/'active';active.touch()
            def encode(args,**options):
                Image.new('1',(29,29),1).save(options['stdout'],format='PNG')
                return Mock(returncode=0)
            with patch.object(menu,'HOTSPOT_STATE',active),patch.object(menu,'RUNTIME',root/'oled'), \
                 patch.object(menu,'load_hotspot',return_value={'HOTSPOT_SSID':'Synthetic Wi-Fi','HOTSPOT_PASS':'fixture-qr-secret'}), \
                 patch.object(menu.subprocess,'run',side_effect=encode) as run:
                nonce=backend.qr();self.assertNotIn('fixture-qr-secret',nonce)
                self.assertNotIn('fixture-qr-secret',str(run.call_args.args))
                self.assertIn(b'fixture-qr-secret',run.call_args.kwargs['input'])
                self.assertTrue((root/'oled/qr.png').is_file());self.assertFalse((root/'oled/.qr-new.png').exists())

    def test_rc12_permissions_are_only_available_on_dedicated_confirmations(self):
        for screen,permit,allowed in [('menu','power',False),('power-confirm','power',True),('network-confirm','network',True),('iso-connect-confirm','delete',False)]:
            h=Harness();h.nav.change(screen);h.frame['context']=h.nav.context()
            data={'action':'start','owner':'c'*64,'gesture_id':'1'*32,'control_id':'b'*64,'permit':permit}
            if allowed:self.assertTrue(h.button.remote(data)['accepted'])
            else:
                with self.assertRaises(oled.OledError):h.button.remote(data)


if __name__=='__main__':unittest.main()
