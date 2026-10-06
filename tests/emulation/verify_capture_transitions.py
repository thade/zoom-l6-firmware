#!/usr/bin/env python3
"""Capture-only cancellation beside original file and transition instructions.

Native open/write/close wrappers, lock selectors and task-context setup execute.
Files, kernel waits, scheduling and physical completion are explicit fixtures.
No gate, firmware image or device operation is supplied by this experiment.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_PROT_NONE
from unicorn import arm_const as A
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT,IMAGE,REGS,INPUT,RETURN
from verify_firmware_workflow import HANDLE,VOLUME,TABLE,RESULT,put32
from verify_record_catalogue import putstr
from verify_record_scheduler import word
from verify_scheduling_boundaries import stop
from verify_capture_integration import IntegrationRig
from verify_extra_lifecycle import LifeRig
from verify_native_worker import WORKER,HANDLE as WORKER_TASK
from verify_control_transport import TASK
from verify_session_manager import MAN,LIVE,STOPPED,BLOCKED

FS1,FS2,FS4,FS5,FS6=0x7101,0x7102,0x7104,0x7105,0x7106
UI=0x7110
SLOTS={0x801f8da0+i*4:0x7100+i for i in range(1,7)}|{0x80446810:UI}
SELECTORS=(0x8001bf88,0x8002b100,0x8002b110,0x8002b130,
           0x80035168,0x80035180,0x80035190,0x800351b0,0x80032810)
POOL=0x801f9270
IO_ERROR=0xffffd825

class FileLocks:
    def __init__(self,m,task,send=None,ordinary_events=False):
        self.m=m;self.task=task;self.send=send
        self.ordinary_events=ordinary_events
        self.tokens={UI};self.trace=[];self.blocked=None
        for fn in SELECTORS:m.hooks.pop(fn,None)
        for slot,token in SLOTS.items():put32(m,slot,token)
        m.hooks[0x800770e8]=lambda a:self.task()
        m.hooks[0x80001848]=lambda a:0 # exception-frame construction is modeled
        m.hooks[0x80076950]=self.take;m.hooks[0x800763d8]=self.give
        # The selected file paths must not call Main event service to complete.
        for fn in (0x8006e4b8,0x80020360,0x80020438,0x80020548):
            m.hooks[fn]=self.main_event

    def main_event(self,a):
        # An independently scheduled ordinary caller may run while another
        # task retains a filesystem exception frame. Only a service call from
        # the task owning that frame would be a file-path Main dependency.
        if self.ordinary_events and word(self.m,0x801f8df0)!=self.task():return 0
        raise AssertionError('Unexpected Main/UI event dependency')
    def take(self,a):
        token=a[0]
        if token not in SLOTS.values():return 1 # unrelated control-queue mutex
        assert a[1]==0xffffffff
        self.trace.append(('take',token))
        if token in self.tokens:self.blocked=token;return stop(self.m)
        self.tokens.add(token);return 1
    def give(self,a):
        token=a[0]
        if token not in SLOTS.values():return self.send(a) if self.send else 1
        assert token in self.tokens,('unowned give',token,self.trace)
        assert token!=UI,'File path released the unavailable UI token'
        self.trace.append(('give',token));self.tokens.remove(token);return 1
    def driver(self,kind):
        expected={UI,FS1,FS2,FS4,FS5,FS6} if kind=='open' else {UI,FS1,FS2,FS4} if kind=='close' else {UI,FS1}
        assert self.tokens==expected,(kind,self.tokens)
        assert word(self.m,0x801f8df0)==self.task()

class Files:
    def __init__(self):
        self.m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True);m=self.m
        m.uc.mem_protect(0x10000000,0x10000,UC_PROT_NONE)
        self.task=0x21039000;self.locks=FileLocks(m,lambda:self.task)
        self.calls=[];self.status=0;self.pending=False;self.suspend=False
        m.hooks[0x8001d9b0]=lambda a:0;m.hooks[0x800670b0]=lambda a:VOLUME
        m.uc.mem_write(VOLUME+0x206,b'\x01');put32(m,VOLUME+0x258,TABLE)
        for i in range(24):m.uc.mem_write(POOL+i*0x2c4,b'\xff')
        m.uc.mem_write(HANDLE,b'\x40\x02');put32(m,HANDLE+0x230,VOLUME)
        putstr(m,INPUT,'A:\\SOUND_PAD\\PAD1\\OD_TEST.TMP')
        m.hooks[0x800604e8]=lambda a:self.driver('open',a)
        m.hooks[0x8005c388]=lambda a:self.driver('close',a)
    def driver(self,kind,a):
        self.locks.driver(kind);self.calls.append((kind,tuple(a[:4])))
        if self.suspend:self.pending=True;return stop(self.m)
        return self.status
    def open(self):return self.m.invoke(0x8005ffe8,[RESULT,INPUT,0x501,0x80])
    def close(self):return self.m.invoke(0x8005c1f8,[HANDLE])
    def complete_close(self,status):
        m=self.m;assert self.pending and m.uc.reg_read(A.UC_ARM_REG_PC)==0x8005c31c
        m.uc.reg_write(REGS[0],status);m.reached_return=False
        m.uc.emu_start(0x8005c31d,RETURN+2,count=100000)
        assert m.reached_return
        return m.uc.reg_read(REGS[0])

class CaptureFiles(IntegrationRig):
    """Real extra-file open/write/close frames around the logical file fixture.

    Ordinary files retain the existing integration model. Suspending a driver
    retains the whole compiled worker/manager/bridge/lifecycle/public-call stack.
    Other tasks use a different stack and preserve that CPU context explicitly.
    """
    def __init__(self):
        super().__init__();m=self.m
        self.locks=FileLocks(m,lambda:word(m,TASK),self.kernel_send,ordinary_events=True)
        self.native=[];self.pause=None;self.pending=None;self.joined=True
        self.unsafe_close=False
        for fn in (0x8005ffe8,0x8005c1f8,0x800622b0):m.hooks.pop(fn,None)
        m.hooks[0x8001d9b0]=lambda a:0;m.hooks[0x800670b0]=lambda a:VOLUME
        m.uc.mem_write(VOLUME+0x206,b'\x01');put32(m,VOLUME+0x258,TABLE)
        for i in range(24):m.uc.mem_write(POOL+i*0x2c4,b'\xff')
        m.hooks[0x800604e8]=self.open_driver
        m.hooks[0x800624a8]=self.write_driver
        m.hooks[0x8005c388]=self.close_driver
        # Only extra handles use the native write wrapper. Ordinary files are
        # still logical bytearrays, as in verify_capture_integration.py.
        def ordinary_write(uc,pc,n,u):
            args=[uc.reg_read(r) for r in REGS]
            if args[0] in self.files:
                uc.reg_write(REGS[0],self.io_write(args));uc.reg_write(A.UC_ARM_REG_PC,uc.reg_read(A.UC_ARM_REG_LR))
        m.uc.hook_add(UC_HOOK_CODE,ordinary_write,begin=0x800622b0,end=0x800622b0)

    def request(self,ui=0):
        # The inherited request fixture replaces kernel endpoints. Restore the
        # stricter file-token model before any native file operation can run.
        try:return super().request(ui)
        finally:
            self.m.hooks[0x80076950]=self.locks.take
            self.m.hooks[0x800763d8]=self.locks.give

    def suspend(self,kind,a):
        self.native.append((kind,tuple(a[:4])))
        self.locks.driver(kind)
        if self.pause==kind:
            assert not self.pending
            self.pause=None;self.joined=False;self.pending=(kind,tuple(a[:4]))
            return True
        return False
    def open_driver(self,a):
        # The read-only final-name probe deliberately reports NOT_FOUND.
        if a[2] and self.suspend('open',a):return stop(self.m)
        if not a[2]:self.locks.driver('open')
        return self.finish_open(a)
    def finish_open(self,a):
        # Public open supplies its reserved native pool slot, not an output
        # pointer. Convert only the logical fixture's handle, preserving the ABI.
        h,p,flags,attrs=a[:4]
        scratch=0x2103e100
        status=LifeRig.open_file(self,[scratch,p,flags,attrs])
        if status:return status
        logical=word(self.m,scratch);self.opened[h]=self.opened.pop(logical)
        self.m.uc.mem_write(h,b'\x40'+bytes([2 if flags else 0]));put32(self.m,h+0x230,VOLUME)
        return 0
    def write_driver(self,a):
        if self.suspend('write',a):return stop(self.m)
        return LifeRig.write_file(self,a)
    def close_driver(self,a):
        if not self.joined:
            self.unsafe_close=True;return stop(self.m) # retain the violating frame
        if self.suspend('close',a):return stop(self.m)
        return self.finish_close(a)
    def finish_close(self,a):
        status=LifeRig.close_file(self,a)
        self.m.uc.mem_write(a[0],b'\xff');return status
    def other_task(self,task,operation):
        m=self.m;context=m.uc.context_save();previous=word(m,TASK);stack=m.stack
        m.stack=0x20030000;put32(m,TASK,task)
        try:return operation()
        finally:m.stack=stack;put32(m,TASK,previous);m.uc.context_restore(context)
    def request_cancel(self):return self.other_task(0x21037100,self.cancel)
    def worker_busy(self):
        return self.other_task(WORKER_TASK,lambda:self.m.invoke(self.syms['native_worker_poll'],[WORKER]))
    def frame(self):
        sp=self.m.uc.reg_read(A.UC_ARM_REG_SP)
        return self.raw(sp,self.m.stack-sp)
    def complete(self,status=0,physical_join=True):
        m=self.m;kind,args=self.pending
        resume={'open':0x80060444,'write':0x80062464,'close':0x8005c31c}[kind]
        assert m.uc.reg_read(A.UC_ARM_REG_PC)==resume
        self.joined=physical_join
        if status==0:
            assert physical_join,'Do not claim logical success while physical work remains'
            status={'open':self.finish_open,'write':lambda a:LifeRig.write_file(self,a),
                    'close':self.finish_close}[kind](list(args))
        elif kind=='write':put32(m,args[3],0)
        self.pending=None
        previous=word(m,TASK);put32(m,TASK,WORKER_TASK)
        m.uc.reg_write(REGS[0],status);m.reached_return=False
        try:m.uc.emu_start(resume|1,RETURN+2,count=100000000)
        finally:put32(m,TASK,previous)
        assert m.reached_return
    def running(self):
        assert self.boot(release=True)==0;self.ready();self.begin_recording()
        self.audio_call();self.tick();assert self.mstate()==LIVE
    def pending_write(self):
        self.pause='write'
        for _ in range(12):
            self.audio_call();self.tick()
            if self.pending:return
        raise AssertionError('Expected one pending payload batch')
    def finish_cancel(self):self.drive(lambda:self.mstate()==STOPPED,with_audio=False)

class Transitions:
    """Execute the outer native ordering with lower transition effects modeled."""
    def __init__(self,entry,mode=1,profile=0,present=1,status=IO_ERROR):
        self.m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True);m=self.m
        m.uc.mem_protect(0x10000000,0x10000,UC_PROT_NONE)
        self.events=[];self.entry=entry
        for fn in (0x80034568,0x80008608,0x8000a198,0x80006ca8,
                   0x80061f60,0x8005f0d0,0x80006aa8,0x80077686,
                   0x80009b18,0x80009a40,0x8003b8a0,0x8003b7e0,
                   0x80062230,0x800075a8,0x80002ce8,0x80009840,
                   0x80009930,0x8000b2a8,0x800088d0):
            if fn==entry:continue
            result=status if fn in (0x80009b18,0x80009a40,0x8003b8a0,0x8003b7e0,0x80062230) else 0
            m.hooks[fn]=lambda a,fn=fn,result=result:self.events.append((fn,tuple(a[:2]))) or result
        m.hooks[0x800345f8]=lambda a:0x1234
        m.hooks[0x80006290]=lambda a:mode;m.hooks[0x80005e28]=lambda a:profile
        m.hooks[0x8001fca0]=lambda a:present;m.hooks[0x80005e90]=lambda a:1
        put32(m,0x8045b620,0xa55a)
    def invoke(self,args):return self.m.invoke(self.entry,args)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    for status in (0,IO_ERROR):
        r=Files();r.status=status
        assert r.open()==status and word(r.m,RESULT)==(POOL if status==0 else 0)
        assert r.locks.trace==[('take',t) for t in (FS1,FS2,FS6,FS5,FS4)]+[('give',t) for t in (FS4,FS5,FS6,FS1,FS2)]
        assert r.locks.tokens=={UI} and word(r.m,0x801f8df0)==0
    passed('native_open_has_five_tokens_and_releases_them_on_driver_success_and_error_without_UI')

    for status in (0,IO_ERROR):
        r=Files();r.status=status
        assert r.close()==status
        assert r.locks.trace==[('take',t) for t in (FS1,FS2,FS4)]+[('give',t) for t in (FS4,FS1,FS2)]
        assert r.locks.tokens=={UI} and word(r.m,0x801f8df0)==0
    passed('native_close_has_three_tokens_and_propagates_error_without_UI')

    for operation,tokens in (('open',(FS1,FS2,FS6,FS5,FS4)),('close',(FS1,FS2,FS4))):
        for token in tokens:
            r=Files();r.locks.tokens.add(token);getattr(r,operation)()
            assert r.locks.blocked==token and not r.calls
    passed('a_transition_guard_holding_any_required_file_token_blocks_open_or_close_before_driver')

    for status in (0,IO_ERROR):
        r=Files();r.suspend=True;r.close()
        assert r.pending and r.locks.tokens=={UI,FS1,FS2,FS4}
        assert word(r.m,0x801f8df0)==r.task
        assert r.complete_close(status)==status and r.locks.tokens=={UI}
        assert word(r.m,0x801f8df0)==0
    passed('unfinished_close_retains_original_frame_tokens_and_context_until_driver_return')

    r=Files()
    for i in range(24):r.m.uc.mem_write(POOL+i*0x2c4,b'\x40')
    assert r.open()!=0 and not r.calls and word(r.m,RESULT)==0 and r.locks.tokens=={UI}
    r=Files();r.m.uc.mem_write(HANDLE,b'\xff')
    assert r.close()!=0 and not r.calls and r.locks.tokens=={UI}
    passed('exhausted_handle_pool_and_invalid_close_release_tokens_without_driver_calls')

    r=CaptureFiles();r.running();r.request_cancel();r.finish_cancel()
    assert not r.opened and r.result()==12 and r.locks.tokens=={UI}
    assert r.queued_record and r.recording # optional cancellation never sent STOP
    r.audio_call();ordinary=r.stop_recording()
    assert all(ordinary[h]==struct.pack('<%df'%len(r.expected[h]),*r.expected[h]) for h in range(1,8))
    r.assert_ordinary()
    passed('compiled_capture_cancel_closes_native_extra_file_while_ordinary_recording_continues')

    r=CaptureFiles();r.pause='open';assert r.boot(release=True)==0
    for _ in range(32):
        r.tick()
        if r.pending:break
    assert r.pending and r.pending[0]=='open';frame=r.frame();r.request_cancel()
    before=list(r.native);assert r.worker_busy()==11 and r.native==before
    assert r.frame()==frame
    assert r.locks.tokens=={UI,FS1,FS2,FS4,FS5,FS6}
    r.complete();r.finish_cancel()
    assert not r.opened and r.result()==12 and r.locks.tokens=={UI}
    passed('cancellation_during_native_creation_waits_for_retained_worker_then_closes_unpublished_file')

    r=CaptureFiles();r.running();r.pending_write();frame=r.frame();r.request_cancel()
    before=list(r.native);assert r.worker_busy()==11 and r.native==before
    assert r.locks.tokens=={UI,FS1} and r.mstate()!=STOPPED and r.opened
    # Main and audio get different stacks while the native write frame is live.
    r.other_task(0x21039000,r.audio_call)
    assert r.pending and r.opened and r.locks.tokens=={UI,FS1}
    assert r.frame()==frame
    r.complete();r.finish_cancel()
    assert not r.opened and r.result()==12 and r.locks.tokens=={UI}
    passed('cancel_pending_native_write_cannot_reenter_worker_and_waits_for_explicit_modeled_join')

    for status in (0,IO_ERROR):
        r=CaptureFiles();r.running();r.pause='close';r.request_cancel();r.tick()
        assert r.pending and r.pending[0]=='close' and r.mstate()!=STOPPED
        assert r.locks.tokens=={UI,FS1,FS2,FS4} and r.worker_busy()==11
        r.complete(status)
        r.drive(lambda:r.mstate() in (STOPPED,BLOCKED),with_audio=False)
        assert r.mstate()==(STOPPED if status==0 else BLOCKED)
        assert r.result()==12 and r.locks.tokens=={UI}
        if status:
            calls=list(r.native)
            for _ in range(3):r.tick()
            assert r.native==calls and r.resume()==12 and r.opened
    passed('native_close_completion_controls_cancellation_and_close_error_blocks_reuse_without_retry')

    # Negative control: the current direct public-file ports do not join SD/DMA.
    # Force a software error return with physical work still outstanding. The
    # compiled lifecycle attempts close; intercept there and retain its frame.
    r=CaptureFiles();r.running();r.pending_write();r.request_cancel()
    r.complete(IO_ERROR,physical_join=False)
    assert r.unsafe_close and not r.joined and r.mstate()!=STOPPED
    assert r.opened and r.locks.tokens=={UI,FS1,FS2,FS4}
    assert word(r.m,WORKER+20)==1 and word(r.m,MAN+12)==1
    passed('software_write_timeout_alone_reaches_unsafe_close_in_current_capture_ports',
           negative_control=True,physical_completion='withheld; close intercepted before driver effects')

    for profile in range(3):
        r=Transitions(0x8000c220,profile=profile);assert r.invoke([1,profile])==0
        addrs=[e[0] for e in r.events]
        assert addrs.index(0x80009b18)<addrs.index(0x8003b7e0)
        assert r.events[addrs.index(0x8003b7e0)][1]==(6+2*profile,0x1234)
        assert word(r.m,0x8045b620)==0 and addrs[-1]==0x80006aa8
    passed('USB_request_guard_is_too_late_for_prior_card_release_and_outer_ignores_release_error')

    for present in (0,1):
        r=Transitions(0x8000c288,present=present);assert r.invoke([1])==0
        addrs=[e[0] for e in r.events]
        assert addrs[0]==0x8003b8a0 and addrs[-2]==(0x80009a40 if present else 0x80009b18)
        assert addrs[-1]==0x80006aa8 and word(r.m,0x8045b620)==0
    passed('USB_stop_error_is_not_retained_by_outer_transition_before_mount_or_detach')

    for mode in (0,1):
        for profile in range(3):
            for present in (0,1):
                r=Transitions(0x8000c2d8,mode,profile,present);assert r.invoke([1])==0
                addrs=[e[0] for e in r.events]
                assert addrs[:3]==[0x80034568,0x80008608,0x8003b8a0]
                request=r.events[addrs.index(0x8003b7e0)]
                assert request[1]==(5+mode+2*profile,0x1234)
                assert addrs[-1]==0x80006aa8 and word(r.m,0x8045b620)==0
                assert addrs.count(0x80009b18)==(0 if not mode else 1 if present else 2)
    passed('alternate_USB_transition_has_effects_before_stop_and_can_release_card_twice')

    r=Transitions(0x80009b18);assert r.invoke([])==0
    assert [e[0] for e in r.events]==[0x80062230,0x800075a8,0x80002ce8,
        0x80009840,0x80009930,0x800075a8,0x8000b2a8,0x800088d0]
    passed('returning_busy_or_error_from_detach_cannot_protect_outer_release_cleanup')

    report=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
            'Native public file wrappers and compiled capture-only lifecycle execute on one CPU.',
            'Logical file bytes, path/volume lookup, kernel tokens and scheduling are modeled.',
            'Physical join is explicit fixture input, not detected by new production code.',
            'Close driver/FAT metadata/cache behavior and lazy volume registration remain untraced.',
            'Outer transition effects are modeled; no complete transition gate or caller coverage.',
            'No device access, image construction or installed storage release.'])
    (ROOT/'analysis/capture_transitions_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),cases=[c['case'] for c in cases]),indent=2))

if __name__=='__main__':main()
