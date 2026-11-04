"""Shared OLED framebuffer, asynchronous telemetry and leased logical input."""
import base64
import importlib
import contextlib
import hashlib
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import threading
import time
from collections import OrderedDict
from pikvm_config import READER

RUNTIME = Path('/run/pikvm-oled')
FRAME = RUNTIME / 'frame.json'
SOCKET = RUNTIME / 'button.sock'
BUTTON_HEARTBEAT = RUNTIME / 'button.json'
MAX_AGE = 15


def button_status():
    try:
        if BUTTON_HEARTBEAT.is_symlink() or BUTTON_HEARTBEAT.stat().st_size > 4096:
            return {'ready':False}
        value = json.loads(BUTTON_HEARTBEAT.read_text())
        age = time.monotonic() - value['monotonic']
        poll_age=value.get('poll_age_ms')
        return {**value, 'age_ms':round(age*1000,1), 'ready':SOCKET.is_socket() and 0 <= age <= .8 and type(poll_age) in (int,float) and 0<=poll_age<=800}
    except (OSError, ValueError, KeyError, TypeError):
        return {'ready':False}


def button_ready():
    return button_status()['ready']


class AsyncCache:
    """Bounded telemetry cache. A slow reader never runs in the render thread."""
    def __init__(self, workers=2):
        self.condition = threading.Condition()
        self.items = OrderedDict()
        self.queue = []
        self.closed = False
        self.revision = 0
        self.threads = [threading.Thread(target=self._work, daemon=True, name='oled-telemetry') for _ in range(workers)]
        for thread in self.threads:
            thread.start()

    def wrap(self, reader, default=None, interval=1):
        def cached(*args):
            key = (reader, args)
            with self.condition:
                item = self.items.get(key)
                if item is None:
                    if len(self.items) >= 32:
                        disposable = next((k for k, v in self.items.items() if not v['pending']), None)
                        if disposable is None:
                            return default
                        self.items.pop(disposable)
                    item = self.items[key] = {'value': default, 'at': float('-inf'), 'pending': False}
                if not self.closed and not item['pending'] and time.monotonic() - item['at'] >= interval:
                    item['pending'] = True
                    self.queue.append((key, reader, args))
                    self.condition.notify()
                return item['value']
        return cached

    def _work(self):
        while True:
            with self.condition:
                while not self.queue and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                key, reader, args = self.queue.pop(0)
            try:
                value, success = reader(*args), True
            except Exception:
                value, success = None, False
            with self.condition:
                item = self.items[key]
                if success:
                    if value != item['value']:
                        self.revision += 1
                    item['value'] = value
                item['at'], item['pending'] = time.monotonic(), False

    def close(self):
        with self.condition:
            self.closed = True
            self.queue.clear()
            self.condition.notify_all()


class ButtonReader:
    """Read-only physical sampler; uncertain input cancels instead of extending."""
    def __init__(self, reader, resource=None, diagnostic=None):
        self.reader, self.sample, self.at = reader, None, float('-inf')
        self.resource, self.diagnostic = resource, diagnostic or {}
        self.lock = threading.Lock()
        self.fault_pending = False
        self.samples = self.errors = 0
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name='oled-button-read')
        self.thread.start()

    def _run(self):
        while not self.stopped.is_set():
            try:
                value = self.reader()
            except Exception:
                value = None
            self.update(value)
            self.stopped.wait(.04)

    def read(self):
        with self.lock:
            if self.fault_pending:
                self.fault_pending = False
                return None  # Never hide a brief GPIO fault between menu polls.
            return self.sample if time.monotonic() - self.at <= .3 else None

    def update(self, value):
        with self.lock:
            now = time.monotonic()
            gap = self.samples and now - self.at > .3
            if value is not True and value is not False:
                value = None
            if value is None or gap:
                self.fault_pending = True
                self.errors += 1
            self.samples += 1
            self.sample, self.at = value, now

    def status(self):
        validation = self.resource.check() if self.resource is not None else None
        with self.lock:
            age = time.monotonic() - self.at
            return {**self.diagnostic,**({'validation':validation} if isinstance(validation,dict) else {}),'samples':self.samples,'errors':self.errors,
                    'sample_age_ms':round(age*1000,1) if self.samples else None}

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=.5)
        # Never unmap memory while its sampling thread could still be reading it.
        if self.resource is not None and not self.thread.is_alive():
            self.resource.close()


