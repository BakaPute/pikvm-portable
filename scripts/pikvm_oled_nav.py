"""Single-button navigation state; graphics run only in the OLED producer.

The input process publishes a small bounded model. One worker handles slow native
API/QR/service work. No GPIO writes and no image deletion are offered.
"""
import json
import os
from pathlib import Path
import threading
import time
from functools import lru_cache
from pikvm_config import atomic
from pikvm_gestures import Permit

NAVIGATION=Path('/run/pikvm-oled/navigation.json')


class Worker:
    def __init__(self):
        self.condition=threading.Condition();self.pending=None;self.running=False;self.result=None;self.closed=False
        self.thread=threading.Thread(target=self._run,daemon=True,name='oled-actions');self.thread.start()
    def submit(self,task):
        with self.condition:
            if self.pending is not None or self.running or self.result is not None:return False
            self.pending=task;self.result=None;self.condition.notify();return True
    def poll(self):
        with self.condition:value=self.result;self.result=None;return value
    def _run(self):
        while True:
            with self.condition:
                while self.pending is None and not self.closed:self.condition.wait()
                if self.closed:return
                task,self.pending=self.pending,None;self.running=True
            try:value={'ok':True,'value':task()}
            except Exception as error:value={'ok':False,'error':str(error)[:180]}
            with self.condition:self.running=False;self.result=value
    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()


