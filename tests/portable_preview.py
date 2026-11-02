"""Local UI fixture: simulated data only, no PiKVM or system command access."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1] / 'web'
FILES = {'welcome.txt': b'Portable OS local test fixture'}
MODE = 'detached'
UPLOADS = {}


class Preview(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *args):
        pass

    def reply(self, data, status=200):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in ('/', '/legacy'):
            self.send_response(302); self.send_header('Location', '/extras/portable-os/' if url.path == '/' else '/legacy/'); self.end_headers(); return
        if url.path == '/api/info':
            return self.reply({'ok': True, 'result': {'auth': {'enabled': True}, 'extras': {
                'webterm': {'name': 'Web Terminal', 'path': 'extras/webterm', 'place': 1, 'enabled': True},
                'portable': {'name': 'Portable OS', 'path': 'extras/portable-os/', 'place': 5, 'enabled': True},
                'wifi': {'name': 'Wi-Fi Wizard', 'path': 'extras/wifi-wizard', 'place': 10, 'enabled': True},
                'images': {'name': 'Image Manager', 'path': 'extras/image-manager', 'place': 20, 'started': True},
                'share': {'name': 'PIKVM-SHARE', 'path': 'extras/pikvm-share', 'place': 30, 'enabled': True},
                'future': {'name': 'Future extension', 'path': 'extras/future', 'place': 40, 'enabled': True}}}})
        if url.path == '/api/auth/check':
            return self.reply({'ok': True, 'result': {}})
        if url.path == '/api/msd':
            return self.reply({'ok': True, 'result': {'drive': {'connected': False, 'image': None},
                'storage': {'images': {'rescue.iso': {'size': 734003200}}, 'parts': {'': {'size': 32000000000, 'free': 21800000000}}}}})
        if url.path == '/extras/image-manager/api/image-manager/folders':
            return self.reply({'ok': True, 'result': {'folders': []}})
        if '/api/battery' in url.path:
            return self.reply({'ok': True, 'battery': {'percent': 82, 'voltage': 3.94, 'charging': False, 'state': 'battery'}})
        if url.path == '/extras/wifi-wizard/api/status':
            return self.reply({'ok': True, 'status': {'connected': True, 'ssid': 'Atelier', 'ip': '192.168.168.99', 'signal': '-48 dBm'}})
        if url.path in ('/extras/wifi-wizard/api/networks', '/extras/wifi-wizard/api/scan'):
            return self.reply({'ok': True, 'networks': [{'id': 1, 'ssid': 'Atelier', 'priority': 10, 'signal': '-48 dBm', 'security': 'secured'}]})
        if url.path == '/extras/portable-os/api/status':
            return self.reply({'ok': True, 'result': {'test_mode': True, 'system': {'hostname': 'pikvm-portable', 'temperature': 42.8},
                'hotspot': False, 'services': {'available': True, 'items': {name: {'ActiveState': 'inactive' if 'auto-shutdown' in name else 'active',
                'UnitFileState': 'disabled' if 'auto-shutdown' in name else 'enabled'} for name in
                ('kvmd.service', 'kvmd-nginx.service', 'pikvm-share-api.service', 'pikvm-portable-api.service', 'pikvm-auto-shutdown.service')}}}})
        if url.path == '/extras/portable-os/api/usb':
            return self.reply({'ok': True, 'result': {'udc': '20980000.usb', 'state': 'configured', 'host_configured': True,
                'drives': {'1': {'present': True, 'configurations': ['c.1'], 'attached': MODE == 'usb',
                    'attributes': {'file': '/var/lib/kvmd/msd/.PIKVM-SHARE.img' if MODE == 'usb' else '', 'ro': '0', 'cdrom': '0', 'removable': '1'}}}}})
        if url.path == '/extras/pikvm-share/api/status':
            return self.reply({'ok': True, 'result': {'mode': MODE, 'attached': MODE == 'usb', 'uploads': len(UPLOADS)}})
        if url.path == '/extras/pikvm-share/api/files':
            return self.reply({'ok': True, 'result': {'items': [{'name': name, 'directory': value is None,
                'size': len(value or b'')} for name, value in FILES.items()], 'space': {'total': 4294967296, 'used': 1048576, 'free': 4293918720}}})
        if url.path in ('/kvm/', '/extras/webterm/ttyd/'):
            payload = (Path(__file__).parent / 'fixtures/native-kvm.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(payload)))
            self.end_headers(); self.wfile.write(payload); return
        if url.path == '/extras/portable-os/api/logs':
            return self.reply({'ok': True, 'result': {'entries': [{'message': 'Local fixture: no remote journal accessed.'}]}})
        if url.path == '/api/streamer/snapshot':
            self.send_error(404); return
        return super().do_GET()

    def do_POST(self):
        global MODE
        url = urlsplit(self.path)
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if url.path == '/__test/reset' and self.headers.get('X-Portable-Test') == '1':
            MODE = 'detached'
            FILES.clear(); FILES['welcome.txt'] = b'Portable OS local test fixture'; UPLOADS.clear()
            return self.reply({'ok': True})
        data = json.loads(raw or b'{}') if self.headers.get('Content-Type') != 'application/octet-stream' else {}
        action = url.path.removeprefix('/extras/pikvm-share/api/')
        if action == 'mode/web':
            if data.get('ejected') is not True or MODE == 'usb':
                return self.reply({'ok': False, 'error': 'Éjection PC requise (simulation).'}, 409)
            MODE = 'web'
        elif action == 'mode/usb':
            MODE = 'usb'
        elif action == 'recover':
            if MODE == 'usb':
                return self.reply({'ok': False, 'error': 'Lecteur attaché.'}, 409)
            MODE = 'detached'
        elif action in ('create-file', 'mkdir'):
            FILES[data['name']] = b'' if action == 'create-file' else None
        elif action == 'rename':
            FILES[data['name']] = FILES.pop(data['path'])
        elif action == 'delete':
            FILES.pop(data['path'], None)
        elif action == 'upload/begin':
            ident = str(len(UPLOADS) + 1)
            UPLOADS[ident] = {'name': data['name'], 'data': b''}
            return self.reply({'ok': True, 'result': {'id': ident}})
        elif action == 'upload/chunk':
            entry = UPLOADS[parse_qs(url.query)['id'][0]]
            entry['data'] += raw
            return self.reply({'ok': True, 'result': {'offset': len(entry['data'])}})
        elif action == 'upload/finish':
            entry = UPLOADS.pop(data['id']); FILES[entry['name']] = entry['data']
        elif action == 'upload/cancel':
            UPLOADS.pop(data['id'], None)
        else:
            return self.reply({'ok': False, 'error': 'Action non prise en charge par la fixture locale.'}, 404)
        self.reply({'ok': True, 'result': {}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    print(f'Local fixture: http://127.0.0.1:{args.port}/extras/portable-os/ (SIMULATED DATA)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Preview).serve_forever()