def receive_json(connection, limit):
    packet = bytearray()
    while len(packet) <= limit:
        chunk = connection.recv(min(1024, limit + 1 - len(packet)))
        if not chunk:
            raise ValueError('Incomplete OLED message')
        packet.extend(chunk)
        if b'\n' in packet:
            line, rest = bytes(packet).split(b'\n', 1)
            if rest or len(line) > limit:
                raise ValueError('Oversized OLED message')
            return json.loads(line)
    raise ValueError('Oversized OLED message')


def authorize_local(connection, allowed_uid=0):
    if hasattr(socket, 'SO_PEERCRED'):
        _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != allowed_uid:
            raise OledError('Client local non autorisé.', 403)


class OledError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        raise OledError('Répertoire OLED invalide.')
    if hasattr(os, 'geteuid') and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise OledError('Permissions du répertoire OLED invalides.')


def read_frame(path=None, clock=time.monotonic):
    path = path or FRAME
    try:
        if path.is_symlink() or path.stat().st_size > 8192:
            raise ValueError()
        data = json.loads(path.read_text(encoding='utf-8'))
        pixels = base64.b64decode(data['pixels'], validate=True)
        if (len(pixels) != 1024 or data['width'] != 128 or data['height'] != 64 or
                data['format'] != '1bpp-msb' or not valid_id(data['id']) or
                data['source'] not in ('menu', 'status') or not isinstance(data['context'], dict)):
            raise ValueError()
        age = clock() - data['monotonic']
        if not 0 <= age <= MAX_AGE:
            raise OledError('Affichage OLED périmé : producteur arrêté ou indisponible.')
        return {**data, 'age': round(age, 2)}
    except OledError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise OledError('Framebuffer OLED indisponible.') from None


def physical_device():
    # Optional and lazy: a missing luma package or display never stops the mirror.
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    core=importlib.import_module('luma.core.device')
    registry=core.atexit;owner=threading.get_ident()
    class OwnedExit:
        def register(self,callback,*args,**kwargs):
            # luma registers a closure holding self BEFORE initialization. Even
            # unregister(self.cleanup) cannot remove that closure. This worker
            # owns its lifetime; registrations from other threads still delegate.
            if threading.get_ident()==owner:return callback
            return registry.register(callback,*args,**kwargs)
        def __getattr__(self,name):return getattr(registry,name)
    serial=None;core.atexit=OwnedExit()
    try:
        serial=i2c(port=1,address=0x3C)
        device=ssd1306(serial,width=128,height=64)
        device._portable_release=serial.cleanup  # Bus close only; no GPIO or blanking command.
        return device
    except BaseException:
        try:
            if serial is not None:serial.cleanup()
        except Exception:pass
        raise
    finally:core.atexit=registry


