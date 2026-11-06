"""RC13 limited HTTP/WS gateway, listening ONLY on loopback behind dedicated TLS.

No KVMD password/token is issued to Portable identities. Native recovery stays
on its original origin. Unknown routes/protocols are denied even to local roles.
"""
import asyncio
import contextlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import time
import sys
from urllib.parse import urlsplit,parse_qs,urlencode
sys.path.insert(0,'/usr/local/lib/pikvm-portable')
from aiohttp import ClientSession,ClientTimeout,TCPConnector,UnixConnector,WSMsgType,web
from yarl import URL
from pikvm_security import LoginManager,SecurityError,SecurityStore,Principal,PERMISSIONS,protected_file
from pikvm_security_admin import SecurityAdmin
from pikvm_security_bridge import Audit,issue,KEY,key_bytes
from pikvm_access import required,target,websocket_permissions,visible_event,safe_info,redact_network

COOKIE='portable_session'
HOP={'connection','upgrade','keep-alive','transfer-encoding','te','trailer','proxy-authorization','proxy-authenticate','set-cookie','server'}

def atx_mapping_safe(config,model,device):
    """Inspect configuration only; never instantiate a GPIO plugin or request lines."""
    pins=[getattr(config,name,None) for name in ('power_led_pin','hdd_led_pin','power_switch_pin','reset_switch_pin')]
    return ('Raspberry Pi Zero 2 W' in model and getattr(config,'type',None)=='gpio'
            and device=='/dev/gpiochip0' and all(type(pin) is int and 0<=pin<=53 and pin not in (17,18) for pin in pins))

def check_atx_mapping():
    from kvmd.apps import init
    config=init(prog='portable-security-atx-check',load_atx=True).config.kvmd.atx
    model=Path('/proc/device-tree/model').read_bytes().decode('ascii').rstrip('\x00')
    if not atx_mapping_safe(config,model,str(Path(config.device).resolve(strict=True))):
        raise SecurityError('Configuration ATX non validée ; GPIO17/18 protégés.',403)

