"""Synthetic OLED input/action harness: no live files, commands or hardware."""
from unittest.mock import Mock
from pikvm_config import defaults
from pikvm_oled import LogicalButton
from pikvm_oled_nav import Navigation
from pikvm_oled_control import Control
from pikvm_gestures import Gesture


class Worker:
    def __init__(self):self.task=None;self.result=None
    def submit(self,task):
        if self.task is not None or self.result is not None:return False
        self.task=task;return True
    def finish(self):
        task,self.task=self.task,None
        try:self.result={'ok':True,'value':task()}
        except Exception as error:self.result={'ok':False,'error':str(error)}
    def poll(self):result,self.result=self.result,None;return result


class Harness:
    def __init__(self):
        self.now=10.;self.values=defaults();self.backend=Mock();self.worker=Worker()
        self.nav=Navigation(self.backend,lambda:self.values,clock=lambda:self.now,worker=self.worker)
        self.nav.publish=Mock()
        self.frame={'id':'a'*64,'control_id':'b'*64,'context':self.nav.context()}
        self.button=LogicalButton(clock=lambda:self.now,frame_reader=lambda:self.frame)
        self.control=Control(self.button,self.nav,lambda:self.values,clock=lambda:self.now)
        self.control.step(False)
    def step(self,down=False,seconds=.02):
        self.now+=seconds;return self.control.step(down)
    def wait(self,seconds,down=False):
        events=[];end=self.now+seconds
        while self.now<end-1e-9:events+=self.step(down,min(.02,end-self.now))
        return events
    def click(self,duration=.12):
        self.step(True);events=self.wait(duration,True);events+=self.step(False);events+=self.wait(.4)
        return events
    def hold(self,seconds):
        self.step(True);self.wait(seconds-.02,True);events=self.step(False);events+=self.wait(.06)
        return events
    def gesture(self,kind='double',duration=.1,authorize=lambda _:False):
        self.nav.handle(Gesture(kind,duration,None,None,self.nav.revision,self.now),authorize)
    def select(self,key):
        self.nav.index=next(i for i,item in enumerate(self.nav.items()) if (item.get('id') or item.get('kind'))==key)
        self.gesture()
    def finish(self):self.worker.finish();self.nav.tick()