class PhysicalOutput:
    """One optional I2C worker, one latest frame. Never blocks the renderer.

    Failed attempts retry after 30 seconds, including failures while displaying.
    A blocked kernel/driver call cannot grow a queue or spawn more workers.
    """
    def __init__(self, factory, clock=time.monotonic, background=True):
        self.factory, self.clock, self.background = factory, clock, background
        self.condition = threading.Condition()
        self.device = None
        self.latest = None
        self.raw = None
        self.generation = 0
        self.sent = 0
        self.retry_at = 0
        self.state = 'disconnected'
        self.closed = False
        self.thread = None
        self.contrast = 160
        self.applied_contrast = None

    def offer(self, image, raw=None, contrast=160):
        raw = image.tobytes() if raw is None else raw
        with self.condition:
            if self.closed:
                return
            if raw == self.raw and contrast == self.contrast:
                return  # Keep reconnect worker alive; no duplicate Pillow copy/I2C write.
            self.raw = raw
            self.contrast = contrast
            self.latest = image.copy()
            self.generation += 1
            if self.background and self.thread is None:
                self.thread = threading.Thread(target=self._run, name='oled-i2c', daemon=True)
                self.thread.start()
            self.condition.notify()

    def _attempt(self):
        with self.condition:
            if self.closed or self.latest is None:
                return False
            if self.device is None and self.clock() < self.retry_at:
                return False
            if self.device is not None and self.sent == self.generation:
                return False
        # All driver calls run OUTSIDE the condition protecting the latest slot.
        try:
            if self.device is None:
                self.device = self.factory()
                if self.device is None:
                    raise OSError('SSD1306 unavailable')
            with self.condition:
                if self.closed:
                    return False
                image, generation = self.latest, self.generation
                contrast = self.contrast
            if self.applied_contrast != contrast and callable(getattr(self.device,'contrast',None)):
                self.device.contrast(contrast)
                self.applied_contrast = contrast
            self.device.display(image)
            with self.condition:
                self.sent, self.state = generation, 'connected'
        except Exception:
            # Keep the failed object alive until OUTSIDE the condition: driver
            # finalizers may themselves access I2C or block during cleanup.
            failed_device,self.device = self.device,None
            self.applied_contrast = None
            with self.condition:
                self.state = 'disconnected'
                self.retry_at = self.clock() + 30
            self._release(failed_device)
        return True

    @staticmethod
    def _release(device):
        release=getattr(device,'_portable_release',None)
        if callable(release):
            try:release()
            except Exception:pass

    def _run(self):
        try:
            while True:
                if not self._attempt():
                    with self.condition:
                        if self.closed:return
                        # New frames wake this wait. A frozen screen also retries.
                        self.condition.wait(timeout=.5)
        finally:
            self._release(self.device);self.device=None

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        # Do not wait on a blocked I2C call or blank a screen owned by the menu.
        if self.thread is not None:
            self.thread.join(timeout=.1)
        elif not self.background:
            self._release(self.device);self.device=None


def prepare_frame(image, values):
    if values['oled_rotation']=='180':
        from PIL import Image
        return image.transpose(Image.Transpose.ROTATE_180)
    return image


