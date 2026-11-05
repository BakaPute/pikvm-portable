"""Verified root-only auth backup; ordinary preference exports never include it."""
import json
from pathlib import Path
from pikvm_security import PST_PATH,SecurityError,protected_file

AUTH_FILES=('/etc/kvmd/htpasswd','/etc/kvmd/vncpasswd','/etc/kvmd/ipmipasswd','/etc/kvmd/totp.secret','/etc/kvmd/override.yaml','/etc/kvmd/auth.yaml','/etc/ssh/sshd_config','/etc/ssh/portable-security-identities.json','/etc/kvmd/portable-security-activation.json','/etc/kvmd/portable-security-native-tests.json')
def selected_auth_paths():
    result=set(AUTH_FILES)
    for folder,suffix in (('/etc/kvmd/override.d','*.yaml'),('/etc/ssh/sshd_config.d','*.conf')):
        result.update(str(path) for path in Path(folder).glob(suffix))
    return sorted(result)
def permitted_auth_path(value):
    p=Path(value)
    return value in AUTH_FILES or (str(p.parent)=='/etc/kvmd/override.d' and p.suffix=='.yaml') or (str(p.parent)=='/etc/ssh/sshd_config.d' and p.suffix=='.conf')
def snapshot(h,backup,state=None,auth_paths=None):
    state=Path(state) if state is not None else PST_PATH
    if auth_paths is None:auth_paths=selected_auth_paths()
    metadata={'state':{'exists':False},'auth':[]}
    if state.exists() or state.is_symlink():
        protected_file(state);h.write_file(backup/'security-state.json',state.read_bytes(),0o600)
        metadata['state']={'exists':True,'sha256':h.digest(backup/'security-state.json')}
    directory=backup/'authentication';directory.mkdir(mode=0o700)
    for number,name in enumerate(auth_paths):
        source=Path(name);entry={'path':str(name),'exists':source.exists()}
        if source.is_symlink():raise SecurityError('Configuration auth symbolique à examiner avant migration.',503)
        if source.exists():
            if not source.is_file() or source.stat().st_size>512*1024:raise SecurityError('Configuration auth non ordinaire.',503)
            destination=directory/str(number);h.write_file(destination,source.read_bytes(),0o600)
            if h.digest(destination)!=h.digest(source):raise SecurityError('Sauvegarde auth instable.',503)
            entry.update(file='authentication/'+str(number),sha256=h.digest(destination))
        metadata['auth'].append(entry)
    return metadata

def verify(h,backup,metadata,auth_paths=None):
    if not isinstance(metadata,dict) or set(metadata)!={'state','auth'}:raise SecurityError('Métadonnées de sauvegarde auth invalides.',503)
    paths={x['path'] for x in metadata['auth']}
    if len(paths)!=len(metadata['auth']) or (auth_paths is not None and paths!={str(p) for p in auth_paths}) or (auth_paths is None and (not set(AUTH_FILES)<=paths or any(not permitted_auth_path(p) for p in paths))):raise SecurityError('Périmètre de sauvegarde auth invalide.',503)
    state=metadata['state']
    if type(state.get('exists')) is not bool:raise SecurityError('État de sécurité sauvegardé invalide.',503)
    items=[{'file':'security-state.json','sha256':state.get('sha256')}] if state['exists'] else []
    items.extend(e for e in metadata['auth'] if e['exists'])
    for item in items:
        source=backup/item['file']
        if source.is_symlink() or not source.resolve().is_relative_to(backup.resolve()) or not source.is_file() or h.digest(source)!=item['sha256']:raise SecurityError('Sauvegarde auth altérée ; restauration refusée.',503)

def restore_state(h,backup,metadata,state=None,writer=None):
    state=Path(state) if state is not None else PST_PATH
    raw=(backup/'security-state.json').read_bytes() if metadata['state']['exists'] else None
    if raw is None and not state.exists() and not state.is_symlink():return
    if state.is_symlink() or (state.exists() and (not state.is_file() or state.stat().st_size>512*1024)):
        raise SecurityError('État courant non ordinaire ; restauration refusée avant lecture.',503)
    if state.exists():h.write_file(backup/'security-before-restore.json',state.read_bytes(),0o600)
    def write(directory):
        if directory.resolve()!=state.parent.resolve():raise SecurityError('Correspondance de restauration PST refusée.',503)
        if state.is_symlink():raise SecurityError('Lien d’état interdit.',503)
        if raw is None:state.unlink(missing_ok=True)
        else:h.write_file(state,raw,0o600)
    if writer:return writer(lambda:write(state.parent))
    import asyncio
    from kvmd.apps import init
    from kvmd.clients.pst import PstError
    from pikvm_config import pst_write
    app=init(prog='portable-security-restore')
    return asyncio.run(pst_write(lambda:app.make_pst_client('portable-security','Portable-Security-Restore'),write,PstError))
