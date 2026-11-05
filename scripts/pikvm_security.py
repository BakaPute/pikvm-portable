"""RC13 identities. Web identities never become KVMD or Linux accounts implicitly."""
import asyncio
import base64
import contextlib
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass
try:
    import fcntl
except ImportError:
    fcntl=None

PERMISSIONS={
 'kvm.video':'Voir la vidéo', 'kvm.keyboard':'Clavier', 'kvm.mouse':'Souris',
 'kvm.macros':'Raccourcis et macros', 'kvm.text':'Envoyer du texte', 'kvm.hid':'Configurer HID',
 'iso.view':'Voir les ISO', 'iso.upload':'Ajouter une ISO', 'iso.mkdir':'Créer un dossier',
 'iso.rename':'Renommer', 'iso.move':'Déplacer', 'iso.delete':'Supprimer',
 'iso.mount':'Monter une ISO', 'iso.eject':'Éjecter', 'iso.info':'Informations et favoris',
 'share.status':'État SHARE', 'share.web':'Fichiers Web SHARE', 'share.start':'Démarrer le transfert',
 'share.stop':'Terminer le transfert', 'share.import':'Importer les ISO', 'share.usb':'Exposer au PC',
 'atx.view':'État ATX', 'atx.on':'Démarrer le PC', 'atx.off':'Arrêter le PC',
 'atx.restart':'Redémarrer le PC', 'atx.sensitive':'Actions ATX forcées',
 'oled.view':'Voir OLED', 'oled.pages':'Pages OLED', 'oled.durations':'Durées OLED',
 'oled.gestures':'Gestes du bouton', 'oled.notifications':'Notifications OLED',
 'system.diagnostics':'Diagnostics', 'system.logs':'Journaux autorisés', 'system.settings':'Paramètres',
 'system.network':'Réseau', 'system.update':'Préparer une mise à jour',
 'system.export':'Exporter les préférences', 'system.restore':'Restaurer les préférences',
 'system.shutdown':'Demander l’arrêt PiKVM',
 'accounts.view':'Voir les comptes', 'accounts.create':'Créer un compte', 'accounts.edit':'Modifier un compte',
 'accounts.delete':'Supprimer un compte', 'roles.manage':'Gérer les rôles',
 'permissions.manage':'Modifier les permissions', 'ssh.manage':'Préparer SSH et gérer les clés',
 'audit.view':'Voir l’audit', 'sessions.revoke':'Révoquer les sessions',
}
ROLES={
 'administrator':{'label':'Administrateur','permissions':sorted(PERMISSIONS)},
 'operator':{'label':'Opérateur','permissions':['kvm.video','kvm.keyboard','kvm.mouse','kvm.macros','kvm.text','kvm.hid','iso.view','iso.mount','iso.eject','iso.info','atx.view','oled.view','system.diagnostics','share.status']},
 'user':{'label':'Utilisateur','permissions':['kvm.video','oled.view','system.diagnostics','share.status']},
 'readonly':{'label':'Lecture seule','permissions':['kvm.video','system.diagnostics','oled.view']},
 'maintenance':{'label':'Maintenance','permissions':['system.diagnostics','system.logs','oled.view','share.status']},
}
ITERATIONS=600_000
PST_PATH=Path('/var/lib/kvmd/pst/portable-security/identities.json')
RUNTIME=Path('/run/pikvm-portable-security')
_LOCK=threading.RLock()

class SecurityError(Exception):
    def __init__(self,message,status=403):super().__init__(message);self.status=status

def username(value):
    if not isinstance(value,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,23}',value):
        raise SecurityError('Identifiant : 1 à 24 caractères minuscules, chiffres, _ ou -.',400)
    if value in ('root','kvmd','http','nobody') or value.startswith(('kvmd-','systemd-')):
        raise SecurityError('Identité technique protégée.',403)
    return value

