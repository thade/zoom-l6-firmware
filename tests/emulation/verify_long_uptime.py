#!/usr/bin/env python3
"""Long uptime: the timed behaviour of the added code at any age of the mixer.

The 1 ms tick is a 32-bit word. A signed difference against it turns negative
2^31 ms (24.9 days) after the time it is measured from, and the word wraps at
2^32 ms (49.7 days). The worker's poll count, the take serial and the played
generation are 32-bit words too. Each group here runs the same scenario on a
fresh rig at several ages and expects the same outcome at every one:

  fresh        just after start-up
  signed       crossing 2^31 ms after Main first received
  later        a minute past that
  wrap         crossing the tick wrap
  wrapped      after the wrap
  late_start   Main first received just before the wrap

Uses verify_master_ref.py's rig and build. No device or card access.
"""
import json,struct
import verify_master_ref as M
from verify_master_ref import MasterRig,N,put32,word,putstr,stock_master,take_master,config,CONFIG,ROOT

TICK=0x801f9050;READY=1001;HALF=1<<31;WRAP=1<<32
LED=lambda sel:0x8062939c+2*(sel+0xc)
CHAIN=CONFIG+0x30f
TOGGLE={(16,17):0x4c364158,(18,19):0x4c364348};RESTORE=0x4c364152;ANCHOR_MAGIC=0x4c36414e
# name: (tick when Main first received, tick when the scenario starts)
AGES=dict(fresh=(READY,5000),signed=(READY,READY+HALF-1000),later=(READY,READY+HALF+60_000),
          wrap=(READY,WRAP-1000),wrapped=(READY,WRAP+5000),late_start=(WRAP-2999,WRAP-1500))

class Clock:
    """The tick as the scenario sees it: milliseconds from its own start."""
    def __init__(self,r,age):
        self.r=r;self.ready,self.start=AGES[age];put32(r.m,N['mr_main_ready'],self.ready&0xffffffff);self.at(0)
    def at(self,ms):self.now=ms;put32(self.r.m,TICK,(self.start+ms)&0xffffffff)
    def later(self,ms):self.at(self.now+ms)

def panel(age):
    """Both holds toggle once per 1.5 s hold."""
    r=MasterRig();keys={};saves=[]
    r.m.hooks.update({0x80008478:lambda a:keys.get(a[0],0),0x80006ab8:lambda a:saves.append(1) or 0,
                      0x80076950:lambda a:1,0x800763d8:lambda a:1})
    c=Clock(r,age);t=0
    # The worker has polled since start-up: one poll as the holds arm.
    put32(r.m,TICK,(c.ready+1000)&0xffffffff);r.m.invoke(N['panel_poll'],[])
    def poll(ms,pair,a=1,b=1):
        keys.clear();keys[pair[0]],keys[pair[1]]=a,b;c.at(ms);r.m.invoke(N['panel_poll'],[])
    posted=lambda magic:len([q for q in r.posts if q[:2]==(3,magic)])
    for pair,magic in TOGGLE.items():
        for n in (1,2):                                   # two holds of each pair
            for ms in range(t,t+1500,50):poll(ms,pair)
            assert posted(magic)==n-1,(age,pair,n)        # 1.45 s: not yet
            poll(t+1500,pair);assert posted(magic)==n,(age,pair,n)
            for ms in range(t+1550,t+3000,50):poll(ms,pair)
            assert posted(magic)==n,(age,pair,n)          # held on: once per hold
            for ms in range(t+3000,t+3200,50):poll(ms,pair,0,0)
            t+=3200
    return dict(toggles=2*len(TOGGLE))

