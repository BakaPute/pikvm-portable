"""Real Portable gateway/login, synthetic upstream, loopback and temp users only."""
import asyncio,copy,json,sys,tempfile
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from pikvm_security import SecurityStore,ROLES,password_hash
from pikvm_security_bridge import Audit
from pikvm_security_gateway import Gateway
PASSWORD='Synthetic-Portal-2026!'

async def application():
    temporary=tempfile.TemporaryDirectory(prefix='portable-gateway-test-');root=Path(temporary.name)
    store=SecurityStore(root/'identities.json',writer=lambda f:f(),lock_path=root/'identities.lock',strict=False)
    encoded=password_hash(PASSWORD)
    users={role:store.new_user(role,encoded,role) for role in ROLES}
    users['empty']=store.new_user('empty',password_hash('',allow_empty=True),'readonly')
    store.write({'schema':1,'revision':0,'users':users,'roles':copy.deepcopy(ROLES),'history':[]})
    async def native(request):return web.json_response({'ok':True,'result':{}},status=401 if request.path=='/auth/check' else 200)
    backend=web.Application();backend.router.add_route('*','/{path:.*}',native);server=TestServer(backend);await server.start_server()
    gateway=Gateway(store,web_root=ROOT/'web',audit=Audit(root/'audit.jsonl',strict=False),delegation_key=b'x'*32,test_upstream=str(server.make_url('')).rstrip('/'),secure=False,natives=lambda:['admin'])
    app=gateway.application()
    async def cleanup(app):await server.close();temporary.cleanup()
    app.on_cleanup.append(cleanup);return app

if __name__=='__main__':web.run_app(application(),host='127.0.0.1',port=8766,access_log=None)
