#!/usr/bin/env python3
"""Tracked read pins versus complete native pad load/unload operations."""
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_CPU_ARM_CORTEX_M7, UC_ARM_REG_PC
from verify_read_ingress import Ingress, CTX, LEDGER, DRIVER
from verify_reload_prefetch import PrefetchRig
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT, RETURN
from verify_read_worker import CURRENT
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_work_ownership import OK, BUSY, CONFLICT, STALE, FAULT

OUT=0x2102b000
YIELD=DRIVER+0x90


def bind_guard(r):
    r.m.hooks[YIELD]=lambda a:stop(r.m)
    assert r.m.invoke(r.m.symbols['pf_bind'],[CTX,YIELD|1])==OK
    for address,name in ((0x800092a0,'load'),(0x800096f8,'unload')):
        def redirect(uc,a,n,u,name=name):uc.reg_write(UC_ARM_REG_PC,r.m.symbols['pf_'+name]|1)
        r.m.uc.hook_add(UC_HOOK_CODE,redirect,begin=address,end=address)


class Guarded(Ingress):
    def __init__(self):super().__init__();bind_guard(self)
    def pf(self,name,*args):return self.m.invoke(self.m.symbols['pf_'+name],list(args))


class Native(PrefetchRig):
    emulator_factory=staticmethod(lambda:Emulator(cpu_model=UC_CPU_ARM_CORTEX_M7,mclass=True))
    def __init__(self):
        super().__init__();self.run();self.consume()
        put32(self.m,CTX,LEDGER);put32(self.m,CURRENT,0x7999);bind_guard(self)
    def pf(self,name,*args):return self.m.invoke(self.m.symbols['pf_'+name],list(args))
    def pin(self,slot=0,pad=0):
        assert self.pf('pin',CTX,slot,pad,OUT)==OK
        return struct.unpack('<2I',self.m.uc.mem_read(OUT,8))


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    r=Guarded();owner=r.run()
    assert r.reads==8 and r.verify(owner) and r.retire()==OK
    for pad in range(4):
        assert r.pf('change_begin',pad,0x7999)==OK
        assert r.pf('change_end',pad,0x7999)==OK
    passed('eight_ingress_reads_release_pins_only_after_join_and_original_load_unload_paths_finish')

    r=Guarded();r.delivery=False;r.schedule=False;r.submit();r.worker()
    assert r.reads==0 and len(r.wire)==1
    assert r.pf('change_begin',0,0x7999)==BUSY
    assert r.pf('change_begin',1,0x7999)==OK and r.pf('change_end',1,0x7999)==OK
    passed('undelivered_tracked_read_keeps_its_pad_pinned_without_blocking_an_unrelated_pad')

    r=Native();handle,first=r.pin();_,second=r.pin(1)
    assert r.pf('change_begin',0,0x7999)==BUSY
    assert r.pf('drop',0,first)==OK and r.pf('change_begin',0,0x7999)==BUSY
    assert r.pf('drop',0,first)==STALE
    assert r.pf('drop',1,second)==OK and r.pf('change_begin',0,0x7999)==OK
    assert r.pf('change_end',0,0x7888)==CONFLICT
    assert r.pf('pin',CTX,0,0,OUT)==BUSY
    assert r.pf('change_end',0,0x7999)==OK
    passed('two_readers_pin_one_pad_and_wrong_or_duplicate_release_cannot_remove_other_ownership')

    r=Native();handle,token=r.pin()
    before=bytes(r.m.uc.mem_read(0x807348d0,0x22c))
    engine=bytes(r.m.uc.mem_read(0x80735180,0x44))
    closes=r.counts.get('close',0)
    r.m.invoke(0x800096f8,[0]) # Pauses in the compiled wrapper before stock entry.
    context=r.m.uc.context_save()
    assert bytes(r.m.uc.mem_read(0x807348d0,0x22c))==before
    assert bytes(r.m.uc.mem_read(0x80735180,0x44))==engine
    assert handle in r.handles and r.counts.get('close',0)==closes
    assert r.pf('drop',0,token)==OK
    r.m.uc.context_restore(context);r.m.reached_return=False
    r.m.uc.emu_start(r.m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=10000000)
    assert r.m.reached_return and handle not in r.handles
    assert r.word(0x807348d0)==0 and r.word(0x807348d4)==0
    assert r.counts.get('close',0)==closes+1
    assert r.pf('pin',CTX,0,0,OUT)==CONFLICT # Stale queue-handle word cannot admit a read.
    r.m.invoke(0x800092a0,[0,0]);new_handle,new_token=r.pin()
    assert new_token>token and new_handle
    assert r.pf('drop',0,token)==STALE and r.pf('change_begin',0,0x7999)==BUSY
    assert r.pf('drop',0,new_token)==OK
    passed('blocked_native_unload_changes_nothing_then_closes_once_after_release_and_reloads_with_fresh_pin')

    r=Native();_,token=r.pin()
    opens=r.counts.get('open',0);before=bytes(r.m.uc.mem_read(0x807348d0,0x22c))
    r.m.invoke(0x800092a0,[0,0])
    assert r.counts.get('open',0)==opens and bytes(r.m.uc.mem_read(0x807348d0,0x22c))==before
    assert r.pf('drop',0,token)==OK
    passed('native_loader_waits_before_opening_or_overwriting_pad_state')

    r=Native();assert r.pf('change_begin',0,0x7999)==OK
    assert r.pf('pin',CTX,0,0,OUT)==BUSY
    assert r.pf('change_end',0,0x7999)==OK
    handle,token=r.pin();assert r.pf('drop',0,token)==OK
    put32(r.m,0x80735b24,handle+4)
    assert r.pf('pin',CTX,0,0,OUT)==CONFLICT
    assert r.pf('bind',CTX,YIELD|1)==CONFLICT
    passed('mutation_excludes_new_pins_and_snapshot_rejects_disagreeing_native_handle_tables')

    r=Native();handle,token=r.pin()
    put32(r.m,0x807348d4+0x22c,handle)
    assert r.pf('change_begin',1,0x7999)==BUSY
    assert r.pf('drop',0,token)==OK and r.pf('change_begin',1,0x7999)==OK
    # Even if the mutator clears its published handle midway, the snapshot
    # continues excluding aliases until the entire original function returns.
    put32(r.m,0x807348d4+0x22c,0)
    assert r.pf('pin',CTX,0,0,OUT)==BUSY
    assert r.pf('change_end',1,0x7999)==OK
    passed('another_pad_aliasing_the_same_handle_cannot_close_a_pinned_file')

    r=Guarded();r.delay=0;joins=[];held=[]
    latch=r.m.symbols['pad_files']+8
    def hold(uc,a,n,u):
        joins.append(1)
        if len(joins)==1:put32(r.m,latch,1)
    def pause(a):
        if r.word(latch):
            held.append(1)
            if len(held)==2:put32(r.m,latch,0)
        return r.pause_read(a)
    r.m.hooks[DRIVER+0x80]=pause
    join=r.m.symbols['rr_finish']&~1
    r.m.uc.hook_add(UC_HOOK_CODE,hold,begin=join,end=join)
    owner=r.run()
    assert len(held)==2 and len(joins)==8 and r.verify(owner) and r.retire()==OK
    passed('busy_pin_release_retries_release_only_without_rejoining_or_repeating_file_IO')

    for mode in ('short','error'):
        r=Guarded();r.read_mode=mode;owner=r.run()
        assert r.verify(owner) and r.retire()==FAULT
        assert r.pf('change_begin',0,0x7999)==OK
        assert r.pf('change_end',0,0x7999)==OK
    passed('observed_failed_reads_release_file_pins_after_join_while_reload_failure_is_retained')

    out=ROOT/'analysis/pad_file_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Pins cover tracked producer reads versus explicitly wrapped native pad load/unload paths',
        'Direct filesystem close, handle-table stores, ordinary reads and card teardown are not covered',
        'Mutation wrappers may wait while callers hold stock resources; lock-order/deadlock audit remains required',
        'Original load/unload and compiled guard execute; scheduling/files/DSP effects are fixtures',
        'Optional guard must bind cold and all relevant wrappers activate together; no firmware installation']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
