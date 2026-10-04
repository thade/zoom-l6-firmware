#!/usr/bin/env python3
"""Compiled shutdown joins original stop, full audio and owned stream workers.

No hardware access. Explicit emulator adapters disable stock stream flags; queue,
fade/seek progress and scheduling remain modeled. Publication itself is not run.
"""
import hashlib,json,struct
from unicorn import UC_PROT_NONE
from verify_playback_session import SessionRig,SESSION,PORT,ERROR
from verify_audio_completion import Bridge
from verify_control_coordinator import C,ARGS,OUT
from verify_work_ownership import LEDGER,OK,BUSY,FAULT,P,F,STALE
from verify_scheduling_boundaries import BASE
from verify_pad_renderer_boundary import AUDIO
from verify_pad_reader_audit import TARGETS,SELECTOR
from verify_firmware_workflow import put32
from verify_overdub_prototype import ELF
from verify_pad_protocol import ROOT,IMAGE
SD=0x21003c00; SDP=0x21003d00

class Rig(SessionRig):
    def __init__(self,pads=(0,)):
        super().__init__(pads)
        m=self.m
        assert struct.unpack('<2I',m.uc.mem_read(m.symbols['od_shutdown_layout'],8))==(40,8)
        m.uc.mem_write(SD,struct.pack('<3I',SESSION,C,SDP))
        m.uc.mem_write(SDP,struct.pack('<2I',m.symbols['od_emulator_shutdown_disable_streams'],m.symbols['od_emulator_session_quiet']))
        put32(m,PORT+12,m.symbols['od_emulator_shutdown_fence'])
        put32(m,PORT+20,m.symbols['od_emulator_shutdown_rearm'])
        self.csize=struct.unpack('<I',m.uc.mem_read(m.symbols['oc_layout'],4))[0]
    def shutdown(self):return self.m.invoke(self.m.symbols['od_shutdown_poll'],[SD])
    def finish(self,ticket=None,failed=0):
        return self.m.invoke(self.m.symbols['od_shutdown_finish'],[SD,self.sf(8) if ticket is None else ticket,failed])
    def sf(self,i):return self.u32(SD+4*i)
    def ctrl(self,name,*args):return self.m.invoke(self.m.symbols['oc_'+name],[C,*args])
    def audio(self,target=TARGETS[0],protect=False,change=False):
        b=Bridge();b.control.m.uc.mem_write(C,bytes(self.m.uc.mem_read(C,self.csize)))
        b.audio.m.uc.mem_write(AUDIO,bytes(self.m.uc.mem_read(AUDIO,240)))
        if protect:
            b.audio.m.uc.mem_protect(0x21028000,0x2000,UC_PROT_NONE)
        if change:b.at_entry=lambda b:put32(b.audio.m,SELECTOR,0x800133e9)
        b.block(target)
        self.m.uc.mem_write(C,b.control.raw(C,self.csize))
        self.m.uc.mem_write(AUDIO,b.audio.raw(AUDIO,240))
        return b
    def ready(self):
        assert self.shutdown()==BUSY
        self.audio();assert self.shutdown()==OK and self.sf(5) and self.sf(8)
        return self.sf(8)

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))

    r=Rig();assert r.invoke('start',0)==OK;old=r.owner()
    assert r.shutdown()==BUSY and r.field(7)==1 and r.mask()==0
    assert r.u32(AUDIO)==0 and r.state(0)[0]==0 and r.owner()==old
    assert r.invoke('start',0)==BUSY and r.invoke('scan')==BUSY and r.promotion()[0]==BUSY
    r.audio();assert r.shutdown()==OK and r.owner()==0 and r.word()==P
    assert r.field(5)==r.field(7)==1 and r.field(6)==old
    assert r.invoke('start',0)==BUSY and r.invoke('scan')==BUSY
    ticket=r.sf(8);assert r.finish(ticket)==OK and r.word()==0 and r.field(7)==0
    assert r.finish(ticket)==STALE and r.invoke('start',0)==OK and r.owner()!=old
    passed('original_stop_then_actual_audio_return_then_exclusive_ownership_then_explicit_rearm')

    r=Rig((0,1));assert r.invoke('start',0)==r.invoke('start',1)==OK
    assert r.shutdown()==BUSY and r.mask()==0
    assert r.u32(AUDIO)==r.u32(AUDIO+60)==0
    assert r.state(0)[0]==r.state(1)[0]==0
    r.audio();assert r.shutdown()==OK
    passed('four_slot_publication_shutdown_stops_all_session_pads_before_barrier')

    r=Rig();r.invoke('start',0);r.invoke('scan');assert r.queue
    # Stock stop waits for fade; allow fade only, leaving worker explicitly queued.
    def fade(a):
        for pad in range(4):put32(r.m,AUDIO+pad*60+0x24,0)
        return 0
    r.m.hooks[0x80077686]=fade
    assert r.shutdown()==BUSY and r.pending(0)==1 and r.queue
    r.audio();assert r.shutdown()==BUSY and r.word()==1 and r.owner()
    r.run_worker();assert r.pending(0)==0
    assert r.shutdown()==OK and r.word()==P
    passed('queued_original_stream_worker_completes_after_stream_disable_and_blocks_publication_until_return')

    r=Rig();r.invoke('start',0);r.invoke('stop',0);r.seed(0);r.invoke('scan')
    assert r.queue;r.m.uc.mem_write(BASE+0x1c,b'\x00')
    r.shutdown();r.audio();assert r.shutdown()==BUSY and r.owner() and r.word()==1
    r.run_worker();assert r.shutdown()==OK
    passed('cleared_pending_flag_cannot_override_unfinished_scan_child_ticket')

    r=Rig();r.invoke('start',0);r.invoke('stop',0)
    r.m.uc.mem_write(BASE+0x1c,b'\x01');r.shutdown();r.audio()
    assert r.shutdown()==BUSY and r.owner() and r.word()==1
    passed('unattributed_pending_flag_blocks_even_with_no_owned_child')

    r=Rig();r.invoke('start',0);r.invoke('stop',0)
    r.return_success=False;r.deliver=False;r.seed(0)
    assert r.invoke('scan')==BUSY and not r.queue
    r.m.uc.mem_write(BASE+0x1c,b'\x00');r.shutdown();r.audio()
    assert r.shutdown()==BUSY and r.owner() and r.word()==1
    passed('uncertain_undelivered_read_is_never_forgiven_by_audio_ack_or_idle_flags')

    r=Rig(());assert r.shutdown()==BUSY and r.field(7)==1 and not r.owner()
    assert r.invoke('start',0)==BUSY
    r.audio();assert r.shutdown()==OK and r.word()==P
    passed('initially_idle_session_still_closes_admission_and_requires_fresh_audio_completion')

    r=Rig();r.invoke('start',0);r.shutdown()
    # Independent root card/read ownership can keep exclusivity unavailable
    # after the session retires; the hold must cover this gap.
    status,other=r.reserve(kind=4);assert status==OK
    r.audio();assert r.shutdown()==BUSY and r.owner()==0 and r.sf(4)==5
    assert r.invoke('start',0)==BUSY and r.invoke('scan')==BUSY and r.field(7)==1
    assert r.call('cancel_prepared',other)==OK
    assert r.shutdown()==OK
    passed('session_retirement_to_publication_gap_keeps_starts_and_scans_closed_while_other_root_finishes')

    r=Rig();r.invoke('start',0);r.shutdown()
    for _ in range(3):assert r.shutdown()==BUSY and r.owner()
    r.audio(change=True);assert r.shutdown()==FAULT and r.word()&F and r.owner()
    assert r.finish()==FAULT and r.invoke('start',0)==FAULT
    passed('missing_audio_waits_and_callback_change_latches_failure_without_releasing_owner')

    r=Rig();r.invoke('start',0);r.ready();ticket=r.sf(8)
    for target in TARGETS*2:
        b=r.audio(target,protect=True);assert not b.audio.samples()
        assert r.shutdown()==OK and r.sf(8)==ticket
        assert r.invoke('start',0)==BUSY and r.invoke('scan')==BUSY
    passed('protected_stopped_buffers_remain_unread_across_all_four_callbacks_during_exclusive_hold')

    r=Rig();r.invoke('start',0);r.ready();ticket=r.sf(8)
    assert r.finish(ticket+1)==STALE and r.word()==P and r.field(7)==1
    assert r.finish(ticket,1)==FAULT and r.word()&F and r.sf(8)==ticket
    assert r.shutdown()==FAULT and r.invoke('start',0)==FAULT
    passed('stale_finish_rejected_and_uncertain_publication_retains_exclusive_ownership_and_hold')

    r=Rig();r.invoke('start',0);r.ready();ticket=r.sf(8)
    put32(r.m,C,1);assert r.finish()==BUSY and r.word()==P
    put32(r.m,C,0);put32(r.m,SESSION+8,1)
    assert r.finish()==BUSY and r.sf(4)==8 and r.field(7)==1 and r.word()==0
    put32(r.m,SESSION+8,0);assert r.finish(ticket)==OK and r.sf(4)==0
    passed('finish_retries_keep_hold_through_control_and_session_lock_contention')

    r=Rig();r.invoke('start',0);r.shutdown();r.audio()
    put32(r.m,LEDGER+4,1);assert r.shutdown()==BUSY and r.owner() and r.field(7)==1
    put32(r.m,LEDGER+4,0);assert r.shutdown()==OK
    passed('ledger_retirement_contention_does_not_drop_playback_ownership')

    r=Rig();r.invoke('start',0);r.shutdown();r.audio();put32(r.m,AUDIO,1)
    assert r.shutdown()==BUSY and r.owner()
    put32(r.m,AUDIO,0);assert r.shutdown()==OK
    put32(r.m,AUDIO,1);assert r.shutdown()==FAULT and r.word()&F
    passed('unexpected_audio_activity_blocks_retirement_and_faults_after_exclusive_access_is_granted')

    r=Rig();r.invoke('start',0);r.ready();first=r.sf(5);ticket=r.sf(8)
    assert r.finish()==OK and r.invoke('start',0)==OK
    assert r.shutdown()==BUSY and r.sf(5)>first
    assert r.finish(ticket)==STALE and r.owner()
    r.audio();assert r.shutdown()==OK and r.sf(8)>ticket
    passed('second_cycle_requires_new_control_audio_and_ownership_epochs')

    r=Rig();r.invoke('start',0);put32(r.m,SESSION+8,1)
    assert r.shutdown()==BUSY and r.sf(4)==1 and r.u32(C+12)==1
    put32(r.m,SESSION+8,0);assert r.shutdown()==BUSY and r.field(7)==1
    passed('session_operation_already_in_progress_is_joined_before_stopping_or_fencing')

    r=Rig();r.invoke('start',0);r.ready();ticket=r.sf(8)
    put32(r.m,LEDGER,r.word()|F)
    assert r.shutdown()==FAULT and r.finish(ticket)==FAULT and r.sf(8)==ticket
    assert r.field(7)==1 and r.u32(C+12)==1
    passed('external_ownership_fault_invalidates_held_result_and_prevents_reopen')

    r=Rig();r.invoke('start',0)
    # Real control worker held inside original effects lock; independent session
    # manager must hold playback admission but leave audio playing until drain.
    from verify_control_coordinator import Rig as ControlRig
    w=ControlRig();_,job=w.submit();w.held=True;w.run()
    r.m.uc.mem_write(C,w.raw(C,w.size))
    assert r.shutdown()==BUSY and r.sf(4)==2 and r.mask()==1 and r.u32(AUDIO)==1
    assert r.invoke('start',0)==BUSY and r.invoke('scan')==BUSY
    w.m.uc.mem_write(C,bytes(r.m.uc.mem_read(C,w.size)));w.held=False;w.resume()
    assert w.phase(job)==3
    r.m.uc.mem_write(C,w.raw(C,w.size))
    assert r.shutdown()==BUSY and r.mask()==0
    r.audio();assert r.shutdown()==OK
    passed('admitted_control_handler_finishes_before_playback_stop_and_audio_completion_request')

    r=Rig();r.invoke('start',0);r.ready();old=r.field(6)
    ticket=r.sf(8)
    assert r.call('promote_end',ticket,0)==OK and r.ctrl('reopen',r.sf(5))==OK
    # State at finish's final unhold return, before bookkeeping resets. A start
    # may acquire the released session latch during this exact allowed interval.
    put32(r.m,SD+16,8);assert r.invoke('unhold')==OK
    assert r.invoke('start',0)==OK and r.owner()!=old and r.field(6)==0
    passed('start_after_final_hold_release_does_not_spuriously_fault_before_finish_bookkeeping_clears')

    out=ROOT/'analysis/playback_shutdown_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=[
      'Compiled offline integration only; session and shutdown port hooks are explicitly bound by harness, not stock dispatcher patches',
      'All four pads stop because existing publication may replace all four; selected-pad-only replacement is not implemented',
      'Fade progress, stream queue scheduling, filesystem reads and seeks modeled; original stop/scan/worker and full DSP instructions exercised',
      'Full audio on separate ARM CPU with explicit state transfer; physical timing/cache/DMA not modeled',
      'Protected sample buffers demonstrate tested inactive-reader paths only, not exhaustive indirect pointer analysis',
      'Direct callers outside session/control admission remain uncovered; sole manager owns closure/reopen',
      'Ledger excludes only attributed work; actual USB/card/ordinary-recorder ingress remains unbound',
      'No actual publication, firmware image packaging, device change or recovery claim']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
