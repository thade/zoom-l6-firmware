#!/usr/bin/env python3
"""Compiled ordinary callbacks and worker boundaries on one emulator CPU.
Native parent attribution, queue scheduling and file effects remain fixtures.
"""
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_LR
from verify_read_ingress import Ingress, FQ, FSEM, FID, WID, UID, CTX, LEDGER, DRIVER
from verify_pad_file import bind_guard
from verify_firmware_workflow import put32
from verify_work_ownership import OK, BUSY, CONFLICT, STALE
from verify_read_worker import CURRENT
from verify_pad_protocol import ROOT, RETURN, STACK, REGS

CONFIG=0x2102d000
OUT=CONFIG+0x100
BUFFER=0x21030000
SEEK_SEM=0x7013
OTHER=0x7999
OTHER_WORD=0x808e2990


class Ordinary(Ingress):
    def __init__(self,bind=True):
        super().__init__();bind_guard(self)
        self.ordinary_packets=[];self.seeks=[];self.signals=[];self.wait_args=[]
        self.parent_ticket=0;self.parent_status=OK;self.wait_result=1
        self.seek_status=0;self.test_mode=None;self.after_io=None;self.after_signal=None
        put32(self.m,0x80446800,SEEK_SEM);put32(self.m,OTHER_WORD,OTHER)
        sym=lambda s:self.m.symbols[s]|1
        self.m.uc.mem_write(CONFIG,struct.pack('<25I',CTX,
            WID,UID,OTHER,*([0]*5),0x80446dc8,0x80446da4,OTHER_WORD,*([0]*5),
            FQ,FSEM,SEEK_SEM,sym('rc_stock_send'),0x80076951,DRIVER+0x81,
            DRIVER+0xa1,0x8005f169))
        self.m.hooks[DRIVER+0xa0]=self.parent
        self.m.hooks[0x8005f168]=self.seek_public
        def seek_entry(uc,a,n,u):uc.reg_write(UC_ARM_REG_PC,sym('rp_seek_entry'))
        self.m.uc.hook_add(UC_HOOK_CODE,seek_entry,begin=0x80036250,end=0x80036250)
        def seek_boundary(uc,a,n,u):
            uc.reg_write(UC_ARM_REG_LR,(a+4)|1);uc.reg_write(UC_ARM_REG_PC,sym('rw_seek'))
        self.m.uc.hook_add(UC_HOOK_CODE,seek_boundary,begin=0x800361bc,end=0x800361bc)
        if bind:assert self.op('bind',CONFIG)==OK
    def op(self,name,*args):return self.m.invoke(self.m.symbols['op_'+name],list(args))
    def pf(self,name,*args):return self.m.invoke(self.m.symbols['pf_'+name],list(args))
    def own(self,name,*args):return self.m.invoke(self.m.symbols['od_own_'+name],[LEDGER,*args])
    def operation(self,slot=0):return self.m.symbols['operations']+76*slot
    def parent(self,a):
        assert a[0]==self.word(CURRENT)
        put32(self.m,a[1],self.parent_ticket);return self.parent_status
    def kernel_send(self,a):
        if a[0] in (FSEM,SEEK_SEM):
            self.signals.append(a[0])
            if self.after_signal:self.after_signal(self)
        if a[0]==FQ:
            raw=bytes(self.m.uc.mem_read(a[1],16))
            if struct.unpack_from('<I',raw)[0]==0x4f494f31:
                self.ordinary_packets.append(raw)
                if self.delivery:self.q[FQ].append(raw)
                return 1 if self.delivery else 0
        return super().kernel_send(a)
    def read_wait(self,a):
        self.waits+=1;self.wait_args.append(tuple(a[:2]));return self.wait_result
    def read_public(self,a):
        if self.test_mode is None:return super().read_public(a)
        self.reads+=1
        if self.test_mode=='error':result=0xffffd825
        else:
            count=dict(normal=64,short=17,eof=0)[self.test_mode]
            self.m.uc.mem_write(a[1],b'R'*count);put32(self.m,a[3],count);result=0
        if self.after_io:self.after_io(self)
        return result
    def seek_public(self,a):
        self.seeks.append(tuple(a[:3]))
        if self.after_io:self.after_io(self)
        return self.seek_status
    def loaded(self):
        owner=self.run();assert self.verify(owner) and self.retire()==OK
        assert self.word(LEDGER)==0;self.signals=[];self.wait_args=[]
        return self
    def invoke_io(self,kind=0,slot=0,pad=0,first=BUFFER,second=64):
        ident=(WID,UID,OTHER)[slot]
        return self.scheduled(0x80036208 if kind==0 else 0x80036250,
                              [pad,first,second],None,ident)
    def result(self,slot=0):
        assert self.m.invoke(self.m.symbols['oi_result'],[self.operation(slot),OUT])==OK
        return struct.unpack('<2I',self.m.uc.mem_read(OUT,8))


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))

    for mode,count,status in (('normal',64,0),('short',17,0),('eof',0,0),('error',0,0xffffd825)):
        r=Ordinary().loaded();assert len(r.wire)==8 and not r.ordinary_packets
        r.test_mode=mode;r.m.uc.mem_write(BUFFER,b'?'*64)
        assert r.invoke_io()==1
        assert r.result()==(status,count) and r.reads==9
        assert len(r.ordinary_packets)==1 and r.wait_args==[(FSEM,1)]
        assert r.signals==[FSEM] and r.word(LEDGER)==0
        if not status:assert bytes(r.m.uc.mem_read(BUFFER,64))==b'R'*count+b'\x00'*(64-count)
        assert r.pf('change_begin',0,OTHER)==OK
    passed('reloads_stay_attributed_then_ordinary_reads_preserve_full_short_eof_and_error_behavior')

    for slot in range(3):
        for status in (0,0xffffd825):
            r=Ordinary().loaded();r.seek_status=status
            assert r.invoke_io(kind=1,slot=slot,first=1234,second=2)==1
            assert r.result(slot)==(status,0) and r.reads==8
            assert r.seeks==[(r.word(0x80735b24),1234,2)]
            assert r.wait_args==[(SEEK_SEM,1)] and r.signals==[SEEK_SEM]
            assert r.word(LEDGER)==0
    passed('seek_from_each_bound_task_uses_matching_ticket_and_distinct_completion_signal')

    for kind in (0,1):
        r=Ordinary().loaded();r.delivery=False;r.schedule=False;r.test_mode='normal'
        assert r.invoke_io(kind=kind) is None
        assert len(r.ordinary_packets)==1 and len(r.wait_args)==1 and r.word(LEDGER)==1
        assert r.reads==8 and not r.seeks
        assert r.pf('change_begin',0,OTHER)==BUSY
        assert r.pf('close_begin',r.word(0x80735b24),OTHER,OUT)==BUSY
    passed('failed_send_and_early_wake_retain_pin_without_resend_wait_or_false_completion')

    r=Ordinary().loaded();r.test_mode='normal';r.wait_result=0
    assert r.invoke_io()==1 and r.result()==(0,64) and r.word(LEDGER)==0
    assert len(r.ordinary_packets)==len(r.wait_args)==1 and r.reads==9
    passed('wait_error_preserves_stock_return_but_still_joins_actual_IO_completion')

    for kind in (0,1):
        r=Ordinary().loaded();r.test_mode='short';observed=[]
        def during_signal(r):
            # Stock worker has performed IO but has not returned from signal.
            observed.append(r.word(r.operation()+4))
            assert r.word(LEDGER)==1
            # Do not reenter compiled code from a Unicorn callback.
        r.after_signal=during_signal
        assert r.invoke_io(kind=kind)==1
        assert observed==[8] and r.word(r.operation()+4)==12
    passed('operation_remains_RUNNING_through_original_signal_and_joins_only_after_worker_return')

    for kind in (0,1):
        r=Ordinary().loaded();r.test_mode='normal';holds=[]
        r.after_io=lambda r:put32(r.m,r.operation(),1)
        original=r.pause_read
        def release(a):
            if r.word(r.operation()):
                holds.append(1)
                if len(holds)==3:put32(r.m,r.operation(),0)
            return original(a)
        r.m.hooks[DRIVER+0x80]=release
        assert r.invoke_io(kind=kind)==1
        assert len(holds)==3 and len(r.signals)==1
        assert r.reads==8+(kind==0) and len(r.seeks)==kind and r.word(LEDGER)==0
    passed('busy_post_IO_observation_retries_without_repeating_read_seek_or_signal')

    r=Ordinary().loaded();r.test_mode='normal'
    r.m.uc.mem_write(OUT,struct.pack('<5I',7,0,0,0,0))
    assert r.own('reserve',OUT,OUT+32)==OK;parent=r.word(OUT+32)
    assert r.own('offer',parent)==OK and r.own('submitted',parent,1)==OK
    assert r.own('claim',parent,OUT)==OK;r.parent_ticket=parent
    assert r.invoke_io(slot=2)==1 and r.word(LEDGER)==1
    assert r.own('finish_session',parent)==OK and r.word(LEDGER)==0
    passed('explicit_parent_port_attaches_ordinary_callback_without_retiring_its_playback_owner')

    r=Ordinary().loaded();r.test_mode='normal';assert r.invoke_io()==1
    stale=r.ordinary_packets[0];r.q[FQ].append(stale)
    assert r.invoke_io()==1 and r.reads==10 and len(r.signals)==2
    assert r.word(LEDGER)==0 and r.ordinary_packets[1]!=stale
    passed('old_packet_is_discarded_before_reused_producer_context_executes_new_read')

    r=Ordinary().loaded();r.test_mode='normal';r.schedule=False
    assert r.invoke_io() is None
    first_context=r.m.uc.context_save()
    assert r.word(LEDGER)==1
    r.schedule=True;r.m.stack=0x20028000
    assert r.invoke_io(kind=1,slot=1,first=1234,second=0)==1
    r.m.stack=0x20028000 # Metadata probes must not overwrite the suspended first stack.
    assert r.reads==9 and len(r.seeks)==1 and r.word(LEDGER)==1
    assert r.word(r.operation()+4)==10 # Returned worker, waiting producer.
    assert r.word(r.operation(1)+4)==12
    assert r.pf('change_begin',0,OTHER)==BUSY
    r.m.uc.context_restore(first_context);put32(r.m,CURRENT,WID)
    r.m.reached_return=False;r.suspended=False
    r.m.uc.emu_start(r.m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=10000000)
    assert r.m.reached_return and not r.suspended and r.m.uc.reg_read(REGS[0])==1
    r.m.stack=STACK
    assert r.result()==(0,64) and r.result(1)==(0,0) and r.word(LEDGER)==0
    passed('two_suspended_native_callers_share_worker_but_release_only_their_own_operation')

    # Pause two readers at the semaphore entry, complete both jobs, then give
    # them a capacity-one notification. Both must join their own returned I/O.
    r=Ordinary().loaded();r.test_mode='normal';contexts=[];blocked=[]
    from verify_scheduling_boundaries import stop
    original_wait=r.m.hooks.pop(0x80076950)
    def pause_wait(uc,a,n,u):
        if uc.reg_read(REGS[0])==FSEM:
            blocked.append(1);stop(r.m)
    token=r.m.uc.hook_add(UC_HOOK_CODE,pause_wait,begin=0x80076950,end=0x80076950)
    for i,ident in enumerate((WID,UID)):
        r.m.stack=STACK-i*0x8000;put32(r.m,CURRENT,ident)
        r.m.invoke(0x80036208,[0,BUFFER+i*128,64]);contexts.append(r.m.uc.context_save())
    r.m.uc.hook_del(token)
    r.m.hooks[0x80076950]=original_wait
    assert len(blocked)==2 and len(r.ordinary_packets)==2
    # This models the original semaphore maximum of one, not two counting
    # tokens. The stock file worker and compiled return tracking still execute.
    r.m.stack=0x20030000;put32(r.m,CURRENT,FID)
    r.m.invoke(0x80036118,[])
    assert r.word(r.operation()+4)==r.word(r.operation(1)+4)==10
    signals=[1]
    def binary_wait(a):
        assert a[:2]==[FSEM,1]
        result=signals[0];signals[0]=0;return result
    r.m.hooks[0x80076950]=binary_wait
    for ident,context in zip((WID,UID),contexts):
        r.m.uc.context_restore(context);put32(r.m,CURRENT,ident)
        r.m.reached_return=False;r.suspended=False
        r.m.uc.emu_start(r.m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=10000000)
        assert r.m.reached_return and not r.suspended and r.m.uc.reg_read(REGS[0])==1
    r.m.stack=STACK
    assert r.word(LEDGER)==0 and r.result()==r.result(1)==(0,64)
    passed('two_completed_reads_join_despite_one_coalesced_binary_semaphore_signal')

    for address,value in ((CONFIG,CTX+4),(CONFIG+4,UID),(CONFIG+36,0),
                          (CONFIG+76,FSEM),(CONFIG+92,0)):
        r=Ordinary(bind=False);old=r.word(address);put32(r.m,address,value)
        assert r.op('bind',CONFIG)==CONFLICT
        put32(r.m,address,old);assert r.op('bind',CONFIG)==OK
        assert r.op('bind',CONFIG)==CONFLICT
    passed('binding_rejects_mismatch_duplicate_identity_and_missing_attribution_without_partial_activation')

    for address in (CTX+4,LEDGER+4,CTX+392,CTX+396,CTX+400):
        r=Ordinary(bind=False);put32(r.m,address,1)
        assert r.op('bind',CONFIG)==BUSY
        put32(r.m,address,0);assert r.op('bind',CONFIG)==OK
    passed('busy_coordinator_or_storage_admission_prevents_partial_ordinary_binding')

    r=Ordinary(bind=False);r.loaded();assert r.op('bind',CONFIG)==BUSY
    passed('ordinary_binding_cannot_be_enabled_after_native_traffic_has_started')

    for address,value in ((OTHER_WORD,OTHER+1),(0x80446800,SEEK_SEM+1)):
        r=Ordinary().loaded();put32(r.m,address,value)
        assert r.invoke_io(slot=2) is None
        assert not r.ordinary_packets and r.word(LEDGER)&0x40000000
    passed('changed_task_or_semaphore_identity_parks_without_untracked_fallback')

    r=Ordinary().loaded()
    assert r.scheduled(0x80036208,[0,BUFFER,64],None,0x7888) is None
    assert not r.ordinary_packets and r.word(LEDGER)&0x40000000
    r=Ordinary().loaded();r.parent_status=CONFLICT
    assert r.invoke_io() is None
    assert not r.ordinary_packets and r.word(LEDGER)==0x40000000
    passed('unknown_caller_or_rejected_parent_never_silently_becomes_an_ordinary_root')

    r=Ordinary().loaded();r.test_mode='normal';r.parent_status=BUSY;pauses=[]
    original=r.pause_read
    def release_parent(a):
        if r.parent_status==BUSY:
            assert not r.ordinary_packets and r.word(LEDGER)==0
            pauses.append(1)
            if len(pauses)==3:r.parent_status=OK
        return original(a)
    r.m.hooks[DRIVER+0x80]=release_parent
    assert r.invoke_io()==1 and len(pauses)==3
    assert len(r.ordinary_packets)==1 and r.word(LEDGER)==0
    passed('busy_parent_attribution_retries_before_reservation_or_queue_publication')

    for kind in (0,1):
        for missing in (False,True):
            r=Ordinary().loaded();r.test_mode='normal';original_send=r.kernel_send
            def change_handle(a):
                result=original_send(a)
                if a[0]==FQ and r.ordinary_packets:
                    put32(r.m,0x80735b24,0 if missing else r.word(0x80735b24)+4)
                return result
            r.m.hooks[0x800763d8]=change_handle
            assert r.invoke_io(kind=kind) is None
            assert r.reads==8 and not r.seeks and r.word(LEDGER)==0x40000001
            assert r.pf('change_begin',0,OTHER)==BUSY
    passed('missing_or_changed_native_handle_rejects_IO_and_retains_file_ownership')

    r=Ordinary().loaded()
    for kind,pad,first in ((0,4,BUFFER),(0,2,0),(1,4,123)):
        assert r.invoke_io(kind=kind,pad=pad,first=first)==pad
    assert not r.ordinary_packets and r.word(LEDGER)==0
    passed('invalid_pad_and_null_read_buffer_keep_original_no_op_behavior')

    r=Ordinary().loaded();r.q[FQ].append(struct.pack('<4I',0,0,BUFFER,64))
    put32(r.m,CURRENT,FID);r.m.invoke(0x80036118,[])
    assert r.reads==8 and r.word(LEDGER)&0x40000000
    passed('raw_ordinary_packet_cannot_bypass_tracking_after_cold_binding')

    r=Ordinary(bind=False);put32(r.m,CURRENT,FID);r.m.invoke(0x80036118,[])
    assert r.op('bind',CONFIG)==BUSY
    passed('even_an_empty_worker_receive_closes_the_cold_binding_window')

    out=ROOT/'analysis/ordinary_routing_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Original reload/read/seek/file-worker instructions and compiled adapters share one CPU',
        'Explicit parent attribution, task identity storage for the third test task, scheduling and file effects are fixtures',
        'Fault policy parks participants; recovery and the caller lock audit remain open',
        'All ordinary callers must be bound before activation; no live cutover or task reuse',
        'Playback-session/refill parent provider and final firmware entry patches remain uninstalled',
        'Synthetic emulator placement only; no device access or physical placement proof']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
