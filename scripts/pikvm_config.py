"""Versioned Portable OS preferences. No GPIO, shell, USB or power writes.

Readers use the standard library and fail to safe defaults. Production writes
require KVMD's PST lease; the root and MSD filesystems are never remounted here.
"""
import copy
import json
import os
from pathlib import Path, PurePosixPath
import stat
import threading
import time
import uuid

VERSION = 1
MAX_BYTES = 16384
CATEGORIES = ['Général', 'Inactivité et veille', 'Alimentation et batterie', 'OLED et écrans',
              'Bouton physique', 'Console KVM', 'USB et stockage', 'Réseau',
              'Performances et ressources', 'Sécurité et maintenance', 'Sauvegarde et restauration', 'Options avancées']
FIELDS = {}
WRITE_LOCK=threading.RLock()


def field(key, category, label, default, description, *, minimum=None, maximum=None, choices=None, sensitive=False):
    FIELDS[key] = dict(category=category, label=label, default=default, description=description,
                       type='boolean' if type(default) is bool else 'number' if type(default) is int else 'select' if choices else 'text',
                       minimum=minimum, maximum=maximum, choices=choices, sensitive=sensitive, application='À chaud')


field('theme', 0, 'Thème', 'dark', 'Préférence partagée ; le navigateur applique le thème après enregistrement.', choices={'dark':'Sombre','light':'Clair'})
field('idle_enabled', 1, 'Activer le suivi de l’inactivité', False, 'Aucune extinction réelle. Les actions OLED et économie sont logicielles.', sensitive=True)
field('idle_first_seconds', 1, 'Première action après (secondes)', 300, 'De 10 secondes à 24 heures.', minimum=10, maximum=86400)
field('idle_shutdown_seconds', 1, 'Échéance d’arrêt simulée (secondes)', 1800, 'Diagnostic uniquement : aucun arrêt système n’est exécuté.', minimum=60, maximum=86400)
field('idle_warning_seconds', 1, 'Avertissement avant l’échéance (secondes)', 60, '0 désactive l’avertissement ; celui-ci reste une simulation.', minimum=0, maximum=600)
field('idle_action', 1, 'Action logicielle', 'none', 'S’applique hors menus interactifs ; une activité reconnue restaure l’affichage.', choices={'none':'Aucune','screen':'Écran OLED d’inactivité','off':'Écran OLED noir','economy':'Économie de rafraîchissements informatifs'})
for source, label in [('web','Interface Portable OS'),('keyboard','Clavier KVM intégré'),('mouse','Souris KVM intégrée'),('terminal','Terminal Web intégré'),('button','Bouton physique ou virtuel'),('menu','Navigation dans les menus OLED')]:
    field('activity_'+source, 1, 'Réinitialiser : '+label, True, 'Événements observés uniquement ; une connexion seule n’est pas une activité.')
