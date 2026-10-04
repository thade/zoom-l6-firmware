#!/usr/bin/env python3
"""Retained UI delivery and cooperative Main mode-5 drain, offline only."""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_R4,UC_ARM_REG_R11,UC_ARM_REG_SP
from verify_reload_compact import Compact,UID,UQ,WQ,CURRENT,CTX,LEDGER,PRODUCER,WORK,UITASK,DRIVER,SCRATCH,packed
from verify_reload_transport import OK,BUSY,FAULT,F
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,STACK
from verify_overdub_prototype import ELF
from verify_scheduling_boundaries import stop

NOISE=(1,4,27,0,0)
class Recovery(Compact):
    def __init__(self):
        super().__init__();self.mode=self.m.symbols['rc_mode5_state'];self.effects=[];self.optional=0
        self.m.hooks[0x800345f8]=lambda a:0x22
        self.m.hooks[0x80077686]=lambda a:0
        self.m.hooks[0x8003b7e0]=lambda a:self.effects.append(('usb',*a[:2])) or 0
        self.m.hooks[0x800085c8]=lambda a:self.optional
        self.m.hooks[0x80008608]=lambda a:self.effects.append(('optional',*a[:2])) or 0
        self.m.hooks[0x80027508]=lambda a:self.effects.append(('ui_setup',)) or 0
        self.m.hooks[0x8003a168]=lambda a:0
        def trace(uc,a,n,u):
            assert self.word(CTX+392)==1 and self.word(CTX+396)==1
            assert self.word(CTX+4)==0
            self.effects.append((hex(a),))
        for addr in (0x8000c210,0x80007ec8,0x8003fb78):
            self.m.uc.hook_add(UC_HOOK_CODE,trace,begin=addr,end=addr)
        for addr in (0x8002c4a2,0x8002c4b2):
            self.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rc_mode5_range_return']|1),begin=addr,end=addr)
        def entry(uc,a,n,u):
            if self.word(self.mode+4)!=2:uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rc_mode5_entry']|1)
        self.m.uc.hook_add(UC_HOOK_CODE,entry,begin=0x8002c480,end=0x8002c480)
    def poll(self):
        put32(self.m,CURRENT,UID);self.active=UITASK
        try:return self.rc('mode5_poll')
        finally:self.active=None
    def retry(self):
        put32(self.m,CURRENT,UID);return self.rc('retry_ui')
    def service(self):
        put32(self.m,CURRENT,UID);self.active=UITASK
        try:return self.rc('service_owned')
        finally:self.active=None

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    r=Recovery();_,o=r.submit();r.seed([NOISE]*4096);r.worker()
    before=len(r.prefetch);assert before==4 and r.retire()==BUSY
    assert r.retry()==BUSY and len(r.q[UQ])==4096
    r.q[UQ].popleft();r.qsync(UQ)
    assert r.retry()==OK and len(r.q[UQ])==4096 and r.ui_events()[-1][3]==o
    assert len(r.prefetch)==before
    r.consume();assert len(r.prefetch)==8 and r.verify(o) and r.retire()==OK
    passed('full_queue_delivery_retries_same_ticket_after_space_opens_without_replaying_worker')

    r=Recovery();_,o=r.submit();r.seed([NOISE]*4096);r.worker();r.consume()
    assert len(r.prefetch)==8 and r.verify(o) and r.retire()==OK and not r.q[UQ]
    passed('original_Main_receive_path_recovers_full_queue_automatically_as_events_are_consumed')

    r=Recovery();_,o=r.submit();r.seed([NOISE]*4096);r.worker()
    assert r.poll()==BUSY and len(r.prefetch)==8 and not r.effects
    assert len(r.q[UQ])==4096 and all(e==NOISE for e in r.ui_events())
    assert r.verify(o) and r.retire()==OK and r.poll()==OK
    assert not r.q[UQ]
    passed('mode_drain_delivers_retained_owned_event_without_free_queue_slot_or_running_ordinary_controls')

    # Model a send which copied the event but returned failure. The replay must
    # not execute a second UI reload, whichever copy arrives first.
    r=Recovery();fired=[];original=r.m.hooks[0x800763d8]
    def ambiguous(a):
        result=original(a)
        if a[0]==UQ and not fired:fired.append(True);return 0
        return result
    r.m.hooks[0x800763d8]=ambiguous
    _,o=r.submit();r.worker();assert len(r.q[UQ])==1
    r.m.hooks[0x800763d8]=original
    assert r.retry()==OK and len(r.q[UQ])==2
    r.consume();assert len(r.prefetch)==8 and r.verify(o) and r.retire()==OK
    passed('ambiguous_delivery_retry_can_duplicate_a_packet_but_never_repeat_UI_file_work')

    r=Recovery();original=r.m.hooks[0x800763d8]
    def delivered_error(a):
        result=original(a);return 0 if a[0]==UQ else result
    r.m.hooks[0x800763d8]=delivered_error
    _,o=r.submit();r.worker();event=r.q[UQ].popleft();r.qsync(UQ)
    r.m.hooks[0x800763d8]=original
    r.m.uc.mem_write(SCRATCH,event);put32(r.m,CURRENT,UID);r.active=UITASK
    assert r.rc('ui',SCRATCH)==OK
    r.active=None;assert r.verify(o) and r.retire()==OK
    assert r.retry()==OK and not r.q[UQ]
    _,new=r.submit();assert new>o;r.worker();r.consume()
    assert r.verify(new) and r.retire()==OK
    passed('late_retry_record_for_retired_owner_is_discarded_before_a_new_reload')

    r=Recovery();_,o=r.submit();r.seed([NOISE]*4096);r.worker();saved=r.q[UQ].pop();r.qsync(UQ)
    put32(r.m,CTX+4,1);assert r.retry()==BUSY and len(r.q[UQ])==4095
    put32(r.m,CTX+4,0);assert r.retry()==OK and r.ui_events()[-1][3]==o
    passed('retry_metadata_contention_retains_copied_event_until_later_poll')

    r=Recovery();_,a=r.submit();_,b=r.submit(PRODUCER+0x20);r.seed([NOISE]*4096);r.worker()
    r.q[UQ].pop();r.q[UQ].pop();r.qsync(UQ)
    assert r.retry()==OK and r.retry()==OK
    assert [e[3] for e in r.ui_events()[-2:]]==[a,b]
    r.consume();assert r.verify(a) and r.retire()==OK
    assert r.verify(b) and r.retire(PRODUCER+0x20)==OK
    passed('bounded_retry_storage_keeps_two_failed_deliveries_distinct')

    r=Recovery();_,o=r.submit();assert r.poll()==BUSY and not r.effects
    assert r.word(CTX+396)==1 and r.word(CTX+392)==0
    assert r.submit(PRODUCER+0x20)[0]==BUSY
    assert r.poll()==BUSY and not r.effects # empty queue, pending worker
    r.worker();ordinary=[(1,4,27,10,20),(0,8,50,30,40)]
    tagged=r.q[UQ][0];r.seed([ordinary[0],struct.unpack('<5I',tagged),ordinary[1]])
    assert r.poll()==BUSY and r.ui_events()==ordinary and not r.effects
    assert len(r.prefetch)==8 and r.retire()==BUSY
    assert r.verify(o) and r.retire()==OK
    assert r.poll()==OK and not r.q[UQ] and r.word(0x801f5ca4)==1
    effects=list(r.effects);assert r.poll()==OK and r.effects==effects
    assert r.word(CTX+396)==0 and r.word(CTX+392)==0
    assert r.submit()[0]==OK
    passed('whole_mode5_branch_waits_for_verified_retirement_services_owned_UI_and_executes_setup_clear_suffix_once')

    r=Recovery();_,o=r.submit();r.worker();r.seed([NOISE]*4095+[r.ui_events()[0]])
    r.m.hooks[0x80076950]=lambda a:0 if a[1]==0 else 1
    assert r.poll()==BUSY and len(r.q[UQ])==4096 and len(r.prefetch)==4
    r.m.hooks[0x80076950]=lambda a:1
    assert r.poll()==BUSY and len(r.q[UQ])==4095 and len(r.prefetch)==8
    assert r.verify(o) and r.retire()==OK and r.poll()==OK
    passed('nonblocking_queue_mutex_failure_defers_drain_without_losing_order_or_running_setup')

    r=Recovery();_,o=r.submit();r.worker();r.fail=('settings_write',2,'short')
    assert r.poll()==BUSY and r.verify(o) and r.retire()==FAULT
    assert r.poll()==FAULT and not r.effects and r.word(r.mode+4)==5
    assert r.poll()==FAULT and r.word(CTX+396)==1
    passed('file_failure_parks_transition_without_setup_clear_or_completion_flag')

    # Contend immediately after the suffix's final store, before lease release.
    # The compiler may inline rl_transition_end into the state machine.
    r=Recovery();addr=0x8003fb82;fired=[]
    def contend(uc,a,n,u):
        if not fired:fired.append(True);put32(r.m,CTX+4,1)
    hook=r.m.uc.hook_add(UC_HOOK_CODE,contend,begin=addr,end=addr)
    assert r.poll()==BUSY and r.word(r.mode+4)==3
    effects=list(r.effects);assert effects and r.word(CTX+396)==1
    r.m.uc.hook_del(hook);put32(r.m,CTX+4,0)
    assert r.poll()==OK and r.effects==effects
    passed('release_contention_retries_only_lease_release_not_original_mode_side_effects')

    r=Recovery();assert r.rl('cleanup_begin')==OK
    assert r.poll()==BUSY and not r.effects and r.word(r.mode+4)==0
    assert r.rl('cleanup_end')==OK and r.poll()==OK
    passed('preexisting_cleanup_must_return_before_transition_can_close_admission')

    r=Recovery();r.optional=1;resumed=[]
    r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:resumed.append(True) or stop(r.m),begin=0x8002c362,end=0x8002c362)
    put32(r.m,CURRENT,UID);r.active=UITASK
    r.m.uc.reg_write(UC_ARM_REG_R4,0x12345678);r.m.uc.reg_write(UC_ARM_REG_R11,5)
    r.m.invoke(0x8002c480,[])
    assert resumed==[True] and ('optional',0,1) in r.effects
    assert r.m.uc.reg_read(UC_ARM_REG_R4)==0x12345678 and r.m.uc.reg_read(UC_ARM_REG_R11)==5
    assert r.m.uc.reg_read(UC_ARM_REG_SP)==STACK and r.word(r.mode+4)==4
    passed('native_mode_entry_adapter_preserves_Main_registers_and_stack_then_resumes_original_common_startup')

    r=Recovery();_,o=r.submit();parked=[]
    r.m.hooks[DRIVER+0x60]=lambda a:parked.append(True) or stop(r.m)
    put32(r.m,CURRENT,UID);r.active=UITASK;r.m.invoke(0x8002c480,[])
    assert parked==[True] and not r.effects and r.word(r.mode+4)==1
    passed('native_entry_yields_while_worker_is_pending_instead_of_blocking_Main_on_a_completion_wait',limitation='Emulator stops at yield; no full RTOS context switch in this test')

    r=Recovery();_,o=r.submit();r.worker();r.seed([r.ui_events()[0]])
    # Hold an attributed root descendant beyond both bodies.
    req=SCRATCH+0x100;out=req+32
    r.m.uc.mem_write(req,packed((2,0,0,0,0)))
    own=lambda name,*args:r.m.invoke(r.m.symbols['od_own_'+name],[LEDGER,*args])
    assert own('child',o,req,out)==OK;child=r.word(out)
    assert own('offer',child)==OK and own('submitted',child,1)==OK
    assert own('claim',child,req)==OK and own('producer_done',child,0)==OK
    assert r.poll()==BUSY and not r.effects
    assert r.rl('verify',o,1)==BUSY and r.poll()==BUSY and not r.effects
    assert own('complete',child)==OK
    assert r.verify(o) and r.retire()==OK and r.poll()==OK
    passed('outstanding_file_descendant_blocks_verification_and_transition_after_both_bodies_return')

    r=Recovery();_,o=r.submit();r.worker();held=[]
    mutex=0x5555;put32(r.m,0x80446810,mutex)
    original_send=r.m.hooks[0x800763d8]
    def wait_mutex(a):
        if a[0]==mutex:assert not held;held.append(True)
        return 1
    def release_mutex(a):
        if a[0]==mutex:assert held;held.pop()
        return original_send(a)
    r.m.hooks[0x80076950]=wait_mutex;r.m.hooks[0x800763d8]=release_mutex
    observations=[]
    def file_boundary(r,op,result):observations.append(op);assert not held
    r.after_io=file_boundary
    assert r.poll()==BUSY and observations and not held
    assert r.verify(o) and r.retire()==OK and r.poll()==OK
    passed('selected_UI_file_work_runs_after_releasing_event_mutex')

    r=Recovery()
    def fail_before_release(uc,a,n,u):put32(r.m,LEDGER,F)
    r.m.uc.hook_add(UC_HOOK_CODE,fail_before_release,begin=0x8003fb82,end=0x8003fb82)
    assert r.poll()==FAULT and r.word(CTX+392)==1 and r.word(CTX+396)==1
    effects=list(r.effects);assert r.poll()==FAULT and r.effects==effects
    passed('fault_during_transition_prevents_admission_reopen_and_common_startup_resume')

    out=ROOT/'analysis/reload_recovery_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Compiled retries and drain state execute with original mode-5 instruction ranges and original reload control flow; entry/return PC interception remains emulator supplied',
      'Mode-5 USB handshake, UI hardware setup, queue mutex/copying and scheduler effects are fixtures; queue-only exclusion is not a global USB/card/playback fence',
      'Successful final evidence and producer retirement are still explicit external verifier actions; no automatic durable-settings/media verification is added here',
      'Mode-5 continuation is one-shot for the recovered Main startup branch; no reset/restart or task-identity recycling',
      'Ordinary UI messages are preserved in order during owned drain and later discarded only by original mode clear; unrelated mode/event handlers are not run while draining',
      'Stock event publication still acquires its mutex with the original wait; queue-full retry never busy-waits for capacity but is not a lock-free real-time path',
      'No device access, native patch installation, SD writes or flashing']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
