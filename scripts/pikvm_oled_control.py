"""Non-blocking input coordinator. No renderer, I2C or GPIO configuration."""
import time
from pikvm_gestures import Gestures


class Control:
    def __init__(self,button,navigation,values,activity=lambda *_:None,clock=time.monotonic):
        self.button=button;self.navigation=navigation;self.values=values;self.activity=activity;self.clock=clock
        self.gestures=Gestures();self.down=False;self.token=None;self.origin='physical';self.owner=None
        self.last_step=None;self.max_gap_ms=0;self.stalls=0
        button.context_guard=navigation.matches

    def step(self,physical):
        now=self.clock();values=self.values()
        if self.last_step is not None:
            gap=now-self.last_step;self.max_gap_ms=max(self.max_gap_ms,gap*1000)
            if gap>.3:self.gestures.cancel();self.stalls+=1
        self.last_step=now
        self.gestures.double_seconds=values['button_double_ms']/1000
        self.gestures.hold_seconds=values['button_back_ms']/1000
        down=self.button.poll(physical)
        if down and not self.down:
            self.token=self.button.start();self.origin=self.token[1]
            self.owner=(self.button.hold or {}).get('owner') if self.origin=='remote' else None
            self.activity('button')
            if self.navigation.screen!='status':self.activity('menu')
        cancelled=self.token is not None and self.button.cancelled(self.token)
        duration=self.button.duration(self.token) if self.token else 0
        events=self.gestures.feed(down,now,token=self.token,origin=self.origin,owner=self.owner,
            context=self.navigation.revision,duration=duration,cancelled=cancelled,
            certain=physical is not None)
        for gesture in events:
            self.navigation.handle(gesture,self.button.sensitive)
        self.navigation.tick(pressed=down)
        self.navigation.publish(held=duration if down and not cancelled else 0)
        self.down=down
        if not down and cancelled:self.token=None
        return events