field('activity_transfer',1,'Réinitialiser : transfert/import en cours',True,'Opération confirmée par le gestionnaire de transfert ; un support simplement attaché ne suffit pas.')
field('activity_storage',1,'Réinitialiser : opération de stockage verrouillée',True,'Verrou d’un écrivain réellement détenu ; ne mesure pas toutes les écritures du système.')
field('inhibit_ssh', 1, 'Inhiber si la présence SSH est inconnue', True, 'RC11 ne certifie pas les sessions SSH : état inconnu et inhibiteur par défaut, sans déduire les frappes.', sensitive=True)
field('inhibit_kvm', 1, 'Inhiber si le KVM intégré est visible', True, 'Présence du navigateur signalée par un bail de 25 secondes ; ne couvre pas les clients externes.', sensitive=True)
field('battery_low', 2, 'Seuil d’avertissement (%)', 20, 'Pourcentage estimé par le code MAX17048 existant ; ne prouve pas l’alimentation externe.', minimum=5, maximum=50)
field('battery_critical', 2, 'Seuil critique (%)', 10, 'Avertissement OLED prioritaire non masquable ; aucun arrêt automatique.', minimum=1, maximum=30)
field('battery_notifications', 2, 'Notifications batterie Web', True, 'Alerte dans la session ouverte, limitée à une notification par épisode.')
field('oled_rotation', 3, 'Rotation OLED', '0', 'Même rotation du framebuffer physique et du miroir ; menus inclus.', choices={'0':'0°','180':'180°'})
field('oled_contrast', 3, 'Contraste SSD1306', 160, 'Appliqué par le worker I2C si le pilote expose contrast(). Le miroir reste monochrome.', minimum=0, maximum=255)
field('oled_auto', 3, 'Rotation automatique des pages', True, 'Sinon, afficher la page permanente choisie. Les alertes critiques gardent la priorité.')
field('oled_fixed', 3, 'Page permanente', 'main', 'Le menu physique reste disponible.', choices={'main':'Accueil / réseau','battery':'Batterie','system':'Système / USB / HDMI'})
field('oled_low_priority', 3, 'Priorité de l’alerte batterie faible', 2, '1 est prioritaire. Le seuil critique reste toujours prioritaire.', minimum=1, maximum=5)
field('oled_transfer_priority', 3, 'Priorité du transfert actif', 1, 'Le transfert reste visible pendant une importation critique.', minimum=1, maximum=5)
field('oled_alert_seconds', 3, 'Durée d’une page conditionnelle (secondes)', 5, 'Retour à la rotation normale entre les avertissements non critiques.', minimum=2, maximum=60)
field('oled_show_ip', 7, 'Adresse IP sur la page OLED d’accueil', True, 'Masque uniquement la ligne IP, sans changer le réseau.')
field('button_short', 4, 'Appui hors menu', 'menu', 'Geste logique existant après relâchement ; aucun changement électrique.', choices={'menu':'Ouvrir le menu existant','next':'Page OLED suivante','battery':'Afficher la batterie','main':'Afficher accueil / IP'})
field('button_menu_timeout', 4, 'Expiration du menu principal (secondes)', 10, 'Les gestes sensibles 2 s, 3 s et 5 s gardent leurs protections.', minimum=5, maximum=60)
field('kvm_default_panel', 5, 'Panneau ouvert à l’arrivée', 'none', 'N’exécute aucune action et n’active jamais la capture.', choices={'none':'Aucun','msd-dropdown':'Lecteur ISO','share':'Clé USB','system-dropdown':'Vidéo & HID'})
field('kvm_fit', 5, 'Affichage vidéo', 'contain', 'Affichage seulement ; la résolution et les événements HID restent natifs.', choices={'contain':'Image complète','cover':'Remplir (bords éventuellement coupés)'})
field('kvm_fullscreen', 5, 'Cible du plein écran', 'console', 'Le bouton et le raccourci de libération de capture restent disponibles.', choices={'console':'Console et commandes','page':'Page complète'})
field('iso_sort', 6, 'Tri de la bibliothèque Portable OS', 'name', 'Tri d’affichage de Images & Drive 0 ; les réglages natifs restent dans le panneau KVMD.', choices={'name':'Nom','size':'Taille','date':'Date de modification'})
field('iso_favorite', 6, 'Dossier ISO favori', '', 'Dossier relatif existant à ouvrir dans Images & Drive 0 ; vide pour la racine.')
field('network_notifications', 7, 'Alerte réseau indisponible', True, 'Signale les échecs de télémétrie ; aucune déduction de présence du PC.')
field('dashboard_ip', 7, 'Afficher l’IP dans le tableau de bord', True, 'Préférence d’affichage uniquement.')
field('profile', 8, 'Profil applicatif', 'balanced', 'Économie : polling 15 s ; équilibré : 8 s ; réactif : 5 s. Aucun réglage CPU, tension ou swap.', choices={'economy':'Économie','balanced':'Équilibré','responsive':'Réactif'})
field('animations', 8, 'Animations de l’interface', True, 'Respecte également la préférence système de réduction des animations.')
field('advanced_diagnostics', 11, 'Afficher les détails des diagnostics', False, 'Métadonnées techniques uniquement ; aucun secret ni commande libre.')

PAGES = ('main', 'battery', 'system', 'transfer')
COMMANDS = ('msd-dropdown', 'share', 'atx-dropdown', 'shortcuts-dropdown', 'macro-dropdown', 'text-dropdown', 'system-dropdown')


class ConfigError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def defaults():
    return {**{key:copy.deepcopy(spec['default']) for key,spec in FIELDS.items()},
            'oled_pages':[{'id':name, 'enabled':True, 'seconds':10} for name in PAGES],
            'kvm_order':list(COMMANDS), 'kvm_hidden':[]}


