"""Settings API coordinator and passive diagnostics. No power control execution."""
import json
import hashlib
import os
from pathlib import Path
import threading
import time
import shutil
import base64
import importlib.machinery
import importlib.util
from types import SimpleNamespace
from pikvm_config import Configuration, ConfigError, FIELDS, CATEGORIES, defaults, validate, IdleEngine, pst_path, VERSION, migrate_rc11, migrate_rc12, PAGES
from pikvm_activity import latest, RUNTIME
from pikvm_config import atomic


LIMITATIONS = {
    'power':'Extinction réelle non activable : validation distincte des inhibiteurs et de la chaîne d’arrêt nécessaire. Simulation disponible.',
    'battery':'MAX17048 : pourcentage estimé. Une charge positive ne prouve pas une alimentation externe ; délais batterie/secteur distincts indisponibles.',
    'presence':'SSH : aucune mesure fiable des frappes. Clients KVM externes, HDMI, présence réseau et utilisateur authentifié ne sont pas déduits comme activité.',
    'oled':'Un seul framebuffer 128×64 : pages, menus et miroir. Le matériel absent est recherché sans bloquer le rendu. Les valeurs inconnues restent signalées.',
    'button':'Clic suivant, double clic ouvrir, maintien retour, 3 s accueil hors confirmation. Dans la confirmation : 2 s relancer KVM, 5 s arrêter ou changer le hotspot. Bail Web 800 ms et autorisation dédiée conservés.',
    'storage':'Pas d’attachement automatique, changement de montage, préférence d’intégrité désactivable ou suppression automatique. Les protections existantes restent obligatoires.',
    'kvm':'Capture manuelle uniquement. Macros/raccourcis restent dans les contrôles KVMD natifs ; aucun éditeur parallèle.',
    'security':'KVMD administrateur conservé. Comptes Portable séparés, passerelle à permissions côté serveur, activation distincte après validation native ; aucun accès Linux implicite.',
}


CPU_LOCK=threading.Lock()
CPU_PREVIOUS=None


def resources():
    global CPU_PREVIOUS
    memory={}
    try:
        for line in Path('/proc/meminfo').read_text(encoding='utf-8').splitlines():
            key,value=line.split(':',1)
            if key in ('MemTotal','MemAvailable','SwapTotal','SwapFree'):memory[key]=int(value.split()[0])*1024
    except (OSError,ValueError):pass
    try:psi=Path('/proc/pressure/memory').read_text(encoding='utf-8')[:512]
    except OSError:psi=None
    try:load=list(os.getloadavg())
    except (OSError,AttributeError):load=None
    cpu=None
    try:
        ticks=[int(v) for v in Path('/proc/stat').read_text(encoding='utf-8').splitlines()[0].split()[1:9]]
        total=sum(ticks);idle=ticks[3]+ticks[4]
        with CPU_LOCK:
            if CPU_PREVIOUS and total>CPU_PREVIOUS[0]:cpu=round(100*(1-(idle-CPU_PREVIOUS[1])/(total-CPU_PREVIOUS[0])),1)
            CPU_PREVIOUS=(total,idle)
    except (OSError,ValueError,IndexError):pass
    disks={}
    for name,path in [('PST',lambda:pst_path().parent.parent),('MSD',lambda:Path('/var/lib/kvmd/msd'))]:
        try:
            size=shutil.disk_usage(path());disks[name]={'total':size.total,'free':size.free,'used':size.used}
        except (OSError,ConfigError):disks[name]=None
    return {'memory':memory,'memory_psi':psi,'load':load,'cpu_percent':cpu,'storage':disks,'observed_at':time.time()}


