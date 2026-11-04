"""Bounded tmpfs activity relay. Never records keys, commands, IPs or credentials."""
import json
import os
from pathlib import Path
import time
from pikvm_config import atomic

RUNTIME=Path('/run/pikvm-portable')
_last={}


def event(source,request=None,clock=time.monotonic):
    if source not in ('button','menu'):return
    now=clock()
    if request is None and now-_last.get(source,float('-inf'))<2:return
    _last[source]=now
    try:
        RUNTIME.mkdir(mode=0o700,exist_ok=True)
        if RUNTIME.is_symlink():return
        atomic(RUNTIME/(source+'.json'),{'source':source,'monotonic':now,'request':request})
    except OSError:pass  # Configuration/telemetry failure must never block input.


def latest(source):
    try:
        path=RUNTIME/(source+'.json')
        if path.is_symlink() or path.stat().st_size>1024:return None
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('source')==source and 0<=time.monotonic()-value['monotonic']<=30:return value
    except (OSError,ValueError,KeyError,TypeError):pass
    return None
