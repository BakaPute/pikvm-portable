"""Read-only USB observation and durable, non-destructive ISO import primitives.

No GPIO, gadget writes, mounts or subprocesses here. Writers must hold the common
MSD lock and have exclusive ownership of a read-only source mount.
"""
import contextlib
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import stat
import time
import uuid

ROOT = Path('/var/lib/kvmd/msd')
IMAGE = ROOT / '.USB-TRANSFER.img'
STATE = Path('/run/pikvm-usb-transfer-state.json')
LOCK = Path('/run/pikvm-usb-transfer.lock')
STORAGE_LOCK = Path('/run/pikvm-image-folders.lock')
GADGET = Path('/sys/kernel/config/usb_gadget/kvmd')
JOURNAL = ROOT / '.pikvm-transfer-journal.json'
SHARE_LEASE = Path('/run/pikvm-share/lease.json')
POWER_MARKER = Path('/run/pikvm-poweroff-requested')
ACTIVE = {'starting', 'stopping', 'importing', 'preparing'}
MAX_ENTRIES = 512
LOCK_FDS = set()


def read_json(path):
    with path.open('rb') as handle:
        raw = handle.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Journal trop volumineux')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Objet JSON attendu')
    return value


def fsync_dir(path):
    # Windows fixtures cannot fsync directories. Production is Linux only.
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_json(path, data, durable=False):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            if durable:
                os.fsync(handle.fileno())
        temporary.replace(path)
        if durable:
            fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def busy(path=LOCK):
    import fcntl
    try:
        with path.open('rb') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except FileNotFoundError:
        return False
    return False


@contextlib.contextmanager
def exclusive(path):
    import fcntl
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Une opération de stockage est déjà en cours') from None
        LOCK_FDS.add(handle.fileno())
        try:
            yield handle.fileno()
        finally:
            LOCK_FDS.discard(handle.fileno())


def observe():
    """Never wait for a writer, launch Python/KVMD helpers, or trust cached media."""
    errors = []
    try:
        data = read_json(STATE)
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as exc:
        data = {}
        errors.append('État temporaire illisible : ' + str(exc))
    drive = {'known': False, 'image': None, 'transfer_active': False,
             'usb_connected': None, 'cdrom': None, 'rw': None}
    try:
        lun = GADGET / 'functions/mass_storage.usb0/lun.0'
        image = (lun / 'file').read_text().strip()
        cdrom, ro = [(lun / name).read_text().strip() for name in ('cdrom', 'ro')]
        if cdrom not in ('0', '1') or ro not in ('0', '1'):
            raise ValueError('Configuration LUN invalide')
        drive.update(known=True, image=image, cdrom=cdrom == '1', rw=ro == '0',
                     usb_connected=bool((GADGET / 'UDC').read_text().strip()),
                     transfer_active=bool(image) and os.path.normpath(image) == str(IMAGE))
    except (OSError, ValueError) as exc:
        errors.append('État matériel inconnu : ' + str(exc))
    try:
        running = busy(LOCK)
    except OSError as exc:
        running = None
        errors.append('Verrou illisible : ' + str(exc))
    old = data.get('state')
    if not drive['known'] or running is None:
        state, message = 'unknown', 'État USB inconnu ; gestion refusée'
    elif running:
        state = old if old in ACTIVE else 'starting'
        message = data.get('message', 'Opération de stockage en cours')
    elif drive['transfer_active']:
        state, message = 'connected', 'PIKVM-XFER attaché au PC'
    elif old in ACTIVE:
        state, message = 'interrupted', 'Opération interrompue ; reprendre l’import sans effacer la source'
    elif old in ('done', 'error', 'interrupted'):
        state, message = old, data.get('message', '')
    else:
        state, message = 'ready', 'Drive 0 déconnecté' if not drive['image'] else 'Autre image attachée au Drive 0'
    try:
        image_stat = IMAGE.stat()
        stats = dict(exists=True, virtual_bytes=image_stat.st_size,
                     used_bytes=getattr(image_stat, 'st_blocks', 0) * 512)
    except FileNotFoundError:
        stats = dict(exists=False, virtual_bytes=0, used_bytes=0)
    except OSError as exc:
        stats = dict(exists=None)
        errors.append(str(exc))
    if not data and drive['known'] and not running and not drive['transfer_active']:
        try:
            journal = read_json(JOURNAL)
            if journal.get('stage') != 'done':
                state, message = 'interrupted', 'Import interrompu ; journal durable disponible dans diagnose'
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as exc:
            errors.append('Journal de reprise illisible : ' + str(exc))
            state, message = 'error', 'Journal de reprise à examiner ; aucune donnée effacée'
    return {**data, **stats, 'state': state, 'message': message, 'drive': drive,
            'busy': running, 'poweroff_pending': POWER_MARKER.exists(),
            'observed_at': time.time(), 'errors': errors}