class Gateway:
    def __init__(self,store=None,web_root=Path('/usr/share/kvmd/web'),kvmd_socket='/run/kvmd/kvmd.sock',stream_socket='/run/kvmd/ustreamer.sock',
                 audit=None,delegation_key=None,test_upstream=None,secure=True,natives=None,public_origin=None,atx_guard=None):
        self.store=store or SecurityStore();self.logins=LoginManager(self.store);self.audit=audit or Audit()
        self.admin=SecurityAdmin(self.store,self.audit,**({'natives':natives} if natives else {}))
        self.web_root=Path(web_root);self.kvmd_socket=kvmd_socket;self.stream_socket=stream_socket
        self.delegation_key=delegation_key;self.test_upstream=test_upstream;self.secure=secure;self.clients={};self.slots=asyncio.Semaphore(16)
        self.public_origin=public_origin
        self.atx_guard=atx_guard or check_atx_mapping
    async def open(self,app):
        self.clients['native']=ClientSession(connector=UnixConnector(path=self.kvmd_socket) if not self.test_upstream else TCPConnector(),timeout=ClientTimeout(total=None,sock_connect=5,sock_read=15))
        self.clients['stream']=ClientSession(connector=UnixConnector(path=self.stream_socket) if not self.test_upstream else TCPConnector(),timeout=ClientTimeout(total=None,sock_connect=5,sock_read=None))
        self.clients['local']=ClientSession(timeout=ClientTimeout(total=None,sock_connect=5,sock_read=150))
        try:
            if not self.test_upstream:
                from kvmd import __version__
                if __version__!='4.213':raise SecurityError('Version KVMD non validée pour ce filtre.',503)
            base=self.test_upstream or 'http://localhost'
            async with self.clients['native'].get(base+'/auth/check',allow_redirects=False) as check:
                if check.status not in (401,403):raise SecurityError('Authentification native désactivée ou non vérifiable.',503)
            async with self.clients['native'].get(base+'/info',allow_redirects=False) as check:
                if check.status!=200:raise SecurityError('Identité Unix locale KVMD non validée.',503)
        except Exception:
            await self.close(app);raise
    async def close(self,app):
        for client in self.clients.values():await client.close()
    async def actor(self,request):return await asyncio.to_thread(self.logins.authenticate,request.cookies.get(COOKIE,''))
    async def csrf(self,request):
        if request.method=='POST':
            if request.headers.get('Sec-Fetch-Site')=='cross-site':raise SecurityError('Requête intersite refusée.',403)
            origin=request.headers.get('Origin')
            if origin!=(self.public_origin or f'{request.scheme}://{request.host}'):raise SecurityError('Origine exacte requise.',403)
            # Native KVMD forms use same-origin URL-encoded POST, unlike Portable.
            if request.path.startswith('/extras/') and request.headers.get('X-Pikvm-Share')!='1':raise SecurityError('Protection CSRF requise.',403)
    async def body(self,request):
        if request.content_length is not None and request.content_length>16384:raise SecurityError('Requête de gestion trop volumineuse.',413)
        try:
            if request.content_type=='application/json':data=await request.json()
            else:data=dict(await request.post())
        except (ValueError,UnicodeError):raise SecurityError('Objet de gestion invalide.',400) from None
        if not isinstance(data,dict):raise SecurityError('Objet JSON requis.',400)
        return data
    async def handle(self,request):
        actor=None
        try:
            # Strictly bound open requests; no unbounded thread/connection spawning.
            if self.slots.locked():raise SecurityError('Trop de requêtes simultanées.',429)
            async with self.slots:
                path,q=target(request.raw_path)
                if request.method not in ('GET','POST'):raise SecurityError('Méthode refusée.',403)
                await self.csrf(request)
                if path=='/api/ws' and request.headers.get('Origin')!=(self.public_origin or f'{request.scheme}://{request.host}'):
                    raise SecurityError('Origine WebSocket exacte requise.',403)
                if path=='/api/auth/login' and request.method=='POST':
                    data=await self.body(request)
                    try:token=await asyncio.to_thread(self.logins.login,data.get('user'),data.get('passwd'),request.remote)
                    except SecurityError:
                        await asyncio.to_thread(self.audit.record,'anonymous','login',False);raise
                    await asyncio.to_thread(self.audit.record,data.get('user'),'login',True)
                    response=web.json_response({'ok':True,'result':{}})
                    response.set_cookie(COOKIE,token,httponly=True,secure=self.secure,samesite='Strict',path='/',max_age=1800)
                    return response
                if path=='/api/portable-entry' and request.method=='GET':
                    return web.json_response({'ok':True,'result':{'kind':'portable-permissions-gateway','native':False}},headers={'Cache-Control':'no-store'})
                # Only login assets may be fetched before authentication.
                if path in ('/login','/login/','/login/index.html','/extras/portable-os/security-login.js','/extras/portable-os/security-login.css','/extras/portable-os/logo.svg'):
                    name='extras/portable-os/security-login.html' if path.startswith('/login') else path.lstrip('/')
                    return self.static(name)
                actor=await self.actor(request)
                if path=='/api/auth/check':return web.json_response({'ok':True,'result':{'user':actor.user,'permissions':sorted(actor.permissions),'native':False}})
                if path=='/api/auth/logout' and request.method=='POST':
                    await asyncio.to_thread(self.logins.logout,request.cookies.get(COOKIE,''));response=web.json_response({'ok':True,'result':{}});response.del_cookie(COOKIE,path='/');return response
                if path=='/':raise web.HTTPFound('/extras/portable-os/')
                if path.startswith('/extras/portable-os/api/security/'):
                    data=await self.body(request) if request.method=='POST' else None
                    result=await asyncio.to_thread(self.admin.dispatch,actor,path.split('/api/',1)[1],data)
                    return web.json_response({'ok':True,'result':result})
                if '/api/' not in path and not path.startswith('/streamer'):
                    if path.startswith('/kvm/'):
                        actor.require('kvm.video')
                        return self.static(path.lstrip('/'))
                    if path.startswith(('/share/','/extras/portable-os/','/legacy/')):
                        # Legacy is never projected: arbitrary native tools bypass fine ACLs.
                        if path.startswith('/legacy/'):raise SecurityError('Interface de secours réservée aux administrateurs KVMD sur l’origine native.',403)
                        return self.static(path.lstrip('/'))
                    raise SecurityError('Interface native non projetée.',403)
                binary_upload=path in ('/api/msd/write','/extras/pikvm-share/api/upload/chunk')
                raw_text=path=='/api/hid/print' and request.method=='POST'
                if raw_text:
                    if request.content_length is None or request.content_length>16384:raise SecurityError('Texte trop volumineux.',413)
                    request['raw_body']=await request.read()
                data=await self.body(request) if request.method=='POST' and not binary_upload and not raw_text else None
                current=None
                if path.endswith('/api/settings/apply'):
                    from pikvm_config import Configuration
                    current=await asyncio.to_thread(lambda:Configuration().read()['values'])
                needs=required(request.method,request.raw_path,data,current);actor.require(*needs)
                if path.startswith('/api/atx/') and request.method=='POST':
                    try:await asyncio.to_thread(self.atx_guard)
                    except SecurityError:raise
                    except Exception:raise SecurityError('Configuration ATX inconnue ; action refusée.',403) from None
                if path=='/api/ws':
                    # KVMD clears BOTH keyboard and mouse on WS add/remove.
                    # A viewer or partial-HID account must never trigger that.
                    actor.require('kvm.keyboard','kvm.macros','kvm.mouse')
                    return await self.websocket(request,actor)
                return await self.revocable(request,self.proxy(request,actor,needs,data,binary_upload))
        except web.HTTPException:raise
        except SecurityError as error:
            # Audit failure must never turn a denial into access.
            with contextlib.suppress(Exception):await asyncio.to_thread(self.audit.record,actor.user if actor else 'anonymous','request-denied',False,request.path)
            if error.status==401 and request.method=='GET' and 'text/html' in request.headers.get('Accept','') and not request.path.startswith(('/api/','/streamer')) and '/api/' not in request.path:
                raise web.HTTPFound('/login/')
            return web.json_response({'ok':False,'error':str(error)},status=error.status)
        except (OSError,TimeoutError,ValueError,KeyError):return web.json_response({'ok':False,'error':'Service indisponible ; accès refusé.'},status=503)
        except Exception:
            # aiohttp exception reprs can include upstream request headers.
            # Never let the server logger serialize a delegation capability.
            return web.json_response({'ok':False,'error':'Passerelle indisponible ; aucune action supplémentaire.'},status=503)
    def static(self,name):
        if not name or '\\' in name:raise SecurityError('Fichier refusé.',403)
        path=self.web_root/name
        if path.is_dir():path=path/'index.html'
        if path.is_symlink() or not path.resolve().is_relative_to(self.web_root.resolve()) or not path.is_file():raise SecurityError('Fichier introuvable.',404)
        # A source/config/backup must never be served through a generic directory.
        if path.suffix not in ('.html','.js','.css','.svg','.png','.ico','.woff','.woff2'):raise SecurityError('Type de fichier refusé.',403)
        response=web.FileResponse(path);response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'"})
        return response
    def upstream(self,path):
        if path.startswith('/api/'):return 'native',path[4:]
        if path.startswith('/streamer'):return 'stream',path.removeprefix('/streamer') or '/'
        if path.startswith('/extras/portable-os/api/'):return 'local',path
        if path.startswith('/extras/pikvm-share/api/'):return 'share',path
        if path.startswith('/extras/image-manager/api/'):return 'wifi',path.removeprefix('/extras/image-manager')
        if path.startswith('/extras/wifi-wizard/api/'):return 'wifi',path.removeprefix('/extras/wifi-wizard')
        raise SecurityError('Cible refusée.',403)
    async def revocable(self,request,operation):
        async def watch():
            while True:await asyncio.sleep(1);await self.actor(request)
        task=asyncio.create_task(operation);observer=asyncio.create_task(watch())
        try:
            done,_=await asyncio.wait((task,observer),return_when=asyncio.FIRST_COMPLETED)
            if observer in done:observer.result()
            return task.result()
        finally:
            task.cancel();observer.cancel();await asyncio.gather(task,observer,return_exceptions=True)
    async def proxy(self,request,actor,needs,data,binary_upload):
        kind,path=self.upstream(request.raw_path);headers={}
        if path.startswith('/msd/set_params'):
            parsed=urlsplit(path);query=parse_qs(parsed.query,keep_blank_values=True);query['rw']=['false']
            path=parsed.path+'?'+urlencode(query,doseq=True)
        if kind in ('local','share','wifi'):
            headers={'X-Portable-Delegation':issue(actor,request.method,path,needs,self.delegation_key),
                     'X-Pikvm-Share':'1','X-Share-Origin':f'{request.scheme}://{request.host}'}
        # NEVER forward Cookie/Authorization/X-KVMD-*/X-Forwarded-* from a client.
        if request.headers.get('Content-Type'):headers['Content-Type']=request.headers['Content-Type']
        async def upload():
            async for chunk in request.content.iter_chunked(65536):
                await self.actor(request);yield chunk
        payload=upload() if binary_upload else request.get('raw_body') if 'raw_body' in request else json.dumps(data).encode() if data is not None else None
        if data is not None:headers['Content-Type']='application/json'
        if request.content_length is not None and binary_upload:headers['Content-Length']=str(request.content_length)
        base=self.test_upstream or ('http://localhost' if kind in ('native','stream') else {'local':'http://127.0.0.1:9878','share':'http://127.0.0.1:9877','wifi':'http://127.0.0.1:9876'}[kind])
        client=self.clients[kind if kind in ('native','stream') else 'local']
        async with client.request(request.method,URL(base+path,encoded=True),headers=headers,data=payload,allow_redirects=False) as upstream:
            if upstream.status in (301,302,303,307,308):raise SecurityError('Redirection amont refusée.',503)
            oled_frame=kind=='local' and urlsplit(path).path=='/extras/portable-os/api/oled'
            if (kind=='native' and urlsplit(path).path=='/info') or (kind=='wifi' and urlsplit(path).path=='/api/networks') or oled_frame:
                chunks=[];size=0
                async for chunk in upstream.content.iter_chunked(16384):
                    size+=len(chunk)
                    if size>512*1024:raise SecurityError('Réponse de diagnostic trop volumineuse.',503)
                    chunks.append(chunk)
                value=json.loads(b''.join(chunks))
                if kind=='native' and isinstance(value.get('result'),dict):value={**value,'result':safe_info(value['result'])}
                if kind=='wifi':value=redact_network(value)
                if oled_frame and value.get('result',{}).get('context',{}).get('screen')=='qr':actor.require('system.network')
                return web.json_response(value,status=upstream.status,headers={'Cache-Control':'no-store'})
            safe={k:v for k,v in upstream.headers.items() if k.lower() not in HOP and k.lower() in ('content-type','content-length','content-disposition','content-security-policy')}
            safe['Cache-Control']='no-store';safe['X-Content-Type-Options']='nosniff'
            response=web.StreamResponse(status=upstream.status,headers=safe);await response.prepare(request)
            while True:
                await self.actor(request) # immediately re-evaluate user/role/epoch
                try:chunk=await asyncio.wait_for(upstream.content.read(65536),1)
                except TimeoutError:continue
                if not chunk:break
                await response.write(chunk)
            await response.write_eof();return response
    async def websocket(self,request,actor):
        kind,path=self.upstream(request.raw_path);base=self.test_upstream or 'http://localhost'
        async with self.clients['native'].ws_connect(base+path,max_msg_size=65536,heartbeat=15) as upstream:
            client=web.WebSocketResponse(max_msg_size=4096,heartbeat=15);await client.prepare(request)
            async def inbound():
                tokens=480.;at=time.monotonic()
                async for message in client:
                    now=time.monotonic();tokens=min(480.,tokens+(now-at)*240)-1;at=now
                    if tokens<0:raise SecurityError('Cadence HID excessive.',429)
                    fresh=await self.actor(request)
                    if message.type==WSMsgType.TEXT:
                        fresh.require(*websocket_permissions(message.data));await upstream.send_str(message.data)
                    elif message.type==WSMsgType.BINARY:
                        fresh.require(*websocket_permissions(message.data,True));await upstream.send_bytes(message.data)
                    elif message.type==WSMsgType.ERROR:break
            async def outbound():
                async for message in upstream:
                    fresh=await self.actor(request)
                    if message.type==WSMsgType.TEXT:
                        event=json.loads(message.data)
                        if visible_event(fresh,event):
                            # KVMD native MJPEG is retained. Unfiltered Janus/media
                            # channels are unavailable on this restricted origin.
                            if event.get('event_type')=='streamer':
                                event['event']['features']={**event['event'].get('features',{}),'h264':False}
                            if event.get('event_type')=='info':event['event']=safe_info(event['event'])
                            await client.send_json(event)
                    elif message.type==WSMsgType.BINARY:
                        if message.data==b'\xff':await client.send_bytes(message.data)
            async def revoke_watch():
                while True:await asyncio.sleep(1);await self.actor(request)
            tasks=[asyncio.create_task(coro()) for coro in (inbound,outbound,revoke_watch)]
            try:
                done,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                for task in done:task.result()
            except SecurityError:
                await asyncio.to_thread(self.audit.record,actor.user,'websocket-denied',False,'/api/ws')
                await client.close(code=1008,message=b'Permission denied')
            finally:
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
                await client.close()
            return client
    def application(self):
        app=web.Application(client_max_size=16384);app.router.add_route('*','/{tail:.*}',self.handle)
        app.on_startup.append(self.open);app.on_cleanup.append(self.close)
        return app

