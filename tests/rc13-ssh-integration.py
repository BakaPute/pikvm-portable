"""REAL OpenSSH, disposable container ONLY. No production users or private keys."""
import copy
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
assert os.geteuid()==0 and Path('/__rc13_isolated__').is_file(),'Disposable RC13 container required'
SOURCE=Path('/project/scripts');LIB=Path('/usr/local/lib/pikvm-portable');LIB.mkdir(parents=True)
for name in ('pikvm_security.py','pikvm_ssh.py','pikvm_config.py','pikvm-maintenance-command','pikvm-security-authorized-keys','pikvm-security-ssh'):
    shutil.copyfile(SOURCE/name,LIB/name);(LIB/name).chmod(0o755 if name.startswith('pikvm-') else 0o644)
sys.path.insert(0,str(LIB))
from pikvm_security import SecurityStore,ROLES,native_admin,password_hash
from pikvm_ssh import plan
loader=importlib.machinery.SourceFileLoader('ssh_setup',str(LIB/'pikvm-security-ssh'));spec=importlib.util.spec_from_loader(loader.name,loader);setup=importlib.util.module_from_spec(spec);loader.exec_module(setup)
PASSWORD='Synthetic-Isolated-SSH-2026!'
def run(args,check=True,timeout=15):return subprocess.run(args,check=check,capture_output=True,text=True,timeout=timeout,stdin=subprocess.DEVNULL)

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);root.chmod(0o700)
    for name in ('rootkey','codexkey'):run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(root/name)])
    admin_keys=Path('/root/.ssh');admin_keys.mkdir(mode=0o700,exist_ok=True)
    shutil.copyfile(root/'rootkey.pub',admin_keys/'authorized_keys');(admin_keys/'authorized_keys').chmod(0o600)
    run(['ssh-keygen','-A'])
    run(['passwd','-d','root']) # disposable container only; empty-password SSH remains forbidden
    config=Path('/etc/ssh/sshd_config');config.write_text('Port 2222\nListenAddress 127.0.0.1\nPidFile /run/sshd-test.pid\nPermitRootLogin prohibit-password\nPermitEmptyPasswords no\nPasswordAuthentication yes\nPubkeyAuthentication yes\nKbdInteractiveAuthentication no\nUsePAM no\nStrictModes yes\nAuthorizedKeysFile .ssh/authorized_keys\nLogLevel ERROR\n')
    process=subprocess.Popen(['/usr/bin/sshd','-D','-e','-f',str(config)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    base=['ssh','-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=no','-o','UserKnownHostsFile=/dev/null','-o','LogLevel=ERROR','-o','ConnectTimeout=3','-p','2222']
    def ssh(user,command,key='codexkey',check=True):return run(base+['-i',str(root/key),user+'@127.0.0.1',command],check)
    try:
        for _ in range(30):
            if ssh('root','true','rootkey',False).returncode==0:break
            time.sleep(.1)
        assert ssh('root','id -u','rootkey').stdout.strip()=='0'
        store=SecurityStore(writer=lambda f:f(),lock_path=Path('/run/ssh-identities.lock'))
        store.path.parent.mkdir(mode=0o700,parents=True)
        encoded=password_hash(PASSWORD)
        store.write({'schema':1,'revision':0,'users':{'supervisor':store.new_user('supervisor',encoded,'administrator'),'codex':store.new_user('codex',encoded,'maintenance')},'roles':copy.deepcopy(ROLES),'history':[]})
        def change(action,**data):store.mutate(native_admin(),{'action':action,'name':'codex','confirmed':True,'expected_revision':store.read()['revision'],**data})
        change('key_add',public_key=(root/'codexkey.pub').read_text().strip());change('ssh',mode='diagnostics')
        proposal=plan(store.read(),'codex');real_run=setup.run
        def reload(args):
            if args[:3]==['/usr/bin/systemctl','reload','sshd.service']:process.send_signal(signal.SIGHUP);time.sleep(.2);return None
            return real_run(args)
        root_before=setup.effective(config,'root')
        with patch.object(setup,'run',side_effect=reload):setup.apply(store,'codex',proposal['sha256'])
        assert setup.effective(config,'root')==root_before
        account=pwd.getpwnam('codex');assert account.pw_uid>=1000 and account.pw_uid!=0
        assert os.getgrouplist('codex',account.pw_gid)==[account.pw_gid]
        assert json.loads(ssh('codex','version').stdout)['privileged'] is False
        status=json.loads(ssh('codex','status').stdout);assert status['uid']==account.pw_uid
        print('PASS real SSH Ed25519 login; distinct UID/home; no supplementary groups',flush=True)
        for command in ('','id','sudo -n id','sh -c id','cat /etc/shadow','status; id','python3 -c print(1)','scp -t /tmp/x'):
            assert ssh('codex',command,check=False).returncode!=0,command
        remote=run(base+['-i',str(root/'codexkey'),'-o','ExitOnForwardFailure=yes','-N','-R','127.0.0.1:29000:127.0.0.1:2222','codex@127.0.0.1'],check=False)
        assert remote.returncode!=0
        print('PASS no shell/sudo/arbitrary paths/SCP/forwarding',flush=True)
        protected=root/'gpio17-and-backup-fixture';protected.write_bytes(b'unchanged');protected.chmod(0o600)
        check=run(['runuser','-u','codex','--','python3','-c','import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b"bad")',str(protected)],check=False)
        assert check.returncode!=0 and protected.read_bytes()==b'unchanged'
        fingerprint=store.read()['users']['codex']['keys'][0]['fingerprint'];change('key_remove',fingerprint=fingerprint)
        assert ssh('codex','version',check=False).returncode!=0
        change('key_add',public_key=(root/'codexkey.pub').read_text().strip());assert ssh('codex','version',check=False).returncode==0
        change('edit',changes={'enabled':False});assert ssh('codex','version',check=False).returncode!=0
        assert ssh('root','id -u','rootkey').stdout.strip()=='0'
        print('PASS key revocation and disabled account deny new connections; native root recovery unchanged',flush=True)
    finally:
        process.terminate()
        try:process.wait(3)
        except subprocess.TimeoutExpired:process.kill();process.wait()
