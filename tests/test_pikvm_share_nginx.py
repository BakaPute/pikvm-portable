"""KVMD 4.213 wildcard-include regression and installer transaction tests.

No PiKVM access. Real nginx tests use -t/-T only, never start/reload a server.
Set NGINX_BINARY to a local executable, or install nginx on the CI runner.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('nginx_installer', str(ROOT / 'scripts/pikvm-share-install'))
spec = importlib.util.spec_from_loader(loader.name, loader)
installer = importlib.util.module_from_spec(spec)
loader.exec_module(installer)


class NginxFixture:
    """Reduced rendered 4.213 layout; native snippets verified at tag v4.213.

    https://github.com/pikvm/kvmd/tree/v4.213/configs/nginx
    Paths and listen/upstream addresses are local test substitutes. The generic
    includes and native auth/proxy/login/nocache semantics match that version.
    """
    def __init__(self, root):
        self.root = root
        self.prefix = root / 'nginx'
        self.extras = root / 'extras' / 'pikvm-share'
        self.config = root / 'run' / 'nginx.conf'
        for path in (self.prefix, self.extras, self.config.parent, self.prefix / 'logs', self.prefix / 'temp'):
            path.mkdir(parents=True)
        for name in ('nginx.ctx-http.conf', 'nginx.ctx-server.conf', 'manifest.yaml'):
            text = (ROOT / 'kvmd-extras/pikvm-share' / name).read_text(encoding='utf-8')
            text = text.replace('/etc/kvmd/nginx/', self.prefix.as_posix() + '/')
            (self.extras / name).write_text(text, encoding='utf-8')
        self.native = {
            'loc-proxy.conf': '''proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Scheme $scheme;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Port $server_port;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
''',
            'loc-login.conf': 'error_page 401 = @login;\nerror_page 403 = @login;\n',
            'loc-nocache.conf': '''add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, pre-check=0, post-check=0, max-age=0";
expires -1;
''',
            'kvmd.ctx-server.conf': '''index index.html;
auth_request /auth_check;
location = /auth_check {
    internal;
    proxy_pass http://kvmd/auth/check;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    auth_request off;
}
location @login { return 302 /login; }
''',
        }
        for name, text in self.native.items():
            (self.prefix / name).write_text(text, encoding='utf-8')
        extras_glob = (self.extras.parent / '*').as_posix()
        # Deliberately contains NO literal SHARE route, as with the real renderer.
        self.rendered = f'''worker_processes 1;
error_log stderr;
events {{ worker_connections 32; }}
http {{
    access_log off;
    upstream kvmd {{ server 127.0.0.1:9980; }}
    include "{extras_glob}/nginx.ctx-http.conf";
    server {{
        listen 127.0.0.1:18088;
        include "{self.prefix.as_posix()}/kvmd.ctx-server.conf";
        include "{extras_glob}/nginx.ctx-server.conf";
    }}
}}
'''
        self.config.write_text('previous active config\n', encoding='utf-8')

    def patch_constants(self):
        return patch.multiple(installer, NGINX_PREFIX=self.prefix, NGINX_CONFIG=self.config,
                              SHARE_EXTRAS=self.extras,
                              NGINX_GLOBALS=f'pid "{self.root.as_posix()}/nginx.pid"; error_log stderr;')

    def dump(self, missing=()):
        sections = {self.config.with_name('pikvm-share-nginx.candidate'): self.rendered}
        for path in (list(self.extras.glob('*.conf')) + list(self.prefix.glob('*.conf'))):
            if path.name not in missing:
                sections[path] = path.read_text(encoding='utf-8')
        return '\n'.join(f'# configuration file {path.as_posix()}:\n{text}\n'
                         for path, text in sections.items())

    def fake_run(self, args):
        if args[0] == 'kvmd-nginx-mkconf':
            Path(args[-1]).write_text(self.rendered, encoding='utf-8')
            return ''
        if args[:2] == ['nginx', '-T']:
            return self.dump()
        return ''


class NginxValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = NginxFixture(Path(self.temp.name))
        constants = self.fixture.patch_constants()
        constants.start()
        self.addCleanup(constants.stop)

    def test_wildcard_includes_load_share_without_literal_route_in_main(self):
        self.assertNotIn('/extras/pikvm-share/api/', self.fixture.rendered)
        with patch.object(installer, 'run', side_effect=self.fixture.fake_run) as run, \
             patch.object(installer, 'reload_nginx') as reload:
            installer.nginx_config()
        self.assertEqual(self.fixture.config.read_text(), self.fixture.rendered)
        self.assertTrue(any(call.args[0][:2] == ['nginx', '-T'] for call in run.call_args_list))
        reload.assert_called_once()
        self.assertFalse(self.fixture.config.with_name('pikvm-share-nginx.candidate').exists())

    def test_missing_effective_include_fails_without_publishing(self):
        for name in ('nginx.ctx-http.conf', 'nginx.ctx-server.conf', 'loc-proxy.conf',
                     'loc-login.conf', 'loc-nocache.conf', 'kvmd.ctx-server.conf'):
            with self.subTest(name=name), patch.object(installer, 'run', side_effect=lambda args:
                    self.fixture.dump(missing=(name,)) if args[:2] == ['nginx', '-T']
                    else self.fixture.fake_run(args)), patch.object(installer, 'reload_nginx') as reload:
                with self.assertRaises(RuntimeError):
                    installer.nginx_config()
                self.assertEqual(self.fixture.config.read_text(), 'previous active config\n')
                reload.assert_not_called()

    def test_missing_manifest_is_not_treated_as_optional(self):
        (self.fixture.extras / 'manifest.yaml').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Manifeste SHARE absent'):
            installer.validate_share_nginx(self.fixture.dump())

    def test_changed_include_after_nginx_test_fails(self):
        dump = self.fixture.dump()
        path = self.fixture.extras / 'nginx.ctx-server.conf'
        path.write_text(path.read_text() + '\n# modified after validation\n')
        with self.assertRaisesRegex(RuntimeError, 'a changé'):
            installer.validate_share_nginx(dump)

    def test_security_and_uri_contracts_are_preserved(self):
        path = self.fixture.extras / 'nginx.ctx-server.conf'
        original = path.read_text()
        replacements = (
            ('auth_request /auth_check;', 'auth_request off;'),
            ('proxy_pass http://pikvm_share_api;', 'proxy_pass http://pikvm_share_api/;'),
            ('proxy_set_header Cookie $http_cookie;', ''),
            ('proxy_set_header X-Share-Origin $scheme://$http_host;', ''),
            ('proxy_set_header X-Pikvm-Share $http_x_pikvm_share;', ''),
            ('proxy_intercept_errors off;', 'proxy_intercept_errors on;'),
        )
        for before, after in replacements:
            with self.subTest(before=before):
                path.write_text(original.replace(before, after, 1))
                with self.assertRaises(RuntimeError):
                    installer.validate_share_nginx(self.fixture.dump())
        path.write_text(original)

    def test_nginx_syntax_failure_never_publishes_or_reloads(self):
        def run(args):
            if args[:2] == ['nginx', '-T']:
                raise RuntimeError('nginx rejected syntax')
            return self.fixture.fake_run(args)
        with patch.object(installer, 'run', side_effect=run), patch.object(installer, 'reload_nginx') as reload:
            with self.assertRaises(RuntimeError):
                installer.nginx_config()
        self.assertEqual(self.fixture.config.read_text(), 'previous active config\n')
        self.assertFalse(self.fixture.config.with_name('pikvm-share-nginx.candidate').exists())
        reload.assert_not_called()

    def test_reload_retests_then_only_reloads_nginx(self):
        with patch.object(installer, 'run', return_value='') as run:
            installer.reload_nginx()
        self.assertEqual(run.call_args_list[0].args[0], installer.nginx_args('-t', self.fixture.config))
        self.assertEqual(run.call_args_list[1].args[0], ['systemctl', 'reload', 'kvmd-nginx.service'])


class InstallerLifecycleTests(unittest.TestCase):
    def test_reinstall_and_repeated_rollback_preserve_native_helper_and_initial_state(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            fixture = NginxFixture(Path(directory))
            stack.enter_context(fixture.patch_constants())
            helper = fixture.root / 'bin' / 'kvmd-helper-otgmsd-remount'
            helper.parent.mkdir()
            native = fixture.root / 'native' / helper.name
            helper.write_bytes(b'native helper with Python 3.14 fixes')
            unit = fixture.root / 'systemd' / installer.SERVICE
            enabled_link = fixture.root / 'systemd' / 'wants' / installer.SERVICE
            backend_module = SimpleNamespace(ORIGINAL_HELPER=str(native))
            target = fixture.root / 'web' / 'index.html'
            mapping = {helper: (ROOT / 'scripts/pikvm-share-remount', 0o755),
                       target: (ROOT / 'web/extras/pikvm-share/index.html', 0o644),
                       unit: (ROOT / 'systemd/pikvm-share-api.service', 0o644)}
            current = {'active': False, 'enabled': False}
            def run(args):
                if args[:3] == ['systemctl', 'enable', '--now']:
                    current.update(active=True, enabled=True)
                    enabled_link.parent.mkdir(parents=True, exist_ok=True)
                    enabled_link.write_text('test enable link')
                elif args[:2] == ['systemctl', 'stop']:
                    current['active'] = False
                elif args[:2] == ['systemctl', 'disable']:
                    current['enabled'] = False
                return fixture.fake_run(args)
            for name, value in (('BACKUPS', fixture.root / 'backups'), ('SHARE_UNIT', unit),
                                ('SHARE_ENABLE_LINK', enabled_link)):
                stack.enter_context(patch.object(installer, name, value))
            stack.enter_context(patch.object(installer, 'check'))
            stack.enter_context(patch.object(installer, 'helper_path', return_value=helper))
            stack.enter_context(patch.object(installer, 'file_map', return_value=mapping))
            stack.enter_context(patch.object(installer, 'service_state', side_effect=lambda:
                {'active': current['active'], 'enabled': enabled_link.exists()}))
            stack.enter_context(patch.object(installer, 'offline', side_effect=lambda module: contextlib.nullcontext()))
            stack.enter_context(patch.object(installer, 'assert_idle'))
            stack.enter_context(patch.object(installer.os, 'chown', create=True))
            stack.enter_context(patch.object(installer, 'run', side_effect=run))
            stack.enter_context(patch('sys.stdout', new_callable=io.StringIO))
            initial_config = fixture.config.read_bytes()
            installer.install(backend_module)
            first_backup = next(installer.BACKUPS.iterdir())
            first_result = {path: path.read_bytes() for path in (*mapping, native, fixture.config)}
            installer.install(backend_module)
            self.assertEqual({path: path.read_bytes() for path in first_result}, first_result)
            self.assertEqual(native.read_bytes(), b'native helper with Python 3.14 fixes')
            self.assertEqual(current, {'active': True, 'enabled': True})
            current['active'] = False  # CLI stops SHARE before restore_files
            for _ in range(2):
                self.assertFalse(installer.restore_files(first_backup))
                installer.reload_nginx()
                self.assertEqual(helper.read_bytes(), b'native helper with Python 3.14 fixes')
                self.assertEqual(fixture.config.read_bytes(), initial_config)
                self.assertFalse(native.exists())
                self.assertFalse(target.exists())
                self.assertFalse(unit.exists())
                self.assertFalse(enabled_link.exists())

    def test_repeated_failed_install_rolls_back_to_same_state(self):
        # Uses the same temporary transaction harness twice; no root operations.
        # The existing suite also checks preservation of pre-existing web files.
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            fixture = NginxFixture(Path(directory))
            stack.enter_context(fixture.patch_constants())
            helper = fixture.root / 'kvmd-helper-otgmsd-remount'
            helper.write_bytes(b'native')
            native = fixture.root / 'native' / helper.name
            module = SimpleNamespace(ORIGINAL_HELPER=str(native))
            stack.enter_context(patch.object(installer, 'BACKUPS', fixture.root / 'backups'))
            stack.enter_context(patch.object(installer, 'SHARE_UNIT', fixture.root / 'absent-unit'))
            stack.enter_context(patch.object(installer, 'SHARE_ENABLE_LINK', fixture.root / 'absent-link'))
            stack.enter_context(patch.object(installer, 'check'))
            stack.enter_context(patch.object(installer, 'helper_path', return_value=helper))
            stack.enter_context(patch.object(installer, 'file_map', return_value={helper: (ROOT / 'scripts/pikvm-share-remount', 0o755)}))
            stack.enter_context(patch.object(installer, 'service_state', return_value={'active': False, 'enabled': False}))
            stack.enter_context(patch.object(installer, 'offline', side_effect=lambda module: contextlib.nullcontext()))
            stack.enter_context(patch.object(installer, 'assert_idle'))
            stack.enter_context(patch.object(installer.os, 'chown', create=True))
            stack.enter_context(patch.object(installer.subprocess, 'run'))
            stack.enter_context(patch.object(installer, 'run', return_value=''))
            stack.enter_context(patch.object(installer, 'reload_nginx'))
            stack.enter_context(patch('sys.stdout', new_callable=io.StringIO))
            for _ in range(2):
                with patch.object(installer, 'nginx_config', side_effect=RuntimeError('bad config')):
                    with self.assertRaisesRegex(RuntimeError, 'bad config'):
                        installer.install(module)
                self.assertEqual(helper.read_bytes(), b'native')
                self.assertFalse(native.exists())
            self.assertEqual(len(list(installer.BACKUPS.iterdir())), 2)


NGINX_BINARY = os.environ.get('NGINX_BINARY') or shutil.which('nginx')


@unittest.skipUnless(NGINX_BINARY, 'nginx executable unavailable; set NGINX_BINARY')
class RealNginxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = NginxFixture(Path(self.temp.name))
        if os.name == 'nt':
            # Windows FindFirstFile cannot glob a directory component. Linux CI
            # exercises the exact 4.213 */nginx.ctx-*.conf patterns. On Windows
            # use a final-component glob, still resolved by the real nginx.
            for context in ('http', 'server'):
                self.fixture.rendered = self.fixture.rendered.replace(
                    f'/extras/*/nginx.ctx-{context}.conf',
                    f'/extras/pikvm-share/nginx.ctx-{context}*.conf')
        constants = self.fixture.patch_constants()
        constants.start()
        self.addCleanup(constants.stop)

    def run_nginx(self, args):
        if args[0] == 'nginx':
            args = [str(NGINX_BINARY), *args[1:]]
            result = subprocess.run(args, capture_output=True, text=True, timeout=15)
            if result.returncode:
                raise RuntimeError('nginx validation failed: ' + result.stderr)
            return result.stdout.strip()
        if args[0] == 'kvmd-nginx-mkconf':
            return self.fixture.fake_run(args)
        self.fail('Unexpected external command: ' + args[0])

    def test_real_nginx_loads_wildcards_proxy_auth_and_nocache(self):
        with patch.object(installer, 'run', side_effect=self.run_nginx), \
             patch.object(installer, 'reload_nginx') as reload:
            installer.nginx_config()
            dump = self.run_nginx(installer.nginx_args('-T', self.fixture.config))
        installer.validate_share_nginx(dump)
        reload.assert_called_once()

    def test_real_nginx_rejects_duplicate_proxy_directive_in_native_include(self):
        path = self.fixture.prefix / 'loc-proxy.conf'
        path.write_text(path.read_text() + '\nproxy_buffering off;\n')
        with patch.object(installer, 'run', side_effect=self.run_nginx), \
             patch.object(installer, 'reload_nginx') as reload:
            with self.assertRaisesRegex(RuntimeError, 'duplicate'):
                installer.nginx_config()
        self.assertEqual(self.fixture.config.read_text(), 'previous active config\n')
        reload.assert_not_called()

    def test_real_nginx_accepts_empty_glob_but_installer_rejects_missing_share(self):
        (self.fixture.extras / 'nginx.ctx-http.conf').unlink()
        (self.fixture.extras / 'nginx.ctx-server.conf').unlink()
        with patch.object(installer, 'run', side_effect=self.run_nginx), \
             patch.object(installer, 'reload_nginx') as reload:
            with self.assertRaisesRegex(RuntimeError, 'non chargée'):
                installer.nginx_config()
        self.assertEqual(self.fixture.config.read_text(), 'previous active config\n')
        reload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
