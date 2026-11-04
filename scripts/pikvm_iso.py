"""Physical OLED ISO adapter: read-only tree and whitelisted native MSD calls.

KVMD 4.213 authenticates the local root service via native Unix credentials for
MSD routes. No web credential is stored; web gestures still pass KVMD+CSRF+IPC
authentication. No configfs write, image creation, deletion or formatting here.
"""
import http.client
import json
from pathlib import Path,PurePosixPath
import socket
from urllib.parse import urlencode
import pikvm_transfer as transfer


def visible(name):
    if not isinstance(name,str) or not name or len(name)>512 or '\\' in name or any(ord(c)<32 for c in name):return False
    path=PurePosixPath(name)
    return not path.is_absolute() and str(path)==name and all(not p.startswith('.') and p!='lost+found' for p in path.parts) and path.suffix.lower() in ('.iso','.img','.raw')


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout)
        self.sock.connect('/run/kvmd/kvmd.sock')


class NativeMsd:
    def request(self,method,path,params=None):
        if (method,path) not in (('GET','/msd'),('POST','/msd/set_params'),('POST','/msd/set_connected')):
            raise RuntimeError('Opération MSD non autorisée')
        connection=UnixConnection('localhost',timeout=5)
        try:
            connection.request(method,path+('?' + urlencode(params) if params else ''))
            response=connection.getresponse();raw=response.read(1024*1024+1)
            if len(raw)>1024*1024:raise RuntimeError('Bibliothèque trop volumineuse pour l’OLED')
            data=json.loads(raw)
            if response.status!=200 or data.get('ok') is not True:
                raise RuntimeError('KVMD refuse l’opération MSD (HTTP '+str(response.status)+')')
            return data.get('result',{})
        except (OSError,ValueError,http.client.HTTPException):raise RuntimeError('API MSD indisponible ; aucune connexion forcée') from None
        finally:connection.close()


class Library:
    def __init__(self,root=Path('/var/lib/kvmd/msd'),native=None):self.root=root;self.native=native or NativeMsd()

    def ordinary(self,name):
        if not visible(name):raise RuntimeError('Chemin ISO non autorisé')
        target=self.root/PurePosixPath(name)
        for parent in [target,*target.parents]:
            if parent==self.root.parent:break
            if parent.is_symlink():raise RuntimeError('Lien symbolique interdit')
        if not target.is_file() or not target.resolve().is_relative_to(self.root.resolve()):raise RuntimeError('Image indisponible')
        return target

    def state(self):
        state=self.native.request('GET','/msd')
        if not isinstance(state,dict):raise RuntimeError('État MSD invalide')
        return state

    def entries(self,state,folder=''):
        if folder and (PurePosixPath(folder).is_absolute() or str(PurePosixPath(folder))!=folder or any(p.startswith('.') for p in PurePosixPath(folder).parts)):
            raise RuntimeError('Dossier ISO invalide')
        images=state.get('storage',{}).get('images')
        if not isinstance(images,dict) or len(images)>4096:raise RuntimeError('Bibliothèque inconnue ou trop volumineuse')
        prefix=folder+'/' if folder else '';dirs=set();files=[]
        for name,info in images.items():
            if not visible(name) or not name.startswith(prefix):continue
            rest=name[len(prefix):]
            if '/' in rest:dirs.add(rest.split('/',1)[0])
            else:files.append({'name':rest,'path':name,'kind':'file','complete':isinstance(info,dict) and info.get('complete') is True,
                               'size':info.get('size') if isinstance(info,dict) else None})
        result=[{'name':'Retour','kind':'back','path':str(PurePosixPath(folder).parent) if folder else ''}]
        if result[0]['path']=='.':result[0]['path']=''
        result.extend({'name':name,'kind':'folder','path':prefix+name} for name in sorted(dirs,key=str.casefold))
        result.extend(sorted(files,key=lambda item:item['name'].casefold()))
        return result

    def guard(self,state,connected=None,locked=False):
        observation=transfer.observe()
        if observation.get('busy') is not locked or observation.get('drive',{}).get('known') is not True or observation['drive'].get('transfer_active'):
            raise RuntimeError('Transfert actif ou état USB inconnu')
        if state.get('online') is not True or state.get('enabled') is not True or state.get('busy') is not False:
            raise RuntimeError('Drive 0 occupé ou indisponible')
        storage=state.get('storage')
        if not isinstance(storage,dict) or 'uploading' not in storage or 'downloading' not in storage or storage['uploading'] or storage['downloading']:
            raise RuntimeError('Opération de stockage active ou inconnue')
        drive=state.get('drive',{})
        if type(drive.get('connected')) is not bool or (connected is not None and drive['connected']!=connected):
            raise RuntimeError('Connexion du Drive 0 modifiée')
        if bool(observation['drive'].get('image'))!=drive['connected']:
            raise RuntimeError('Désaccord entre KVMD et le lecteur réel')
        if drive['connected']:
            image=drive.get('image') or {};name=image.get('name')
            if not visible(name) or str(self.root/name)!=observation['drive']['image']:
                raise RuntimeError('Image native différente du média réellement attaché')
        transfer.require_not_stopping()

    def connect(self,name,cdrom):
        if type(cdrom) is not bool:raise RuntimeError('Mode ISO invalide')
        with transfer.exclusive(transfer.STORAGE_LOCK),transfer.exclusive(transfer.LOCK):
            self.ordinary(name);state=self.state();self.guard(state,False,locked=True)
            info=state['storage'].get('images',{}).get(name)
            if not isinstance(info,dict) or info.get('complete') is not True:raise RuntimeError('Image absente ou incomplète')
            self.native.request('POST','/msd/set_params',{'image':name,'cdrom':int(cdrom),'rw':0})
            fresh=self.state();self.guard(fresh,False,locked=True)
            if fresh['drive'].get('image',{}).get('name')!=name or fresh['drive'].get('rw') is not False or fresh['drive'].get('cdrom')!=cdrom:
                raise RuntimeError('Sélection native non confirmée ; connexion annulée')
            self.native.request('POST','/msd/set_connected',{'connected':1})
            final=self.state();self.guard(final,True,locked=True)
            if final['drive'].get('rw') is not False or final['drive'].get('cdrom')!=cdrom:
                raise RuntimeError('Mode natif non confirmé ; vérifier le lecteur avant toute nouvelle action')
            return final

    def eject(self,host_ejected=False):
        if host_ejected is not True:raise RuntimeError('Éjection propre côté PC à confirmer')
        with transfer.exclusive(transfer.STORAGE_LOCK),transfer.exclusive(transfer.LOCK):
            state=self.state();self.guard(state,True,locked=True)
            self.native.request('POST','/msd/set_connected',{'connected':0})
            final=self.state();self.guard(final,False,locked=True);return final
