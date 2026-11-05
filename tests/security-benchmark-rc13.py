"""Synthetic authorization timing on the development host; no device access."""
import copy
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from pikvm_security import SecurityStore,ROLES,password_hash
from pikvm_access import required

def main():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);store=SecurityStore(root/'identities.json',writer=lambda f:f(),lock_path=root/'lock',strict=False)
        at=time.perf_counter();encoded=password_hash('Synthetic-Benchmark-2026!');kdf=(time.perf_counter()-at)*1000
        users={f'user{i}':store.new_user(f'user{i}',encoded,'operator' if i else 'administrator') for i in range(16)}
        store.write({'schema':1,'revision':0,'users':users,'roles':copy.deepcopy(ROLES),'history':[]});store.principal('user1');times=[]
        for _ in range(1000):
            at=time.perf_counter();store.principal('user1').require(*required('GET','/api/msd'));times.append((time.perf_counter()-at)*1000)
        result={'platform':platform.platform(),'python':platform.python_version(),'scope':'PC only; synthetic 16 users; cached validated state, stat rechecked each request. Not Pi CPU/memory or KVMD latency.',
                'iterations':1000,'authorization_mean_ms':round(statistics.mean(times),4),'authorization_p95_ms':round(sorted(times)[949],4),'pbkdf2_600000_ms':round(kdf,2),'state_bytes':store.path.stat().st_size,
                'limits':{'concurrent_proxy_requests':16,'sessions':128,'credential_checks':1,'users':64,'roles':32,'public_keys_per_user':8,'http_management_bytes':16384,'ws_client_bytes':4096}}
        path=ROOT/'docs/performance/rc13-local.json';path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(result))
if __name__=='__main__':main()
