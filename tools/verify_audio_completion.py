#!/usr/bin/env python3
"""Compiled completion protocol at real stock dispatch/return boundaries.

Python supplies proposed hooks using a separate ARM CPU and copies coordinator
state at explicit scheduling points. This is not an installed trampoline or an
interrupt/cache timing model. Original callbacks run without DSP substitutions.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0
from verify_control_coordinator import Rig,C,OK,BUSY,STALE,EXHAUSTED
from verify_pad_reader_audit import AuditRig,SELECTOR,SECONDARY,TARGETS
from verify_pad_renderer_boundary import AUDIO
from verify_firmware_workflow import put32
from verify_overdub_prototype import ELF
from verify_pad_protocol import ROOT,IMAGE
FAULT=6
PRIMARY=0x2022a791; SECOND=0x2022a789

class Bridge:
    def __init__(self,control=None):
        self.control=control or Rig();self.audio=AuditRig();self.token=None
        self.events=[];self.at_entry=None;self.midblock=None;self.at_return=None
        a=self.audio
        def entry(uc,pc,n,u):
            # BLX r0: use the actual admitted target, not a reread of SELECTOR.
            self.token=self.control.call('audio_begin',uc.reg_read(UC_ARM_REG_R0),a.word(SECONDARY))
            self.events.append(('entry',self.token))
            if self.at_entry:self.at_entry(self)
        def middle(uc,pc,n,u):
            if self.midblock:self.midblock(self)
        def end(uc,pc,n,u):
            if self.token is None:return # Null dispatch did not enter callback.
            if self.at_return:self.at_return(self)
            result=self.control.call('audio_end',self.token,a.word(SELECTOR),a.word(SECONDARY))
            self.events.append(('end',result));self.token=None
        a.m.uc.hook_add(UC_HOOK_CODE,entry,begin=0x8001078c,end=0x8001078c)
        a.m.uc.hook_add(UC_HOOK_CODE,middle,begin=0x2022a796,end=0x2022a796)
        a.m.uc.hook_add(UC_HOOK_CODE,end,begin=0x8001078e,end=0x8001078e)
    def request(self):
        assert self.control.close()==(OK,1)
        assert self.control.call('audio_request',1)==OK
    def block(self,target=TARGETS[0],select=True):self.audio.full(target,select)

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    for target in TARGETS:
        b=Bridge();b.request();b.audio.seed(length=17)
        assert b.control.call('audio_poll',1)==BUSY and b.control.call('reopen',1)==BUSY
        b.at_entry=lambda b:check(b.control.call('audio_poll',1)==BUSY)
        b.at_return=lambda b:check(b.control.call('audio_poll',1)==BUSY)
        b.block(target)
        assert b.events==[('entry',1),('end',OK)] and b.audio.entries[0]==target
        assert b.control.call('audio_poll',1)==OK and b.control.call('reopen',1)==OK
    passed('all_four_actual_stock_callbacks_acknowledge_only_after_complete_postrequest_return')

    b=Bridge();b.audio.seed(length=17)
    def mid(b):
        b.request();assert b.control.call('audio_poll',1)==BUSY
    b.midblock=mid;b.block();assert b.control.call('audio_poll',1)==BUSY
    b.midblock=None;b.block();assert b.control.call('audio_poll',1)==OK
    passed('request_between_renderer_return_and_later_DSP_completion_waits_for_next_whole_callback')

    b=Bridge();b.request();put32(b.audio.m,SELECTOR,0);b.block(select=False)
    assert not b.events and b.control.call('audio_poll',1)==BUSY
    assert b.control.call('reopen',1)==BUSY
    for _ in range(4):assert b.control.call('audio_poll',1)==BUSY
    passed('null_dispatch_and_absent_audio_never_acknowledge_or_time_out_into_reopen')

    b=Bridge();b.request();b.audio.seed(length=17)
    # Change selection after the stock load and our entry, before actual BLX.
    b.at_entry=lambda b:put32(b.audio.m,SELECTOR,0x800133e9)
    b.block();assert b.audio.entries[0]==TARGETS[0]
    assert b.events[-1]==('end',FAULT) and b.control.call('audio_poll',1)==FAULT
    assert b.control.call('reopen',1)==FAULT
    passed('loaded_old_callback_finishing_after_selector_change_latches_fault')

    b=Bridge();b.request()
    b.at_return=lambda b:put32(b.audio.m,SECONDARY,0)
    b.block();assert b.control.call('audio_poll',1)==FAULT
    passed('secondary_slot_change_invalidates_return_even_when_primary_matches')

    for primary,secondary in ((0,SECOND),(0x2022a790,SECOND),(0x21000281,SECOND),(PRIMARY,0)):
        r=Rig();r.close();r.call('audio_request',1)
        assert r.call('audio_begin',primary,secondary)==0
        assert r.call('audio_poll',1)==FAULT and r.call('reopen',1)==FAULT
    passed('unknown_null_non_thumb_or_unrecognized_secondary_entry_is_rejected')

    for bad in ('nested','zero','wrong','duplicate'):
        r=Rig();r.close();r.call('audio_request',1);t=r.call('audio_begin',PRIMARY,SECOND)
        if bad=='nested':assert r.call('audio_begin',PRIMARY,SECOND)==0
        elif bad=='duplicate':
            assert r.call('audio_end',t,PRIMARY,SECOND)==OK
            assert r.call('audio_end',t,PRIMARY,SECOND)==FAULT
        else:assert r.call('audio_end',0 if bad=='zero' else t+1,PRIMARY,SECOND)==FAULT
        assert r.call('audio_poll',1)==FAULT and r.call('reopen',1)==FAULT
    passed('nested_unmatched_and_duplicate_returns_latch_fault_including_after_prior_ack')

    r=Rig();r.close();r.call('audio_request',1);r.call('audio_begin',PRIMARY,SECOND)
    assert r.call('audio_poll',1)==BUSY and r.call('reopen',1)==BUSY
    passed('missing_return_keeps_closure_pinned')

    r=Rig();_,job=r.submit();r.held=True;r.run();p=r.peer();p.close()
    assert p.call('audio_request',1)==BUSY
    r.import_peer(p);r.held=False;r.resume()
    assert r.phase(job)==3 and r.call('audio_request',1)==OK
    b=Bridge(r);b.block();assert r.call('audio_poll',1)==OK
    passed('request_cannot_overtake_running_control_handler_but_succeeds_after_real_return')

    b=Bridge();b.request();_,job=b.control.submit(5,(0,0));b.block()
    assert b.control.call('audio_poll',1)==OK and b.control.run()==BUSY
    assert b.control.phase(job)==1 and b.control.call('reopen',1)==OK
    assert b.control.run()==OK and b.control.phase(job)==3
    assert b.control.close()==(OK,2) and b.control.call('audio_poll',1)==STALE
    assert b.control.call('audio_request',2)==OK and b.control.call('audio_poll',2)==BUSY
    b.block();assert b.control.call('audio_poll',2)==OK
    passed('queued_controls_remain_parked_after_ack_until_reopen_and_new_epoch_needs_new_completion')

    r=Rig();assert r.call('audio_request',1)==STALE
    r.close();assert r.call('audio_poll',1)==STALE
    assert r.call('audio_request',2)==STALE and r.call('audio_request',1)==OK
    assert r.call('audio_request',1)==BUSY and r.call('audio_poll',2)==STALE
    passed('missing_stale_and_duplicate_requests_do_not_replace_current_epoch')

    r=Rig();r.close();r.call('audio_request',1);put32(r.m,C,1)
    t=r.call('audio_begin',PRIMARY,SECOND);assert t==1
    assert r.call('audio_end',t,PRIMARY,SECOND)==OK and r.word(C)==1
    assert r.call('audio_poll',1)==BUSY
    put32(r.m,C,0);assert r.call('audio_poll',1)==OK
    passed('audio_entry_and_return_never_wait_for_control_metadata_lock')

    r=Rig();_,seq,_=struct.unpack('<3I',r.raw(r.m.symbols['oc_audio_layout'],12))
    put32(r.m,C+seq,0xffffffff);r.close();r.call('audio_request',1)
    assert r.call('audio_begin',PRIMARY,SECOND)==0 and r.call('audio_poll',1)==FAULT
    passed('callback_tokens_never_wrap_or_reuse')

    b=Bridge();b.request();b.audio.seed(length=128,loop=1);b.block()
    assert b.control.call('audio_poll',1)==OK and b.audio.word(AUDIO)==1
    b.block();assert len(b.audio.samples())==128 and b.control.call('audio_poll',1)==OK
    passed('negative_control_ack_does_not_stop_audio_or_make_looping_pad_buffers_safe_to_replace')

    out=ROOT/'analysis/audio_completion_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      coordinator_bytes=r.size,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
      elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=[
      'Python dispatch/return hooks invoke compiled protocol on a separate ARM CPU; no installed assembly adapter or register-preservation proof',
      'Actual original callback instructions, with synthetic memory/input routing and idle effects processor; output continuation not executed',
      'Single serialized audio producer assumed; atomics emitted but hardware interrupt/cache/DMA scheduling unverified',
      'Only known targets and endpoint selector checks; transient changes restored before return are not detectable',
      'Control admission coverage incomplete; acknowledgement is a past completion barrier, not future reader exclusion',
      'Playback session fence remains unbound; no stream/card/recorder join, manager publication wiring or hardware change']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))

def check(value):assert value
if __name__=='__main__':main()