def ordinary(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RuntimeError('Fichier non ordinaire ou lien symbolique : ' + path.name)


def require_idle_for_power():
    """Last backend guard, independent of stale browser/OLED observations."""
    data = observe()
    if data['state'] == 'unknown' or data['busy'] or SHARE_LEASE.exists() or POWER_MARKER.exists():
        raise RuntimeError('Arrêt/redémarrage refusé : stockage actif ou état inconnu')
    for index in (0, 1):
        file = GADGET / f'functions/mass_storage.usb{index}/lun.0/file'
        if file.read_text().strip():
            raise RuntimeError('Éjecter proprement les deux lecteurs avant arrêt/redémarrage')
    for base, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'lost+found']
        if any(n.startswith('.__') and n.endswith('.incomplete') for n in files):
            raise RuntimeError('Upload natif incomplet/en cours ; arrêt refusé')


def reserve_poweroff():
    # Shares the admission lock with XFER/folders; once queued, a new custom
    # storage operation cannot start during the existing delayed poweroff path.
    with exclusive(STORAGE_LOCK):
        require_idle_for_power()
        atomic_json(POWER_MARKER, {'requested_at': time.time(), 'reason': 'explicit-poweroff'})


def require_not_stopping():
    if POWER_MARKER.exists():
        raise RuntimeError('Arrêt demandé ; nouvelles opérations de stockage refusées')


def digest(path):
    ordinary(path)
    result = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def source_chunks(path):
    """Bound XZ dictionary memory as well as decompressed output buffers."""
    with path.open('rb') as source:
        if not path.name.lower().endswith('.xz'):
            while chunk := source.read(1024 * 1024):
                yield chunk
            return
        decoder = lzma.LZMADecompressor(memlimit=32 * 1024 * 1024)
        while True:
            raw = source.read(256 * 1024) if decoder.needs_input else b''
            if not raw and decoder.needs_input:
                raise RuntimeError('Archive XZ tronquée')
            chunk = decoder.decompress(raw, max_length=1024 * 1024)
            if chunk:
                yield chunk
            if decoder.eof:
                if decoder.unused_data or source.read(1):
                    raise RuntimeError('Archive XZ concaténée ou données supplémentaires non prises en charge')
                return