def show(age,before):
    """The LED show ends 2 s after Main started it: the worker asks Main to
    redraw, every 250 ms until Main has. The show starts `before` ms ahead of
    the age's boundary, so the 2 s or the retries cross it."""
    r=MasterRig();keys={}
    r.m.hooks.update({0x80008478:lambda a:keys.get(a[0],0),0x80006ab8:lambda a:0,0x80076950:lambda a:1,0x800763d8:lambda a:1})
    c=Clock(r,age);t=1000-before
    def poll(ms):c.at(ms);r.m.invoke(N['panel_poll'],[])
    posted=lambda:len([q for q in r.posts if q[:2]==(3,RESTORE)])
    leds=lambda:[bytes(r.m.uc.mem_read(LED(s),2)) for s in (6,7)]
    c.at(t);r.main_receive(3,TOGGLE[18,19],0,0)           # Main switches the chain: EFX and PAN show it
    shown=leds();assert shown[0]==shown[1] and shown[0][0]==0x10,(age,before,shown)
    for ms in range(t+50,t+2000,50):poll(ms)
    assert posted()==0,(age,before)
    r.main_receive(3,0,0,0);assert leds()==shown,(age,before)             # an event before it is due
    poll(t+2000);assert posted()==1,(age,before)
    for ms in range(t+2050,t+2250,50):poll(ms)
    assert posted()==1,(age,before)
    poll(t+2250);assert posted()==2,(age,before)                          # not redrawn yet: asked again
    for ms in range(t+2300,t+2500,50):poll(ms)
    assert posted()==2,(age,before)
    poll(t+2500);assert posted()==3,(age,before)
    view=r.m.uc.mem_read(0x804430d8,1)[0]
    c.at(t+2550);r.main_receive(3,RESTORE,0,0)
    assert leds()==[bytes([0x10 if view==s else 0,0]) for s in (6,7)],(age,before)
    for ms in range(t+2600,t+4000,50):poll(ms)
    assert posted()==3,(age,before)
    return dict(show_ms=2000,retry_ms=250)

def arming(age):
    """The holds stay off until 1 s after Main first received, then stay armed."""
    r=MasterRig();keys={16:1,17:1};r.m.hooks[0x80008478]=lambda a:keys.get(a[0],0)
    ready,_=AGES[age];first=ready                         # times below are from the tick Main stored
    posted=lambda:len([q for q in r.posts if q[:2]==(3,TOGGLE[16,17])])
    def poll(ms):put32(r.m,TICK,(first+ms)&0xffffffff);r.m.invoke(N['panel_poll'],[])
    for ms in range(-3000,0,50):poll(ms)
    assert not posted(),age                               # Main has not received
    put32(r.m,N['mr_main_ready'],ready&0xffffffff)
    for ms in range(-200,1000,50):poll(ms)                # a tick read before Main stored, then the first second
    assert not posted(),age
    for ms in range(1000,2500,50):poll(ms)
    assert not posted(),age                               # the hold counts from arming
    poll(2500);assert posted()==1,age
    return dict(armed_ms=1000)

def anchors(age):
    """A storage change is acted on once Main has handled it and 2 s have passed."""
    r=MasterRig(catalogue=('BACKING.WAV',),anchors=());r.set('anchor_boot',0)
    r.m.hooks.update({0x80006ab8:lambda a:0,0x80076950:lambda a:1,0x800763d8:lambda a:1})
    c=Clock(r,age);put32(r.m,N['mr_main_waits'],1)
    for _ in range(5):r.step()
    assert (r.field('anchor_created'),r.field('anchor_pending'))==(4,0),age    # the start-up check
    pad3='A:\\SOUND_PAD\\PAD3\\MASTER.WAV';del r.card[pad3]
    r.main_receive(0,0,0x32,0);r.main_receive(3,0,0,0)                         # a storage change, handled
    r.step();c.later(1999);r.step()
    assert pad3 not in r.card and r.field('anchor_pending')==0xf,age           # not quiet for 2 s yet
    c.later(1)
    for _ in range(5):r.step()
    assert pad3 in r.card and r.field('anchor_pending')==0,age
    return dict(settle_ms=2000)

