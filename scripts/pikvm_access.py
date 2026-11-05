"""Default-deny RC13 policy. No implicit administrator or broad proxy fallback."""
import json
import re
from urllib.parse import parse_qs,urlsplit,unquote
from pikvm_security import SecurityError

# A keyboard stream cannot distinguish typed keys from a client-generated macro.
# Conservatively require both; never describe a UI-only macro switch as an ACL.
KEYBOARD=('kvm.keyboard','kvm.macros')
MOUSE=('kvm.mouse',)

def target(raw):
    url=urlsplit(raw)
    if url.scheme or url.netloc or url.fragment or '%' in url.path or '\\' in url.path or '//' in url.path or any(p in ('.','..') for p in url.path.split('/')):
        raise SecurityError('Chemin ambigu refusé.',400)
    try:query=parse_qs(url.query,keep_blank_values=True,strict_parsing=bool(url.query))
    except ValueError:raise SecurityError('Paramètre HTTP ambigu.',400) from None
    if any(len(v)!=1 for v in query.values()):raise SecurityError('Paramètre répété refusé.',400)
    return url.path,{k:v[0] for k,v in query.items()}

def iso_name(value,allow_empty=False):
    if value=='' and allow_empty:return
    if not isinstance(value,str) or not value or len(value)>700 or value.startswith('/') or '\\' in value or '%' in value or any(not p or p.startswith('.') or any(ord(c)<32 for c in p) for p in value.split('/')) or not value.lower().endswith('.iso'):
        raise SecurityError('Seules les images ISO visibles sont accessibles ; conteneurs internes protégés.',403)

def required(method,raw,data=None,current_settings=None):
    path,q=target(raw);post=method=='POST'
    if method not in ('GET','POST'):raise SecurityError('Méthode refusée.',403)
    if path=='/api/ws':return ('kvm.video',)
    if path in ('/streamer','/streamer/stream','/streamer/snapshot') and not post:
        if not set(q)<={'action','key','extra_headers','advance_headers','dual_final_frames','zero_data'}:raise SecurityError('Paramètre vidéo refusé.',403)
        return ('kvm.video',)
    read={'/api/info':('system.diagnostics',),'/api/hid':('kvm.video',),'/api/hid/keymaps':KEYBOARD,
          '/api/hid/inactivity':('system.diagnostics',),'/api/streamer':('kvm.video',),
          '/api/msd':('iso.view',),'/api/atx':('atx.view',)}
    if not post and path in read:return read[path]
    if post:
        if path in ('/api/hid/events/send_key','/api/hid/events/send_shortcut'):return KEYBOARD
        if path.startswith('/api/hid/events/send_mouse_'):return MOUSE if path in ('/api/hid/events/send_mouse_button','/api/hid/events/send_mouse_move','/api/hid/events/send_mouse_relative','/api/hid/events/send_mouse_wheel') else reject()
        if path=='/api/hid/print':return (*KEYBOARD,'kvm.text')
        if path in ('/api/hid/set_params','/api/hid/set_connected','/api/hid/reset'):return ('kvm.hid',)
        if path=='/api/msd/set_params':
            if not set(q)<={'image','cdrom','rw'} or q.get('rw','false') not in ('0','false'):raise SecurityError('ISO en lecture seule ; paramètres inconnus refusés.',403)
            if 'image' in q:iso_name(q['image'],True)
            return ('iso.mount',)
        if path=='/api/msd/set_connected':
            if set(q)!={'connected'} or q['connected'] not in ('true','false','0','1'):raise SecurityError('État de connexion invalide.',400)
            return ('iso.mount' if q['connected'] in ('true','1') else 'iso.eject',)
        if path=='/api/msd/write':
            iso_name((q.get('prefix','').strip('/')+'/' if q.get('prefix') else '')+q.get('image',''))
            return ('iso.upload',)
        if path=='/api/msd/remove':iso_name(q.get('image'));return ('iso.delete',)
        # URL imports can perform SSRF; reset can affect more than the chosen image.
        if path in ('/api/msd/reset','/api/msd/write_remote'):return reject()
        if path in ('/api/atx/power','/api/atx/click'):
            action=q.get('action',q.get('button'))
            permission={'on':'atx.on','off':'atx.off','off_hard':'atx.sensitive','reset_hard':'atx.restart','power':'atx.on','power_long':'atx.sensitive','reset':'atx.restart'}.get(action)
            if permission is None or not isinstance(data,dict) or data.get('confirmed') is not True:raise SecurityError('Action ATX et confirmation indépendante requises.',403)
            return (permission,)
    prefix='/extras/portable-os/api/'
    if path.startswith(prefix):
        route=path[len(prefix):]
        if route.startswith('security/'):
            if route=='security/session':return ()
            return ('accounts.view',) if not post else () # mutations have their own granular checks
        reads={'status':('system.diagnostics',),'usb':('share.status',),'logs':('system.logs',),'oled':('oled.view',),
               'settings':(),'settings/current':(),'settings/export':('system.export',),
               'idle':('system.diagnostics',),'integrity':('system.diagnostics',),'report':('system.export',)}
        if not post and route in reads:return reads[route]
        if post and route=='activity':return ()
        if post and route=='settings/preview':return ('oled.view',)
        if post and route in ('settings/import','settings/reset'):return ('system.restore','system.settings','oled.pages','oled.durations','oled.gestures','oled.notifications')
        if post and route=='settings/apply':
            if not isinstance(data,dict) or not isinstance(data.get('values'),dict) or current_settings is None:raise SecurityError('Différence de paramètres non vérifiable.',403)
            wanted=data['values'];changed={key for key in wanted if wanted[key]!=current_settings.get(key)};needs=set()
            for key in changed:
                if key=='oled_pages':continue
                needs.add('oled.notifications' if key in ('oled_low_priority','oled_transfer_priority','battery_notifications','battery_low','battery_critical') else
                          'oled.durations' if key=='oled_alert_seconds' else
                          'oled.pages' if key.startswith('oled_') else 'oled.gestures' if key.startswith('button_') else
                          'iso.info' if key in ('iso_favorite','iso_sort') else 'system.settings')
            if 'oled_pages' in changed:
                old={p['id']:p for p in current_settings['oled_pages']}
                if not isinstance(wanted['oled_pages'],list) or any(not isinstance(p,dict) for p in wanted['oled_pages']):raise SecurityError('Pages OLED invalides.',400)
                if [p.get('id') for p in wanted['oled_pages']]!=[p['id'] for p in current_settings['oled_pages']] or any(p.get('enabled')!=old.get(p.get('id'),{}).get('enabled') for p in wanted['oled_pages']):needs.add('oled.pages')
                if any(p.get('seconds')!=old.get(p.get('id'),{}).get('seconds') for p in wanted['oled_pages']):needs.add('oled.durations')
            return tuple(needs)
        # OLED navigation can mount images, change Wi-Fi and confirm power.
        # It is an indivisible native menu: restricted accounts get pixels only.
        if post and route in ('oled/short','oled/button'):return ('oled.gestures','iso.mount','iso.eject','system.network','system.shutdown')
        if post and route=='hotspot':return ('system.network',)
        if post and route=='idle/simulate':return ('system.diagnostics',)
        return reject()
    if path.startswith('/extras/pikvm-share/api/'):
        action=path.rsplit('/api/',1)[1]
        if not post:return ('share.status',) if action=='status' else ('share.web',) if action in ('files','download') else reject()
        if action=='mode/usb':return ('share.usb',)
        if action=='mode/web':return ('share.web',)
        if action in ('upload/begin','upload/chunk','upload/finish','upload/cancel','create-file','mkdir','rename','delete'):return ('share.web',)
        return reject()
    if path.startswith(('/extras/wifi-wizard/api/','/extras/image-manager/api/')):
        route=path.split('/api/',1)[1]
        if not post:
            return {'status':('system.diagnostics',),'battery':('system.diagnostics',),'usb-transfer/status':('share.status',),'image-manager/folders':('iso.view',),'networks':('system.network',),'scan':('system.network',)}.get(route) or reject()
        if route=='image-manager/folders/action':
            operation=(data or {}).get('action');permission={'mkdir':'iso.mkdir','rmdir':'iso.delete','rename_dir':'iso.rename','move_file':'iso.move','rename_file':'iso.rename'}.get(operation)
            return (permission,) if permission else reject()
        if route=='image-manager/rename':return ('iso.rename',)
        if route.startswith('usb-transfer/'):
            return {'usb-transfer/start':('share.start','share.usb'),'usb-transfer/stop':('share.stop',),'usb-transfer/import':('share.import',)}.get(route) or reject()
        if route in ('add','update','delete','force','restart'):return ('system.network',)
        return reject() # no reboot, poweroff, USB reset, prepare, arbitrary maintenance
    return reject()