def validate(values):
    expected = defaults()
    if not isinstance(values, dict) or set(values) != set(expected):
        raise ConfigError('Configuration incomplète ou champs inconnus.')
    for key,spec in FIELDS.items():
        value = values[key]
        if type(value) is not type(spec['default']):
            raise ConfigError('Type invalide : '+spec['label'])
        if spec['choices'] and value not in spec['choices']:
            raise ConfigError('Choix invalide : '+spec['label'])
        if spec['minimum'] is not None and not spec['minimum'] <= value <= spec['maximum']:
            raise ConfigError('Valeur hors limites : '+spec['label'])
    path = values['iso_favorite']
    if len(path)>180 or '\\' in path or path.startswith('/') or (path and any(not p or p in ('.','..') or p.startswith('.') for p in path.split('/'))) or any(ord(c)<32 for c in path):
        raise ConfigError('Dossier favori relatif invalide.')
    if values['battery_critical'] >= values['battery_low']:
        raise ConfigError('Le seuil critique doit être inférieur au seuil d’avertissement.')
    if values['idle_shutdown_seconds'] <= values['idle_first_seconds'] or values['idle_warning_seconds'] >= values['idle_shutdown_seconds']:
        raise ConfigError('Délais d’inactivité incohérents.')
    pages = values['oled_pages']
    if not isinstance(pages,list) or len(pages)!=len(PAGES):
        raise ConfigError('Liste de pages OLED invalide.')
    for page in pages:
        if not isinstance(page,dict) or set(page)!={'id','enabled','seconds'} or page['id'] not in PAGES or type(page['enabled']) is not bool or type(page['seconds']) is not int or not 2<=page['seconds']<=300:
            raise ConfigError('Page OLED invalide (durée de 2 à 300 secondes).')
    if len({page['id'] for page in pages})!=len(PAGES) or not any(p['enabled'] for p in pages if p['id']!='transfer'):
        raise ConfigError('Conserver au moins une page OLED ordinaire ; aucun doublon.')
    if not next(p['enabled'] for p in pages if p['id']==values['oled_fixed']):
        raise ConfigError('La page permanente doit être activée.')
    if not isinstance(values['kvm_order'],list) or any(type(v) is not str for v in values['kvm_order']) or sorted(values['kvm_order'])!=sorted(COMMANDS):
        raise ConfigError('Ordre des commandes KVM invalide.')
    if not isinstance(values['kvm_hidden'],list) or any(type(n) is not str or n not in COMMANDS for n in values['kvm_hidden']) or len(set(values['kvm_hidden']))!=len(values['kvm_hidden']):
        raise ConfigError('Visibilité KVM invalide.')
    return copy.deepcopy(values)


def pst_path(fstab=Path('/etc/fstab')):
    """Same X-kvmd.pst-root contract as kvmd.fstab, without importing KVMD."""
    for line in fstab.read_text(encoding='utf-8').splitlines():
        fields=line.split()
        if len(fields)!=6 or line.lstrip().startswith('#'):continue
        options=dict((item.split('=',1)+[''])[:2] for item in fields[3].split(','))
        if any(key in options for key in ('X-kvmd.pst-root','X-kvmd.pst-user','X-kvmd.pst-group')):
            root=PurePosixPath(options.get('X-kvmd.pst-root','') or fields[1])
            if not root.is_absolute() or '..' in root.parts:break
            return Path(str(root))/'portable-os'/'settings.json'
    raise ConfigError('Partition PST non identifiée ; préférences persistantes indisponibles.',503)


def ordinary(path, missing=False):
    for parent in [*reversed(path.parents),path]:
        if parent.is_symlink():raise ConfigError('Lien symbolique interdit dans les préférences.',503)
    try:info=path.stat()
    except FileNotFoundError:
        if missing:return
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_size>MAX_BYTES:
        raise ConfigError('Fichier de préférences invalide.',503)
    if os.name!='nt' and (info.st_uid!=os.geteuid() or info.st_mode&0o077):
        raise ConfigError('Permissions des préférences invalides.',503)


def atomic(path, document):
    temporary=path.with_name('.settings-'+uuid.uuid4().hex)
    try:
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as handle:
            json.dump(document,handle,ensure_ascii=False,separators=(',',':'));handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
        if os.name!='nt':
            fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    finally:temporary.unlink(missing_ok=True)


