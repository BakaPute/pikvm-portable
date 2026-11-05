"""Native administrator management facade; reads only names from htpasswd."""
from pathlib import Path
from functools import lru_cache
import json
from pikvm_security import SecurityStore,SecurityError,native_admin,PERMISSIONS,ROLES,protected_file
from pikvm_security_bridge import Audit

@lru_cache(maxsize=1)
def native_auth_path():
    from kvmd.apps import init
    auth=init(prog='portable-security-identity',load_auth=True).config.kvmd.auth
    if not auth.enabled or auth.internal.type!='htpasswd' or auth.external.type:
        raise SecurityError('RC13 prend en charge htpasswd interne actif uniquement ; accès natifs conservés, mutation bloquée.',503)
    return Path(auth.internal.file)

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
            return {**document,'native_users':[{'name':n,'identity':'kvmd','protected':True,'role':'administrator'} for n in self.natives()],
                    'production_activation':False,'notice':'Les comptes Web restreints utilisent la passerelle dédiée. Aucun compte KVMD/Linux n’est créé automatiquement. SSH et activation nécessitent une procédure explicite.'}
        if route=='security/audit' and data is None:
            actor.require('audit.view');return {'entries':self.audit.read(),'retention':'Boot courant, 200 événements ; changements persistants dans les révisions.'}
        if not isinstance(data,dict):raise SecurityError('Route inconnue.',404)
        if route=='security/initialize':
            if data.get('confirmed') is not True:raise SecurityError('Confirmation requise.',400)
            if data.get('name') in self.natives():raise SecurityError('Choisir une identité distincte des comptes natifs.',403)
            result=self.store.initialize(data.get('name'),data.get('password'),actor)
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