class ImportJournal:
    """One bounded current operation; no per-chunk flash journal writes.

    Crashes before publication keep .part; after link publication either name is
    sufficient for recovery. Existing output is never replaced or truncated.
    """
    def __init__(self, root=ROOT):
        self.root = root
        self.path = root / JOURNAL.name
        try:
            self.data = read_json(self.path)
        except FileNotFoundError:
            self.data = {'version': 1, 'operation': uuid.uuid4().hex, 'files': {}}
        if self.data.get('version') != 1 or not isinstance(self.data.get('files'), dict):
            raise RuntimeError('Journal incompatible : conserver les données et examiner le diagnostic')

    def save(self, stage, **extra):
        self.data.update(stage=stage, updated_at=time.time(), **extra)
        atomic_json(self.path, self.data, durable=True)

    def copy(self, source, target, progress=lambda *_: None):
        ordinary(source)
        if target.parent != self.root or target.name.startswith('.'):
            raise RuntimeError('Destination d’import invalide')
        source_stat = source.stat()
        identity = [source.name, source_stat.st_size, source_stat.st_mtime_ns]
        entries = self.data['files']
        entry = entries.get(source.name)
        if entry and entry.get('source') != identity:
            raise RuntimeError('Source modifiée depuis l’import précédent : examen requis')
        if entry is None:
            if len(entries) >= MAX_ENTRIES:
                raise RuntimeError('Limite de journal atteinte ; archiver le journal après examen')
            entry = entries[source.name] = {'source': identity, 'target': target.name,
                'temp': '.__usbimport-' + uuid.uuid4().hex + '.part', 'stage': 'planned'}
        if entry.get('target') != target.name:
            raise RuntimeError('Destination du journal incohérente')
        temp_name = entry.get('temp', '')
        if (Path(temp_name).name != temp_name or not temp_name.startswith('.__usbimport-')
                or not temp_name.endswith('.part')):
            raise RuntimeError('Chemin temporaire du journal invalide')
        temporary = self.root / temp_name
        # Source hash means decompressed content for .xz, so independent reread
        # of the destination detects short/corrupt writes and damaged recovery.
        self.save('importing')
        source_hash = hashlib.sha256()
        written = 0
        output_exists = target.exists() or target.is_symlink()
        recover = temporary.exists() or temporary.is_symlink()
        if output_exists:
            ordinary(target)
        if recover:
            ordinary(temporary)
        writer = None
        try:
            if not output_exists and not recover:
                if (not source.name.lower().endswith('.xz') and
                        shutil.disk_usage(self.root).free < source_stat.st_size + 16 * 1024 * 1024):
                    raise RuntimeError('Espace libre insuffisant ; source conservée')
                writer = temporary.open('xb')
            for chunk in source_chunks(source):
                source_hash.update(chunk)
                written += len(chunk)
                if writer:
                    writer.write(chunk)
                progress(written, source_stat.st_size)
            if writer:
                writer.flush()
                os.fsync(writer.fileno())
                writer.close()
                writer = None
            now = source.stat()
            if [source.name, now.st_size, now.st_mtime_ns] != identity:
                raise RuntimeError('La source a changé pendant la lecture')
            candidate = target if output_exists else temporary
            before = candidate.stat()
            expected = source_hash.hexdigest()
            if candidate.stat().st_size != written or digest(candidate) != expected:
                # Preserve partial data, source and any destination. Retry cannot
                # silently overwrite an incomplete file: explicit recovery below.
                entry['stage'] = 'partial_or_conflict'
                self.save('interrupted')
                raise RuntimeError('Copie partielle ou destination différente ; données conservées')
            def signature(info):
                return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
            with candidate.open('r+b' if os.name == 'nt' else 'rb') as handle:
                if signature(os.fstat(handle.fileno())) != signature(before):
                    raise RuntimeError('Destination modifiée pendant la vérification')
                # Required also after recovering an earlier failed fsync/crash.
                os.fsync(handle.fileno())
            if signature(candidate.stat()) != signature(before):
                raise RuntimeError('Destination remplacée pendant la vérification')
            entry.update(stage='verified', sha256=expected, bytes=written)
            self.save('importing')
            if not output_exists:
                # Atomic no-clobber. Unlike replace(), cannot overwrite an ISO
                # created concurrently by native KVMD or another administrator.
                os.link(temporary, target)
                fsync_dir(self.root)
            entry['stage'] = 'published'
            self.save('importing')
            if temporary.exists():
                # Only remove a redundant link to precisely the published inode.
                if os.path.samefile(temporary, target):
                    temporary.unlink()
                    fsync_dir(self.root)
                else:
                    entry['retained_temp'] = True
            entry['stage'] = 'done'
            self.save('importing')
            return target.name
        finally:
            if writer:
                writer.close()

    def recover_partial(self, source_name):
        """Explicitly quarantine a partial copy; never delete unverified bytes."""
        entry = self.data['files'].get(source_name)
        if not entry or entry.get('stage') != 'partial_or_conflict':
            raise RuntimeError('Aucune copie partielle reconnue à mettre de côté')
        name = entry.get('temp', '')
        if Path(name).name != name or not name.startswith('.__usbimport-') or not name.endswith('.part'):
            raise RuntimeError('Chemin temporaire invalide')
        temporary = self.root / name
        ordinary(temporary)
        quarantine = self.root / ('.usbimport-retained-' + uuid.uuid4().hex)
        os.link(temporary, quarantine)
        fsync_dir(self.root)
        temporary.unlink()
        fsync_dir(self.root)
        entry.update(temp='.__usbimport-' + uuid.uuid4().hex + '.part', stage='planned',
                     retained=quarantine.name)
        self.save('interrupted')


def recovery_report(root=ROOT):
    """Inventory only, including old unjournaled files; never auto-clean."""
    try:
        journal = read_json(root / JOURNAL.name)
    except FileNotFoundError:
        journal = None
    pending = []
    for path in root.glob('.__usbimport-*.part'):
        info = path.lstat()
        pending.append({'name': path.name, 'bytes': info.st_size,
                        'links': info.st_nlink, 'ordinary': stat.S_ISREG(info.st_mode)})
    return {'journal': journal, 'temporary_files': pending, 'source_retained': IMAGE.exists()}


def recover_link(root, temporary_name, target_name):
    """Explicit, repeatable removal of a proven redundant name, never its data."""
    if (not isinstance(temporary_name, str) or Path(temporary_name).name != temporary_name
            or not temporary_name.startswith('.__usbimport-') or not temporary_name.endswith('.part')
            or not isinstance(target_name, str) or Path(target_name).name != target_name
            or target_name.startswith('.') or Path(target_name).suffix.lower() not in ('.iso', '.img', '.raw')):
        raise RuntimeError('Noms de récupération invalides')
    temporary, target = root / temporary_name, root / target_name
    ordinary(target)
    if not temporary.exists() and not temporary.is_symlink():
        return 'Lien temporaire déjà absent ; destination conservée'
    ordinary(temporary)
    if not os.path.samefile(temporary, target):
        raise RuntimeError('Inodes différents ; aucun fichier supprimé')
    temporary.unlink()
    fsync_dir(root)
    return 'Lien redondant retiré ; inode et ISO conservés'
