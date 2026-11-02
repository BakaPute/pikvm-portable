"""Additive installer transaction and real nginx coexistence tests."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_pikvm_share_nginx import NginxFixture, NGINX_BINARY

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('portable_install_tests', str(ROOT / 'scripts/pikvm-portable-install'))
spec = importlib.util.spec_from_loader(loader.name, loader)
portable = importlib.util.module_from_spec(spec)
loader.exec_module(portable)


class PortableInstallTests(unittest.TestCase):
    def test_repeated_install_restore_and_failed_install_leave_native_files_untouched(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            h = portable.helper()
            h.BACKUPS = root / 'backups'
            h.NGINX_CONFIG = root / 'nginx.conf'
            h.NGINX_CONFIG.write_bytes(b'original nginx')
            h.SHARE_UNIT = root / 'portable.service'
            h.SHARE_ENABLE_LINK = root / 'wants' / 'portable.service'
            native = root / 'native-kvmd.html'
            native.write_bytes(b'native Python 3.14 and web fixes')
            target = root / 'portable.html'
            state = {'active': False, 'enabled': False}
            def run(args):
                if args[:2] == ['systemctl', 'start']:
                    state['active'] = True
                elif args[:2] == ['systemctl', 'enable']:
                    state.update(active=True, enabled=True)
                elif args[:2] == ['systemctl', 'stop']:
                    state['active'] = False
                return ''
            stack.enter_context(patch.object(h, 'run', side_effect=run))
            stack.enter_context(patch.object(h, 'service_state', side_effect=lambda: dict(state)))
            stack.enter_context(patch.object(h.os, 'chown', create=True))
            stack.enter_context(patch.object(portable, 'policy_preflight', return_value=(b'', False)))
            stack.enter_context(patch.object(portable, 'active', return_value=True))
            stack.enter_context(patch.object(portable, 'wait_ready'))
            stack.enter_context(patch.object(portable, 'file_map', return_value={target: (b'portable app', 0o644)}))
            stack.enter_context(patch('sys.stdout', new_callable=io.StringIO))
            with patch.object(portable, 'nginx_config'):
                portable.install(h)
                first = next(h.BACKUPS.iterdir())
                portable.install(h)
            self.assertEqual(target.read_bytes(), b'portable app')
            self.assertEqual(native.read_bytes(), b'native Python 3.14 and web fixes')
            portable.restore(h, first)
            portable.restore(h, first)
            self.assertFalse(target.exists())
            self.assertEqual(h.NGINX_CONFIG.read_bytes(), b'original nginx')
            with patch.object(portable, 'nginx_config', side_effect=RuntimeError('invalid nginx')):
                with self.assertRaisesRegex(RuntimeError, 'invalid nginx'):
                    portable.install(h)
            self.assertFalse(target.exists())
            self.assertEqual(native.read_bytes(), b'native Python 3.14 and web fixes')


@unittest.skipUnless(NGINX_BINARY, 'nginx unavailable')
class PortableNginxTests(unittest.TestCase):
    def test_share_and_portable_api_auth_configs_coexist_in_real_nginx(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            fixture = NginxFixture(Path(directory))
            h = portable.helper()
            h.NGINX_PREFIX, h.NGINX_CONFIG = fixture.prefix, fixture.config
            h.NGINX_GLOBALS = f'pid "{fixture.root.as_posix()}/nginx.pid"; error_log stderr;'
            extra = fixture.extras.parent / 'portable-os'
            extra.mkdir()
            for source in (ROOT / 'kvmd-extras/portable-os').glob('*.conf'):
                text = source.read_text().replace('/etc/kvmd/nginx/', fixture.prefix.as_posix() + '/')
                text = text.replace('/usr/share/kvmd/extras/portable-os/', extra.as_posix() + '/')
                (extra / source.name).write_text(text)
            if os.name == 'nt':
                # Windows cannot glob directories; explicit per-extension includes
                # test their real coexistence. Linux uses the exact native globs.
                for context in ('http', 'server'):
                    old = f'include "{fixture.extras.parent.as_posix()}/*/nginx.ctx-{context}.conf";'
                    new = '\n'.join(f'include "{path.as_posix()}/nginx.ctx-{context}.conf";'
                                    for path in (fixture.extras, extra))
                    fixture.rendered = fixture.rendered.replace(old, new)
            def run(args):
                if args[0] == 'kvmd-nginx-mkconf':
                    Path(args[-1]).write_text(fixture.rendered)
                    return ''
                if args[0] == 'nginx':
                    result = subprocess.run([str(NGINX_BINARY), *args[1:]], capture_output=True, text=True, timeout=15)
                    if result.returncode:
                        raise RuntimeError(result.stderr)
                    return result.stdout.strip()
                raise AssertionError('Unexpected system command')
            stack.enter_context(patch.object(portable, 'SHARE_EXTRAS', extra))
            stack.enter_context(patch.object(h, 'run', side_effect=run))
            reload = stack.enter_context(patch.object(h, 'reload_nginx'))
            portable.nginx_config(h)
            reload.assert_called_once()
            dump = run(h.nginx_args('-T', fixture.config))
            self.assertIn('127.0.0.1:9878', dump)
            self.assertIn('127.0.0.1:9877', dump)
            self.assertIn('proxy_intercept_errors off;', dump)


if __name__ == '__main__':
    unittest.main()