def main():
    # Explicit deployment creates root-only state. Never initialize accounts here.
    import hashlib
    activation=Path('/etc/kvmd/portable-security-activation.json');report=Path('/etc/kvmd/portable-security-native-tests.json')
    protected_file(activation);protected_file(report)
    settings=json.loads(activation.read_text());proof=json.loads(report.read_text())
    installed=Path('/usr/local/lib/pikvm-portable/integrity.json')
    digest=hashlib.sha256(installed.read_bytes()).hexdigest()
    if settings.get('reviewed') is not True or settings.get('kvmd')!='4.213' or settings.get('application_integrity_sha256')!=digest or settings.get('native_test_report_sha256')!=hashlib.sha256(report.read_bytes()).hexdigest():raise SecurityError('Activation non validée pour cette installation.',503)
    if proof.get('candidate_integrity_sha256')!=digest or any(proof.get(k) is not True for k in ('native_auth','ws_filters','readonly_no_hid_effects','readonly_video_available','terminal_denied','vnc_denied','legacy_denied','root_recovery')):raise SecurityError('Tests natifs et récupération non validés.',503)
    origin=urlsplit(settings.get('origin',''))
    if origin.scheme!='https' or not origin.hostname or origin.path or origin.query or origin.fragment or origin.username or origin.password:raise SecurityError('Origine TLS explicite requise.',503)
    from pikvm_settings import Settings
    if not Settings(None).integrity()['valid']:raise SecurityError('Intégrité applicative non vérifiée.',503)
    store=SecurityStore();store.read()
    if not KEY.exists():
        KEY.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd=os.open(KEY,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as output:output.write(secrets.token_bytes(32))
    key_bytes()
    web.run_app(Gateway(store,public_origin=settings['origin']).application(),host='127.0.0.1',port=9879,access_log=None,print=None)

if __name__=='__main__':main()
