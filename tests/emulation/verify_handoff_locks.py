#!/usr/bin/env python3
"""Bounded original prefetch/public-read lock trace, with modeled RTOS tokens.

Original filesystem lock selectors, task-context getter and error-frame setup
execute. Driver bytes, conversion, scheduler, gate and sealing remain fixtures.
This does not prove DMA completion, arbitrary scheduling or device readiness.
"""
import hashlib,json,struct
from unicorn.arm_const import UC_CPU_ARM_CORTEX_M7
from verify_overdub_prototype import Emulator
from verify_simple_handoff import Simple
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT,IMAGE

SCRATCH=0x7100
FS1=0x7101
SLOTS={0x80446868:SCRATCH,**{0x801f8da0+i*4:0x7100+i for i in range(1,7)}}
TASK=0x21039000

def word(m,p):return struct.unpack('<I',m.uc.mem_read(p,4))[0]

class Locks(Simple):
    # Needed for the original MRS IPSR in the task-context getter. This is an
    # emulator configuration, not a claim that the physical MCU is Cortex-M7.
    emulator_factory=staticmethod(lambda:Emulator(cpu_model=UC_CPU_ARM_CORTEX_M7,mclass=True))
    def __init__(self):
        super().__init__()
        self.trace=[];self.tokens=set();self.blocked=None;self.reserve=None
        self.task=TASK;self.contexts=[];self.queue_calls=[]
        m=self.m
        for fn in (0x8001bf88,0x8002b100,0x8002b110,0x8002b130,
                   0x80035168,0x80035180,0x80035190,0x800351b0,
                   0x80032810,0x80001848):
            m.hooks.pop(fn,None)
        for slot,token in SLOTS.items():put32(m,slot,token)
        # Actual getter 32810 -> 32448 reads IPSR, then calls this task source.
        m.hooks[0x800770e8]=lambda a:self.task
        m.hooks[0x80076950]=self.take_token
        m.hooks[0x800763d8]=self.give_token
        m.hooks[0x800483f8]=lambda a:self.queue_calls.append(a[:2]) or 0

    def take_token(self,a):
        token=a[0]
        if token not in SLOTS.values():return 1 # unrelated modeled engine calls
        assert a[1]==0xffffffff
        self.trace.append(('take',token,sorted(self.tokens)))
        if token in self.tokens:
            self.blocked=token;return stop(self.m) # suspend, never fake success
        self.tokens.add(token);return 1

    def give_token(self,a):
        token=a[0]
        if token not in SLOTS.values():return 1
        assert token in self.tokens,('unowned give',token,self.trace)
        self.trace.append(('give',token,sorted(self.tokens)))
        self.tokens.remove(token);return 1

    def enter(self,a):
        result=super().enter(a)
        if result==0 and self.reserve is not None:self.tokens.add(self.reserve)
        return result

    def read(self,a):
        h,buffer,size,out=a[:4]
        assert FS1 in self.tokens
        current=word(self.m,0x801f8df0)
        assert current==self.task
        self.contexts.append(current)
        if 0x80735b80<=buffer<0x8077c580:
            assert self.locked and SCRATCH in self.tokens
            self.trace.append(('sample_read',size,sorted(self.tokens)))
        return super().read(a)

    def convert(self,a):
        assert SCRATCH in self.tokens and FS1 not in self.tokens
        self.trace.append(('convert',a[1],sorted(self.tokens)))
        return super().convert(a)

    def leave(self,a):
        assert not self.tokens
        assert word(self.m,0x801f8df0)==0 # public-call task context was retired
        self.trace.append(('leave',))
        return super().leave(a)

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,**data))
    r=Locks();assert r.step()==0 and not r.blocked and not r.tokens
    reads=[t for t in r.trace if t[0]=='sample_read']
    assert reads==[('sample_read',5120,[SCRATCH,FS1])]
    assert r.contexts and set(r.contexts)=={TASK} and not r.queue_calls
    passed('prefetch_takes_scratch_then_filesystem_and_drops_filesystem_before_conversion',
           sample_trace=[t for t in r.trace if t[0] in ('sample_read','convert','leave')])

    for task in (0x21039000,0x2103a000):
        r=Locks();r.task=task;assert r.step()==0
        assert set(r.contexts)=={task} and not r.queue_calls
    passed('public_read_records_the_calling_worker_without_requiring_the_sample_file_task')

    r=Locks();raw=r.files[r.capture.result()[1]]
    raw.extend(bytes(range(256))*2400)
    struct.pack_into('<I',raw,4,len(raw)-8);struct.pack_into('<I',raw,508,len(raw)-512)
    assert r.step()==0
    reads=[t for t in r.trace if t[0]=='sample_read']
    assert len(reads)>1 and all(t[2]==[SCRATCH,FS1] for t in reads)
    assert not r.tokens and not r.queue_calls
    passed('multi_chunk_prefetch_repeats_the_same_lock_order_without_queued_read_waits',chunks=len(reads))

    for kind in ('error','short'):
        r=Locks();assert r.step()==0;r.next();r.trace=[];r.read_failures=[kind]
        assert r.step()==7 and not r.tokens and not r.locked
        assert len([t for t in r.trace if t[0]=='sample_read'])==2
    passed('read_failure_and_short_read_release_native_locks_before_verified_rollback')

    for token in (SCRATCH,FS1):
        r=Locks();r.reserve=token;r.step()
        assert r.blocked==token and token in r.tokens and r.locked
        assert not r.prefetch_reads and not any(t[0]=='leave' for t in r.trace)
    passed('a_gate_holding_scratch_or_filesystem_token_blocks_its_own_handoff',
           limitation='Controlled suspension at contended RTOS take; not hardware deadlock timing')

    # Direct public read with an already-owned context: stock explicitly rejects
    # reentry from the same task. Keep FS1 held to model the enclosing operation.
    r=Locks();assert r.step()==0
    h=next(h for h,v in r.handles.items() if v[0]==r.paths()[0])
    put32(r.m,0x801f8dc4,TASK);r.tokens.add(FS1)
    count=len(r.contexts)
    result=r.m.invoke(0x80060620,[h,0x2102c000,8,0x2102c100])
    assert result==0xffffd825 and len(r.contexts)==count
    assert FS1 not in r.tokens
    passed('same_task_filesystem_reentry_is_rejected_before_driver_and_releases_domain',
           result=hex(result),note='Do not implement admission by nesting an existing filesystem operation')

    report=dict(passed=True,groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
            'Original prefetch, public wrapper, lock selectors and task-context setup execute.',
            'RTOS tokens, driver bytes, conversion, gate and sealing remain modeled.',
            'Contended waits suspend the CPU; no physical timing or arbitrary interleavings.',
            'Lower SD/DMA lifetime, all scratch users and the eventual gate remain unproved.',
            'No device access, firmware patch image or gate implementation.'])
    (ROOT/'analysis/handoff_locks_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),cases=[r['case'] for r in results]),indent=2))

if __name__=='__main__':main()
