"""Short-lived, request-bound root-to-root delegation, never a client credential."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from pikvm_security import SecurityStore,SecurityError,protected_file,RUNTIME

KEY=RUNTIME/'delegation.key'
_NONCES={}
_LOCK=threading.Lock()

def key_bytes(path=KEY):
    protected_file(Path(path));value=Path(path).read_bytes()
    if len(value)!=32:raise SecurityError('Délégation indisponible.',503)
    return value

def issue(principal,method,target,needs,key=None,now=None):
    principal.require(*needs)
    body={'user':principal.user,'epoch':principal.epoch,'owner':principal.owner,'method':method,'target':target,
          'needs':list(needs),'expires':int(time.time() if now is None else now)+10,'nonce':secrets.token_hex(16)}
    raw=json.dumps(body,sort_keys=True,separators=(',',':')).encode()
    token=base64.urlsafe_b64encode(raw).decode().rstrip('=')
    return token+'.'+hmac.new(key if key is not None else key_bytes(),token.encode(),'sha256').hexdigest()

def verify(headers,method=None,target=None,store=None,key=None,now=None,consume=False):
    value=headers.get('X-Portable-Delegation','')
    try:
        if not isinstance(value,str) or len(value)>8192:raise ValueError()
        token,digest=value.split('.')
        expected=hmac.new(key if key is not None else key_bytes(),token.encode(),'sha256').hexdigest()
        if not hmac.compare_digest(digest,expected):raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
        if set(data)!={'user','epoch','owner','method','target','needs','expires','nonce'}:raise ValueError()
        at=time.time() if now is None else now
        if not at<data['expires']<=at+11 or (method is not None and data['method']!=method) or (target is not None and data['target']!=target):raise ValueError()
        principal=(store or SecurityStore()).principal(data['user'],data['owner'])
        if principal.epoch!=data['epoch']:raise ValueError()
        principal.require(*data['needs'])
        if consume:
            with _LOCK:
                expired=[k for k,v in _NONCES.items() if v<=at]
                for k in expired:_NONCES.pop(k,None)
                if data['nonce'] in _NONCES or len(_NONCES)>4096:raise ValueError()
                _NONCES[data['nonce']]=data['expires']
        return principal
    except SecurityError:raise
    except (ValueError,KeyError,TypeError):raise SecurityError('Délégation refusée.',403) from None

def bind(headers,method,target):
    if headers.get('X-Portable-Delegation'):
        # The public gateway signs the backend target AFTER its fixed rewrite.
        return verify(headers,method,target,consume=True)
    return None

class Audit:
    def __init__(self,path=RUNTIME/'audit.jsonl',strict=True):
        self.path=Path(path);self.lock=threading.Lock();self.strict=strict
    def record(self,actor,event,allowed,target=''):
        # No request bodies, cookies, passwords, private keys, query values or tokens.
        record={'at':int(time.time()),'actor':str(actor)[:64],'event':str(event)[:80],
                'allowed':bool(allowed),'target':str(target).split('?',1)[0][:120]}
        with self.lock:
            self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if self.path.exists():
                protected_file(self.path,self.strict)
                if self.path.stat().st_size>480*1024:self.path.replace(self.path.with_suffix('.previous'))
            fd=os.open(self.path,os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'a',encoding='utf-8') as output:output.write(json.dumps(record,ensure_ascii=False)+'\n')
    def read(self):
        if not self.path.exists():return []
        protected_file(self.path,self.strict)
        try:return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()[-200:]]
        except (ValueError,OSError):raise SecurityError('Audit indisponible.',503) from None
