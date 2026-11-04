"""Actual RC12 gesture/navigation/render path on synthetic data, localhost only."""
import base64
import copy
import hashlib
import json
import threading
import time
from pikvm_config import defaults
from pikvm_iso import Library
from pikvm_oled import LogicalButton
from pikvm_oled_control import Control
from pikvm_oled_nav import Navigation,render_navigation
from pikvm_oled_ui import render_status


class Backend:
    def __init__(self,fixture):self.fixture=fixture;self.calls=[];self.folder_api=Library()
    def status_page(self,page):self.calls.append(['status',page])
    def library(self,folder,scope='browse'):
        self.calls.append(['library',folder,scope]);state=copy.deepcopy(self.fixture.msd)
        if scope!='browse':
            key='iso_favorites' if scope=='favorites' else 'iso_recent'
            state['storage']['images']={name:info for name,info in state['storage']['images'].items() if name in self.fixture.values[key]}
        return state,self.folder_api.entries(state,folder)
    def connect(self,name,cdrom):
        self.calls.append(['connect',name,cdrom]);self.fixture.msd['drive'].update(connected=True,image={'name':name},cdrom=cdrom,rw=False)
        self.fixture.values['iso_recent']=[name];return copy.deepcopy(self.fixture.msd)
    def eject(self,confirmed):
        self.calls.append(['eject',confirmed]);self.fixture.msd['drive']['connected']=False;return copy.deepcopy(self.fixture.msd)
    def favorite(self,name):self.fixture.values['iso_favorites']=[name]
    def sensitive(self,*_):raise RuntimeError('Actions système interdites dans la simulation')


class Fixture:
    def __init__(self):
        self.lock=threading.RLock();self.values=defaults();self.frame={};self.closed=threading.Event()
        self.msd={'enabled':True,'online':True,'busy':False,'drive':{'connected':False,'image':None,'cdrom':True,'rw':False},
                  'storage':{'uploading':None,'downloading':False,'images':{'Linux/Debian/Synthetic test.iso':{'complete':True,'size':4096},'Windows/Win11/Example.iso':{'complete':True,'size':8192}}}}
        self.backend=Backend(self);self.navigation=Navigation(self.backend,lambda:self.values)
        self.button=LogicalButton(frame_reader=self.read);self.control=Control(self.button,self.navigation,lambda:self.values)
        self.navigation.publish=lambda **_:None  # Never writes live tmpfs.
        self.last_error=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        while not self.closed.is_set():
            with self.lock:
                try:
                    self.control.step(False);model=self.navigation.snapshot()
                    image=render_status('main',{'ip':'192.0.2.1','percent':82},self.values).image if model['context']['screen']=='status' else render_navigation(model,self.values,time.monotonic()%10).image
                    raw=image.tobytes();context=model['context'];control=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
                    self.frame={'width':128,'height':64,'format':'1bpp-msb','pixels':base64.b64encode(raw).decode(),'pixel_id':hashlib.sha256(raw).hexdigest(),
                                'id':hashlib.sha256(raw+control.encode()).hexdigest(),'control_id':control,'context':context,'source':'status' if self.navigation.screen=='status' else 'menu',
                                'physical':'disconnected','button_available':True,'age':0}
                except Exception as error:self.last_error=str(error)
            self.closed.wait(.02)
    def read(self):
        with self.lock:return copy.deepcopy(self.frame)
    def event(self,data):
        with self.lock:return self.button.remote({**data,'owner':'a'*64})
    def close(self):self.closed.set();self.thread.join(2);self.navigation.worker.close()
