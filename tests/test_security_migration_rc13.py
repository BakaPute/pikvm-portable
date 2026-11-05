"""Auth backups/rollback and backend direct-access denials, isolated data only."""
import contextlib
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from test_pikvm_share import api
from test_portable_install import portable
import pikvm_security as security
import pikvm_security_bridge as bridge
import pikvm_security_migration as migration
from test_security_rc13 import Fixture,OTHER

class MigrationTests(unittest.TestCase):
    def test_secret_backup_verified_restore_exact_and_tampering_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);backup=root/'backup';backup.mkdir();state=root/'identities.json';state.write_bytes(b'{"synthetic":"old-secret-fixture"}')
            auth=root/'htpasswd';auth.write_bytes(b'fixture:synthetic-hash-not-real\n');h=portable.helper()
            with patch.object(migration,'protected_file',return_value=None):metadata=migration.snapshot(h,backup,state,[str(auth)])
            migration.verify(h,backup,metadata,[str(auth)])
            state.write_bytes(b'{"synthetic":"new"}')
            migration.restore_state(h,backup,metadata,state,writer=lambda f:f())
            self.assertEqual(state.read_bytes(),b'{"synthetic":"old-secret-fixture"}')
            self.assertEqual((backup/'security-before-restore.json').read_bytes(),b'{"synthetic":"new"}')
            (backup/'authentication/0').write_bytes(b'bad')
            with self.assertRaises(security.SecurityError):migration.verify(h,backup,metadata,[str(auth)])
    def test_restore_to_rc121_without_state_preserves_failed_state_in_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);backup=root/'backup';backup.mkdir();state=root/'identities.json';state.write_bytes(b'synthetic failed candidate')
            migration.restore_state(portable.helper(),backup,{'state':{'exists':False}},state,writer=lambda f:f())
            self.assertFalse(state.exists());self.assertEqual((backup/'security-before-restore.json').read_bytes(),b'synthetic failed candidate')
    def test_install_requires_explicit_candidate_digest_before_any_preflight(self):
        with patch.object(sys,'argv',['installer','install']),patch.object(portable.os,'geteuid',return_value=0,create=True),patch.object(portable,'preflight') as check:
            with self.assertRaisesRegex(RuntimeError,'validation explicite'):portable.main()
            check.assert_not_called()
    def test_share_patch_is_surgical_idempotent_preserves_storage_and_unknown_fix(self):
        source=(Path(__file__).resolve().parents[1]/'scripts/pikvm-share-api').read_text()
        self.assertEqual(portable.security_share_policy(source),source)
        # Reconstruct RC12.1 additions only; all unrelated storage text survives.
        prefix="    if headers.get('X-Portable-Delegation'):\n        from pikvm_security_bridge import verify\n        return verify(headers).owner\n"
        binding="            if self.headers.get('X-Portable-Delegation'):\n                from pikvm_security_bridge import bind\n                bind(self.headers,self.command,self.path)\n"
        legacy=source.replace(prefix,'').replace(binding,'').replace("import sys\nsys.path.insert(0, '/usr/local/lib/pikvm-portable')\n",'')
        marker='\n# Local Python compatibility fix must survive\n'
        self.assertEqual(portable.security_share_policy(legacy+marker),source+marker)
        with self.assertRaises(RuntimeError):portable.security_share_policy(legacy.replace('def authenticate(headers, checker=kvmd_check):','def authenticate(headers):'))

class DirectBackendTests(Fixture):
    def setUp(self):
        super().setUp();self.actor=self.create();self.calls=[]
        fixture=self
        class Controller:
            mode='detached'
            @contextlib.contextmanager
            def operation(self):yield
            def status(self):fixture.calls.append('status');return {'mode':'detached'}
        self.server=api.Server(('127.0.0.1',0),api.Handler);self.server.controller=Controller();self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close_server)
    def close_server(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,path,proof=None,cookie=None):
        connection=http.client.HTTPConnection(*self.server.server_address,timeout=5);headers={}
        if proof:headers['X-Portable-Delegation']=proof
        if cookie:headers['Cookie']=cookie
        connection.request('GET',path,headers=headers);response=connection.getresponse();response.read();status=response.status;connection.close();return status
    def test_portable_cookie_cannot_authenticate_an_existing_backend_directly(self):
        self.assertEqual(self.request('/extras/pikvm-share/api/status',cookie='portable_session='+'x'*43),401);self.assertEqual(self.calls,[])
    def test_request_bound_delegation_and_role_change_checked_in_real_backend(self):
        path='/extras/pikvm-share/api/status';key=b'k'*32
        with patch.object(bridge,'key_bytes',return_value=key),patch.object(bridge,'SecurityStore',return_value=self.store):
            proof=bridge.issue(self.actor,'GET',path,['share.status'],key)
            self.assertEqual(self.request(path,proof),200);self.assertEqual(self.calls,['status'])
            self.assertNotEqual(self.request(path,proof),200) # nonce cannot be replayed
            proof=bridge.issue(self.actor,'GET',path,['share.status'],key);self.change('revoke')
            self.assertNotEqual(self.request(path,proof),200);self.assertEqual(self.calls,['status'])

if __name__=='__main__':unittest.main()
