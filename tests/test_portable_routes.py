"""Real localhost nginx routing/auth regression. Never contacts a PiKVM."""
import contextlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from test_pikvm_share_nginx import NginxFixture, NGINX_BINARY, ROOT


@unittest.skipUnless(NGINX_BINARY, 'nginx unavailable')
class RoutingTests(unittest.TestCase):
    def test_main_legacy_native_routes_and_auth_with_portable_service_absent(self):
        class Auth(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200 if self.headers.get('Cookie') == 'session=valid' else 401)
                self.end_headers()

        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            backend = ThreadingHTTPServer(('127.0.0.1', 0), Auth)
            threading.Thread(target=backend.serve_forever, daemon=True).start()
            stack.callback(backend.server_close)
            stack.callback(backend.shutdown)
            fixture = NginxFixture(Path(directory))
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            web = (ROOT / 'web').as_posix()
            extra = fixture.extras.parent / 'portable-os'
            extra.mkdir()
            for source in (ROOT / 'kvmd-extras/portable-os').glob('*.conf'):
                text = source.read_text().replace('/etc/kvmd/nginx/', fixture.prefix.as_posix() + '/')
                text = text.replace('/usr/share/kvmd/extras/portable-os/', extra.as_posix() + '/')
                text = text.replace('root /usr/share/kvmd/web;', f'root "{web}";')
                (extra / source.name).write_text(text)
            native = fixture.prefix / 'kvmd.ctx-server.conf'
            native.write_text('absolute_redirect off;\n' + native.read_text() + '''
location /kvm/ { default_type text/plain; alias "NATIVE_ROOT/"; include loc-login.conf; }
location /api/ { proxy_pass http://kvmd/; auth_request off; }
location /share/ { auth_request off; alias "NATIVE_ROOT/"; }
'''.replace('NATIVE_ROOT', fixture.root.as_posix()).replace('include loc-login.conf;', f'include "{fixture.prefix.as_posix()}/loc-login.conf";'))
            (fixture.root / 'index.html').write_text('native KVM untouched')
            (fixture.root / 'asset.js').write_text('native asset')
            text = fixture.rendered.replace('127.0.0.1:18088', f'127.0.0.1:{port}')
            text = text.replace('127.0.0.1:9980', f'127.0.0.1:{backend.server_port}')
            for context in ('http', 'server'):
                old = f'include "{fixture.extras.parent.as_posix()}/*/nginx.ctx-{context}.conf";'
                text = text.replace(old, '\n'.join(f'include "{path.as_posix()}/nginx.ctx-{context}.conf";'
                                                  for path in (fixture.extras, extra)))
            fixture.config.write_text(text)
            args = [str(NGINX_BINARY), '-p', fixture.prefix.as_posix() + '/', '-c', str(fixture.config),
                    '-g', f'pid "{fixture.root.as_posix()}/nginx.pid"; error_log stderr;']
            check = subprocess.run([*args, '-t'], capture_output=True, text=True, timeout=10)
            self.assertEqual(check.returncode, 0, check.stderr)
            # A foreground master with a private PID file, loopback ports only.
            process = subprocess.Popen([*args[:-1], args[-1] + ' daemon off;'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            def request(path, authenticated=False):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                try:
                    connection.request('GET', path, headers={'Cookie': 'session=valid'} if authenticated else {})
                    response = connection.getresponse()
                    return response.status, response.getheader('Location'), response.read()
                finally:
                    connection.close()
            try:
                for _ in range(40):
                    try:
                        request('/'); break
                    except OSError:
                        time.sleep(.1)
                self.assertEqual(request('/')[:2], (302, '/extras/portable-os/'))
                self.assertEqual(request('/legacy')[:2], (302, '/legacy/'))
                for path in ('/legacy/', '/extras/portable-os/', '/kvm/'):
                    code, location, _ = request(path)
                    self.assertEqual(code, 302, path)
                    self.assertTrue(location.endswith('/login'), (path, location))
                    self.assertEqual(request(path, True)[0], 200, path)
                self.assertIn(b'Interface de secours', request('/legacy/', True)[2])
                self.assertIn(b'native KVM untouched', request('/kvm/', True)[2])
                self.assertEqual(request('/api/auth/check')[0], 401)
                self.assertEqual(request('/extras/portable-os/api/status')[0], 401)
                self.assertEqual(request('/api/auth/check', True)[0], 200)
                self.assertEqual(request('/share/asset.js')[0], 200)
                self.assertEqual(request('/legacy/main.js', True)[0], 200)
                for tool in ('pikvm-share', 'image-manager', 'wifi-wizard'):
                    self.assertEqual(request('/extras/' + tool + '/', True)[0], 302)
                    self.assertNotEqual(request('/extras/' + tool + '/?legacy=1', True)[0], 302)
            finally:
                subprocess.run([*args, '-s', 'quit'], capture_output=True, timeout=10)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate(); process.wait(timeout=5)
                process.stderr.close()
