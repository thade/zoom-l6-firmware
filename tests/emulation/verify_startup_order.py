#!/usr/bin/env python3
"""Execute bounded stock startup paths; peripherals and scheduling are fixtures.

This audit intentionally does not authorize any startup/release hook.
"""
import hashlib
import json
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn.arm_const import UC_CPU_ARM_CORTEX_M7
from verify_overdub_prototype import Emulator
from verify_reload_queue_audit import QueueRig
from verify_pad_protocol import ROOT, IMAGE, BIAS
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop

SCHEDULER=0x801f9048
INIT=0x801f8f1c


class StartupRig(QueueRig):
    def __init__(self,fail=None,real_scheduler=False):
        # Reuse only the allocator/task fixture helpers; do not initialize first.
        self.m=Emulator(cpu_model=UC_CPU_ARM_CORTEX_M7,mclass=True)
        self.allocations=[];self.tasks=[];self.next=0x21000000
        self.events=[];self.mutexes=0;self.queue_calls=0
        self.init_result=None;self.kernel_entered=False;self.idle_failed=False
        m=self.m
        m.uc.mem_map(0x20220000,0xe000)
        m.uc.mem_write(0x20220000,IMAGE[0x800a9408-BIAS:0x800a9408-BIAS+0xd6dc])
        m.uc.mem_map(0xe000e000,0x1000)
        # Early cache/board initialization is outside this bounded audit.
        for fn in (0x8001b320,0x8001b650):
            m.hooks[fn]=lambda a,fn=fn:self.events.append(hex(fn)) or 0
        m.hooks[0x8006de78]=self.allocate
        for fn in (0x80073ec8,0x80073f18):m.hooks[fn]=lambda a:0
        def task(a):
            assert self.word(SCHEDULER)==0
            # Original early timer setup has already enabled this source.
            assert self.word(0xe000e010)==7
            n=len(self.tasks)+1
            result=self.task(a)
            if fail==('task',n) or (fail==('idle',1) and n==36):
                put32(m,a[5],0);return 0xffffffff
            return result
        m.hooks[0x80076c60]=task
        def mutex(a):
            self.mutexes+=1
            return 0 if fail==('mutex',self.mutexes) else 0x5555
        m.hooks[0x80076318]=mutex
        original_allocate=self.allocate
        def allocate(a):
            self.queue_calls+=1
            return 0 if fail==('queue',self.queue_calls) else original_allocate(a)
        m.hooks[0x8006de78]=allocate
        if not real_scheduler:
            def scheduler(a):
                self.init_result=a[0];self.events.append('scheduler');return 0
            m.hooks[0x800745b8]=scheduler
        else:
            def entered(a):self.kernel_entered=True;return stop(m)
            def failed(a):self.idle_failed=True;return stop(m)
            m.hooks[0x80076158]=entered
            m.hooks[0x80074628]=failed

    def boot(self):return self.m.invoke(0x80067a60,[])


def main():
    results=[]
    def passed(case,**kw):results.append(dict(case=case,**kw))
    r=StartupRig();assert r.boot()==0
    assert len(r.tasks)==35 and r.mutexes==86 and r.queue_calls==8
    assert r.init_result==0 and r.word(SCHEDULER)==0
    assert r.word(0x801f8f38)!=0 and r.m.uc.mem_read(INIT,1)==b'\1'
    assert r.word(0xe000e014)==599999 and r.word(0xe000e010)==7
    assert r.m.uc.mem_read(0xe000ed23,1)==b'\xf0'
    passed('stock_boot_configures_SysTick_before_creating_tasks_and_queues',
           stock_tasks=r.tasks,limits='Timer register writes execute; no interrupt is delivered')

    for fail in (('task',1),('mutex',1),('queue',1),('queue',7)):
        r=StartupRig(fail);assert r.boot()==0
        assert r.init_result==0xffffffff and r.events[-1]=='scheduler'
        assert r.m.uc.mem_read(INIT,1)==b'\1'
        assert (r.word(0x801f8f38)==0)==(fail==('queue',7))
        before=(len(r.tasks),r.mutexes,r.queue_calls)
        assert r.m.invoke(0x80048248,[])==0
        assert before==(len(r.tasks),r.mutexes,r.queue_calls)
    passed('initializer_failure_is_ignored_by_boot_and_latched_done_flag_is_not_success',
           injected_failures=['first task','first mutex','first queue','RecPlayCtl queue'])

    r=StartupRig(real_scheduler=True);r.boot()
    assert r.kernel_entered and not r.idle_failed and r.word(SCHEDULER)==1
    assert len(r.tasks)==36 and r.tasks[-1]['stack_words']==90
    assert r.tasks[-1]['creation_priority']==0
    passed('stock_idle_task_is_created_after_the_candidate_optional_registration_site')
    r=StartupRig(('idle',1),real_scheduler=True);r.boot()
    assert r.idle_failed and not r.kernel_entered and r.word(SCHEDULER)==0
    passed('stock_idle_creation_failure_reaches_terminal_spin',
           limits='Forced creator failure; no heap-exhaustion threshold measured')

    # Execute the Main task, its board-initialization control flow, and the UI
    # startup prefix. Child drivers and clock/delay effects are fixtures.
    m=Emulator();events=[]
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for addr,size,op,arg in md.disasm_lite(IMAGE[0x8001b0e8-BIAS:0x8001b2a2-BIAS],0x8001b0e8):
        if op in ('bl','b.w') and arg.startswith('#'):
            target=int(arg[1:],16)
            if target!=0x8000178e:
                m.hooks[target]=lambda a,target=target:events.append(hex(target)) or 0
    for fn in (0x800328f8,0x8002f8a0,0x80008bc0,0x80009a40,0x80034de8,
               0x80009848,0x80009930,0x8003bc30,0x800402c0,0x80076950):
        m.hooks[fn]=lambda a,fn=fn:events.append(hex(fn)) or 0
    def boundary(a):events.append('UI_mode_selection');return stop(m)
    # Stop at a caller instruction, not the shared getter used during board init.
    m.hooks[0x8002c21a]=boundary
    m.invoke(0x8006dd70,[])
    assert events.count('0x80077686')==4
    assert events.index('0x80077686')<events.index('0x8002f8a0')<events.index('0x80009a40')
    assert events[-1]=='UI_mode_selection'
    passed('Main_task_waits_during_setup_and_card_setup_occurs_in_later_UI_prefix',
           events=events,limits='Driver results and elapsed time are fixtures; no successful mount inferred')

    report=dict(passed=True,groups=len(results),results=results,
                firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
                limitations=['No whole-device boot, interrupts, preemption, DMA or real storage',
                             'Successful task creation and synchronization allocation are fixtures',
                             'Only selected original startup bodies execute; early board/cache setup is intercepted',
                             'No production initialization/release hook is approved or installed'])
    out=ROOT/'analysis/startup_order_verification.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(results))))


if __name__=='__main__':main()