class MirrorDevice:
    mode, size = '1', (128, 64)

    def __init__(self, source, path=None, factory=None, clock=time.monotonic, background=True):
        self.source, self.path = source, path or FRAME
        self.clock = clock
        self.output = PhysicalOutput(factory or physical_device, clock, background)
        self.published = float('-inf')
        self.context = {}
        self.reported_physical = None
        self.last_id = None
        self.render_ms = 0
        self.navigation_at = None
        self.navigation_latency = None
        self.navigation_event = None
        self.publish_ms = 0
        self.pixel_raw = None
        self.pixel_id = None
        self.encoded_pixels = None

    def set_context(self, **values):
        self.context = values

    @property
    def physical(self):
        return self.output.state

    def close(self):
        self.output.close()

    def publish(self, image, force=False, raw=None):
        now = self.clock()
        physical = self.physical
        control = {key: value for key, value in self.context.items() if key != 'remaining'}
        control_id = hashlib.sha256((self.source + json.dumps(control, sort_keys=True)).encode()).hexdigest()
        if not force and control_id == getattr(self,'last_control',None) and physical == self.reported_physical and now - self.published < .25:
            return
        raw = image.tobytes() if raw is None else raw
        identity = hashlib.sha256(raw + json.dumps(self.context, sort_keys=True).encode() + self.source.encode()).hexdigest()
        if not force and identity == self.last_id and physical == self.reported_physical and now - self.published < 1:
            return  # A 1s producer heartbeat keeps stale detection, without 4 identical writes/s.
        if raw != self.pixel_raw:
            self.pixel_raw = raw
            self.pixel_id = hashlib.sha256(raw).hexdigest()
            self.encoded_pixels = base64.b64encode(raw).decode()
        data = {'width': 128, 'height': 64, 'format': '1bpp-msb', 'pixels': self.encoded_pixels, 'pixel_id': self.pixel_id,
                'id': identity, 'control_id': control_id, 'source': self.source, 'context': self.context, 'physical': physical,
                'monotonic': now, 'updated_at': time.time(),
                'timing':{'render_ms':round(self.render_ms,2),'previous_publish_ms':round(self.publish_ms,2),
                          'navigation_ms':self.navigation_latency}}
        if self.navigation_at!=self.navigation_event:
            self.navigation_latency=round(max(0,now-self.navigation_at)*1000,2) if self.navigation_at is not None else None
            self.navigation_event=self.navigation_at
            data['timing']['navigation_ms']=self.navigation_latency
        started = time.perf_counter()
        private_directory(self.path.parent)
        temporary = self.path.with_name(f'.frame-{os.getpid()}.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, separators=(',', ':'))
        os.replace(temporary, self.path)
        self.published, self.last_id = now, identity
        self.last_control = control_id
        self.reported_physical = physical
        self.publish_ms = (time.perf_counter()-started)*1000

    def display(self, image):
        if image.size != self.size or image.mode != self.mode:
            raise ValueError('Framebuffer OLED attendu : 128×64 monochrome.')
        values=READER.get()
        image=prepare_frame(image,values)
        raw = image.tobytes()
        self.publish(image, raw=raw)
        self.output.offer(image, raw=raw, contrast=values['oled_contrast'])  # Bounded, non-blocking.

    def refresh(self):
        # Status producer heartbeat / physical state without redrawing Pillow.
        if self.output.latest is not None:
            self.publish(self.output.latest, raw=self.output.raw)


@contextlib.contextmanager
def canvas(device):
    # Same Pillow drawing path as luma.canvas; no font or layout is recreated.
    from PIL import Image, ImageDraw
    started = time.perf_counter()
    image = Image.new(device.mode, device.size)
    yield ImageDraw.Draw(image)
    device.render_ms = (time.perf_counter()-started)*1000
    device.display(image)


class LogicalButton:
    """Physical input, leased session-owned holds and legacy short pulses.

    Gesture tokens retain their origin. A slow draw/scheduler can NEVER turn a
    virtual click into a physical hold, even if the real button is pressed too.
    """
    def __init__(self, clock=time.monotonic, frame_reader=read_frame):
        self.clock, self.frame_reader = clock, frame_reader
        self.lock = threading.Lock()
        self.pending = None
        self.origin = 'physical'
        self.until = 0
        self.last_poll = float('-inf')
        self.last_short = float('-inf')
        self.physical = False
        self.release_barrier = False
        self.hold = None
        self.physical_cancelled = False
        self.heartbeat = None
        self.last_heartbeat = float('-inf')
        self.early = OrderedDict()
        self.gesture_token = None
        self.last_rpc_ms = 0
        self.input_status = None
        self.context_guard = None

    def publish_heartbeat(self):
        if self.heartbeat is None or self.clock() - self.last_heartbeat < .2:
            return
        private_directory(self.heartbeat.parent)
        temporary = self.heartbeat.with_name('.button-' + str(os.getpid()))
        fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | getattr(os,'O_NOFOLLOW',0), 0o600)
        with os.fdopen(fd, 'w') as file:
            json.dump({'monotonic': self.clock(), 'pid':os.getpid(),
                       'poll_age_ms':round((self.clock()-self.last_poll)*1000,1) if self.last_poll!=float('-inf') else None,
                       'rpc_ms':round(self.last_rpc_ms,2),
                       **({'input':self.input_status()} if self.input_status else {})}, file)
        os.replace(temporary, self.heartbeat)
        self.last_heartbeat = self.clock()

    def start(self):
        if self.origin == 'remote' and self.hold:
            token = (self.hold['started'], 'remote', self.hold['id'])
        else:
            token = (self.clock(), self.origin)
        self.gesture_token = token
        return token

    def duration(self, token):
        if token[1] == 'remote':
            with self.lock:
                self._expire()
                hold = self.hold
                if not hold or token[2] != hold['id'] or hold['cancelled']:
                    return 0
                return max(.01, (hold['stopped'] if hold['stopped'] is not None else self.clock()) - hold['started'])
        if token[1] == 'physical' and self.physical_cancelled:
            return 0
        return .10 if token[1] == 'virtual' else max(0, self.clock() - token[0])

    def cancelled(self, token):
        if token[1] == 'remote':
            self.duration(token)
            return not self.hold or self.hold['id'] != token[2] or self.hold['cancelled']
        return token[1] == 'physical' and self.physical_cancelled

    def _expire(self):
        if self.hold and self.hold['stopped'] is None and self.clock() > self.hold['lease']:
            self.hold['cancelled'] = True
            self.hold['stopped'] = self.clock()

    def sensitive(self, action):
        token = self.gesture_token
        origin = token[1] if token else self.origin
        if origin == 'remote':
            try:
                control_id = self.frame_reader().get('control_id')
            except OledError:
                return False
        else:
            control_id = None
        with self.lock:
            self._expire()
            if origin == 'physical':
                return not self.physical_cancelled
            hold = self.hold
            return bool(origin == 'remote' and token and hold and token[2] == hold['id'] and not hold['cancelled'] and
                        hold['control_id'] == control_id and
                        hold['permit'] == action and self.clock() <= hold['lease'] and
                        (hold['stopped'] is None or self.clock() - hold['stopped'] <= 1))

    def remote(self, data):
        action, owner, gesture = data.get('action'), data.get('owner'), data.get('gesture_id')
        if not valid_id(owner) or not isinstance(gesture, str) or len(gesture) != 32 or any(c not in '0123456789abcdef' for c in gesture):
            raise OledError('Session ou geste invalide.', 400)
        expected = {'action', 'owner', 'gesture_id', 'control_id', 'permit'} if action == 'start' else {'action', 'owner', 'gesture_id'}
        if set(data) != expected or action not in ('start', 'keep', 'stop', 'cancel'):
            raise OledError('Événement de bouton invalide.', 400)
        # File reads are outside the input lock, so a slow reader cannot stall polling.
        frame = self.frame_reader() if action == 'start' else None
        if action == 'start' and self.context_guard and not self.context_guard(frame):
            raise OledError('Navigation en cours d’actualisation. Réessayer.',409)
        with self.lock:
            self._expire()
            now, hold = self.clock(), self.hold
            for key in list(self.early):
                if now - self.early[key][1] > 2:
                    self.early.pop(key)
            if action == 'start':
                if (self.physical or self.pending or self.until or
                        (hold and (hold['stopped'] is None or not hold['released'] or now - hold['stopped'] <
                                   (.04 if hold['owner']==owner and hold['control_id']==data['control_id'] else .15)))):
                    raise OledError('Le bouton est occupé.', 409)
                if frame.get('control_id') != data['control_id']:
                    raise OledError('Le menu a changé. Réessayer sur le nouvel écran.', 409)
                permit = data['permit']
                context = frame.get('context', {})
                allowed = ('power' if (context.get('screen') == 'menu' and context.get('selection') == 0) or context.get('screen') == 'rescue-power' else
                           'network' if context.get('screen') == 'rescue' else
                           'delete' if context.get('screen') == 'iso-confirm' else '')
                if context.get('ui_version')==2:
                    allowed={'power-confirm':'power','network-confirm':'network'}.get(context.get('screen'),'')
                if permit not in ('', allowed):
                    raise OledError('Autorisation incompatible avec cet écran.', 403)
                self.hold = {'id': gesture, 'owner': owner, 'started': now, 'stopped': None,
                             'lease': now + .8, 'cancelled': False, 'consumed': False, 'released': False,
                             'permit': permit, 'control_id':data['control_id']}
                early = self.early.pop((owner, gesture), None)
                if early:
                    self.hold['stopped'] = now
                    self.hold['cancelled'] = early[0] == 'cancel'
                    self.hold['permit'] = ''  # Out-of-order input can only become a short or cancel.
            else:
                if hold and hold['id'] == gesture and hold['owner'] != owner:
                    raise OledError('Ce geste appartient à une autre session.', 403)
                if not hold or hold['id'] != gesture or hold['owner'] != owner:
                    if action in ('stop','cancel'):
                        self.early[(owner,gesture)] = (action,now)
                        while len(self.early) > 64:
                            self.early.popitem(last=False)
                        return {'accepted': True, 'action': action, 'gesture_id': gesture}
                    raise OledError('Geste inconnu pour cette session.', 409)
                if action == 'cancel':
                    hold['cancelled'] = True
                    if hold['stopped'] is None: hold['stopped'] = now
                elif action == 'stop':
                    if hold['stopped'] is None: hold['stopped'] = now
                elif not hold['cancelled'] and hold['stopped'] is None:
                    hold['lease'] = now + .8
                else:
                    raise OledError('Le maintien est terminé.', 409)
            return {'accepted': True, 'action': action, 'gesture_id': gesture}

    def require_physical(self):
        if self.origin != 'physical' or self.physical_cancelled:
            raise OledError('Cette action exige un appui physique long.', 403)

    def submit(self, frame_id):
        frame = self.frame_reader()
        now = self.clock()
        with self.lock:
            if self.physical or now - self.last_poll > 2:
                raise OledError('Bouton physique occupé ou gestionnaire indisponible.', 409)
            if self.pending or (self.hold and not self.hold['released']) or now - self.last_short < .7:
                raise OledError('Un appui est déjà en cours. Réessayer après actualisation.', 429)
            if frame['id'] != frame_id:
                raise OledError('L’écran a changé. Actualiser avant de cliquer.', 409)
            event = {'id': frame_id, 'expires': now + 1, 'done': threading.Event(), 'error': None}
            self.pending = event
        if not event['done'].wait(1.2):
            with self.lock:
                if self.pending is event:
                    self.pending = None
            raise OledError('Appui non consommé par le gestionnaire.', 503)
        if event['error']:
            raise event['error']
        return {'accepted': True, 'action': 'short'}

    def poll(self, physical):
        now = self.clock()
        target = self.hold
        control = None
        if target and not target['consumed']:
            try:
                control = self.frame_reader().get('control_id')
            except OledError:
                pass
        with self.lock:
            self._expire()
            if physical is None and self.origin == 'physical':
                self.physical_cancelled = True
                self.release_barrier = True
            self.physical, self.last_poll = bool(physical), now
            if self.hold and not self.hold['released']:
                hold = self.hold
                if physical:
                    hold['cancelled'] = True
                    hold['stopped'] = now
                    self.release_barrier = True
                self.origin = 'remote'
                if hold['cancelled']:
                    hold['released'] = True
                    return False
                if not hold['consumed']:
                    # A gesture queued across a renderer handoff must never be
                    # applied to a different menu. Keep renewals remain independent.
                    if target is not hold or control is None:
                        return False
                    if control != hold['control_id']:
                        hold['cancelled'] = True; hold['released'] = True
                        return False
                    hold['consumed'] = True
                    return True  # Even a fast press/release is observed exactly once.
                if hold['stopped'] is None:
                    return True
                hold['released'] = True
                return False
            if self.until:
                # Never merge an overlapping physical press with a virtual pulse.
                if physical:
                    self.release_barrier = True
                if now < self.until:
                    return True
                self.until = 0
                return False
            if self.release_barrier:
                if physical is False:
                    self.release_barrier = False
                return False
            if self.pending:
                event, self.pending = self.pending, None
                try:
                    if physical or now > event['expires'] or self.frame_reader()['id'] != event['id']:
                        raise OledError('Appui refusé : état OLED ou bouton modifié.', 409)
                    self.origin, self.until, self.last_short = 'virtual', now + .10, now
                except OledError as error:
                    event['error'] = error
                event['done'].set()
                if not event['error']:
                    return True
            if physical:
                self.origin = 'physical'
                self.physical_cancelled = False
            return bool(physical)

    @contextlib.contextmanager
    def listen(self, path=None, allowed_uid=0):
        path = path or SOCKET
        private_directory(path.parent)
        if path.exists():
            if not stat.S_ISSOCK(path.lstat().st_mode):
                raise OledError('Point de contrôle OLED invalide.')
            with socket.socket(socket.AF_UNIX) as probe:
                try:
                    probe.connect(str(path))
                except ConnectionRefusedError:
                    path.unlink()
                else:
                    raise OledError('Un gestionnaire OLED écoute déjà.')
        button = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    started = time.perf_counter()
                    self.request.settimeout(2)
                    authorize_local(self.request, allowed_uid)
                    data = receive_json(self.request, 1024)
                    if data == {'action': 'ping'}:
                        result = {'ok': True, 'result': {'ready': button.clock() - button.last_poll <= 2}}
                    elif isinstance(data, dict) and data.get('action') in ('start', 'keep', 'stop', 'cancel'):
                        result = {'ok': True, 'result': button.remote(data)}
                    elif not isinstance(data, dict) or set(data) != {'action', 'frame_id'} or data['action'] != 'short' or not valid_id(data['frame_id']):
                        raise OledError('Seul un appui court logique est autorisé.', 400)
                    else:
                        result = {'ok': True, 'result': button.submit(data['frame_id'])}
                    button.last_rpc_ms = (time.perf_counter()-started)*1000
                except OledError as error:
                    result = {'ok': False, 'error': str(error), 'status': error.status}
                except (OSError, ValueError, TypeError):
                    result = {'ok': False, 'error': 'Requête OLED invalide.', 'status': 400}
                try:
                    self.request.sendall(json.dumps(result).encode() + b'\n')
                except OSError:
                    pass

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
        with Server(str(path), Handler) as server:
            os.chmod(path, 0o600)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            heartbeat_stop = threading.Event()
            def heartbeat():
                while not heartbeat_stop.is_set():
                    try:
                        button.publish_heartbeat()
                    except OSError:
                        pass  # Temporary publication error must not kill control health.
                    heartbeat_stop.wait(.1)
            health = threading.Thread(target=heartbeat, name='oled-control-health', daemon=True)
            health.start()
            try:
                yield
            finally:
                heartbeat_stop.set(); health.join(timeout=1)
                server.shutdown(); thread.join(timeout=2)
                path.unlink(missing_ok=True)


def valid_id(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def request_short(frame_id, path=None):
    if not valid_id(frame_id):
        raise OledError('Identifiant de frame invalide.', 400)
    return local_request({'action': 'short', 'frame_id': frame_id}, path)


def ping(path=None):
    return local_request({'action': 'ping'}, path)


def request_event(data, path=None):
    return local_request(data, path)


def local_request(payload, path=None):
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(2)
            connection.connect(str(path or SOCKET))
            connection.sendall(json.dumps(payload).encode() + b'\n')
            data = receive_json(connection, 4096)
        if data.get('ok') is not True:
            raise OledError(data.get('error', 'Appui OLED refusé.'), data.get('status', 503))
        return data['result']
    except OledError:
        raise
    except (OSError, ValueError):
        raise OledError('Gestionnaire du bouton OLED indisponible ; aucun appui rejoué.') from None