class Navigation:
    MAIN=[('power','Alimentation','power'),('wifi','Wi-Fi / QR','wifi'),('network','Hotspot / secours','wifi'),('iso','Lecteur ISO','disc'),('home','Accueil','back')]
    def __init__(self,backend,values,clock=time.monotonic,worker=None):
        self.backend=backend;self.values=values;self.clock=clock;self.worker=worker or Worker()
        self.screen='status';self.index=0;self.revision=1;self.last_action=clock();self.event_at=clock()
        self.folder='';self.entries=[];self.target=None;self.operation=None;self.mode=True
        self.scope='browse'
        self.msd=None;self.info={};self.error='';self.pending_kind=None;self.return_screen='menu'
        self.last_refresh=float('-inf');self.last_publish=float('-inf');self.last_key=None
        self.last_attempt=float('-inf')
        self.qr_id=None

    def context(self):
        return {'screen':self.screen,'selection':self.index,'navigation_id':self.revision,'ui_version':2,
                **({'target':self.target} if self.target else {}),**({'operation':self.operation} if self.operation else {})}

    def matches(self,frame):
        context=frame.get('context',{})
        return all(context.get(key)==value for key,value in self.context().items())

    def change(self,screen,index=0):
        self.screen=screen;self.index=index;self.revision+=1;self.last_action=self.clock();self.error=''

    def home(self):
        self.change('status');self.backend.status_page(self.values()['oled_start']);self.target=None;self.operation=None

    def items(self):
        if self.screen=='menu':return [{'id':key,'name':label,'icon':icon} for key,label,icon in self.MAIN]
        if self.screen=='power':return [{'id':'back','name':'Retour','icon':'back'},{'id':'restart','name':'Relancer KVM','icon':'power'},{'id':'shutdown','name':'Arrêter PiKVM','icon':'power'}]
        if self.screen=='iso':return self.entries
        if self.screen=='iso-action':
            return [{'id':'back','name':'Retour','icon':'back'},{'id':'cdrom','name':'Connecter CD/DVD · RO','icon':'disc'},
                    {'id':'flash','name':'Connecter Flash · RO','icon':'usb'},{'id':'favorite','name':'Retirer favori' if self.target in self.values()['iso_favorites'] else 'Ajouter aux favoris','icon':'folder'},
                    {'id':'info','name':'Informations','icon':'system'}]
        if self.screen=='iso-root':
            connected=(self.msd or {}).get('drive',{}).get('connected')
            return [{'id':'browse','name':'Parcourir les dossiers','icon':'folder'},
                    {'id':'favorites','name':'Favoris','icon':'folder'},{'id':'recent','name':'Dernières images montées','icon':'disc'},
                    {'id':'eject','name':'Éjecter Drive 0' if connected else 'Drive 0 sans média','icon':'usb'},
                    {'id':'refresh','name':'Actualiser','icon':'system'},{'id':'back','name':'Retour','icon':'back'}]
        if self.screen=='wifi':return [{'id':'qr','name':'Afficher QR Wi-Fi','icon':'wifi'},{'id':'back','name':'Retour','icon':'back'}]
        if self.screen=='network':return [{'id':'toggle','name':'Changer état hotspot','icon':'wifi'},{'id':'back','name':'Retour','icon':'back'}]
        return []

    def back(self):
        if self.screen=='iso' and self.folder and self.scope=='browse':
            self.folder=str(Path(self.folder).parent).replace('\\','/');self.folder='' if self.folder=='.' else self.folder
            self.refresh_library();return
        if self.screen in ('iso-action','iso-info','iso-connect-confirm'):self.change('iso');return
        if self.screen in ('iso','iso-eject-confirm'):self.change('iso-root');return
        if self.screen in ('power-confirm',):self.change('power');self.operation=None;return
        if self.screen in ('qr',):self.change('wifi');return
        if self.screen=='network-confirm':self.change('network');self.operation=None;return
        if self.screen=='menu':self.home();return
        self.change('menu')

    def launch(self,kind,task,return_screen):
        if not self.worker.submit(task):self.error='Opération en cours';return False
        self.pending_kind=kind;self.return_screen=return_screen;self.change('working');self.job_revision=self.revision;return True

    def refresh_library(self,screen='iso'):
        folder,scope=self.folder,self.scope
        return self.launch('library',lambda:self.backend.library(folder,scope),screen)

    def handle(self,gesture,authorize=lambda _:False):
        if gesture.context!=self.revision:return
        self.last_action=self.clock();self.event_at=gesture.released_at if hasattr(gesture,'released_at') else self.clock()
        if gesture.kind=='hold':
            if self.screen in ('power-confirm','network-confirm'):
                kind='power' if self.screen=='power-confirm' else 'network'
                threshold=2 if self.operation=='restart' else 5
                if gesture.duration>=threshold and authorize(kind):
                    permit=Permit(kind,self.clock());operation=self.operation
                    self.launch(kind,lambda:self.backend.sensitive(operation,permit), 'menu')
                elif gesture.duration>=threshold:self.error='Action verrouillée : autorisation requise'
                else:self.back()
                return
            if gesture.duration>=3:self.home()
            else:self.back()
            return
        if self.screen=='status':
            if gesture.kind=='double':self.change('menu')
            elif self.values()['button_short']=='menu':self.change('menu')
            else:self.backend.status_page(self.values()['button_short'])
            return
        if self.screen=='working':return
        if self.screen in ('message','iso-info'):
            if gesture.kind in ('single','double'):self.back()
            return
        if self.screen=='iso-connect-confirm' and gesture.kind=='double':
            target,mode=self.target,self.mode
            self.launch('connect',lambda:self.backend.connect(target,mode),'iso-root');return
        if self.screen=='iso-eject-confirm' and gesture.kind=='double':
            self.launch('eject',lambda:self.backend.eject(True),'iso-root');return
        if self.screen in ('power-confirm','network-confirm','qr'):
            if gesture.kind=='single':self.back()
            return
        items=self.items()
        if not items:return
        if gesture.kind=='single':self.index=(self.index+1)%len(items);self.revision+=1;return
        if gesture.kind!='double':return
        selected=items[self.index];key=selected.get('id') or selected.get('kind')
        if self.screen=='menu':
            if key=='home':self.home()
            elif key=='iso':self.folder='';self.scope='browse';self.refresh_library('iso-root')
            else:self.change(key)
        elif self.screen=='power':
            if key=='back':self.back()
            else:self.operation=key;self.change('power-confirm')
        elif self.screen=='iso-root':
            if key in ('browse','favorites','recent'):
                self.scope=key;self.folder='';self.refresh_library()
            elif key=='refresh':self.refresh_library('iso-root')
            elif key=='back':self.back()
            elif (self.msd or {}).get('drive',{}).get('connected') is True:self.change('iso-eject-confirm')
            else:self.error='Aucun média connecté'
        elif self.screen=='iso':
            if key=='back':self.back()
            elif key=='folder':self.folder=selected['path'];self.scope='browse';self.refresh_library()
            elif not selected.get('complete'):self.error='Image incomplète : sélection refusée'
            else:self.target=selected['path'];self.info=selected;self.change('iso-action')
        elif self.screen=='iso-action':
            if key=='back':self.back()
            elif key=='info':self.change('iso-info')
            elif key=='favorite':
                target=self.target
                self.launch('favorite',lambda:self.backend.favorite(target),'iso-action')
            else:self.mode=key=='cdrom';self.change('iso-connect-confirm')
        elif self.screen=='wifi':
            if key=='back':self.back()
            else:self.launch('qr',self.backend.qr,'qr')
        elif self.screen=='network':
            if key=='back':self.back()
            else:self.operation='hotspot';self.change('network-confirm')

    def tick(self,pressed=False):
        result=self.worker.poll()
        if result:
            kind=self.pending_kind;self.pending_kind=None
            display=self.screen=='working' and self.revision==self.job_revision
            if result['ok']:
                value=result['value']
                if kind=='library':self.msd,self.entries=value
                elif kind in ('connect','eject'):self.msd=value
                elif kind=='qr':self.qr_id=value
                if display:
                    self.change(self.return_screen)
                    if isinstance(value,dict):self.error=value.get('portable_notice','')
            else:
                if display:self.change('message');self.error=result['error']
        timeout=max(self.values()['button_menu_timeout'],30 if self.screen.startswith('iso') else 20)
        if self.screen not in ('status','working') and not pressed and self.clock()-self.last_action>=timeout:self.home()

    def snapshot(self,held=0):
        items=self.items();count=len(items);index=min(self.index,max(0,count-1));start=min(max(0,index-1),max(0,count-3))
        rows=[]
        for item in items[start:start+3]:
            rows.append({'name':str(item.get('name','?'))[:256], 'icon':item.get('icon') or ('folder' if item.get('kind')=='folder' else 'back' if item.get('kind')=='back' else 'disc')})
        return {'pid':os.getpid(),'context':self.context(),'revision':self.revision,'event_at':self.event_at,
                'folder':self.folder,'scope':self.scope,'target':self.target,'mode':self.mode,'operation':self.operation,'size':self.info.get('size'),
                'rows':rows,'start':start,'count':count,'held':round(max(0,held),1),'error':self.error,
                'qr_id':self.qr_id,'remaining':max(0,int(max(self.values()['button_menu_timeout'],30 if self.screen.startswith('iso') else 20)- (self.clock()-self.last_action)))}

    def publish(self,path=NAVIGATION,held=0):
        if self.clock()-self.last_attempt<.09:return
        self.last_attempt=self.clock()
        model=self.snapshot(held);key=json.dumps(model,sort_keys=True)
        if key==self.last_key or self.clock()-self.last_publish<.09:return
        if len(key.encode())>8192:raise RuntimeError('Modèle OLED trop volumineux')
        path.parent.mkdir(mode=0o700,exist_ok=True)
        if path.parent.is_symlink():raise RuntimeError('Répertoire OLED invalide')
        atomic(path,model);self.last_key=key;self.last_publish=self.clock()


