"""Reviewable SSH plans. Web API NEVER executes useradd, sshd reload or sudo."""
import hashlib
import json
import re
from pathlib import Path
from pikvm_security import username,SecurityError,public_key

BROKER='/usr/local/lib/pikvm-portable/pikvm-maintenance-command'
KEY_COMMAND='/usr/local/lib/pikvm-portable/pikvm-security-authorized-keys'
def ssh_options(text):
    result={}
    for line in text.splitlines():
        found=re.fullmatch(r'\s*([a-z][a-z0-9]+)(?:\s+|=)(.*?)\s*',line,re.I)
        if found:
            key,value=found.groups()
            key=key.lower()
            if key in result and key not in ('acceptenv','hostkey','listenaddress'):raise SecurityError('Option SSH ambiguë.',503)
            result[key]=(result[key]+' '+value) if key=='acceptenv' and key in result else value
    return result
def plan(document,name):
    username(name);user=document['users'].get(name)
    if not user:raise SecurityError('Compte Web introuvable.',404)
    login='codex' if name=='codex' else 'pos_'+name
    keys=[public_key(k['public']) for k in user['keys']]
    mode=user['ssh'] if user['enabled'] else 'disabled'
    key_lines=['restrict '+k['public'] for k in keys] if mode=='diagnostics' else []
    configuration='\n'.join(['Match all','Match User '+login,
        '    AuthenticationMethods publickey','    PasswordAuthentication no','    KbdInteractiveAuthentication no',
        '    PubkeyAuthentication yes','    AuthorizedKeysFile none',
        '    PubkeyAcceptedAlgorithms ssh-ed25519',
        '    AuthorizedKeysCommand /usr/bin/python3 -I '+KEY_COMMAND+' %u','    AuthorizedKeysCommandUser root',
        '    PermitUserRC no','    PermitTTY no',
        '    AllowTcpForwarding no','    AllowStreamLocalForwarding no','    AllowAgentForwarding no',
        '    X11Forwarding no','    PermitTunnel no',
        '    ForceCommand /usr/bin/python3 -I '+BROKER,'Match all',''])
    result={'schema':1,'web_user':name,'identity_id':user['id'],'linux_user':login,'revision':document['revision'],'mode':mode,
            'keys':key_lines,'configuration':configuration,'sudo':False,'groups':[],
            'commands':['status','services','version'],'forced_command':BROKER,
            'notice':'Provisionnement Linux initial distinct. Après provisionnement, sshd consulte les clés et l’activation Web à chaque connexion : révocation immédiate des nouvelles connexions, commande en cours limitée à 8 s.'}
    result['sha256']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return result
