#!/usr/bin/env python3
"""Original reload/prefetch with a synchronous compiled read callback.
One CPU, explicit saved-register scheduling, separate fixture task stacks.
Kernel, file effects, conversion and enclosing reload scopes remain fixtures.
"""
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_CPU_ARM_CORTEX_M7, UC_ARM_REG_PC
from verify_overdub_prototype import Emulator
from verify_reload_prefetch import PrefetchRig, FILE_QUEUE, READ_SEM
from verify_pad_reload import BUSY_WORD
from verify_read_producer import Producers, IDS, T0, P_YIELD
from verify_read_worker import CURRENT
from verify_reload_read_queue import READ, SECOND
from verify_work_ownership import OK, FAULT
from verify_scheduling_boundaries import stop
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, RETURN, STACK, REGS


class CallbackRig(PrefetchRig):
    emulator_factory=staticmethod(lambda:Emulator(cpu_model=UC_CPU_ARM_CORTEX_M7,mclass=True))
    def __init__(self):
        super().__init__()
        self.p=Producers(self.m)
        self.io_cpu=self.m # All native code and shared memory use the same CPU.
        self.ordinary=False;self.suspended=False;self.resumes=0;self.callback_entries=[]
        self.schedule=True;self.delay_reads=3;self.hold_join=0;self.mutate_tag=False
        self.join_hold_remaining=0;self.join_blocks=0
        self.m.hooks.pop(0x800483f8);self.m.hooks.pop(0x800483a8)
        self.m.hooks[0x80076710]=self.receive_native
        self.m.hooks[0x800763d8]=self.send_native
        self.m.hooks[0x80076950]=self.wait_native
        self.m.hooks[0x80060620]=self.read_native
        self.m.hooks[P_YIELD]=self.pause_producer
        self.m.uc.hook_add(UC_HOOK_CODE,self.redirect,begin=0x80036208,end=0x80036208)
    def redirect(self,uc,address,size,user):
        if not self.ordinary:
            self.callback_entries.append(self.word(CURRENT))
            uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rp_callback']|1)
    def receive_native(self,a):
        if a[0]==FILE_QUEUE:return self.p.receive(a)
        result=super().dequeue(a)
        return 1 if result==0 else result
    def send_native(self,a):
        if a[0]==FILE_QUEUE:return self.p.signal(a)
        if a[0]==0x6543:return 1 if super().enqueue(a)==0 else 0
        return 1 # Original file-worker signal / unrelated synchronization.
    def wait_native(self,a):
        if a[0]!=READ_SEM:return 1
        self.p.waits.append(self.word(CURRENT))
        if self.ordinary:
            # Stock callback has no join loop: model its blocking semaphore
            # by scheduling the queued worker before resuming this stack.
            self.suspended=True;stop(self.m)
        # Deliberately report an early wake, before scheduling the file worker.
        return self.p.wait_result
    def read_native(self,a):
        self.p.reads+=1
        # Identify the stock pad handle without depending on handle allocation.
        self.read_pad=next(i for i in range(4) if self.word(0x80735b24+20*i)==a[0])
        return super().read_samples(a)
    def convert(self,a):
        buffer,frames,dest,pad,channels,width=a[:6]
        # The completed ticket must precede conversion on the original caller.
        if not self.ordinary:
            slot=READ if self.word(CURRENT)==IDS[0] else SECOND
            assert self.word(slot+4)==7 # RR_DONE
        data=bytes(self.m.uc.mem_read(buffer,frames*channels*width))
        self.converted.append((pad,data));return len(data)
    def pause_producer(self,a):
        self.suspended=True;return stop(self.m)
    def execute(self,address,args,role):
        self.p.select(role);self.suspended=False
        result=self.m.invoke(address,args)
        for _ in range(150):
            if not self.suspended:return result
            self.resumes+=1
            # Save after the fixture yield has returned to its compiled caller.
            context=self.m.uc.context_save()
            if self.p.waits and len(self.p.waits)>self.p.reads and self.schedule:
                if self.delay_reads and not self.ordinary:self.delay_reads-=1
                else:
                    self.m.stack=0x20030000
                    self.p.run()
                    self.m.stack=STACK
                    if self.hold_join:
                        put32(self.m,READ,1)
                        self.join_hold_remaining=self.hold_join;self.hold_join=0
            elif self.join_hold_remaining:
                self.join_blocks+=1;self.join_hold_remaining-=1
                if not self.join_hold_remaining:put32(self.m,READ,0)
            if self.mutate_tag:put32(self.m,T0+12,self.p.owner+100)
            self.m.uc.context_restore(context);self.p.select(role)
            self.suspended=False;self.m.reached_return=False
            self.m.uc.emu_start(self.m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=10000000)
            assert self.m.reached_return
            result=self.m.uc.reg_read(REGS[0])
        return None # Bounded fixture observation of a still-suspended callback.
    def dispatch(self):return self.execute(0x80036290,[],0)
    def consume(self):
        # Same UI dependencies as ReloadRig; invoke via the saved-stack scheduler.
        self.ui=[]
        self.m.hooks[0x8001e4d8]=lambda a:0
        self.m.hooks[0x80018350]=lambda a:self.ui.append(('stop',a[0])) or 0
        self.m.hooks[0x8000ac90]=lambda a:0
        self.m.hooks[0x80006b18]=lambda a:self.ui.append(('save',self.word(BUSY_WORD))) or 0
        self.m.hooks[0x8000a5d8]=lambda a:self.ui.append(('refresh',self.word(BUSY_WORD))) or 0
        self.m.uc.mem_write(0x21008000,struct.pack('<5I',*self.events_reload[-1][1:6]))
        return self.execute(0x8002d568,[0x21008000],1)


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    r=CallbackRig();r.run();r.consume()
    assert len(r.converted)==8 and r.callback_entries==[IDS[0]]*4+[IDS[1]]*4
    assert len(r.p.sent)==len(r.p.waits)==r.p.reads==8 and r.p.end()==OK
    for pad,data in r.converted:
        raw=r.files[r.expected[pad]];assert data==bytes(raw[raw.find(b'data')+8:])
    passed('eight_original_prefetch_calls_wait_inside_compiled_callback_before_exact_conversion')

    for mode in ('short','error'):
        r=CallbackRig();r.read_mode=mode;r.run();r.consume()
        assert len(r.converted)==8 and r.p.end()==FAULT
    r=CallbackRig();r.p.wait_result=0;r.run();r.consume()
    assert len(r.converted)==8 and r.p.end()==OK
    passed('joined_IO_failures_reject_reload_but_coalesced_notifications_do_not')

    r=CallbackRig();r.hold_join=4;r.run();r.consume()
    assert r.join_blocks==4 and len(r.converted)==8
    assert len(r.p.sent)==len(r.p.waits)==8 and r.p.end()==OK
    passed('suspended_callback_resumes_on_its_original_stack_without_replaying_send_or_wait')

    r=CallbackRig();r.p.deliver=False;r.schedule=False;r.run()
    assert len(r.p.sent)==len(r.p.waits)==1 and not r.converted and not r.callback_returns
    assert not any(e[0]=='event' for e in r.events_reload)
    passed('undelivered_read_never_returns_to_conversion_or_reload_event')

    r=CallbackRig();r.mutate_tag=True;r.run()
    assert not r.converted and not r.callback_returns and r.p.word()&0x40000000
    passed('changed_parent_identity_parks_callback_and_latches_fault_instead_of_returning_busy')

    r=CallbackRig();r.ordinary=True;r.run();r.consume()
    assert len(r.converted)==8 and r.p.reads==8 and not r.callback_entries
    assert r.word(READ+4)==r.word(SECOND+4)==0
    for raw in r.p.sent:assert struct.unpack('<4I',raw)[0]==0
    for pad,data in r.converted:
        raw=r.files[r.expected[pad]];assert data==bytes(raw[raw.find(b'data')+8:])
    passed('explicit_ordinary_route_keeps_stock_callback_and_creates_no_read_tracking_evidence')

    r=CallbackRig();r.execute(r.m.symbols['rp_callback'],[4,0x21010000,16],0)
    assert not r.p.sent and not r.converted and r.p.word()&0x40000000
    passed('invalid_attributed_request_parks_without_publishing_or_returning_to_its_caller')

    out=ROOT/'analysis/read_callback_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Original assignment/UI reload and prefetch execute with compiled read callback and file adapter on one CPU',
        'Callback entry redirection is fixture supplied only for attributed reload tests; no installed dispatcher',
        'Reload RUNNING scopes, queue copying, semaphore outcomes, task scheduling and file effects are fixtures',
        'Saved-register switches and separate stacks test callback continuation, not real RTOS preemption',
        'Invariant failures park the caller; production fault isolation and storage lifetime remain unresolved',
        'No device access, firmware patch, physical placement or startup release']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
