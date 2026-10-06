#!/usr/bin/env python3
"""Native ABI adapter tests; task scheduling and delay completion are fixtures."""
import json
import struct
from verify_manager_boot import ColdRig
from verify_session_manager import MAN, RESET, PREPARE, STAGE, ACTIVATE, LIVE, STOPPED, BLOCKED
from verify_session_handover import DESC
from verify_control_transport import TASK
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_pad_protocol import ROOT

WORKER=0x2201f000
CONFIG=0x21036000
HANDLE=0x21037000
SCHEDULER=0x801f9048
MAIN_SLOT=0x80446da4
MAIN_HANDLE=0x21037100


class WorkerRig(ColdRig):
    def __init__(self,count=32):
        super().__init__(count)
        self.wlayout=struct.unpack('<5I',self.raw(self.syms['native_worker_layout'],20))
        self.m.uc.mem_write(WORKER,bytes(self.wlayout[0]))
        # Fixture choices only: not selected or measured device settings.
        self.m.uc.mem_write(CONFIG,struct.pack('<5I',4096,1,4,1,25))
        put32(self.m,SCHEDULER,0)
        self.creates=[]
        def create(a):
            self.creates.append(a[:6])
            assert self.raw(a[1],10)==b'L6Overdub\0'
            assert a[0]==self.syms['native_worker_entry'] and a[2:5]==[4096,WORKER,1]
            assert a[5]==WORKER+self.wlayout[1]
            put32(self.m,a[5],HANDLE);return 1
        self.m.hooks[0x80076c60]=create

    def release(self):
        previous=word(self.m,TASK);put32(self.m,TASK,MAIN_HANDLE)
        put32(self.m,MAIN_SLOT,MAIN_HANDLE)
        try:return self.m.invoke(self.syms['native_worker_release'],[WORKER])
        finally:put32(self.m,TASK,previous)

    def boot(self,pad=0,serial=1,release=True):
        self.m.uc.mem_write(self.m.stack,struct.pack('<2I',pad,serial))
        status=self.m.invoke(self.syms['native_worker_register'],[WORKER,MAN,DESC,CONFIG])
        if status==0:
            put32(self.m,SCHEDULER,1)
            # Explicit readiness fixture, not a recovered production hook.
            if release:assert self.release()==0
        return status

    def tick(self):
        previous=word(self.m,TASK);put32(self.m,TASK,HANDLE)
        try:status=self.m.invoke(self.syms['native_worker_poll'],[WORKER])
        finally:put32(self.m,TASK,previous)
        self.session=word(self.m,MAN+16)
        assert word(self.m,WORKER+self.wlayout[4])<=4
        return status

    def loops(self,count):
        delays=[]
        def delay(a):
            delays.append(a[0])
            if len(delays)==count:
                self.m.reached_return=True;self.m.uc.emu_stop()
            return 0
        self.m.hooks[0x80074158]=delay
        previous=word(self.m,TASK);put32(self.m,TASK,HANDLE)
        try:self.m.invoke(self.syms['native_worker_entry'],[WORKER])
        finally:put32(self.m,TASK,previous)
        return delays