def reposts(polls):
    """An unhandled post is repeated every 40 worker polls, 30 times, then given up."""
    r=MasterRig();r.set('polls',polls);r.take();r.settle()
    assert r.field('handoff_state')==M.H_POSTED and len(r.posts)==1,hex(polls)
    for n in range(2,31):
        for _ in range(39):r.step()
        assert len(r.posts)==n-1,(hex(polls),n)
        r.step();assert len(r.posts)==n,(hex(polls),n)
    for _ in range(40):r.step()
    assert r.field('handoff_state')==M.H_LOST and len(r.posts)==30,hex(polls)
    return dict(posts=30)

def serials(first):
    """Takes are assigned in order and old serials ignored, whatever the serial's value."""
    r=MasterRig();r.set('handoff_serial',first);r.set('handled',first)
    t=[take_master(n) for n in range(1,4)]
    for n,path in enumerate(t):
        r.card[path]=stock_master(10**6);r.quick_take(path[:-len('\\MASTER.WAV')]);r.settle()
        serial=(first+n+1)&0xffffffff
        assert r.field('handoff_serial')==serial and r.field('handoff_state')==M.H_POSTED,(hex(first),n)
        assigned=len(r.assigned)
        r.deliver(serial=(serial-1)&0xffffffff);assert len(r.assigned)==assigned,(hex(first),n)   # the previous serial
        r.deliver();assert r.field('handoff_state')==M.H_ASSIGNED and r.pads()[0]==path,(hex(first),n)
        assigned=len(r.assigned);r.deliver();assert len(r.assigned)==assigned,(hex(first),n)      # a repeat
    assert r.pads()[:3]==t[::-1],hex(first)
    return dict(takes=3)

def played(first):
    """Each take lists the pads started during it and none from earlier takes."""
    r=MasterRig();r.set('played_gen',first)
    files=['A:\\SOUND_PAD\\PAD%d\\SOUND%d.WAV'%(p+1,p) for p in range(4)]
    for p,path in enumerate(files):putstr(r.m,config(p),path)
    for n,pads in enumerate(([0,1],[2],[3,0],[1])):
        M.normal_recording_state(r.m);putstr(r.m,M.TAKE_DIR,'A:\\RECORDER\\261011_14%04d'%n)
        r.m.invoke(N['mr_admit'],[])
        for p in pads:r.play(p)
        r.m.invoke(N['mr_stop'],[0,M.REC_STOP]);r.silence()
        assert r.stop_played()==[files[p] for p in pads],(hex(first),n,r.stop_played())
        assert r.field('played_gen')!=0,(hex(first),n)
        r.settle()
    return dict(takes=4)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    passed('both_holds_toggle_once_per_hold_at_any_uptime',ages={a:panel(a) for a in AGES})
    passed('the_led_show_lasts_two_seconds_and_its_redraw_is_retried_at_any_uptime',
           ages={f'{a}/{b}':show(a,b) for a in AGES for b in (1000,2100,2400)})
    passed('the_holds_arm_one_second_after_main_first_received_at_any_start_tick',
           ages={a:arming(a) for a in ('fresh','late_start')})
    passed('pad_folders_wait_two_seconds_after_a_storage_change_at_any_uptime',ages={a:anchors(a) for a in AGES})
    counts=(0,HALF-45,WRAP-45,WRAP-600)
    passed('reposts_keep_their_pace_across_the_poll_count_wrap',polls={hex(n):reposts(n) for n in counts})
    values=(0,HALF-2,WRAP-2)
    passed('take_serials_stay_ordered_across_their_sign_change_and_wrap',serials={hex(n):serials(n) for n in values})
    passed('the_played_generation_wraps_without_reusing_old_entries',generations={hex(n):played(n) for n in values})
    result=dict(passed=True,groups=len(cases),results=cases,ages={k:[hex(v&0xffffffff) for v in a] for k,a in AGES.items()},
        limitations=['Runs on the trial link (status query, no stereo AUX module); panel.c and master_ref.c are the release sources',
                     'Time is a tick word written by the test; nothing runs for days',
                     'The anchor relist retry shares the poll-count expression tested for reposts and is not run here',
                     "Zoom's own use of the tick is not examined"])
    (ROOT/'analysis/long_uptime_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