def label(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=80 or any(ord(c)<32 for c in value):
        raise SecurityError('Nom affiché invalide.',400)
    return value.strip()

def password_hash(password):
    if not isinstance(password,str) or not 14<=len(password)<=128 or any(ord(c)<32 for c in password):
        raise SecurityError('Mot de passe : 14 à 128 caractères, sans contrôle.',400)
    classes=sum((any(c.islower() for c in password),any(c.isupper() for c in password),any(c.isdigit() for c in password),any(not c.isalnum() for c in password)))
    if len(set(password))<8 or (classes<3 and not (len(password)>=20 and ' ' in password)):
        raise SecurityError('Utiliser une phrase de passe longue ou trois familles de caractères.',400)
    salt=secrets.token_bytes(16);digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,ITERATIONS)
    return 'pbkdf2_sha256$'+str(ITERATIONS)+'$'+salt.hex()+'$'+digest.hex()

def valid_hash(value):return isinstance(value,str) and re.fullmatch(r'pbkdf2_sha256\$600000\$[a-f0-9]{32}\$[a-f0-9]{64}',value) is not None

def password_matches(password,encoded):
    if not isinstance(password,str) or len(password)>128 or not valid_hash(encoded):return False
    _,_,salt,expected=encoded.split('$')
    return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),ITERATIONS).hex(),expected)

def permission_list(value):
    if not isinstance(value,list) or len(value)>len(PERMISSIONS) or len(value)!=len(set(value)) or any(p not in PERMISSIONS for p in value):
        raise SecurityError('Permission inconnue ou liste invalide.',400)
    return set(value)

def effective(document,user):
    role=document['roles'][user['role']]
    return (permission_list(role['permissions'])|permission_list(user['allow']))-permission_list(user['deny']) if user['enabled'] else set()

@dataclass(frozen=True)
class Principal:
    user:str
    permissions:frozenset
    epoch:int=0
    owner:str=''
    native:bool=False
    def require(self,*permissions):
        if any(p not in PERMISSIONS or p not in self.permissions for p in permissions):
            raise SecurityError('Permission refusée.',403)

def native_admin(owner=''):
    return Principal('@kvmd-administrator',frozenset(PERMISSIONS),owner=owner,native=True)

def validate(document):
    if not isinstance(document,dict) or set(document)!={'schema','revision','users','roles','history'} or document['schema']!=1 or type(document['revision']) is not int or document['revision']<0:
        raise ValueError('Security document')
    if not isinstance(document['users'],dict) or len(document['users'])>64 or not isinstance(document['roles'],dict) or len(document['roles'])>32:
        raise ValueError('Security limits')
    for key,base in ROLES.items():
        if document['roles'].get(key)!=base:raise ValueError('Builtin role changed')
    for key,role in document['roles'].items():
        if not re.fullmatch('[a-z][a-z0-9_-]{0,31}',key) or set(role)!={'label','permissions'}:raise ValueError('Role')
        label(role['label']);permission_list(role['permissions'])
    for key,user in document['users'].items():
        username(key)
        if set(user)!={'id','display','enabled','role','allow','deny','password','epoch','ssh','keys','created_at'} or not isinstance(user['id'],str) or not re.fullmatch('[a-f0-9]{32}',user['id']) or type(user['enabled']) is not bool or user['role'] not in document['roles'] or not valid_hash(user['password']) or type(user['epoch']) is not int or user['epoch']<0:
            raise ValueError('User')
        label(user['display']);permission_list(user['allow']);permission_list(user['deny'])
        if user['ssh'] not in ('disabled','diagnostics') or not isinstance(user['keys'],list) or len(user['keys'])>8:raise ValueError('SSH')
        for key in user['keys']:
            if public_key(key['public'])!=key:raise ValueError('SSH key')
    if not any(u['enabled'] and u['role']=='administrator' and not u['deny'] for u in document['users'].values()):
        raise ValueError('Last administrator')
    if not isinstance(document['history'],list) or len(document['history'])>200:raise ValueError('Audit')
    return document