class Settings:
    def __init__(self,backend,path=None):
        self.backend=backend;self.configuration=Configuration(path);self.idle=IdleEngine();self.seen={};self.lock=threading.Lock()
        self.last_evidence={};self.last_status=None;self.stop_event=threading.Event();self.thread=None
        self.preview_lock=threading.Lock();self.preview_module=None

    def describe(self):
        document=self.configuration.read()
        installed=None
        try:
            path=Path('/usr/local/lib/pikvm-portable/release.json')
            if not path.is_symlink() and path.stat().st_size<1024:installed=json.loads(path.read_text(encoding='utf-8')).get('installed_at')
        except (OSError,ValueError,AttributeError):pass
        return {**document,'fields':FIELDS,'categories':CATEGORIES,'defaults':defaults(),'limitations':LIMITATIONS,
                'release':'0.2.0-rc.13.1','installed_at':installed,'restart_required':[],
                'persistence':'PST KVMD : bail natif en écriture, jamais de remount racine ou MSD'}

    def apply(self,data,reset=False):
        expected={'expected_revision','confirmed'} if reset else {'expected_revision','confirmed','values'}
        if not isinstance(data,dict) or set(data)!=expected:raise ConfigError('Requête de préférences invalide.')
        values=defaults() if reset else validate(data['values'])
        result=self.configuration.save(values,data['expected_revision'],data['confirmed'],reset)
        if result['revision']!=data['expected_revision']:
            print('Portable OS préférences : révision '+str(result['revision'])+' ; champs '+','.join(result['history'][-1]['keys']),flush=True)
        # No subprocess, daemon restart, GPIO call, or power policy activation.
        return result

    def preview(self,data):
        menus=('menu','power','wifi','network','iso-root','iso','iso-action','iso-info','iso-connect-confirm','iso-eject-confirm','power-confirm','network-confirm','working')
        if not isinstance(data,dict) or set(data)!={'values','page'} or data['page'] not in (*PAGES,*('menu-'+name for name in menus)):
            raise ConfigError('Aperçu OLED invalide.')
        values=validate(data['values'])
        if not self.preview_lock.acquire(blocking=False):raise ConfigError('Aperçu déjà en cours.',423)
        try:
            if data['page'].startswith('menu-'):
                from pikvm_oled_nav import preview_navigation
                from pikvm_oled import prepare_frame
                image=prepare_frame(preview_navigation(data['page'][5:],values).image,values)
                return {'width':128,'height':64,'format':'1bpp-msb','pixels':base64.b64encode(image.tobytes()).decode(),
                        'synthetic':True,'message':'Menu natif avec données d’exemple ; aucune action exécutée.'}
            if self.preview_module is None:
                source=Path('/usr/local/bin/pikvm-oled-custom')
                if not source.is_file():source=Path(__file__).with_name('pikvm-oled-custom')
                loader=importlib.machinery.SourceFileLoader('portable_oled_preview',str(source))
                spec=importlib.util.spec_from_loader(loader.name,loader)
                self.preview_module=importlib.util.module_from_spec(spec);loader.exec_module(self.preview_module)
                demo={'battery':(42,3.75),'battery_charging':False,'wifi':('Exemple Wi-Fi',-55),
                      'ip_address':'192.0.2.1','usb_state':'OK','hdmi_state':'1920x1080',
                      'cpu_temp':43,'cpu_usage':12,'uptime':'1h 20m',
                      'memory_info':{'percent':62,'available_mb':148},'kvm_state':True,
                      'network_info':{'connected':True,'ssid':'Exemple Wi-Fi','dbm':-55,'ip':'192.0.2.1'},
                      'drive_info':{'0':{'known':True,'attached':True,'cdrom':True},'1':{'known':True,'attached':False,'cdrom':False}},
                      'transfer_info':{'active':True,'state':'importing','percent':50,'done':1,'total':2,'current':'Exemple.iso'},'msd_free_space':8}
                for name,value in demo.items():setattr(self.preview_module,name,lambda value=value:value)
            self.preview_module.CONFIG=SimpleNamespace(get=lambda:values)
            self.preview_module.PAGE_STARTED=time.monotonic()
            captured=[]
            device=SimpleNamespace(mode='1',size=(128,64),display=lambda image:captured.append(image))
            seconds=next(p['seconds'] for p in values['oled_pages'] if p['id']==data['page'])
            renderer=getattr(self.preview_module,'page_'+('usb_transfer' if data['page']=='transfer' else data['page']))
            renderer(device,seconds if values['oled_auto'] else None)
            from pikvm_oled import prepare_frame
            image=prepare_frame(captured[0],values)
            return {'width':128,'height':64,'format':'1bpp-msb','pixels':base64.b64encode(image.tobytes()).decode(),
                    'synthetic':True,'message':'Même moteur natif ; données d’exemple. Aucune écriture I2C, aucune application du brouillon.'}
        finally:self.preview_lock.release()

    def export(self):
        document=self.configuration.read()
        if not document['healthy']:raise ConfigError('Configuration non exportable : valeurs sûres de secours actives.',409)
        return {'format':'pikvm-portable-settings','schema_version':VERSION,'values':document['values']}

    def integrity(self):
        try:
            manifest=Path('/usr/local/lib/pikvm-portable/integrity.json')
            if manifest.is_symlink() or manifest.stat().st_size>65536:raise ValueError()
            entries=json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(entries,dict) or len(entries)>256:raise ValueError()
            result=[]
            for name,digest in entries.items():
                path=Path(name)
                if not path.is_absolute() or '..' in path.parts or not name.startswith(('/usr/local/bin/','/usr/local/lib/pikvm-portable/','/usr/share/kvmd/web/','/usr/share/kvmd/extras/','/etc/systemd/system/pikvm-portable-api.service')):raise ValueError()
                okay=not path.is_symlink() and path.is_file() and path.stat().st_size<1048576 and hashlib.sha256(path.read_bytes()).hexdigest()==digest
                result.append({'file':name,'valid':okay})
            return {'files':result,'valid':all(r['valid'] for r in result),'scope':'Fichiers de l’installateur Portable OS ; ne contrôle pas les données ISO ni tout Python système.'}
        except (OSError,ValueError,TypeError):raise ConfigError('Manifeste applicatif indisponible ou invalide.',503) from None

    def import_config(self,data):
        if not isinstance(data,dict) or set(data)!={'expected_revision','confirmed','config'}:raise ConfigError('Import invalide.')
        document=data['config']
        if not isinstance(document,dict) or set(document)!={'format','schema_version','values'} or document['format']!='pikvm-portable-settings' or type(document['schema_version']) is not int or document['schema_version'] not in (1,2,VERSION):
            raise ConfigError('Format ou version d’import non pris en charge.')
        if data['confirmed'] is not True:raise ConfigError('Confirmation d’import requise.',409)
        imported=migrate_rc11(document['values']) if document['schema_version']==1 else migrate_rc12(document['values']) if document['schema_version']==2 else document['values']
        return self.apply({**{k:data[k] for k in ('expected_revision','confirmed')},'values':imported})

    def activity(self,data):
        if not isinstance(data,dict) or set(data)!={'source'}:raise ConfigError('Activité invalide.')
        if data['source']=='kvm_presence':self.idle.presence()
        elif data['source'] in ('web','keyboard','mouse','terminal','button','menu'):self.idle.activity(data['source'],self.configuration.read()['values'])
        else:raise ConfigError('Source Web non prise en charge.')
        return {'accepted':True}

    def evidence(self):
        # Read-only observations. A negative result requires positive proof;
        # absent APIs/files and locks that cannot be inspected remain unknown.
        evidence={key:None for key in ('drive0','drive1','transfer','share','storage','install','ssh')}
        observed_activity=set()
        try:
            drives=self.backend.usb()['drives']
            for i in (0,1):
                drive=drives.get(str(i),{})
                if drive.get('present') and drive.get('configurations') and drive.get('attributes',{}).get('file') is not None:
                    evidence['drive'+str(i)]=bool(drive['attributes']['file'])
        except Exception:pass
        try:
            import pikvm_transfer as transfer
            state=transfer.observe()
            if state.get('busy') is True or state.get('state') in transfer.ACTIVE:observed_activity.add('transfer')
            evidence['transfer']=bool(state.get('busy') or state.get('state') in transfer.ACTIVE or state.get('drive',{}).get('transfer_active')) if state.get('drive',{}).get('known') else None
            # A free lock alone cannot exclude every possible native MSD writer.
            # Keep storage unknown until a comprehensive native observer exists.
            if transfer.busy(transfer.STORAGE_LOCK):evidence['storage']=True;observed_activity.add('storage')
        except Exception:pass
        try:
            lease=self.backend.share_lease()
            evidence['share']=lease
        except Exception:pass
        return evidence,observed_activity

    def diagnostic(self,simulate=None):
        values=self.configuration.read()['values']
        for source in ('button','menu'):
            value=latest(source)
            if value and value['monotonic']>self.seen.get(source,0):
                self.seen[source]=value['monotonic'];self.idle.activity(source,values)
        evidence,observed_activity=self.evidence()
        for source in observed_activity:self.idle.activity(source,values)
        with self.lock:self.last_evidence=evidence
        result=self.idle.evaluate(values,evidence)
        if simulate is not None:
            if not isinstance(simulate,dict) or set(simulate)!={'elapsed','evidence'} or type(simulate['elapsed']) is not int or not 0<=simulate['elapsed']<=86400:
                raise ConfigError('Scénario de simulation invalide.')
            proposed=simulate['evidence']
            if not isinstance(proposed,dict) or set(proposed)!=set(evidence) or any(v is not None and type(v) is not bool for v in proposed.values()):raise ConfigError('Observations simulées invalides.')
            engine=IdleEngine(clock=lambda:float(simulate['elapsed']));engine.last=0
            result=engine.evaluate(values,proposed);result['simulation']=True
        return result

    def start(self):
        def watch():
            while not self.stop_event.is_set():
                try:
                    result=self.diagnostic();RUNTIME.mkdir(mode=0o700,exist_ok=True)
                    if not RUNTIME.is_symlink():atomic(RUNTIME/'idle.json',result)
                except Exception:pass
                self.stop_event.wait(5)
        self.thread=threading.Thread(target=watch,daemon=True,name='portable-idle');self.thread.start()

    def close(self):self.stop_event.set()