def main():
    results=[]
    def passed(case,**kw):results.append(dict(case=case,**kw))
    r=WorkerRig(4096);assert r.boot()==0 and len(r.creates)==1 and not r.calls
    assert r.loops(3)==[1,1,1] and r.mstate() in (RESET,PREPARE,STAGE,ACTIVATE)
    assert word(r.m,r.syms['ct_active'])==0 # no control admission before audio adoption
    r.ready();first=r.take(2);second=r.take(3)
    assert bytes(r.disk[first[1]])==first[2] and r.result()==second[:2]
    passed('native_registration_arguments_and_bounded_worker_drive_first_boot_and_two_takes')

    r=WorkerRig();assert r.boot()==0
    before=r.raw(MAN,r.mlayout[0]);calls=list(r.calls)
    assert r.m.invoke(r.syms['native_worker_poll'],[WORKER])==12
    assert r.raw(MAN,r.mlayout[0])==before and r.calls==calls
    put32(r.m,SCHEDULER,0)
    previous=word(r.m,TASK);put32(r.m,TASK,HANDLE)
    assert r.m.invoke(r.syms['native_worker_poll'],[WORKER])==12
    put32(r.m,TASK,previous);put32(r.m,SCHEDULER,1)
    r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    assert r.loops(3)==[1,1,1] and r.mstate()==ACTIVATE
    r.cancel();r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    before=r.raw(MAN,r.mlayout[0]);assert r.loops(3)==[25,25,25]
    assert r.raw(MAN,r.mlayout[0])==before and word(r.m,WORKER+r.wlayout[4])==0
    passed('wrong_task_or_scheduler_state_cannot_run_manager_and_wait_stopped_paths_sleep')

    r=WorkerRig();assert r.boot()==0
    r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    r.inject=('close_write',1,'error');r.cancel()
    r.drive(lambda:r.mstate()==BLOCKED,with_audio=False)
    before=r.raw(MAN,r.mlayout[0]);assert r.loops(2)==[25,25]
    assert r.raw(MAN,r.mlayout[0])==before and r.resume()==12
    passed('uncertain_close_keeps_blocked_manager_and_worker_does_not_retry')

    for failed_allocation in (1,2):
        r=WorkerRig();del r.m.hooks[0x80076c60]
        allocations=[];freed=[]
        def allocate(a):
            allocations.append(a[0]);return 0 if len(allocations)==failed_allocation else 0x21038000
        r.m.hooks[0x8006de78]=allocate
        r.m.hooks[0x80073f48]=lambda a:freed.append(a[0])
        # Original task-creation failure path executes, including its rollback.
        assert r.boot()==13 and not r.calls
        assert allocations==([16384] if failed_allocation==1 else [16384,148])
        assert freed==([] if failed_allocation==1 else [0x21038000])
        assert word(r.m,WORKER+r.wlayout[2])==3
        assert word(r.m,r.syms['ct_active'])==0 and word(r.m,r.syms['emulator_bridge_current'])==0
        assert word(r.m,r.syms['ct_gateway_readers'])==0x80000000
        assert r.boot()==12  # Do not implicitly reinitialize after failed creation.
    passed('stock_task_creator_allocation_failures_leave_capture_closed_and_free_partial_stack')

    r=WorkerRig();r.m.hooks[0x80076c60]=lambda a:1
    assert r.boot()==13 and word(r.m,WORKER+r.wlayout[2])==3
    passed('success_without_task_handle_does_not_enable_worker')

    for field,value in ((0,1023),(0,65536),(1,32),(2,0),(2,17),(3,0),(4,0),(4,1001)):
        r=WorkerRig();put32(r.m,CONFIG+4*field,value)
        assert r.boot()==12 and not r.creates and not r.calls and r.mstate()==0
        assert word(r.m,r.syms['ct_gateway_readers'])==0
    for reason in ('scheduler','queue','overlap','dirty'):
        r=WorkerRig()
        if reason=='scheduler':put32(r.m,SCHEDULER,1)
        elif reason=='queue':put32(r.m,0x801f8f38,0)
        elif reason=='overlap':put32(r.m,DESC,WORKER)
        else:put32(r.m,WORKER,1)
        assert r.boot()==12 and not r.creates and not r.calls
    passed('invalid_config_runtime_state_missing_queue_overlapping_or_dirty_worker_rejected')

    r=WorkerRig();assert r.boot(release=False)==0
    before=r.raw(MAN,r.mlayout[0]);assert r.loops(5)==[25]*5
    assert r.raw(MAN,r.mlayout[0])==before and not r.calls
    assert word(r.m,WORKER+r.wlayout[2])==4
    assert word(r.m,r.syms['ct_active'])==0
    assert word(r.m,r.syms['emulator_bridge_current'])==0
    # Neither a missing main handle, another task, nor a stopped scheduler can
    # authorize release. The release API deliberately cannot prove readiness.
    assert r.m.invoke(r.syms['native_worker_release'],[WORKER])==12
    put32(r.m,MAIN_SLOT,MAIN_HANDLE)
    assert r.m.invoke(r.syms['native_worker_release'],[WORKER])==12
    put32(r.m,SCHEDULER,0);assert r.release()==12
    put32(r.m,SCHEDULER,1);assert r.release()==0 and r.release()==12
    r.ready();r.take(2)
    passed('registered_worker_sleeps_without_manager_or_file_work_until_explicit_main_release')

    report=dict(passed=True,groups=len(results),results=results,
                fixture_config=dict(stack_words=4096,priority=1,steps_per_pass=4,poll_ticks=1,idle_ticks=25),
                limits=['No native task scheduling, preemption or real passage of delay time',
                        'Successful task creation intercepted; original failure branches executed with allocator fixtures',
                        'Configuration values are test inputs, not verified device budgets',
                        'Startup release is explicit fixture authorization; no device readiness hook is established',
                        'Bounded step count does not bound blocking filesystem duration',
                        'No startup hook installed, code/RAM address assigned or device accessed'])
    (ROOT/'analysis/native_worker_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(results))))


if __name__=='__main__':main()
