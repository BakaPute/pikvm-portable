"""Native config isolation is bounded, cached and fail-closed; no real commands."""
import json,subprocess,sys,tempfile,unittest,hashlib,threading
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import pikvm_security_admin as admin
from pikvm_security import SecurityError
from pikvm_settings import Settings
from pikvm_config import ConfigError

class NativeConfigTests(unittest.TestCase):
    def tearDown(self):admin.native_auth_path.cache_clear()
    def test_isolated_lookup_returns_only_path_and_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'htpasswd';child=Mock(returncode=0)
            child.communicate.return_value=(json.dumps({'enabled':True,'internal':'htpasswd','external':'','file':str(path)}),'')
            with patch.object(admin.subprocess,'Popen',return_value=child) as spawn:
                self.assertEqual(admin.native_auth_path(),path);self.assertEqual(admin.native_auth_path(),path);spawn.assert_called_once()
                self.assertEqual(spawn.call_args.kwargs['stdin'],subprocess.DEVNULL)
                self.assertTrue(spawn.call_args.kwargs['start_new_session'])
                self.assertNotIn('passwd=',spawn.call_args.args[0][-1])
    def test_bad_native_configuration_never_grants_fallback(self):
        for output in ('broken',json.dumps({'enabled':False,'internal':'htpasswd','external':'','file':'/etc/kvmd/htpasswd'}),json.dumps({'enabled':True,'internal':'htpasswd','external':'','file':'relative'})):
            admin.native_auth_path.cache_clear();child=Mock(returncode=0);child.communicate.return_value=(output,'')
            with patch.object(admin.subprocess,'Popen',return_value=child):
                with self.assertRaises(SecurityError):admin.native_auth_path()
    def test_parallel_cold_reads_spawn_only_one_reader(self):
        entered=threading.Event();release=threading.Event();values=[]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'htpasswd';child=Mock(returncode=0)
            def answer(**kwargs):
                entered.set();release.wait(2)
                return json.dumps({'enabled':True,'internal':'htpasswd','external':'','file':str(path)}),''
            child.communicate.side_effect=answer
            with patch.object(admin.subprocess,'Popen',return_value=child) as spawn:
                threads=[threading.Thread(target=lambda:values.append(admin.native_auth_path())) for _ in range(2)]
                for thread in threads:thread.start()
                self.assertTrue(entered.wait(1));release.set()
                for thread in threads:thread.join(3);self.assertFalse(thread.is_alive())
                self.assertEqual(values,[path,path]);spawn.assert_called_once()
    def test_timeout_kills_reader_group_and_drains_pipes(self):
        child=Mock(pid=123456);child.communicate.side_effect=[subprocess.TimeoutExpired('reader',15),('','')]
        with patch.object(admin.subprocess,'Popen',return_value=child),patch.object(admin.os,'killpg',create=True) as kill:
            with self.assertRaises(SecurityError):admin.native_auth_path()
            if admin.os.name=='posix':kill.assert_called_once()
            else:child.kill.assert_called_once()
            self.assertEqual(child.communicate.call_count,2)

class GatewayIntegrityTests(unittest.TestCase):
    def test_gateway_unit_is_in_integrity_scope_but_other_units_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);unit=root/'gateway.service';unit.write_bytes(b'synthetic unit')
            manifest=root/'integrity.json';name='/etc/systemd/system/pikvm-security-gateway.service'
            def path(value):return manifest if value=='/usr/local/lib/pikvm-portable/integrity.json' else unit
            manifest.write_text(json.dumps({name:hashlib.sha256(unit.read_bytes()).hexdigest()}))
            with patch('pikvm_settings.Path',side_effect=path):self.assertTrue(Settings(None).integrity()['valid'])
            manifest.write_text(json.dumps({name+'.unexpected':hashlib.sha256(unit.read_bytes()).hexdigest()}))
            with patch('pikvm_settings.Path',side_effect=path):
                with self.assertRaises(ConfigError):Settings(None).integrity()

if __name__=='__main__':unittest.main()
