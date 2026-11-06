"""RC13.1 weak/empty Web secrets, canonical glyphs, timer, RAM and TLS SAN."""
import copy,io,json,subprocess,tempfile,unittest,unicodedata
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw,ImageFont
from test_security_rc13 import Fixture,PASSWORD
from test_security_nginx_rc13 import OPENSSL
from test_oled import status
import pikvm_security as security
import pikvm_oled_ui as ui
import pikvm_config as config

class PasswordTests(Fixture):
    def test_short_missing_empty_byte_bound_and_strict(self):
        for value in ('123','admin','test','phrase '+('é'*200)):
            encoded=security.password_hash(value);self.assertTrue(security.password_matches(value,encoded))
        for value in (None,123,'', 'é'*513,'\ud800'):
            with self.assertRaises(security.SecurityError):security.password_hash(value)
        encoded=security.password_hash('',allow_empty=True)
        self.assertTrue(security.password_matches('',encoded));self.assertFalse(security.password_matches(None,encoded))
        with self.assertRaises(security.SecurityError):security.password_hash('',allow_empty=True,strict=True)
    def test_empty_creation_login_reauthentication_revocation_and_policy(self):
        with self.assertRaises(security.SecurityError):self.change('create','empty',password='',role='administrator')
        self.change('create','empty',password='',allow_empty_password=True,role='administrator')
        logins=security.LoginManager(self.store);token=logins.login('empty','','fixture');actor=logins.authenticate(token)
        data={'action':'policy','name':'password-policy','strict':True,'confirmed':True,'expected_revision':self.store.read()['revision']}
        with self.assertRaises(security.SecurityError):self.store.mutate(actor,data)
        self.store.mutate(actor,{**data,'admin_password':''})
        with self.assertRaises(security.SecurityError):self.change('create','weak',password='123')
        self.change('policy','password-policy',strict=False)
        self.change('password','empty',password='test')
        with self.assertRaises(security.SecurityError):logins.authenticate(token)
        token=logins.login('empty','test','fixture');logins.logout(token)
        with self.assertRaises(security.SecurityError):logins.authenticate(token)

class OledTests(unittest.TestCase):
    def test_french_glyph_pixels_and_nfc_match_reference_font(self):
        chars='é è ê ë à â ù û ç ï ô É È À Ç'
        reference=ImageFont.truetype(str(Path(__file__).resolve().parents[1]/'assets/fonts/DejaVuSans.ttf'),11)
        missing=ui.text_mask('\U0010ffff',11).tobytes()
        for char in chars.replace(' ',''):
            box=reference.getbbox(char,mode='1');expected=Image.new('1',(box[2]-box[0],box[3]-box[1]));ImageDraw.Draw(expected).text((-box[0],-box[1]),char,font=reference,fill=255)
            actual=ui.text_mask(char,11);self.assertEqual(actual.tobytes(),expected.tobytes());self.assertNotEqual(actual.tobytes(),missing)
            self.assertEqual(ui.text_mask(unicodedata.normalize('NFD',char),11).tobytes(),actual.tobytes())
    def test_battery_timer_charge_and_estimated_text_do_not_overlap(self):
        for style in ('readable','compact'):
            for seconds in (10,9,8,0,None):
                frame=ui.render_status('battery',{'percent':78,'voltage':4.02,'charging':True},{**config.defaults(),'oled_style':style},seconds)
                texts=[r['text'] for r in frame.text_runs]
                if seconds is not None:self.assertIn(str(seconds)+'s',texts)
                self.assertIn('Charge',texts)
                if style=='readable':self.assertIn('Estimée',texts)
                for i,a in enumerate(frame.text_regions):
                    for b in frame.text_regions[i+1:]:self.assertFalse(max(a[0],b[0])<min(a[2],b[2]) and max(a[1],b[1])<min(a[3],b[3]))
    def test_ram_uses_available_not_free_and_rejects_invalid(self):
        with patch('builtins.open',return_value=io.StringIO('MemTotal: 398472 kB\nMemAvailable: 86440 kB\nMemFree: 10108 kB\n')):
            value=status.memory_info();self.assertEqual(value,{'percent':78,'available_mb':84,'total_mb':389})
        with patch('builtins.open',return_value=io.StringIO('MemTotal: 10 kB\nMemAvailable: 20 kB\n')):self.assertIsNone(status.memory_info()['percent'])
        frame=ui.render_status('system_details',{'ram':78,'available_mb':84,'total_mb':389},config.defaults(),10)
        self.assertTrue({'RAM 78%','84 Mio','389 Mio'}<=set(r['text'] for r in frame.text_runs))

@unittest.skipUnless(OPENSSL,'OpenSSL required')
class TlsTests(unittest.TestCase):
    def test_disposable_certificate_ip_san_accepts_expected_and_rejects_other_ip(self):
        # No trust store, Pi config or production key touched.
        with tempfile.TemporaryDirectory() as d:
            key=Path(d)/'key.pem';cert=Path(d)/'cert.pem';ca=Path(d)/'ca.pem';ca_key=Path(d)/'ca.key';csr=Path(d)/'request.pem'
            def run(args):return subprocess.run([OPENSSL,*args],capture_output=True,text=True,timeout=20)
            template=Path(__file__).resolve().parents[1]/'config/tls/pikvm-server-request.cnf'
            result=run(['req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=Isolated-Test-CA','-addext','basicConstraints=critical,CA:TRUE','-keyout',str(ca_key),'-out',str(ca)])
            self.assertEqual(result.returncode,0,result.stderr)
            result=run(['req','-new','-newkey','rsa:2048','-nodes','-config',str(template),'-keyout',str(key),'-out',str(csr)]);self.assertEqual(result.returncode,0,result.stderr)
            result=run(['x509','-req','-in',str(csr),'-CA',str(ca),'-CAkey',str(ca_key),'-CAcreateserial','-days','2','-extfile',str(template),'-extensions','server_req','-out',str(cert)]);self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(run(['verify','-CAfile',str(ca),'-purpose','sslserver','-verify_ip','192.168.168.99',str(cert)]).returncode,0)
            self.assertNotEqual(run(['verify','-CAfile',str(ca),'-verify_ip','192.168.168.98',str(cert)]).returncode,0)
            self.assertEqual(run(['verify','-CAfile',str(ca),'-verify_hostname','share.pikvm.home.arpa',str(cert)]).returncode,0)
            self.assertNotEqual(run(['verify',str(cert)]).returncode,0)

if __name__=='__main__':unittest.main()
