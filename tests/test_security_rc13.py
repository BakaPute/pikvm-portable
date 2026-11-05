"""Real isolated accounts, permission decisions, concurrent changes and corruption."""
import base64
import copy
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import pikvm_security as security
import pikvm_access as access
import pikvm_security_bridge as bridge
from pikvm_ssh import plan,ssh_options

PASSWORD='Synthetic-Administrator-2026!'
OTHER='Synthetic-Operator-2026!'
PUBLIC='ssh-ed25519 '+base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0 '+bytes(range(32))).decode()

class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded=security.password_hash(PASSWORD)
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.directory.cleanup);self.root=Path(self.directory.name)
        self.store=security.SecurityStore(self.root/'identities.json',writer=lambda f:f(),lock_path=self.root/'users.lock',strict=False)
        document={'schema':1,'revision':0,'users':{'supervisor':self.store.new_user('supervisor',self.encoded,'administrator')},'roles':copy.deepcopy(security.ROLES),'history':[]}
        self.store.write(document);self.admin=security.native_admin('a'*64)
    def change(self,action,name='member',**data):
        return self.store.mutate(self.admin,{'action':action,'name':name,'expected_revision':self.store.read()['revision'],'confirmed':True,**data},native_users=['admin'])
    def create(self,name='member',role='operator'):
        self.change('create',name,role=role,password=OTHER,display='Synthetic member');return self.store.principal(name)