def public_key(value):
    # AuthorizedKeys options, certificates, private keys and comments are not accepted.
    if not isinstance(value,str) or len(value)>1024 or '\n' in value or '\r' in value:
        raise SecurityError('Clé publique Ed25519 sur une ligne uniquement.',400)
    parts=value.strip().split()
    if len(parts) not in (2,3) or parts[0]!='ssh-ed25519':raise SecurityError('Seules les clés publiques ssh-ed25519 sans options sont acceptées.',400)
    try:raw=base64.b64decode(parts[1],validate=True)
    except ValueError:raise SecurityError('Clé publique invalide.',400) from None
    if len(raw)!=51 or raw[:19]!=b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':raise SecurityError('Structure Ed25519 invalide.',400)
    normalized='ssh-ed25519 '+base64.b64encode(raw).decode()
    return {'public':normalized,'fingerprint':'SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')}

def protected_file(path,strict=True):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_size>512*1024 or path.resolve()!=path.absolute():raise SecurityError('Fichier de sécurité non sûr.',503)
    if strict and sys_linux() and (s.st_uid!=0 or stat.S_IMODE(s.st_mode)&0o077):raise SecurityError('Permissions du fichier de sécurité non sûres.',503)
    return s

def sys_linux():return os.name=='posix' and Path('/proc').is_dir()

