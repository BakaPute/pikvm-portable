"""Parse the opt-in TLS vhost with REAL nginx and disposable TLS keys."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_pikvm_share_nginx import NGINX_BINARY

ROOT=Path(__file__).resolve().parents[1]
OPENSSL=shutil.which('openssl') or ('C:/Program Files/Git/usr/bin/openssl.exe' if Path('C:/Program Files/Git/usr/bin/openssl.exe').exists() else None)
class SecurityNginxTests(unittest.TestCase):
    @unittest.skipUnless(NGINX_BINARY and OPENSSL,'nginx and openssl required')
    def test_opt_in_vhost_tls_websocket_limits_and_credential_stripping(self):
        source=(ROOT/'config/portable-security/nginx.example.conf').read_text()
        self.assertNotIn('portable-security', (ROOT/'kvmd-extras/portable-os/nginx.ctx-server.conf').read_text())
        for text in ('limit_conn portable_security_connections 8','proxy_request_buffering off','proxy_set_header X-Portable-Delegation ""','proxy_set_header Authorization ""','proxy_set_header Origin $http_origin'):
            self.assertIn(text,source)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);key=root/'key.pem';cert=root/'cert.pem'
            subprocess.run([OPENSSL,'req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-keyout',str(key),'-out',str(cert)],check=True,capture_output=True,timeout=20)
            source=source.replace('include /etc/kvmd/nginx/ssl.conf;',f'ssl_certificate "{cert.as_posix()}"; ssl_certificate_key "{key.as_posix()}";')
            (root/'logs').mkdir();(root/'temp').mkdir();config=root/'nginx.conf';config.write_text('pid "'+(root/'nginx.pid').as_posix()+'"; error_log stderr; events {} http { access_log off; '+source+' }',encoding='utf-8')
            result=subprocess.run([str(NGINX_BINARY),'-p',root.as_posix()+'/','-c',config.as_posix(),'-t'],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
