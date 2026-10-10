#!/usr/bin/env python3
"""Five encoded Main receive calls retain requests across optional file closure.

Original receive/dispatch instructions run. FIFO copying, kernel scheduling,
deep UI effects and positive physical I/O completion are explicit fixtures.
"""
from collections import deque
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_storage_transitions import TransitionRig,PLAN,N,ELF
from verify_storage_lease import Pending,IO_ERROR
from verify_storage_stop import finish_storage
from verify_native_worker import MAIN_HANDLE
from verify_control_transport import TASK
from verify_session_manager import BLOCKED
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT,IMAGE,BIAS,RETURN
from verify_reload_queue_audit import packed,UI_SLOT
from plan_capture_transitions import RECEIVERS,receive_patch

UI_HANDLE=0x2103e000
BUFFER=0x20031000
LOOPS=((0x8002c256,A.UC_ARM_REG_R5),(0x8002c39a,A.UC_ARM_REG_R4),
       (0x8002c3d2,A.UC_ARM_REG_R4),(0x8002c406,A.UC_ARM_REG_R4),
       (0x8002c43e,A.UC_ARM_REG_R4))
LATER=(1,4,26,71,72)

class MainRig(TransitionRig):
    def ui_setup(self,packets):
        self.ui=deque(packed(p) for p in packets);self.delays=[];self.dispatched=[]
        self.effects=[];self.waiting=None;self.main_context=None
        m=self.m;put32(m,UI_SLOT,UI_HANDLE)
        prior_receive=m.hooks[0x800483a8];prior_send=m.hooks[0x800763d8]
        def receive(a,blocking=True):
            if a[0]!=UI_HANDLE:return prior_receive(a)
            if not self.ui:
                if not blocking:return 0xffffffff
                self.waiting='empty';return stop(m)
            m.uc.mem_write(a[1],self.ui.popleft());put32(m,UI_HANDLE+0x38,len(self.ui));return 0
        def send(a):
            if a[0]!=UI_HANDLE:return prior_send(a)
            assert len(self.ui)<4096
            self.ui.append(self.raw(a[1],20));put32(m,UI_HANDLE+0x38,len(self.ui));return 1
        def delay(a):
            assert a[0]==1
            self.delays.append(1);self.waiting='join';return stop(m)
        m.hooks[0x800483a8]=receive
        m.hooks[0x800483d0]=lambda a:receive(a,False)
        m.hooks[0x800763d8]=send
        m.hooks[0x80074158]=delay
        for address in (0x80034530,0x800344e0,0x8001e4d8,0x8003bd58,
                        0x8003f0c8,0x80030fb0):
            m.hooks[address]=lambda a,address=address:self.effects.append((address,tuple(a[:3]))) or 0
        for address in (0x8003f0b8,0x80006290,0x800060d0,0x8000a220):m.hooks[address]=lambda a:0
        for address in (0x800061f0,0x80006238):m.hooks[address]=lambda a:1
        m.hooks[0x80034da8]=lambda a:0xffffffff
        m.hooks[0x80008b68]=lambda a:self.dispatched.append(('reload',self.lstate())) or 0
        m.hooks[0x8000a5d8]=lambda a:self.effects.append(('card_tail',)) or 0
        m.hooks[0x800350d8]=lambda a:self.effects.append(('ordinary_stop',)) or 0
        put32(m,UI_HANDLE+0x38,len(self.ui))
    def run_main(self,start=LOOPS[-1]):
        def run():
            self.m.uc.reg_write(start[1],self.m.stack+4)
            self.m.invoke(start[0],[])
            self.main_context=self.m.uc.context_save()
        self.other(run,MAIN_HANDLE)
    def resume_main(self):
        def run():
            self.m.uc.context_restore(self.main_context);put32(self.m,TASK,MAIN_HANDLE)
            self.waiting=None;self.m.reached_return=False
            self.m.uc.emu_start(self.m.uc.reg_read(A.UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
            assert self.m.reached_return
            self.main_context=self.m.uc.context_save()
        self.other(run,MAIN_HANDLE)
    def packets(self):return [struct.unpack('<5I',p) for p in self.ui]

class MainPending(Pending,MainRig):pass

def main():
    cases=[]
    def passed(name,**details):cases.append(dict(case=name,**details))

    patches=[p for p in PLAN['patches'] if p.get('adapter')=='storage_main_receive']
    assert [p['site'] for p in patches]==[s for s,_ in RECEIVERS]
    for site,old in RECEIVERS:
        bad=bytearray(IMAGE);bad[site-BIAS]^=1
        for stock,target in ((bad,N['storage_main_receive']),(IMAGE,N['storage_main_receive']&~1),(IMAGE,0x10010001)):
            try:receive_patch(stock,site,old,target)
            except ValueError:pass
            else:raise AssertionError('Invalid receive patch accepted')
    passed('All five original BL sites are byte checked, independently decoded and reject mismatched inputs',
           packed_spare_bytes=PLAN['packing']['spare_bytes'])

    # At each actual Main loop, preserve its stack packet/register and handler
    # route. A fresh closed lease retires synchronously without touching files.
    for loop in LOOPS:
        r=MainRig();assert r.boot()==0;r.ui_setup([(1,0,2,91,92),LATER])
        def handler(a):
            r.dispatched.append((struct.unpack('<5I',r.raw(a[0],20)),r.lstate()));return 0
        r.m.hooks[0x8002d568]=handler;r.run_main(loop)
        assert r.dispatched==[((1,0,2,91,92),3),(LATER,3)]
        assert r.waiting=='empty' and not r.delays and not r.calls
    passed('All five original Main loops deliver the retained request and following packet in order, once each')

    changes=[(0,9,c,0x1234,0x5678) for c in range(0x32,0x36)]
    changes += [(1,0,c,0x1234,0x5678) for c in range(6)]
    changes += [(2,s,c,0x1234,0x5678) for s in (0,3,4,0xffffffff) for c in (0xa2,0xa3)]
    ordinary=[(0,0,0x31,1,2),(0,0,0x36,1,2),(1,0,6,1,2),(1,1,2,1,2),
              (2,3,0xa1,1,2),(2,4,0xa1,1,2),(2,4,0xa4,1,2),(3,0,0,1,2),LATER]
    for packet in changes+ordinary:
        r=MainRig();assert r.boot()==0;r.ui_setup([packet])
        assert r.other(lambda:r.m.invoke(N['storage_main_receive'],[BUFFER]),MAIN_HANDLE)==0
        assert r.raw(BUFFER,20)==packed(packet) and not r.packets()
        assert r.lstate()==(3 if packet in changes else 0)
    passed('Conservative card, USB, power and mode classification preserves complete original packet bytes',
           cancellation_cases=len(changes),ordinary_cases=len(ordinary))

    for absent in ('allocation','binding'):
        r=MainRig();assert r.boot()==0;r.ui_setup([changes[0],LATER])
        if absent=='allocation':put32(r.m,N['startup_arena'],0)
        else:put32(r.m,r.lease(),0)
        assert r.other(lambda:r.m.invoke(N['storage_main_receive'],[BUFFER]),MAIN_HANDLE)==0
        assert not r.delays and r.raw(BUFFER,20)==packed(changes[0]) and r.packets()==[LATER]
    passed('Failed optional allocation or cold binding leaves original receive usable')

    combinations=0
    for loop in LOOPS[-2:]:
        for code in (0x32,0x33):
            for phase in ('create','initial_header','audio','final_header','read_header',
                          'read_audio','close_write','close_read'):
                r=MainPending();assert r.boot(release=True)==0
                if phase in ('create','initial_header'):
                    r.pause=phase;r.wait_pending()
                else:
                    r.ready();r.begin_recording()
                    for _ in range(5):r.audio_call();r.tick()
                    r.pause=phase
                    if phase=='audio':r.wait_pending(audio=True)
                    else:r.stop_recording();r.wait_pending(audio=True)
                worker_frame=r.frame();pending=r.pending;before=list(r.calls)
                packet=(0,9 if code==0x32 else 0,code,0,0)
                # Native mode bodies stay stock up to their established lower
                # driver fixtures. Observe whether the outer body was entered.
                r.install(3 if code==0x32 else 2)
                r.ui_setup([packet,LATER]);r.run_main(loop)
                assert r.waiting=='join' and r.packets()==[LATER] and not r.transition_events
                assert r.frame()==worker_frame and r.pending==pending and r.calls==before
                for _ in range(3):
                    r.resume_main()
                    assert r.waiting=='join' and r.packets()==[LATER] and not r.transition_events
                    assert r.frame()==worker_frame and r.pending==pending
                r.complete();finish_storage(r)
                assert r.lstate()==3 and not r.opened
                r.resume_main()
                assert r.waiting=='empty' and not r.packets() and r.transition_events
                assert r.dispatched==[('reload',3)]
                combinations+=1
    passed('Real normal and alternate dispatch hold all eight pending file phases before card or USB side effects',
           combinations=combinations,physical_completion='explicit positive fixture')

    r=MainPending();assert r.boot(release=True)==0;r.ready()
    r.pause='close_write';r.install(3);r.ui_setup([(0,9,0x32,0,0),LATER]);r.run_main()
    assert r.waiting=='join';r.wait_pending();r.complete(IO_ERROR)
    r.drive(lambda:r.mstate()==BLOCKED,with_audio=False)
    calls=list(r.calls)
    for _ in range(6):
        r.resume_main()
        assert r.waiting=='join' and not r.transition_events and r.packets()==[LATER]
        assert r.calls==calls and r.opened
    passed('Uncertain file close retains Main request indefinitely without retry, timeout, later dispatch or native teardown')

    r=MainRig();assert r.boot(release=True)==0;r.ready();r.request()
    wire=list(r.wire);r.ui_setup([(1,0,2,1,2),LATER])
    r.m.hooks[0x8002d568]=lambda a:r.dispatched.append((tuple(struct.unpack('<5I',r.raw(a[0],20))),r.lstate())) or 0
    r.run_main();assert r.waiting=='join' and r.wire==wire
    finish_storage(r);assert r.wire==wire and r.lstate()==3
    r.resume_main();assert r.waiting=='empty' and len(r.dispatched)==2 and r.wire==wire
    r.dispatch_all();assert not r.wire and r.mstate()==12
    passed('Actual Main retention joins storage without delivering an old control callback; retained callback later completes')

    # Original receive timer helpers must remain ahead of handler effects.
    # Their deeper kernel timers and power state are separately modeled here.
    r=MainRig();assert r.boot()==0;r.ui_setup([(0,9,0x32,0,0)])
    assert r.other(lambda:r.m.invoke(N['storage_main_receive'],[BUFFER]),MAIN_HANDLE)==0
    assert [a[0] for a in r.effects]==[0x80034530,0x800344e0]
    passed('Original receive housekeeping remains before the gate; no extra Main packet or private queue is introduced')

    out=ROOT/'analysis/storage_main_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,device_access=False,
        stock_sha256=hashlib.sha256(IMAGE).hexdigest(),fixture_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['Original receiver, encoded BLs and selected Main/native handlers execute; startup admission remains absent.',
            'Kernel copy/wakeup, task progress, lower UI/native mode effects and physical SD completion are fixtures.',
            'Finite classified ingress; not exhaustive indirect-call or native-lock-dependency proof.',
            'A stalled physical close deliberately stalls Main; this does not establish recovery or real timing.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
