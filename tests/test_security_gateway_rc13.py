"""Real HTTP logins and WebSockets against a synthetic hardware-free upstream."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from aiohttp import web,CookieJar,WSMsgType
from aiohttp.test_utils import TestServer,TestClient
from pikvm_security import SecurityStore,native_admin,ROLES,password_hash
from pikvm_security_bridge import Audit
from pikvm_security_gateway import Gateway

PASSWORD='Synthetic-Gateway-2026!'
class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.directory.cleanup);self.root=Path(self.directory.name)
        self.store=SecurityStore(self.root/'security.json',writer=lambda f:f(),lock_path=self.root/'lock',strict=False)
        encoded=password_hash(PASSWORD)
        self.store.write({'schema':1,'revision':0,'users':{name:self.store.new_user(name,encoded,role) for name,role in [('supervisor','administrator'),('operator','operator'),('viewer','readonly')]},'roles':copy.deepcopy(ROLES),'history':[]})
        self.seen=[];self.events=[];self.native_ws=set()
        async def upstream(request):
            self.seen.append((request.method,request.path,dict(request.headers),request.raw_path))
            if request.path=='/auth/check':return web.Response(status=401)
            if request.path=='/extras/pikvm-share/api/mode/usb':return web.json_response({'ok':False,'error':'Synthetic SHARE busy'},status=409)
            if request.path=='/ws':
                ws=web.WebSocketResponse();await ws.prepare(request);self.native_ws.add(ws)
                await ws.send_json({'event_type':'msd','event':{'secret':'not for viewers'}})
                await ws.send_json({'event_type':'loop','event':{}})
                async for msg in ws:
                    if msg.type in (WSMsgType.TEXT,WSMsgType.BINARY):self.events.append(msg.data);await ws.send_json({'event_type':'pong','event':{}})
                self.native_ws.discard(ws);return ws
            return web.json_response({'ok':True,'result':{'synthetic':True}})
        app=web.Application();app.router.add_route('*','/{path:.*}',upstream)
        self.native=TestServer(app);await self.native.start_server()
        self.gateway=Gateway(self.store,web_root=ROOT/'web',audit=Audit(self.root/'audit.jsonl',strict=False),delegation_key=b'k'*32,test_upstream=str(self.native.make_url('')).rstrip('/'),secure=False,natives=lambda:['admin'])
        self.server=TestServer(self.gateway.application());await self.server.start_server();self.clients=[]
    async def asyncTearDown(self):
        for client in self.clients:await client.close()
        await self.server.close();await self.native.close()
    async def client(self,user):
        client=TestClient(self.server,cookie_jar=CookieJar(unsafe=True));await client.start_server();self.clients.append(client)
        response=await client.post('/api/auth/login',headers={'Origin':str(self.server.make_url('')).rstrip('/')},json={'user':user,'passwd':PASSWORD})
        self.assertEqual(response.status,200,await response.text());return client
    def origin(self):return {'Origin':str(self.server.make_url('')).rstrip('/'),'X-Pikvm-Share':'1'}
    def change(self,action,name,**data):return self.store.mutate(native_admin(),{'action':action,'name':name,'confirmed':True,'expected_revision':self.store.read()['revision'],**data})
    async def test_real_accounts_cookie_scope_and_direct_native_http_denials(self):
        viewer=await self.client('viewer');cookies=viewer.session.cookie_jar.filter_cookies(self.server.make_url('/'))
        self.assertIn('portable_session',cookies);self.assertNotIn('auth_token',cookies)
        for path in ('/api/msd','/api/atx','/legacy/','/extras/webterm/ws','/api/media/ws','/janus/ws','/redfish/v1'):
            response=await viewer.get(path);self.assertEqual(response.status,403,path)
        response=await viewer.get('/streamer/snapshot');self.assertEqual(response.status,200)
        # No client-controlled credential reaches the privileged Unix backend.
        response=await viewer.get('/api/hid',headers={'Authorization':'Basic fake','X-KVMD-User':'root','Cookie':'portable_session='+cookies['portable_session'].value+'; auth_token='+'a'*64})
        self.assertEqual(response.status,200)
        headers=self.seen[-1][2];self.assertNotIn('Cookie',headers);self.assertNotIn('Authorization',headers);self.assertNotIn('X-KVMD-User',headers)
    async def test_readonly_ws_rejects_key_before_forwarding_and_filters_msd_state(self):
        viewer=await self.client('viewer');ws=await viewer.ws_connect('/api/ws',headers=self.origin())
        initial=await ws.receive_json();self.assertEqual(initial['event_type'],'loop')
        await ws.send_json({'event_type':'key','event':{'key':'KeyA','state':True}})
        message=await ws.receive(timeout=3);self.assertIn(message.type,(WSMsgType.CLOSE,WSMsgType.CLOSED));self.assertEqual(self.events,[])
        await ws.close()
    async def test_operator_keyboard_mouse_binary_and_session_revocation_close_ws(self):
        operator=await self.client('operator');ws=await operator.ws_connect('/api/ws',headers=self.origin())
        self.assertEqual((await ws.receive_json())['event_type'],'msd');await ws.receive_json()
        await ws.send_json({'event_type':'key','event':{'key':'KeyA','state':True}});await ws.receive_json()
        await ws.send_bytes(b'\x03\x00\x00\x00\x00');await ws.receive_json()
        self.assertEqual(len(self.events),2)
        self.change('revoke','operator');message=await ws.receive(timeout=3)
        self.assertIn(message.type,(WSMsgType.CLOSE,WSMsgType.CLOSED));await ws.close()
    async def test_operator_iso_cdrom_flash_ejection_and_no_reset(self):
        operator=await self.client('operator')
        for connected in ('true','false'):
            response=await operator.post('/api/msd/set_connected?connected='+connected,headers=self.origin(),json={});self.assertEqual(response.status,200)
        for cdrom in ('true','false'):
            response=await operator.post('/api/msd/set_params?image=Linux%2FTest+ISO.iso&cdrom='+cdrom+'&rw=false',headers=self.origin(),json={});self.assertEqual(response.status,200)
        count=len(self.seen)
        response=await operator.post('/api/msd/reset',headers=self.origin(),json={});self.assertEqual(response.status,403);self.assertEqual(len(self.seen),count)
    async def test_csrf_role_escalation_unknown_paths_and_account_disable(self):
        operator=await self.client('operator')
        for headers in ({}, {'Origin':'https://evil.example','X-Pikvm-Share':'1'}):
            response=await operator.post('/api/msd/set_connected?connected=true',headers=headers,json={});self.assertEqual(response.status,403)
        response=await operator.post('/extras/portable-os/api/security/mutate',headers=self.origin(),json={'action':'edit','name':'operator','confirmed':True,'expected_revision':0,'changes':{'role':'administrator'}})
        self.assertEqual(response.status,403)
        self.change('edit','operator',changes={'enabled':False});response=await operator.get('/api/hid');self.assertEqual(response.status,401)
    async def test_share_panel_read_does_not_connect_and_busy_error_preserved(self):
        admin=await self.client('supervisor');before=len(self.seen)
        response=await admin.get('/extras/pikvm-share/api/status');self.assertEqual(response.status,200)
        self.assertEqual(self.seen[-1][0:2],('GET','/extras/pikvm-share/api/status'));self.assertEqual(len(self.seen),before+1)
        self.assertIn('X-Portable-Delegation',self.seen[-1][2])
        response=await admin.post('/extras/pikvm-share/api/mode/usb',headers=self.origin(),json={})
        self.assertEqual(response.status,409);self.assertEqual((await response.json())['error'],'Synthetic SHARE busy')
    async def test_cross_origin_websocket_is_rejected_before_upstream(self):
        viewer=await self.client('viewer');before=len(self.seen)
        response=await viewer.get('/api/ws',headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status,403);self.assertEqual(len(self.seen),before)
    async def test_delegation_target_preserves_encoded_subfolders_and_spaces_on_wire(self):
        from pikvm_security_bridge import verify
        admin=await self.client('supervisor')
        response=await admin.get('/extras/pikvm-share/api/files?path=Linux%2FFolder+with+spaces')
        self.assertEqual(response.status,200)
        sent=self.seen[-1]
        actor=verify(sent[2],sent[0],sent[3],self.store,key=b'k'*32)
        self.assertEqual(actor.user,'supervisor')
    async def test_password_reauth_required_and_last_admin_protected_via_http(self):
        admin=await self.client('supervisor');payload={'action':'delete','name':'supervisor','confirmed':True,'expected_revision':0}
        response=await admin.post('/extras/portable-os/api/security/mutate',headers=self.origin(),json=payload);self.assertEqual(response.status,403)
        response=await admin.post('/extras/portable-os/api/security/mutate',headers=self.origin(),json={**payload,'admin_password':PASSWORD});self.assertEqual(response.status,409)
    async def test_corruption_is_not_an_admin_fallback(self):
        admin=await self.client('supervisor');self.store.path.write_text('{broken')
        response=await admin.get('/extras/portable-os/api/security/users');self.assertEqual(response.status,503)
    async def test_auth_disabled_native_backend_blocks_gateway_startup(self):
        async def disabled(request):return web.json_response({'ok':True})
        app=web.Application();app.router.add_route('*','/{path:.*}',disabled)
        bad=TestServer(app);await bad.start_server()
        gateway=Gateway(self.store,audit=Audit(self.root/'other-audit',strict=False),delegation_key=b'k'*32,test_upstream=str(bad.make_url('')).rstrip('/'),secure=False)
        try:
            with self.assertRaises(Exception):await gateway.open(None)
        finally:await bad.close()

if __name__=='__main__':unittest.main()
