"""Pure gesture recognition; no device access or actions.

Physical debounce, deferred single clicks, same-owner double clicks and explicit
hold events. Unknown/cancelled input discards pending gestures and requires a
stable release. Renderer delays cannot extend a server-measured virtual press.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Gesture:
    kind: str
    duration: float
    token: object
    owner: object
    context: object
    released_at: float = 0


class Gestures:
    def __init__(self,double_seconds=.35,debounce=.03,hold_seconds=1.2):
        self.double_seconds=double_seconds;self.debounce=debounce;self.hold_seconds=hold_seconds
        self.candidate=False;self.changed=0;self.stable=False;self.pending=None
        self.press=None;self.blocked=False;self.low_since=None

    def cancel(self):
        self.pending=None;self.press=None;self.stable=False;self.blocked=True;self.low_since=None

    def feed(self,down,now,*,token=None,origin='physical',owner=None,context=None,duration=None,cancelled=False,certain=True):
        events=[]
        if cancelled or (origin=='physical' and not certain):self.cancel();return events
        if self.blocked:
            if down:self.low_since=None
            elif self.low_since is None:self.low_since=now
            elif now-self.low_since>=self.debounce:self.blocked=False;self.candidate=False;self.changed=now
            return events
        if self.pending and self.pending['context']!=context:self.pending=None
        if down!=self.candidate:
            self.candidate=down;self.changed=now
            if down and not self.stable:self.press={'at':now,'token':token,'origin':origin,'owner':owner,'context':context}
            elif not down:
                self.release_at=now;self.release_duration=duration
        delay=self.debounce if origin=='physical' else 0
        if down!=self.stable and now-self.changed>=delay:
            self.stable=down
            if not down and self.press:
                press=self.press;self.press=None
                released_at=self.release_at
                elapsed=round(max(0,self.release_duration if press['origin']!='physical' and self.release_duration is not None else released_at-press['at']),9)
                if elapsed>=self.hold_seconds:
                    self.pending=None
                    events.append(Gesture('hold',elapsed,press['token'],press['owner'],press['context'],released_at))
                elif elapsed>=self.debounce or press['origin']!='physical':
                    if self.pending and now<=self.pending['until'] and press['origin']==self.pending['origin'] and press['owner']==self.pending['owner'] and press['context']==self.pending['context']:
                        self.pending=None;events.append(Gesture('double',elapsed,press['token'],press['owner'],press['context'],released_at))
                    else:
                        self.pending={**press,'duration':elapsed,'until':released_at+self.double_seconds,'released_at':released_at}
        # A second press can be held longer than the double-click window. It must
        # finish before any pending single is dispatched; holds discard that single.
        if self.pending and now>=self.pending['until'] and not down and not self.stable:
            press=self.pending;self.pending=None
            events.append(Gesture('single',press['duration'],press['token'],press['owner'],press['context'],press['released_at']))
        return events


class Permit:
    """One-shot local authorization captured at the confirmed release."""
    def __init__(self,kind,issued):self.kind=kind;self.issued=issued;self.used=False
    def consume(self,kind,now):
        if self.used or kind!=self.kind or not 0<=now-self.issued<=2:raise RuntimeError('Autorisation expirée ou déjà consommée')
        self.used=True