class SecurityStore:
    def __init__(self,path=PST_PATH,writer=None,lock_path=None,strict=True):
        self.path=Path(path);self.writer=writer;self.lock_path=Path(lock_path) if lock_path else RUNTIME/'identities.lock'
        self.strict=strict
        self._cached=None
    def read(self):
        return copy.deepcopy(self._document())
    def _document(self):
        try:
            info=protected_file(self.path,self.strict)
            identity=(info.st_dev,info.st_ino,info.st_mtime_ns,info.st_size,info.st_mode,info.st_uid,info.st_gid)
            if self._cached and self._cached[0]==identity:return self._cached[1]
            document=validate(json.loads(self.path.read_text(encoding='utf-8')))
            after=protected_file(self.path,self.strict)
            if (after.st_ino,after.st_mtime_ns,after.st_size)!=(info.st_ino,info.st_mtime_ns,info.st_size):raise SecurityError('Autorisations modifiées pendant lecture ; réessayer.',503)
            self._cached=(identity,document);return document
        except FileNotFoundError:raise SecurityError('Sécurité non initialisée : préparation administrateur requise.',503) from None
        except SecurityError:raise
        except (OSError,ValueError,TypeError,KeyError):raise SecurityError('Autorisations illisibles : accès refusé, restauration administrateur nécessaire.',503) from None
    def write(self,document):
        validate(document)
        def save(directory):
            from pikvm_config import atomic
            if directory.resolve()!=self.path.parent.resolve():raise SecurityError('Correspondance PST refusée.',503)
            if self.path.exists():protected_file(self.path,self.strict)
            atomic(self.path,document)
        if self.writer:return self.writer(lambda:save(self.path.parent))
        if self.path!=PST_PATH:raise SecurityError('Écriture de test non configurée.',503)
        from kvmd.apps import init
        from kvmd.clients.pst import PstError
        from pikvm_config import pst_write
        app=init(prog='portable-security')
        return asyncio.run(pst_write(lambda:app.make_pst_client('portable-security','Portable-Security'),save,PstError))
    @contextlib.contextmanager
    def locked(self):
        with _LOCK:
            self.lock_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            fd=os.open(self.lock_path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
            try:
                if fcntl:fcntl.flock(fd,fcntl.LOCK_EX)
                yield
            finally:os.close(fd)
    def initialize(self,name,password,actor):
        if not actor.native:raise SecurityError('Initialisation réservée à la récupération KVMD.',403)
        username(name);encoded=password_hash(password)
        with self.locked():
            if self.path.exists() or self.path.is_symlink():raise SecurityError('Initialisation déjà effectuée ; ne pas écraser.',409)
            document={'schema':1,'revision':0,'users':{},'roles':copy.deepcopy(ROLES),'history':[]}
            document['users'][name]=self.new_user(name,encoded,'administrator')
            self.write(document)
        return self.public(document)
    @staticmethod
    def new_user(name,encoded,role):return {'id':secrets.token_hex(16),'display':name,'enabled':True,'role':role,'allow':[],'deny':[],'password':encoded,'epoch':0,'ssh':'disabled','keys':[],'created_at':int(time.time())}
    def principal(self,name,owner=''):
        document=self._document();user=document['users'].get(name)
        if not user or not user['enabled']:raise SecurityError('Session révoquée.',401)
        return Principal(name,frozenset(effective(document,user)),user['epoch'],owner)
    @staticmethod
    def public(document):
        # Never export hashes, tokens, secrets or the private authorization file.
        return {'revision':document['revision'],'roles':document['roles'],'permissions':PERMISSIONS,
                'users':[{'name':name,**{k:v for k,v in u.items() if k not in ('password','epoch')},'effective':sorted(effective(document,u)),'identity':'web','linux_applied':False} for name,u in document['users'].items()],
                'history':document['history'],'native_accounts':'Administrateurs KVMD protégés ; gestion distincte. Aucun compte Linux créé implicitement.'}
    def mutate(self,actor,data,native_users=()):
        if not isinstance(data,dict) or data.get('confirmed') is not True or type(data.get('expected_revision')) is not int:
            raise SecurityError('Confirmation et révision requises.',400)
        action=data.get('action');name=data.get('name')
        needed={'create':'accounts.create','edit':'accounts.edit','password':'accounts.edit','delete':'accounts.delete','revoke':'sessions.revoke','role':'roles.manage','key_add':'ssh.manage','key_remove':'ssh.manage','ssh':'ssh.manage'}.get(action)
        if needed is None:raise SecurityError('Action inconnue.',400)
        actor.require(needed)
        encoded=password_hash(data.get('password')) if action in ('create','password') else None
        with self.locked():
            document=self.read()
            if not actor.native:
                current=self.principal(actor.user,actor.owner)
                if current.epoch!=actor.epoch:raise SecurityError('Session révoquée.',401)
                actor=current;actor.require(needed)
                if not password_matches(data.get('admin_password'),document['users'][actor.user]['password']):
                    raise SecurityError('Réauthentification requise pour une modification sensible.',403)
            if data['expected_revision']!=document['revision']:raise SecurityError('Configuration modifiée ; recharger avant de réessayer.',409)
            if action=='role':
                actor.require('permissions.manage')
                if not isinstance(name,str) or not re.fullmatch('custom_[a-z0-9_]{1,24}',name) or name in ROLES:raise SecurityError('Seuls les rôles personnalisés sont modifiables.',400)
                permissions=permission_list(data.get('permissions'))
                if not permissions<=actor.permissions:raise SecurityError('Délégation supérieure aux droits détenus.',403)
                if name in document['roles'] and not permission_list(document['roles'][name]['permissions'])<=actor.permissions:raise SecurityError('Rôle supérieur aux droits détenus.',403)
                document['roles'][name]={'label':label(data.get('display')),'permissions':sorted(permissions)}
                for u in document['users'].values():
                    if u['role']==name:u['epoch']+=1
            else:
                username(name)
                if name in native_users:raise SecurityError('Compte natif protégé ; aucune modification implicite.',403)
                user=document['users'].get(name)
                if action=='create':
                    if user:raise SecurityError('Compte existant.',409)
                    role=data.get('role','readonly')
                    if role not in document['roles']:raise SecurityError('Rôle inconnu.',400)
                    user=self.new_user(name,encoded,role);user['display']=label(data.get('display',name))
                    if not effective(document,user)<=actor.permissions:raise SecurityError('Élévation de privilèges refusée.',403)
                    document['users'][name]=user
                else:
                    if not user:raise SecurityError('Compte introuvable.',404)
                    if not effective(document,{**user,'enabled':True})<=actor.permissions:
                        raise SecurityError('Compte supérieur aux droits détenus ; modification refusée.',403)
                    if action=='delete':del document['users'][name]
                    elif action=='edit':
                        fields=data.get('changes')
                        if not isinstance(fields,dict) or not fields or not set(fields)<={'display','enabled','role','allow','deny'}:raise SecurityError('Modification invalide.',400)
                        if set(fields)&{'role','allow','deny'}:actor.require('permissions.manage')
                        if 'enabled' in fields and type(fields['enabled']) is not bool:raise SecurityError('Activation invalide.',400)
                        if 'role' in fields and fields['role'] not in document['roles']:raise SecurityError('Rôle inconnu.',400)
                        if 'display' in fields:label(fields['display'])
                        for key in ('allow','deny'):
                            if key in fields:permission_list(fields[key])
                        user.update(copy.deepcopy(fields))
                        if not effective(document,user)<=actor.permissions:raise SecurityError('Élévation de privilèges refusée.',403)
                    elif action=='password':user['password']=encoded
                    elif action=='ssh':
                        if data.get('mode') not in ('disabled','diagnostics'):raise SecurityError('Sudo et accès administrateur nécessitent une procédure distincte.',403)
                        user['ssh']=data['mode']
                    elif action=='key_add':
                        key=public_key(data.get('public_key'))
                        if key in user['keys']:raise SecurityError('Clé déjà enregistrée.',409)
                        user['keys'].append(key)
                    elif action=='key_remove':user['keys']=[k for k in user['keys'] if k['fingerprint']!=data.get('fingerprint')]
                    if action!='delete':user['epoch']+=1
            document['revision']+=1
            document['history']=(document['history']+[{'at':int(time.time()),'actor':actor.user,'action':action,'target':name}])[-200:]
            try:validate(document)
            except (ValueError,KeyError,TypeError):raise SecurityError('Modification refusée : dernier administrateur, limite ou état invalide.',409) from None
            self.write(document)
            return self.public(document)

class LoginManager:
    """Bounded in-memory sessions; service restart revokes all Portable sessions."""
    def __init__(self,store,clock=time.monotonic):
        self.store=store;self.clock=clock;self.sessions={};self.attempts={};self.lock=threading.RLock();self.hash_slots=threading.BoundedSemaphore(1)
        self.dummy=password_hash('Synthetic-No-Account-2026!')
    def login(self,name,password,address):
        now=self.clock();bucket=(str(address)[:64],str(name)[:24])
        with self.lock:
            self.attempts={k:v for k,v in self.attempts.items() if v[0]>now-300}
            if len(self.attempts)>512 or self.attempts.get(bucket,(0,0))[1]>=5 or sum(v[1] for k,v in self.attempts.items() if k[0]==bucket[0])>=15:
                raise SecurityError('Trop de tentatives ; patienter cinq minutes.',429)
            self.attempts[bucket]=(now,self.attempts.get(bucket,(0,0))[1]+1)
        if not self.hash_slots.acquire(blocking=False):raise SecurityError('Vérification déjà en cours ; réessayer.',429)
        try:
            document=self.store.read();user=document['users'].get(name) if isinstance(name,str) else None
            valid=password_matches(password,user['password'] if user else self.dummy)
        finally:self.hash_slots.release()
        if not valid or not user or not user['enabled']:raise SecurityError('Identifiant ou mot de passe incorrect.',401)
        with self.lock:
            self.sessions={k:v for k,v in self.sessions.items() if v['expires']>now}
            if len(self.sessions)>=128:raise SecurityError('Limite de sessions atteinte.',429)
            token=secrets.token_urlsafe(32);owner=hashlib.sha256(token.encode()).hexdigest()
            self.sessions[owner]={'user':name,'epoch':user['epoch'],'expires':now+1800}
            self.attempts.pop(bucket,None)
            return token
    def authenticate(self,token):
        if not isinstance(token,str) or not re.fullmatch('[A-Za-z0-9_-]{43}',token):raise SecurityError('Session requise.',401)
        owner=hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            session=self.sessions.get(owner)
            if not session or self.clock()>=session['expires']:self.sessions.pop(owner,None);raise SecurityError('Session expirée.',401)
            principal=self.store.principal(session['user'],owner)
            if principal.epoch!=session['epoch']:self.sessions.pop(owner,None);raise SecurityError('Session révoquée.',401)
            return principal
    def logout(self,token):
        with self.lock:self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(),None)