class IdentityTests(Fixture):
    def test_password_hash_strength_no_export_and_native_collision(self):
        self.create();data=self.store.public(self.store.read());encoded=json.dumps(data)
        self.assertNotIn(OTHER,encoded);self.assertNotIn('pbkdf2',encoded);self.assertNotIn('password',encoded)
        self.assertTrue(security.password_matches(PASSWORD,self.encoded))
        for value in ('short','a'*30,'weakpasswordonlylong'):
            with self.assertRaises(security.SecurityError):security.password_hash(value)
        with self.assertRaises(security.SecurityError):self.change('create','admin',role='readonly',password=OTHER)
        for name in ('root','kvmd-user','../test','user name','-option','Upper','école'):
            with self.assertRaises(security.SecurityError):security.username(name)
    def test_last_administrator_delete_disable_demote_or_deny_are_refused(self):
        cases=[('delete',{}),('edit',{'changes':{'enabled':False}}),('edit',{'changes':{'role':'readonly'}}),('edit',{'changes':{'deny':['roles.manage']}})]
        for action,data in cases:
            with self.assertRaises(security.SecurityError):self.change(action,'supervisor',**data)
            self.assertEqual(self.store.read()['revision'],0)
    def test_second_admin_and_delete_recreate_does_not_reclaim_linux_identity(self):
        self.create('backupadmin','administrator');self.change('delete','supervisor')
        self.create('codex','maintenance');old=self.store.read()['users']['codex']['id']
        self.change('delete','codex');self.create('codex','maintenance')
        self.assertNotEqual(old,self.store.read()['users']['codex']['id'])
    def test_role_duplication_and_unknown_permissions_fail_closed(self):
        self.change('role','custom_team',permissions=['system.diagnostics'],display='Team')
        self.create(role='custom_team');self.assertEqual(self.store.principal('member').permissions,{'system.diagnostics'})
        with self.assertRaises(security.SecurityError):self.change('role','administrator',permissions=[],display='Unsafe')
        with self.assertRaises(security.SecurityError):self.change('role','custom_team',permissions=['made.up'],display='Unsafe')
        self.change('edit',changes={'allow':['iso.view'],'deny':['system.diagnostics']})
        self.assertEqual(self.store.principal('member').permissions,{'iso.view'})
    def test_operator_cannot_escalate_or_manage_another_user_directly(self):
        operator=self.create()
        for action in ('edit','create','role','revoke','password','key_add','ssh'):
            with self.assertRaises(security.SecurityError):self.store.mutate(operator,{'action':action,'name':'member','expected_revision':1,'confirmed':True,'changes':{'role':'administrator'}})
    def test_delegated_account_editor_cannot_reset_administrator_password_or_key(self):
        self.create();self.change('edit',changes={'allow':['accounts.edit','accounts.delete','ssh.manage','sessions.revoke']})
        actor=self.store.principal('member')
        for action in ('password','delete','key_add','revoke'):
            with self.assertRaises(security.SecurityError):self.store.mutate(actor,{'action':action,'name':'supervisor','confirmed':True,'expected_revision':self.store.read()['revision'],'password':OTHER,'admin_password':OTHER,'public_key':PUBLIC})
    def test_concurrent_changes_have_one_winner_and_one_conflict(self):
        revision=self.store.read()['revision'];results=[];barrier=threading.Barrier(2)
        def update(name):
            barrier.wait()
            try:self.store.mutate(self.admin,{'action':'role','name':name,'display':name,'permissions':[],'expected_revision':revision,'confirmed':True});results.append(200)
            except security.SecurityError as error:results.append(error.status)
        threads=[threading.Thread(target=update,args=(n,)) for n in ('custom_a','custom_b')]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertEqual(sorted(results),[200,409])
    def test_corrupt_unknown_roles_and_symlinks_do_not_grant_defaults(self):
        document=self.store.read();document['roles']['administrator']['permissions'].append('unknown')
        self.store.path.write_text(json.dumps(document))
        with self.assertRaises(security.SecurityError) as error:self.store.principal('supervisor')
        self.assertEqual(error.exception.status,503)
        self.store.path.write_text('{broken')
        with self.assertRaises(security.SecurityError):self.store.read()
        with self.assertRaises(security.SecurityError):self.store.initialize('newadmin',PASSWORD,self.admin)
    def test_real_sessions_password_change_disable_role_change_and_expiry(self):
        self.create();clock=[10];manager=security.LoginManager(self.store,clock=lambda:clock[0]);token=manager.login('member',OTHER,'127.0.0.1')
        self.assertEqual(manager.authenticate(token).user,'member')
        self.change('password',password=PASSWORD)
        with self.assertRaises(security.SecurityError):manager.authenticate(token)
        token=manager.login('member',PASSWORD,'127.0.0.1');self.change('edit',changes={'enabled':False})
        with self.assertRaises(security.SecurityError):manager.authenticate(token)
        self.change('edit',changes={'enabled':True});token=manager.login('member',PASSWORD,'127.0.0.1');clock[0]+=1801
        with self.assertRaises(security.SecurityError):manager.authenticate(token)
    def test_login_throttled_unknown_user_and_logout(self):
        manager=security.LoginManager(self.store)
        for _ in range(5):
            with self.assertRaises(security.SecurityError):manager.login('absent',OTHER,'test')
        with self.assertRaises(security.SecurityError) as error:manager.login('absent',OTHER,'test')
        self.assertEqual(error.exception.status,429)
        token=manager.login('supervisor',PASSWORD,'other');manager.logout(token)
        with self.assertRaises(security.SecurityError):manager.authenticate(token)
    def test_delegation_is_bound_nonreplayable_expiring_and_revoked(self):
        actor=self.create();key=b'k'*32
        token=bridge.issue(actor,'GET','/msd',['iso.view'],key,now=100)
        headers={'X-Portable-Delegation':token}
        self.assertEqual(bridge.verify(headers,'GET','/msd',self.store,key,now=101,consume=True).user,'member')
        for method,path,at in [('POST','/msd',101),('GET','/atx',101),('GET','/msd',111)]:
            with self.assertRaises(security.SecurityError):bridge.verify(headers,method,path,self.store,key,now=at)
        with self.assertRaises(security.SecurityError):bridge.verify(headers,'GET','/msd',self.store,key,now=101,consume=True)
        self.change('revoke')
        with self.assertRaises(security.SecurityError):bridge.verify(headers,'GET','/msd',self.store,key,now=101)
    def test_key_validation_and_ssh_no_sudo_no_group_no_shell_plan(self):
        self.create('codex','maintenance');self.change('key_add','codex',public_key=PUBLIC+' example');self.change('ssh','codex',mode='diagnostics')
        proposal=plan(self.store.read(),'codex');self.assertFalse(proposal['sudo']);self.assertEqual(proposal['groups'],[])
        for required in ('ForceCommand','AuthorizedKeysFile none','PubkeyAcceptedAlgorithms ssh-ed25519','AllowTcpForwarding no','AllowStreamLocalForwarding no','PermitTTY no','AuthorizedKeysCommandUser root'):
            self.assertIn(required,proposal['configuration'])
        for value in ('command="bad" '+PUBLIC,'-----BEGIN PRIVATE KEY-----','ssh-rsa AAAA',PUBLIC+'\n'+PUBLIC):
            with self.assertRaises(security.SecurityError):security.public_key(value)
        self.change('key_remove','codex',fingerprint=security.public_key(PUBLIC)['fingerprint']);self.assertEqual(plan(self.store.read(),'codex')['keys'],[])
        with self.assertRaises(security.SecurityError):self.change('ssh','codex',mode='administrator')