class Store:
    """Persistence primitive; production caller MUST own a PST write lease."""
    def __init__(self,path):self.path=Path(path);self.lock=WRITE_LOCK

    def read(self):
        try:
            ordinary(self.path,missing=True)
            if not self.path.exists():return dict(schema_version=VERSION,revision=0,values=defaults(),history=[],healthy=True)
            document=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(document,dict):raise ValueError()
            if type(document.get('schema_version')) is int and document['schema_version']==0 and set(document)=={'schema_version','theme'} and document['theme'] in ('dark','light'):
                return dict(schema_version=VERSION,revision=0,values={**defaults(),'theme':document['theme']},history=[],healthy=True,migrated=True)
            if set(document)!={'schema_version','revision','values','history'} or type(document['schema_version']) is not int or document['schema_version']!=VERSION or type(document['revision']) is not int or document['revision']<0 or not isinstance(document['history'],list) or len(document['history'])>20:
                raise ValueError()
            validate(document['values'])
            # History is a bounded, server-authored list of field names only.
            for item in document['history']:
                if not isinstance(item,dict) or set(item)!={'at','keys'} or type(item['at']) not in (float,int) or not isinstance(item['keys'],list) or any(k not in defaults() for k in item['keys']):raise ValueError()
            return {**document,'healthy':True}
        except (OSError,ValueError,TypeError,KeyError,ConfigError):
            return dict(schema_version=VERSION,revision='corrupt',values=defaults(),history=[],healthy=False,error='Préférences illisibles : valeurs sûres actives. Restauration explicite nécessaire.')

    def save(self,values,expected,confirmed=False,reset=False):
        values=validate(values)
        if type(expected) is not int and expected!='corrupt':raise ConfigError('Révision invalide.')
        if type(confirmed) is not bool:raise ConfigError('Confirmation invalide.')
        with self.lock:
            ordinary(self.path,missing=True)
            self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            lockpath=self.path.with_name('settings.lock')
            fd=os.open(lockpath,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'r+') as handle:
                if os.name!='nt':
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX)
                current=self.read()
                if current['revision']!=expected:raise ConfigError('Préférences modifiées ailleurs. Recharge avant d’appliquer.',409)
                if not current['healthy'] and not (reset and confirmed):raise ConfigError('Restauration explicite requise.',409)
                changed=[key for key in values if values[key]!=current['values'][key]]
                if not reset and not changed:return current
                if not confirmed and (reset or any(FIELDS.get(k,{}).get('sensitive') for k in changed)):
                    raise ConfigError('Confirmation explicite des réglages sensibles requise.',409)
                revision=(current['revision'] if current['healthy'] else 0)+1
                history=[*current['history'],{'at':time.time(),'keys':changed or list(values)}][-20:]
                document=dict(schema_version=VERSION,revision=revision,values=values,history=history)
                while len(json.dumps(document,ensure_ascii=False,separators=(',',':')).encode())>MAX_BYTES:
                    if len(history)<=1:raise ConfigError('Préférences trop volumineuses.')
                    history.pop(0)
                atomic(self.path,document)
                return self.read()


class Configuration:
    def __init__(self,path=None):
        self.override=path

    def store(self):return Store(self.override or pst_path())

    def read(self):
        try:return self.store().read()
        except (OSError,ConfigError):return dict(schema_version=VERSION,revision=0,values=defaults(),history=[],healthy=False,error='PST indisponible ; valeurs sûres actives.')

    def save(self,values,expected,confirmed=False,reset=False):
        if self.override is not None:return self.store().save(values,expected,confirmed,reset)
        import asyncio  # Read-only OLED/button processes never import the PST stack.
        async def commit():
            # Native KVMD config resolves overridden PST sockets; no new dependency.
            from kvmd.apps import init
            app=init(prog='pikvm-portable-settings')
            async with app.make_pst_client('portable-os','PiKVM-Portable-OS').writable() as path:
                target=pst_path()
                if Path(path).resolve()!=target.parent.resolve():raise ConfigError('Correspondance PST incohérente.',503)
                return Store(target).save(values,expected,confirmed,reset)
        try:return asyncio.run(commit())
        except ConfigError:raise
        except Exception:raise ConfigError('Écriture PST refusée ou indisponible ; aucune configuration système modifiée.',503) from None


class Reader:
    def __init__(self,path=None,clock=time.monotonic):self.path=path;self.clock=clock;self.at=float('-inf');self.values=defaults();self.revision=None
    def get(self):
        if self.clock()-self.at>=2:
            document=Configuration(self.path).read();self.values=document['values'];self.revision=document['revision'];self.at=self.clock()
        return self.values


READER=Reader()