def reject():raise SecurityError('Cette voie native n’est pas autorisée par la passerelle RC13.',403)

def websocket_permissions(data,binary=False):
    if binary:
        if not data or len(data)>4096:return reject()
        event=data[0]
        if event==0 and len(data)==1:return ()
        if event==1:return KEYBOARD
        if event in (2,3,4,5):return MOUSE
        return reject()
    try:value=json.loads(data)
    except (ValueError,TypeError):raise SecurityError('Événement WebSocket invalide.',400) from None
    if not isinstance(value,dict) or set(value)!={'event_type','event'} or not isinstance(value['event'],dict):return reject()
    event=value['event_type']
    if event=='ping':return ()
    if event=='key':return KEYBOARD
    if event in ('mouse_button','mouse_move','mouse_relative','mouse_wheel'):return MOUSE
    return reject()

def visible_event(principal,event):
    kind=event.get('event_type');p=principal.permissions
    return kind in ('loop','pong','clients','hid','hid_keymaps','streamer') or (kind=='info' and 'system.diagnostics' in p) or (kind=='msd' and 'iso.view' in p) or (kind=='atx' and 'atx.view' in p)

def safe_info(info):
    # Native metadata/extras are administrator-authored and may contain secrets.
    # Keep native telemetry needed by the KVM; never project arbitrary metadata.
    return {key:value for key,value in info.items() if key in ('system','hw','auth')}

def redact_network(value):
    if isinstance(value,list):return [redact_network(item) for item in value]
    if isinstance(value,dict):return {key:False if key=='password_visible' else '' if key in ('password','psk','passwd','secret','auth_token') else redact_network(item) for key,item in value.items()}
    return value
