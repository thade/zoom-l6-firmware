#!/usr/bin/env python3
"""Compiled manager owns file/arena/handover sequencing; harness only schedules."""
import hashlib,json,struct
from unicorn import UC_HOOK_MEM_READ
from verify_session_handover import HandoverRig,DESC,RESULT
from verify_control_transport import T
from verify_request_router import ROUTER
from verify_emulator_bridge import BR
from verify_block_exchange import P,SLOTS
from verify_extra_capture import STATE,ELF
from verify_extra_lifecycle import LIFE
from verify_record_scheduler import word
from verify_record_catalogue import getstr
from verify_history_capture import payload
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
MAN=0x2201d000
LIVE,FINISH,FENCE,RESET,PREPARE,STAGE,ACTIVATE,ABORT,STOPPED,BLOCKED,UNPUBLISHED=range(1,12)
class ManagerRig(HandoverRig):
    def __init__(self):
        super().__init__()
        self.mlayout=struct.unpack('<7I',self.raw(self.syms['manager_layout'],28))
        self.m.uc.mem_write(DESC,struct.pack('<10I',T,ROUTER,BR,P,LIFE,STATE,SLOTS,32,self.session,0x21032000))
        assert self.m.invoke(self.syms['manager_init'],[MAN,DESC,0])==0
    def mstate(self):return word(self.m,MAN)
    def tick(self):
        s=self.m.invoke(self.syms['manager_step'],[MAN]);self.session=word(self.m,MAN+12+4)
        return s
    def cancel(self):self.m.invoke(self.syms['manager_cancel'],[MAN])
    def resume(self):return self.m.invoke(self.syms['manager_resume'],[MAN])
    def result(self,index=0):
        s=self.m.invoke(self.syms['manager_copy_result'],[MAN,index,RESULT])
        return (word(self.m,RESULT),getstr(self.m,RESULT+4)) if s==0 else s
    def drive(self,goal,with_audio=True,with_queue=True):
        for _ in range(1024):
            if goal():return
            self.tick()
            if with_queue and self.wire:self.dispatch_all()
            if with_audio and self.mstate()==ACTIVATE:self.audio_call()
        raise AssertionError(('Manager did not reach goal',self.mstate(),word(self.m,MAN+4)))
    def take(self,blocks=2):
        assert self.mstate()==LIVE;session=self.session;start=self.sequence
        self.request();self.dispatch_all()
        for _ in range(blocks):self.audio_call();self.tick()
        self.request(1);self.dispatch_all()
        self.drive(lambda:self.mstate()==LIVE and self.session>session)
        got,path=self.result();assert got==session
        data=bytes(self.disk[path]);assert data[512:]==payload(start,start+blocks*64)
        assert struct.unpack_from('<I',data,508)[0]==blocks*64*8
        self.assert_ordinary();return got,path,data

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=ManagerRig();r.audio_call();saved=[]
    for n in range(6):
        saved.append(r.take(n%3+1))
        assert all(bytes(r.disk[p])==data for _,p,data in saved)
    assert word(r.m,MAN+r.mlayout[4])==4
    for i in range(4):assert r.result(i)==saved[-1-i][:2]
    assert r.result(4)==12 and len({p for _,p,_ in saved})==6
    passed('compiled_manager_runs_six_takes_preserves_every_WAV_and_retains_latest_four_result_copies',takes=6)

    r=ManagerRig();r.audio_call();r.take();old=r.result();r.cancel()
    r.drive(lambda:r.mstate()==STOPPED)
    assert not r.opened and r.result()==old
    r.cancel();assert r.tick()==16 and r.resume()==0
    r.drive(lambda:r.mstate()==LIVE);r.take()
    passed('cancel_armed_session_closes_its_file_preserves_history_and_explicit_resume_rearms')

    r=ManagerRig();r.audio_call();r.request();r.dispatch_all();r.audio_call();r.tick();r.cancel()
    r.drive(lambda:r.mstate()==STOPPED)
    assert r.result()==12 and not r.opened
    # Optional cancellation does not issue ordinary STOP. A user STOP can still
    # run through stock code after optional transport shutdown.
    r.request(1);r.dispatch_all();r.assert_ordinary()
    passed('cancel_recording_discards_only_optional_result_without_stopping_ordinary_control')

    for state in (RESET,PREPARE,STAGE,ACTIVATE):
        r=ManagerRig();r.audio_call();r.request();r.dispatch_all();r.audio_call();r.tick()
        r.request(1);r.dispatch_all();r.drive(lambda:r.mstate()==state,with_audio=False)
        saved=r.result();r.cancel();r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
        assert not r.opened and r.result()==saved and r.resume()==0
        r.drive(lambda:r.mstate()==LIVE);r.take()
    passed('cancel_during_reset_prepare_prepublication_or_pending_adoption_needs_no_future_audio_and_resumes_cleanly')

    r=ManagerRig();r.audio_call();r.request();r.dispatch_all();r.audio_call();r.tick()
    r.request(1);r.dispatch_all();r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    r.audio_call();r.cancel();r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert not r.opened and r.resume()==0;r.drive(lambda:r.mstate()==LIVE);r.take()
    passed('cancel_adopted_but_not_control_activated_session_drains_and_closes_before_reuse')

    r=ManagerRig();r.audio_call();r.request();r.dispatch_all();r.audio_call();r.tick()
    r.request(1);r.dispatch_all();r.drive(lambda:r.mstate()==PREPARE,with_audio=False)
    saved=r.result();r.inject=('create',r.counts.get('create',0)+1,'error')
    assert r.tick()==13 and r.mstate()==STOPPED and not r.opened and r.result()==saved
    assert r.tick()==13;r.inject=None;assert r.resume()==0
    r.drive(lambda:r.mstate()==LIVE);r.take()
    passed('new_file_failure_stops_without_automatic_retry_and_preserves_verified_previous_result')

    for operation in ('audio','close_write'):
        r=ManagerRig();r.audio_call();r.request();r.dispatch_all()
        r.inject=(operation,r.counts.get(operation,0)+1,'short' if operation=='audio' else 'error')
        r.audio_call();r.tick();r.request(1);r.dispatch_all()
        terminal=STOPPED if operation=='audio' else BLOCKED
        r.drive(lambda:r.mstate()==terminal,with_audio=False)
        assert r.result()==12
        if terminal==BLOCKED:
            assert r.resume()==12;before=r.raw(STATE,0x10000);calls=len(r.calls)
            for _ in range(3):assert r.tick()!=0
            assert r.raw(STATE,0x10000)==before and len(r.calls)==calls
    r=ManagerRig();r.audio_call();r.request();r.dispatch_all();r.audio_call();r.tick()
    r.request(1);r.dispatch_all();r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    r.inject=('close_write',r.counts.get('close_write',0)+1,'error');r.cancel()
    r.drive(lambda:r.mstate()==BLOCKED,with_audio=False)
    assert word(r.m,MAN+4)==13 and r.resume()==12 # cleanup fault replaces cancellation code
    passed('short_write_never_publishes_result_and_uncertain_close_blocks_resume_and_memory_reuse')

    r=ManagerRig();r.audio_call();r.send_result=0xffffffff;r.request()
    r.drive(lambda:r.mstate()==FENCE,with_audio=False,with_queue=False)
    calls=len(r.calls);before=r.raw(T,r.tlayout[0])
    for _ in range(4):assert r.tick()==11 and r.mstate()==FENCE
    assert r.raw(T,r.tlayout[0])==before and len(r.calls)==calls and r.result()==12
    passed('uncertain_control_send_retains_fenced_state_without_forced_reset_or_reopening')

    r=ManagerRig();r.audio_call();r.request();r.dispatch_all();r.audio_call();r.tick()
    r.request(1);r.dispatch_all();r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    r.audio_call(mode=2);r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert not r.opened and r.result()!=12 and r.resume()==0
    r.drive(lambda:r.mstate()==LIVE);r.take()
    passed('first_adopted_block_failure_automatically_runs_stage_cleanup_and_retains_prior_result')

    r=ManagerRig();r.audio_call();r.request();r.dispatch_all();r.audio_call();r.tick()
    r.request(1);r.dispatch_all();r.drive(lambda:r.mstate()==FENCE,with_queue=False,with_audio=False)
    r.send_result=0xffffffff
    r.drive(lambda:r.mstate()==BLOCKED,with_queue=False,with_audio=False)
    assert r.result()==12 and r.resume()==12
    passed('marker_send_failure_blocks_result_publication_even_after_file_verification')

    r=ManagerRig();r.audio_call();r.request();r.dispatch_all();r.audio_call();r.tick()
    r.request(1);r.dispatch_all();r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    seen=[];address=r.syms['bridge_gateway_readers']
    def withdraw_after_load(uc,access,addr,size,value,user):
        if seen:return
        seen.append(True)
        # Adopter has loaded pending_bridge but has not reserved the gate.
        peer=ManagerRig();peer.m.uc.mem_write(0x10010000,r.raw(0x10010000,0x10000))
        peer.m.uc.mem_write(STATE,r.raw(STATE,0x20000))
        peer.disk={k:bytearray(v) for k,v in r.disk.items()}
        peer.opened={k:list(v) for k,v in r.opened.items()};peer.next_handle=r.next_handle
        peer.session=r.session;calls=len(peer.calls);peer.cancel()
        assert peer.tick()==10 and peer.mstate()==ABORT
        assert peer.tick()==11 and word(peer.m,peer.syms['pending_bridge'])==0
        assert peer.tick()==11 and len(peer.calls)==calls # caller still owns audio interval
        r.m.uc.mem_write(0x10010000,peer.raw(0x10010000,0x10000))
        r.m.uc.mem_write(MAN,peer.raw(MAN,r.mlayout[0]))
    handle=r.m.uc.hook_add(UC_HOOK_MEM_READ,withdraw_after_load,begin=address,end=address+3)
    r.m.uc.ctl_remove_cache(0x10010000,0x10020000)
    r.audio_call();r.m.uc.hook_del(handle)
    assert seen==[True] and word(r.m,r.syms['emulator_bridge_current'])==0
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert not r.opened and r.resume()==0;r.drive(lambda:r.mstate()==LIVE);r.take()
    passed('pending_stage_withdrawn_after_audio_pointer_load_is_rechecked_before_adoption_and_cleanup_waits_for_return')

    r=ManagerRig();put32(r.m,MAN+12,1);before=r.raw(MAN,r.mlayout[0]);calls=len(r.calls)
    assert r.tick()==11 and r.raw(MAN,r.mlayout[0])==before and len(r.calls)==calls
    put32(r.m,MAN+12,0)
    other=MAN+0x900;r.m.uc.mem_write(other,bytes(r.mlayout[0]))
    assert r.m.invoke(r.syms['manager_init'],[other,DESC,0])==12
    other_r=HandoverRig()
    desc=[T,ROUTER,BR,P,LIFE,MAN,SLOTS,32,123,0x21032000]
    other_r.m.uc.mem_write(DESC,struct.pack('<10I',*desc))
    assert other_r.m.invoke(other_r.syms['manager_init'],[MAN,DESC,0])==12
    passed('worker_reentry_duplicate_manager_and_manager_session_memory_overlap_are_rejected')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      manager_bytes=r.mlayout[0],retained_results=4,
      limitations=['Manager attaches to already initialized ARMED first session; cold boot/task creation remain fixture setup',
        'Compiled manager owns worker/file/clearing/handover steps; harness schedules calls, audio and stock queue delivery',
        'Synthetic DSP and synchronous files; no physical SD/DMA, real-time or hardware memory proof',
        'No automatic ordinary STOP, pad assignment, power-loss journal or deployed firmware'])
    path=ROOT/'analysis/session_manager_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))
if __name__=='__main__':main()
