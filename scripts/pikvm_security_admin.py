"""Native administrator management facade; reads only names from htpasswd."""
from pathlib import Path
from functools import lru_cache
import json
import os
import signal
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from pikvm_security import SecurityStore,SecurityError,native_admin,PERMISSIONS,ROLES,protected_file
from pikvm_security_bridge import Audit

_NATIVE_CONFIG_LOCK=threading.Lock()

@lru_cache(maxsize=1)
def _native_auth_path():
    # Reading the native config must not retain KVMD/aiohttp in this API merely
    # to list account names. The isolated reader returns no password/hash/token.
    code="from kvmd.apps import init; import json; a=init(prog='portable-security-identity',load_auth=True).config.kvmd.auth; print(json.dumps({'enabled':a.enabled,'internal':a.internal.type,'external':a.external.type,'file':a.internal.file}))"
    child=subprocess.Popen([sys.executable,'-I','-B','-c',code],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',start_new_session=True)
    try:
        out,_=child.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name=='posix':os.killpg(child.pid,signal.SIGKILL)
        else:child.kill()
        child.communicate();raise SecurityError('Lecture de configuration native expirée.',503) from None
    if child.returncode or len(out)>4096:raise SecurityError('Configuration native indisponible.',503)
    try:
        auth=json.loads(out)
        if set(auth)!={'enabled','internal','external','file'} or any(not isinstance(auth[key],str) for key in ('internal','external','file')):raise ValueError()
        path=Path(auth['file'])
        if not path.is_absolute() or '..' in path.parts:raise ValueError()
    except (ValueError,TypeError,KeyError):raise SecurityError('Configuration native non reconnue.',503) from None
    if auth['enabled'] is not True or auth['internal']!='htpasswd' or auth['external']:
        raise SecurityError('RC13 prend en charge htpasswd interne actif uniquement ; accès natifs conservés, mutation bloquée.',503)
    return path

def native_auth_path():
    # Single-flight cold lookup: concurrent UI reads must not spawn readers.
    with _NATIVE_CONFIG_LOCK:return _native_auth_path()
native_auth_path.cache_clear=_native_auth_path.cache_clear

def native_users(path=None):
    path=Path(path) if path is not None else native_auth_path()
    if path.is_symlink():raise SecurityError('Source native non reconnue.',503)
    try:
        return [line.split(':',1)[0] for line in path.read_text(encoding='utf-8').splitlines() if ':' in line]
    except OSError:raise SecurityError('Identités natives non vérifiées ; mutation bloquée.',503) from None

class SecurityAdmin:
    def __init__(self,store=None,audit=None,natives=native_users):
        self.store=store or SecurityStore();self.audit=audit or Audit();self.natives=natives
    def dispatch(self,actor,route,data=None):
        try:return self._dispatch(actor,route,data)
        except SecurityError:
            self.audit.record(actor.user,'security-denied',False,route)
            raise
    def _dispatch(self,actor,route,data=None):
        if route=='security/session':return {'user':actor.user,'native':actor.native,'permissions':sorted(actor.permissions)}
        if route=='security/users' and data is None:
            actor.require('accounts.view')
            try:document=self.store.public(self.store.read());document['initialized']=True
            except SecurityError as e:
                if self.store.path.exists() or self.store.path.is_symlink():raise
                document={'initialized':False,'revision':0,'users':[],'roles':ROLES,'permissions':PERMISSIONS,'history':[]}
            document=self.linux_state(document)
            events=self.audit.read()
            for user in document.get('users',[]):
                times=[e['at'] for e in events if e.get('actor')==user['name'] and e.get('event')=='login' and e.get('allowed')]
                user['last_login']=max(times) if times else None
            portal={'url':'https://share.pikvm.home.arpa:8443/login/','configured':False,'validation':'Activation et certificat de confiance à approuver séparément.'}
            activation=Path('/etc/kvmd/portable-security-activation.json')
            if activation.exists():
                protected_file(activation);settings=json.loads(activation.read_text(encoding='utf-8'));origin=urlsplit(settings.get('origin',''))
                if settings.get('reviewed') is True and origin.scheme=='https' and origin.hostname and not (origin.username or origin.password or origin.path or origin.query or origin.fragment):
                    portal.update(url=settings['origin']+'/login/',configured=True)
            return {**document,'portal':portal,'native_users':[{'name':n,'identity':'kvmd','protected':True,'role':'administrator'} for n in self.natives()],
                    'production_activation':False,'notice':'Les comptes Web restreints utilisent la passerelle dédiée. Aucun compte KVMD/Linux n’est créé automatiquement. SSH et activation nécessitent une procédure explicite.'}
        if route=='security/audit' and data is None:
            actor.require('audit.view');return {'entries':self.audit.read(),'retention':'Boot courant, 200 événements ; changements persistants dans les révisions.'}
        if not isinstance(data,dict):raise SecurityError('Route inconnue.',404)
        if route=='security/initialize':
            if data.get('confirmed') is not True:raise SecurityError('Confirmation requise.',400)
            if data.get('name') in self.natives():raise SecurityError('Choisir une identité distincte des comptes natifs.',403)
            result=self.store.initialize(data.get('name'),data.get('password'),actor,allow_empty=data.get('allow_empty_password') is True)
        elif route=='security/mutate':result=self.store.mutate(actor,data,self.natives())
        elif route=='security/ssh-plan':
            actor.require('ssh.manage')
            from pikvm_ssh import plan
            return plan(self.store.read(),data.get('name'))
        else:raise SecurityError('Route inconnue.',404)
        try:self.audit.record(actor.user,'security-change',True,route)
        except OSError:result={**result,'warning':'Modification enregistrée ; historique persistant disponible, audit temporaire indisponible.'}
        return result
    @staticmethod
    def linux_state(document):
        try:import pwd
        except ImportError:return {**document,'linux_accounts':[],'linux_notice':'Linux indisponible sur ce poste de test.'}
        mapping=Path('/etc/ssh/portable-security-identities.json');links={}
        if mapping.exists():
            protected_file(mapping);links=json.loads(mapping.read_text())
        users=document.get('users',[])
        for user in users:
            matches=[(name,link) for name,link in links.items() if link.get('web_user')==user['name'] and link.get('identity_id')==user['id']]
            if matches:
                name,link=matches[0]
                try:account=pwd.getpwnam(name)
                except KeyError:continue
                if account.pw_uid==link['uid'] and account.pw_uid>=1000:
                    user.update(linux_applied=True,linux_user=name,linux_uid=account.pw_uid,identity='linked')
        return {**document,'users':users,'linux_accounts':[{'name':p.pw_name,'uid':p.pw_uid,'protected':p.pw_name not in links} for p in pwd.getpwall()]}