class NavigationReader:
    def __init__(self,path=NAVIGATION):self.path=path;self.signature=None;self.model=None
    def read(self,health):
        if not health.get('ready'):return None
        try:
            info=self.path.stat();signature=(info.st_mtime_ns,info.st_size)
            if self.path.is_symlink() or info.st_size>8192:return None
            if signature!=self.signature:
                value=json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value,dict) or value.get('pid')!=health.get('pid') or not isinstance(value.get('context'),dict) or value['context'].get('navigation_id')!=value.get('revision'):return None
                self.model=value;self.signature=signature
            return self.model if self.model and self.model.get('pid')==health.get('pid') else None
        except (OSError,ValueError,TypeError):return None


@lru_cache(maxsize=1)
def qr_image(nonce):
    from PIL import Image
    path=NAVIGATION.parent/'qr.png'
    if path.is_symlink() or path.stat().st_size>32768:raise RuntimeError('QR indisponible')
    with Image.open(path) as source:
        if source.width>56 or source.width!=source.height:raise RuntimeError('QR trop dense pour cet écran')
        return source.convert('1')


def render_navigation(model,values,phase=0):
    from pikvm_oled_ui import render_list,render_message,render_qr
    screen=model['context']['screen'];selected=model['context'].get('selection',0)
    class Rows:
        def __len__(self):return model['count']
        def __getitem__(self,key):
            if isinstance(key,slice):return model['rows'][max(0,key.start-model['start']):key.stop-model['start']]
            return model['rows'][key-model['start']]
    titles={'menu':'Menu PiKVM','power':'Alimentation','wifi':'Wi-Fi','network':'Secours Wi-Fi','iso-root':'Lecteur ISO',
            'iso':'Favoris' if model.get('scope')=='favorites' else 'Historique ISO' if model.get('scope')=='recent' else 'ISO / '+(model['folder'] or '/'),'iso-action':'Actions ISO'}
    if screen in titles:
        surface=render_list(titles[screen],Rows(),selected,values,'1 suivant · 2 ouvrir',phase,model['remaining'])
        if model.get('error'):
            # Errors replace help, without covering selectable rows.
            from pikvm_oled_ui import Surface
            surface.draw.rectangle((0,52,127,63),fill=0);surface.footer(model['error'])
        return surface
    if screen=='qr':
        return render_qr(qr_image(model['qr_id']),'Scanner Wi-Fi',values,phase)
    if screen=='iso-connect-confirm':return render_message('Connecter ISO ?',[Path(model['target']).name,'CD/DVD · RO' if model['mode'] else 'Flash · RO'],values,'2 clics : connecter',symbol='disc',phase=phase)
    if screen=='iso-eject-confirm':return render_message('Éjection propre',['Éjecter sur le PC','puis confirmer ici'],values,'Double : déconnecter',symbol='usb')
    if screen in ('power-confirm','network-confirm'):
        operation=model['operation'];threshold=2 if operation=='restart' else 5
        title='Relancer KVM ?' if operation=='restart' else 'Arrêter PiKVM ?' if operation=='shutdown' else 'Changer Wi-Fi ?'
        return render_message(title,[f'Tenir {threshold}s, lâcher','Clic : annuler'],values,'Relâcher pour confirmer',symbol='power' if screen=='power-confirm' else 'wifi',progress=model['held']/threshold)
    if screen=='iso-info':
        size=model.get('size');size=f'{size/1024**3:.2f} Gio' if type(size) is int and size>=0 else 'Taille inconnue'
        return render_message('Informations ISO',[model['target'],size,'Lecture seule'],values,'Clic : retour',symbol='disc',phase=phase)
    if screen=='working':return render_message('En cours',['Patientez…','Bouton actif'],values,'Aucune action automatique',symbol='system')
    return render_message('Information',[model.get('error') or 'Opération terminée'],values,'Clic : menu',phase=phase)


def preview_navigation(screen,values):
    """Synthetic model, same renderer; no worker, persistence, API or hardware."""
    class NoWorker:
        def poll(self):return None
    nav=Navigation(None,lambda:values,clock=lambda:0,worker=NoWorker())
    nav.screen=screen;nav.target='Linux/Exemple long avec espaces.iso';nav.operation='shutdown'
    nav.entries=[{'name':'Retour','kind':'back'},{'name':'Linux','kind':'folder','path':'Linux'},
                 {'name':'Exemple long avec espaces.iso','kind':'file','path':nav.target,'complete':True}]
    nav.index=1;nav.info={'size':768*1024**2};nav.msd={'drive':{'connected':False}}
    return render_navigation(nav.snapshot(),values)
