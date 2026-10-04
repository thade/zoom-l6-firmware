#!/usr/bin/env python3
"""Prepared-file handover at strict audio boundary; synthetic DSP and file API."""
import hashlib,json,struct
from types import MethodType
from verify_control_drain import DrainRig
from verify_audio_invocation import AudioRig
from verify_transport_shutdown import shutdown
from verify_control_transport import T,QHANDLE
from verify_request_router import ROUTER
from verify_emulator_bridge import BR
from verify_block_exchange import P,SLOTS
from verify_extra_capture import STATE,ELF
from verify_extra_lifecycle import LIFE
from verify_history_capture import payload
from verify_record_scheduler import word
from verify_record_catalogue import getstr
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
DESC=0x21034000;RESULT=0x21035000
class HandoverRig(DrainRig):
    def __init__(self):
        super().__init__();AudioRig.install(self);self.audio_call=MethodType(AudioRig.audio_call,self)
        self.session=123
    def step(self,session=None):return self.m.invoke(self.syms['bridge_step'],[BR,self.session if session is None else session])
    def eligible(self):return self.m.invoke(self.syms['bridge_verified_path'],[BR,self.session])
    def close(self,session=None):return self.m.invoke(self.syms['ct_close_admission'],[T,self.session if session is None else session])
    def activate(self):return self.m.invoke(self.syms['ct_activate_next'],[T,self.session])
    def stage(self,serial=None,session=None):
        # Caller owns fenced storage. No guest callback may use this arena now;
        # direct low-level pointers have been abandoned. Disk/result live outside.
        self.m.uc.mem_write(STATE,bytes(0x20000))
        self.session=self.session+1 if session is None else session
        result=self.life('life_prepare',0,self.session if serial is None else serial)
        if result:return result
        self.m.uc.mem_write(DESC,struct.pack('<10I',T,ROUTER,BR,P,LIFE,STATE,SLOTS,32,self.session,QHANDLE))
        return self.m.invoke(self.syms['ct_stage_next'],[DESC])
    def record(self,blocks=2):
        start=self.sequence;self.request();self.dispatch_all()
        for _ in range(blocks):self.audio_call();assert self.pump()==11
        self.request(1);assert self.close()==0;self.dispatch_all();assert self.pump()==0
        self.validate(payload(start,self.sequence))
        assert self.m.invoke(self.syms['life_copy_verified'],[LIFE,RESULT,261])==0
        copied=getstr(self.m,RESULT);assert copied==self.path()
        assert shutdown(self,self.session)==10;self.dispatch_all();assert shutdown(self,self.session)==0
        return copied,bytes(self.disk[copied])

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=HandoverRig();r.audio_call();saved=[r.record()]
    for i in range(4):
        old=list(r.sent);assert r.stage(serial=1)==0 # collision must pick unused name
        assert r.activate()==11 and not r.wire
        copied=getstr(r.m,RESULT);assert copied==saved[-1][0]
        r.audio_call();assert r.activate()==0
        before=r.raw(T,r.tlayout[0]);callbacks=len(r.callback_args)
        r.wire.extend(old);r.dispatch_all()
        assert len(r.callback_args)==callbacks and r.raw(T,r.tlayout[0])==before
        saved.append(r.record(blocks=i+1))
        assert all(bytes(r.disk[p])==data for p,data in saved)
    assert len({p for p,_ in saved})==5 and not r.opened
    passed('five_recordings_reuse_fenced_arena_preserve_all_WAVs_and_reject_old_generation_envelopes',takes=5)

    r=HandoverRig();r.audio_call();old=r.record();staged=[]
    # Prepare a new session while an ordinary CLOSED-gateway callback is
    # already between its outer hook and commit. It cannot adopt mid-call.
    def checkpoint(a):
        if a[0]==1 and not staged:
            # A second CPU represents the manager, not recursive emulation.
            peer=HandoverRig()
            peer.m.uc.mem_write(0x10010000,r.raw(0x10010000,0x10000))
            peer.m.uc.mem_write(STATE,r.raw(STATE,0x20000))
            peer.disk={k:bytearray(v) for k,v in r.disk.items()};peer.opened={};peer.next_handle=r.next_handle
            peer.session=r.session;assert peer.stage()==0
            r.m.uc.mem_write(0x10010000,peer.raw(0x10010000,0x10000))
            r.m.uc.mem_write(STATE,peer.raw(STATE,0x20000))
            r.disk=peer.disk;r.opened=peer.opened;r.next_handle=peer.next_handle;r.session=peer.session
            staged.append(True)
        return None
    r.m.hooks[r.syms['audio_fixture_checkpoint']&~1]=checkpoint
    r.audio_call();assert staged==[True] and r.activate()==11 and word(r.m,P+16)==0
    r.audio_call();assert r.activate()==0;r.record()
    assert bytes(r.disk[old[0]])==old[1]
    passed('file_prepared_during_closed_callback_waits_for_next_outer_boundary')

    r=HandoverRig();r.audio_call();r.record();assert r.stage()==0
    put32(r.m,r.syms['bridge_gateway_readers'],0x80000001)
    r.audio_call();assert r.activate()==11
    put32(r.m,r.syms['bridge_gateway_readers'],0x80000000)
    r.audio_call();assert r.activate()==0;r.record()
    passed('transient_closed_gateway_arrival_defers_adoption_without_resetting_its_count')

    r=HandoverRig();r.audio_call();r.record();r.inject=('create',r.counts.get('create',0)+1,'error')
    assert r.stage()!=0 and not r.opened
    assert word(r.m,r.syms['ct_active'])==0 and word(r.m,r.syms['emulator_bridge_current'])==0
    assert r.activate()==12
    r.inject=None;assert r.stage()==0;r.audio_call();assert r.activate()==0;r.record()
    passed('fresh_file_creation_failure_leaves_capture_closed_and_clean_retry_can_prepare_another_generation')

    r=HandoverRig();r.audio_call();r.record();assert r.stage()==0
    r.audio_call(callback=0);assert r.activate()==18
    assert r.m.invoke(r.syms['ct_cancel_failed_stage'],[T,r.session])==0 and not r.opened
    assert r.stage()==0;r.audio_call();assert r.activate()==0;r.record()
    passed('invalid_adoption_callback_leaves_gates_closed_worker_cancels_file_then_fresh_generation_can_retry')

    r=HandoverRig();r.audio_call();r.record();assert r.stage()==0
    r.audio_call(mode=2);assert r.activate()==18
    assert r.m.invoke(r.syms['ct_cancel_failed_stage'],[T,r.session])==0 and not r.opened
    assert word(r.m,r.syms['emulator_bridge_current'])==0
    assert r.stage()==0;r.audio_call();assert r.activate()==0;r.record()
    passed('failure_in_first_adopted_block_is_cancelled_and_detached_before_retry')

    r=HandoverRig();r.audio_call();r.record();oldsession=r.session
    assert r.stage(session=oldsession)==12
    assert word(r.m,r.syms['ct_active'])==0 and r.activate()==12
    # Rejected stage owns an ARMED fixture file; explicit worker cancellation.
    assert r.life('life_cancel_quiesced')==16 and not r.opened
    passed('reused_session_token_rejected_before_publication')

    r=HandoverRig();r.audio_call();r.record();assert r.stage()==0;r.audio_call();assert r.activate()==0
    # A plain old stock callback lacks an owned envelope. Preserve stock work,
    # but invalidate the optional new file rather than silently missing STOP.
    r.wire.append(struct.pack('<8I',0x8004ba41,0,0,0,0,0,0,0));r.dispatch_all()
    assert word(r.m,BR+16)==27;r.assert_failed()
    passed('late_unowned_stock_stop_cancels_optional_new_file_while_original_callback_executes')

    r=HandoverRig();r.audio_call();r.record();switched=[]
    from verify_record_scheduler import request_setup
    request_setup(r.m,1,0)
    def delayed_control(a):
        if not switched:
            peer=HandoverRig();peer.m.uc.mem_write(0x10010000,r.raw(0x10010000,0x10000))
            peer.m.uc.mem_write(STATE,r.raw(STATE,0x20000))
            peer.disk={k:bytearray(v) for k,v in r.disk.items()};peer.opened={};peer.next_handle=r.next_handle
            peer.session=r.session;peer.sequence=r.sequence;peer.cursor=r.cursor
            put32(peer.m,0x20015e2c,r.cursor)
            assert peer.stage()==0;peer.audio_call();assert peer.activate()==0
            r.m.uc.mem_write(0x10010000,peer.raw(0x10010000,0x10000))
            r.m.uc.mem_write(STATE,peer.raw(STATE,0x20000));r.m.uc.mem_write(SLOTS,peer.raw(SLOTS,0x20000))
            put32(r.m,0x20015e2c,peer.cursor)
            r.disk=peer.disk;r.opened=peer.opened;r.next_handle=peer.next_handle
            r.session=peer.session;r.sequence=peer.sequence;r.cursor=peer.cursor;switched.append(True)
        return 0
    r.m.hooks[0x8000ac70]=delayed_control;r.m.invoke(0x80034f40,[0xffffffff])
    assert switched==[True] and word(r.m,BR+16)==27
    r.dispatch_all();r.assert_failed()
    passed('stock_request_started_while_closed_cannot_borrow_new_session_when_it_resumes_after_activation')

    r=HandoverRig();r.audio_call();r.record();assert r.stage()==0;r.audio_call(callback=0)
    r.inject=('close_write',r.counts.get('close_write',0)+1,'error')
    assert r.m.invoke(r.syms['ct_cancel_failed_stage'],[T,r.session])==13
    assert r.m.invoke(r.syms['ct_stage_next'],[DESC])==12 and r.activate()==18
    passed('uncertain_close_during_failed_stage_cleanup_blocks_restage_instead_of_reusing_resources')

    r=HandoverRig();assert r.m.invoke(r.syms['life_copy_verified'],[LIFE,RESULT,261])==12
    r.audio_call();r.record();assert r.m.invoke(r.syms['life_copy_verified'],[LIFE,RESULT,1])==12
    passed('result_copy_requires_verified_closed_file_and_sufficient_caller_storage')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Fresh arena clearing and sequencing provided by single manager fixture after successful full shutdown',
        'Synthetic DSP body/cursor and synchronous filesystem; not real SD/DMA ownership or full RTOS',
        'Prepared file adoption at strict outer callback; control activation waits for first completed block',
        'Late unowned stock callbacks cancel extra capture; input behavior preserved, not suppressed',
        'No automatic pad catalogue assignment, complete UI workflow or deployable firmware'])
    path=ROOT/'analysis/session_handover_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))
if __name__=='__main__':main()
