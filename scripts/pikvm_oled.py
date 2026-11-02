"""Shared OLED framebuffer and short logical input. No GPIO or shell operations."""
import base64
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

RUNTIME = Path('/run/pikvm-oled')
FRAME = RUNTIME / 'frame.json'
SOCKET = RUNTIME / 'button.sock'
MAX_AGE = 15


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
    return ssd1306(i2c(port=1, address=0x3C), width=128, height=64)


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
        self.generation = 0
        self.sent = 0
        self.retry_at = 0
        self.state = 'disconnected'
        self.closed = False
        self.thread = None

    def offer(self, image):
        with self.condition:
            if self.closed:
                return
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
            self.device.display(image)
            with self.condition:
                self.sent, self.state = generation, 'connected'
        except Exception:
            # Keep the failed object alive until OUTSIDE the condition: driver
            # finalizers may themselves access I2C or block during cleanup.
            failed_device = self.device
            self.device = None
            with self.condition:
                self.state = 'disconnected'
                self.retry_at = self.clock() + 30
            del failed_device
        return True

    def _run(self):
        while True:
            if not self._attempt():
                with self.condition:
                    if self.closed:
                        return
                    # New frames wake this wait. A frozen screen also retries.
                    self.condition.wait(timeout=.5)

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        # Do not wait on a blocked I2C call or blank a screen owned by the menu.
        if self.thread is not None:
            self.thread.join(timeout=.1)


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

    def set_context(self, **values):
        self.context = values

    @property
    def physical(self):
        return self.output.state

    def close(self):
        self.output.close()

    def publish(self, image, force=False):
        now = self.clock()
        physical = self.physical
        if not force and physical == self.reported_physical and now - self.published < .25:
            return
        raw = image.tobytes()
        identity = hashlib.sha256(raw + json.dumps(self.context, sort_keys=True).encode() + self.source.encode()).hexdigest()
        data = {'width': 128, 'height': 64, 'format': '1bpp-msb', 'pixels': base64.b64encode(raw).decode(),
                'id': identity, 'source': self.source, 'context': self.context, 'physical': physical,
                'monotonic': now, 'updated_at': time.time()}
        private_directory(self.path.parent)
        temporary = self.path.with_name(f'.frame-{os.getpid()}.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, separators=(',', ':'))
        os.replace(temporary, self.path)
        self.published, self.last_id = now, identity
        self.reported_physical = physical

    def display(self, image):
        if image.size != self.size or image.mode != self.mode:
            raise ValueError('Framebuffer OLED attendu : 128×64 monochrome.')
        self.publish(image)
        self.output.offer(image)  # Non-blocking, bounded latest-frame slot.


@contextlib.contextmanager
def canvas(device):
    # Same Pillow drawing path as luma.canvas; no font or layout is recreated.
    from PIL import Image, ImageDraw
    image = Image.new(device.mode, device.size)
    yield ImageDraw.Draw(image)
    device.display(image)


class LogicalButton:
    """Single bounded short pulse, consumed by the existing physical menu loops.

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

    def start(self):
        return (self.clock(), self.origin)

    def duration(self, token):
        return .10 if token[1] == 'virtual' else max(0, self.clock() - token[0])

    def require_physical(self):
        if self.origin == 'virtual':
            raise OledError('Cette action exige un appui physique long.', 403)

    def submit(self, frame_id):
        now = self.clock()
        with self.lock:
            if self.physical or now - self.last_poll > 2:
                raise OledError('Bouton physique occupé ou gestionnaire indisponible.', 409)
            if self.pending or now - self.last_short < .7:
                raise OledError('Un appui est déjà en cours. Réessayer après actualisation.', 429)
            if self.frame_reader()['id'] != frame_id:
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
        with self.lock:
            self.physical, self.last_poll = bool(physical), now
            if self.until:
                # Never merge an overlapping physical press with a virtual pulse.
                if physical:
                    self.release_barrier = True
                if now < self.until:
                    return True
                self.until = 0
                return False
            if self.release_barrier:
                if not physical:
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
                    self.request.settimeout(2)
                    authorize_local(self.request, allowed_uid)
                    data = receive_json(self.request, 1024)
                    if data == {'action': 'ping'}:
                        result = {'ok': True, 'result': {'ready': button.clock() - button.last_poll <= 2}}
                    elif not isinstance(data, dict) or set(data) != {'action', 'frame_id'} or data['action'] != 'short' or not valid_id(data['frame_id']):
                        raise OledError('Seul un appui court logique est autorisé.', 400)
                    else:
                        result = {'ok': True, 'result': button.submit(data['frame_id'])}
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
            try:
                yield
            finally:
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