class PolicyTests(unittest.TestCase):
    def test_ssh_effective_options_handle_spaces_tabs_and_equals_and_deny_ambiguity(self):
        self.assertEqual(ssh_options('permitrootlogin yes\npasswordauthentication\tno\npubkeyauthentication=yes\n'),{'permitrootlogin':'yes','passwordauthentication':'no','pubkeyauthentication':'yes'})
        self.assertEqual(ssh_options('Port 22\nAddressFamily any\nListenAddress [::]:22\nPermitRootLogin yes\nPasswordAuthentication no\n'),{'port':'22','addressfamily':'any','listenaddress':'[::]:22','permitrootlogin':'yes','passwordauthentication':'no'})
        with self.assertRaises(security.SecurityError):ssh_options('passwordauthentication no\npasswordauthentication yes\n')
    def test_unknown_direct_native_legacy_terminal_vnc_and_encodings_refused(self):
        for path in ('/legacy/','/extras/webterm/ws','/janus/ws','/api/media/ws','/redfish/v1','/api/gpio/switch','/api/msd/reset','/api/msd/write_remote','/api%2fmsd','//api/msd','/api/../msd','/api/msd?x=1&x=2'):
            with self.subTest(path=path),self.assertRaises((security.SecurityError,ValueError)):access.required('POST',path,{})
    def test_iso_mount_and_eject_cdrom_flash_and_readonly_preserved(self):
        for cdrom in ('true','false'):
            self.assertEqual(access.required('POST','/api/msd/set_params?image=Linux%2FTest+Image.iso&cdrom='+cdrom+'&rw=false'),('iso.mount',))
        self.assertEqual(access.required('POST','/api/msd/set_connected?connected=false'),('iso.eject',))
        self.assertEqual(access.required('POST','/api/msd/set_connected?connected=true'),('iso.mount',))
        with self.assertRaises(security.SecurityError):access.required('POST','/api/msd/set_params?rw=true')
    def test_each_folder_operation_has_backend_permission(self):
        for action,permission in [('mkdir','iso.mkdir'),('rmdir','iso.delete'),('rename_dir','iso.rename'),('move_file','iso.move'),('rename_file','iso.rename')]:
            self.assertEqual(access.required('POST','/extras/image-manager/api/image-manager/folders/action',{'action':action}),(permission,))
    def test_no_share_connection_on_panel_get_and_mutations_separate(self):
        self.assertEqual(access.required('GET','/extras/pikvm-share/api/status'),('share.status',))
        self.assertEqual(access.required('POST','/extras/pikvm-share/api/mode/usb',{}),('share.usb',))
        for path in ('/extras/wifi-wizard/api/usb-transfer/reset','/extras/wifi-wizard/api/pikvm-poweroff','/extras/wifi-wizard/api/usb-transfer/prepare'):
            with self.assertRaises(security.SecurityError):access.required('POST',path,{})
    def test_ws_text_binary_individual_permissions_unknown_and_macro_dependency(self):
        self.assertEqual(access.websocket_permissions('{"event_type":"key","event":{}}'),('kvm.keyboard','kvm.macros'))
        self.assertEqual(access.websocket_permissions(b'\x01\x01KeyA',True),('kvm.keyboard','kvm.macros'))
        self.assertEqual(access.websocket_permissions(b'\x02\x01left',True),('kvm.mouse',))
        for message in ('{"event_type":"gpio","event":{}}','[]','{broken'):
            with self.assertRaises(security.SecurityError):access.websocket_permissions(message)
        for message in (b'',b'\x99bad'):
            with self.assertRaises(security.SecurityError):access.websocket_permissions(message,True)
    def test_settings_diffs_import_and_oled_action_do_not_bypass_gesture_permissions(self):
        from pikvm_config import defaults
        current=defaults();changed={**current,'button_double_ms':400}
        self.assertIn('oled.gestures',access.required('POST','/extras/portable-os/api/settings/apply',{'values':changed},current))
        self.assertIn('oled.gestures',access.required('POST','/extras/portable-os/api/settings/import',{}))
        self.assertIn('system.shutdown',access.required('POST','/extras/portable-os/api/oled/button',{}))
    def test_atx_requires_action_permission_and_confirmation(self):
        with self.assertRaises(security.SecurityError):access.required('POST','/api/atx/power?action=off_hard',{})
        self.assertEqual(access.required('POST','/api/atx/power?action=off_hard',{'confirmed':True}),('atx.sensitive',))

if __name__=='__main__':unittest.main()