class PageRotation:
    """Shared status-page schedule, including conditional pages and button requests."""
    def __init__(self):self.current=None;self.started=0;self.signature=None;self.alert_until=0;self.alert_key=None;self.manual_until=0
    def choose(self,values,now,transfer=False,percent=None,request=None,critical_transfer=False):
        pages=[p for p in values['oled_pages'] if p['enabled'] and p['id']!='transfer']
        signature=json.dumps([pages,values['oled_auto'],values['oled_fixed']],sort_keys=True)
        if signature!=self.signature or self.current not in [p['id'] for p in pages]:
            self.current=pages[0]['id'];self.started=now;self.signature=signature
        if request:
            ids=[p['id'] for p in pages]
            self.current=ids[(ids.index(self.current)+1)%len(ids)] if request=='next' else request if request in ids else self.current
            self.started=now
            self.manual_until=now+next(p['seconds'] for p in pages if p['id']==self.current)
        duration=next(p['seconds'] for p in pages if p['id']==self.current)
        if values['oled_auto'] and now-self.started>=duration:
            ids=[p['id'] for p in pages];self.current=ids[(ids.index(self.current)+1)%len(ids)];self.started=now
        elif not values['oled_auto'] and not request and now>=self.manual_until:self.current=values['oled_fixed']
        choices=[]
        if transfer and (critical_transfer or next(p['enabled'] for p in values['oled_pages'] if p['id']=='transfer')):choices.append((values['oled_transfer_priority'],'transfer'))
        if percent is not None and percent<=values['battery_low']:choices.append((values['oled_low_priority'],'battery'))
        critical=percent is not None and percent<=values['battery_critical']
        alert=min(choices)[1] if choices else None
        if critical:alert='battery'
        elif critical_transfer:alert='transfer'
        # Critical battery / active import cannot be hidden by page preferences.
        alert_seconds=next(p['seconds'] for p in values['oled_pages'] if p['id']=='transfer') if alert=='transfer' else values['oled_alert_seconds']
        if alert and (critical or critical_transfer or self.alert_key!=alert):self.alert_key=alert;self.alert_until=now+alert_seconds
        if not alert:self.alert_key=None
        if alert and (critical or critical_transfer or now<self.alert_until):return alert,max(1,int(self.alert_until-now+.999))
        if alert and now>=self.alert_until+duration:self.alert_until=now+alert_seconds
        return self.current,max(1,int(duration-(now-self.started)+.999))


class IdleEngine:
    """Policy evaluator. Deliberately has NO shutdown/reboot execution branch."""
    def __init__(self,clock=time.monotonic):self.clock=clock;self.last=clock();self.source='démarrage';self.presence_until=0;self.lock=threading.Lock()
    def activity(self,source,values):
        if source not in ('web','keyboard','mouse','terminal','button','menu','transfer','storage'):raise ConfigError('Source d’activité non prise en charge.')
        with self.lock:
            if values['activity_'+source]:self.last=self.clock();self.source=source
    def presence(self):
        with self.lock:self.presence_until=self.clock()+25
    def evaluate(self,values,evidence):
        with self.lock:elapsed=max(0,self.clock()-self.last);source=self.source;present=self.clock()<self.presence_until
        inhibitors=[]
        # Only exactly false means safe. Unknown, absent and stale remain blocked.
        for key,label in [('drive0','Drive 0 attaché ou inconnu'),('drive1','Drive 1 attaché ou inconnu'),
                          ('transfer','Transfert/import actif ou inconnu'),('share','SHARE Web/occupé ou inconnu'),
                          ('storage','Écriture stockage active ou inconnue'),('install','Installation active ou inconnue')]:
            if evidence.get(key) is not False:inhibitors.append(label)
        if values['inhibit_ssh'] and evidence.get('ssh') is not False:inhibitors.append('Session SSH présente ou observation inconnue')
        if values['inhibit_kvm'] and present:inhibitors.append('KVM intégré visible (bail navigateur)')
        remaining=max(0,values['idle_shutdown_seconds']-int(elapsed))
        enabled=values['idle_enabled'];due=enabled and remaining==0
        state='extinction inhibée' if due and inhibitors else 'inconnu' if enabled and any(evidence.get(k) is None for k in ('drive0','drive1','transfer','share','storage','install')) else 'inactif' if enabled and elapsed>=values['idle_first_seconds'] else 'actif'
        return {'state':state,
                'elapsed':int(elapsed),'remaining':remaining,'source':source,'inhibitors':inhibitors,
                'warning':enabled and 0<remaining<=values['idle_warning_seconds'],
                'action':values['idle_action'] if enabled and elapsed>=values['idle_first_seconds'] else 'none',
                'shutdown_due':due,'shutdown_allowed':False,'simulation_would_allow':due and not inhibitors,
                'reason':'Arrêt réel non activable dans RC11 : validation matérielle exhaustive des inhibiteurs requise.',
                'monotonic':self.clock()}
