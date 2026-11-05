"""Official KVMD 4.213 auth/htpasswd/HTTP and Unix credentials, no hardware daemon."""
import asyncio
import importlib.util
import os
from pathlib import Path
import pwd
import sys
import tempfile
import types
from aiohttp import web,ClientSession,UnixConnector,CookieJar
from aiohttp.test_utils import TestServer,TestClient

SOURCE=Path(os.environ['KVMD_SOURCE']).resolve();sys.path.insert(0,str(SOURCE))
import kvmd
assert kvmd.__version__=='4.213'
# Skip only the hardware application entrypoints. All auth/HTTP/crypto modules
# below are upstream files imported unchanged from the pinned checkout.
for name,path in [('kvmd.apps',SOURCE/'kvmd/apps'),('kvmd.apps.kvmd',SOURCE/'kvmd/apps/kvmd'),('kvmd.apps.kvmd.api',SOURCE/'kvmd/apps/kvmd/api')]:
    package=types.ModuleType(name);package.__path__=[str(path)];sys.modules[name]=package
from kvmd.apps.kvmd.auth import AuthManager
from kvmd.apps.kvmd.api.auth import AuthApi,check_request_auth
from kvmd.crypto import KvmdHtpasswdFile
from kvmd.htserver import _get_exposed_http,HttpExposed,HttpError

async def main():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);path=root/'htpasswd'
        passwords=KvmdHtpasswdFile(str(path),new=True);passwords.set_password('admin','Synthetic-Native-2026!');passwords.save()
        manager=AuthManager(enabled=True,expire=120,extend=False,usc_users=[pwd.getpwuid(os.getuid()).pw_name],usc_groups=[],unauth_paths=[],
                            int_c=types.SimpleNamespace(type='htpasswd',file=str(path)),ext_c=types.SimpleNamespace(type=''),force_int_users=[],totp_secret_path='')
        api=AuthApi(manager,['/']);app=web.Application();calls=[]
        async def guarded(request,exposed):
            try:await check_request_auth(manager,exposed,request);return await exposed.handler(request)
            except HttpError as error:return web.json_response({'ok':False,'error':str(error)},status=error.status)
        for exposed in _get_exposed_http(api):
            async def handler(request,exposed=exposed):return await guarded(request,exposed)
            app.router.add_route(exposed.method,exposed.path,handler)
        async def synthetic_hardware(request):calls.append(request.path);return web.json_response({'ok':True,'synthetic':True})
        for path_name in ('/msd','/ws','/hid/events/send_key'):
            exposed=HttpExposed('GET',path_name,True,True,synthetic_hardware)
            async def handler(request,exposed=exposed):return await guarded(request,exposed)
            app.router.add_route('GET',path_name,handler)
        server=TestServer(app);await server.start_server();client=TestClient(server,cookie_jar=CookieJar(unsafe=True));await client.start_server()
        try:
            for target in ('/auth/check','/msd','/ws','/hid/events/send_key'):
                response=await client.get(target,headers={'Cookie':'portable_session='+'x'*43});assert response.status==401,(target,response.status)
            response=await client.post('/auth/login',data={'user':'viewer','passwd':'Synthetic-Portable-2026!'});assert response.status==403
            assert calls==[]
            response=await client.post('/auth/login',data={'user':'admin','passwd':'Synthetic-Native-2026!','expire':'120'});assert response.status==200
            response=await client.get('/msd');assert response.status==200
            assert await manager.login('viewer','Synthetic-Portable-2026!',120) is None
            token=await manager.login('admin','Synthetic-Native-2026!',120);assert token and manager.check(token)=='admin'
            # This exact native limitation motivates a separate Portable realm.
            changed=KvmdHtpasswdFile(str(path));changed.set_password('admin','Synthetic-Replaced-2026!');changed.save()
            assert manager.check(token)=='admin','Native password change semantics unexpectedly changed'
            manager.logout(token);assert manager.check(token) is None
            sock=root/'kvmd.sock';site=web.UnixSite(server.runner,str(sock));await site.start()
            async with ClientSession(connector=UnixConnector(path=str(sock))) as unix:
                async with unix.get('http://localhost/auth/check') as result:assert result.status==401
                async with unix.get('http://localhost/msd') as result:assert result.status==200
            print('PASS official KVMD 4.213: htpasswd native login, Portable identities/tokens refused on direct HTTP/WS auth, password-change session limitation, logout revocation, Unix privilege and /auth/check negative proof')
        finally:await client.close();await server.close()
asyncio.run(main())
