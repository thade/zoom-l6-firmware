#!/usr/bin/env python3
"""Owned request attribution across original L6 branches, entirely offline.

Scopes and queue identity sidecars are supplied by this serialized adapter.
They are not discovered task-local storage or installed stock message changes.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_emulator_bridge import BridgeRig,BR
from verify_record_scheduler import request_setup,word
from verify_record_events import START_SAVED
from verify_history_capture import payload
from verify_extra_capture import ELF
from verify_pad_protocol import ROOT,IMAGE

ROUTER=0x2201a000
REQUESTS=0x2201a100
MORE={0x80035030:'emulator_accept_start_hook',0x8004b718:'emulator_submit_stop_hook',
      0x8004b708:'emulator_start_sent_hook',0x8004b74a:'emulator_stop_sent_hook'}

class RequestRig(BridgeRig):
    def __init__(self,count=32):
        super().__init__(count);self.jobs=[];self.next_request=REQUESTS;self.current=0;self.send_result=0
        self.rlayout=struct.unpack('<3I',self.raw(self.syms['rr_layout'],12))
        assert self.m.invoke(self.syms['rr_init'],[ROUTER,BR,123])==0
        for address,name in MORE.items():
            self.m.uc.hook_add(UC_HOOK_CODE,
                lambda uc,a,s,u,name=name:uc.reg_write(UC_ARM_REG_PC,self.syms[name]),begin=address,end=address)
        self.m.hooks[0x800483f8]=self.send
    def rr(self,name,q,*args):return self.m.invoke(self.syms['rr_'+name],[ROUTER,q,*args])
    def begin(self):
        q=self.next_request;self.next_request+=0x80
        assert self.rr('begin',q)==0;return q
    def released(self,q):return self.m.invoke(self.syms['rr_released'],[q])
    def scope(self,q,callback=0):
        return self.m.invoke(self.syms['bridge_route_scope'],[BR,q,callback])
    def send(self,a):
        if self.send_result==0:self.jobs.append((self.current,bytes(self.m.uc.mem_read(a[1],32))))
        return self.send_result
    def request(self,ui=0,busy=0,reject=False):
        q=self.begin();self.current=q;assert self.scope(q)==0
        request_setup(self.m,ui,busy)
        if reject:self.m.hooks[0x80006290]=lambda a:1
        self.m.invoke(0x80034f40,[0xffffffff])
        assert self.scope(0)==0;assert self.rr('finish_request',q)==0
        self.current=0;return q
    def dispatch(self):
        q,msg=self.jobs.pop(0);assert self.rr('dispatch',q)==0
        assert self.scope(q,1)==0
        kind=struct.unpack_from('<I',msg)[0]
        # The body checkpoints are original windows; unrelated file setup/UI
        # remain fixtures. Exact request identity comes from the queue sidecar.
        if kind==0x8004b9a1:self.admit()
        elif kind==0x8004ba41:self.stop()
        else:raise AssertionError(hex(kind))
        assert self.scope(0,1)==0;assert self.rr('complete',q)==0
        return q
    def seed_snapshot(self,q):
        assert self.scope(q)==0;self.start();assert self.scope(0)==0
    def finish(self):
        self.request(1);self.dispatch();assert self.pump()==0

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=RequestRig();r.block();q=r.request();assert len(r.jobs)==1
    assert r.step()==11 and not r.released(q)
    r.dispatch();assert r.released(q)
    for _ in range(8):r.block();assert r.pump()==11
    r.finish();r.validate(payload(64,576))
    passed('full_stock_request_start_and_Record_to_stop_produce_exact_extra_file',frames=512)

    # Bad snapshots for ignored/rejected requests must remain local.
    for ui,busy,reject in ((0,1,False),(2,0,False),(1,0,True)):
        r=RequestRig();r.block();r.request();r.dispatch();r.block();assert r.pump()==11
        before=word(r.m,BR+16)
        q=r.request(ui,busy,reject);assert r.released(q) and not r.jobs
        assert word(r.m,BR+16)==before==0
        r.block();r.finish();r.validate(payload(64,192))
    passed('ignored_busy_playback_and_rejected_requests_do_not_cancel_active_take')

    # Timestamp comes from actual early setter, before admission or later laps.
    r=RequestRig();r.block();q=r.begin();r.seed_snapshot(q)
    stamp=struct.unpack('<Q',r.raw(q+r.rlayout[2],8))[0];assert stamp==64
    for _ in range(10):r.block()
    assert r.rr('submit',q,3)==0 and r.rr('sent',q,0)==0
    assert r.rr('dispatch',q)==0;assert r.scope(q,1)==0;r.admit();r.scope(0,1)
    assert r.rr('complete',q)==0;assert r.pump()==11
    r.finish();r.validate(payload(64,704))
    passed('owned_start_timestamp_survives_delay_across_multiple_stock_ring_wraps')

    # The queue can deliver before its sender resumes; reservation covers both.
    r=RequestRig();r.block();q=r.begin();r.seed_snapshot(q)
    assert r.rr('submit',q,3)==0 and r.rr('dispatch',q)==0
    r.scope(q,1);r.admit();r.scope(0,1);assert r.rr('complete',q)==0
    assert not r.released(q)
    assert r.rr('sent',q,0)==0 and r.released(q)
    r.block();r.finish();r.validate(payload(64,128))
    passed('callback_can_complete_before_send_result_without_losing_request_ownership')

    for is_stop in (False,True):
        r=RequestRig();r.block()
        if is_stop:r.request();r.dispatch();r.block();assert r.pump()==11
        r.send_result=0xffffffff;q=r.request(1 if is_stop else 0)
        assert not r.released(q) and not r.jobs
        assert r.pump() not in (0,10,11) and not r.eligible() and not r.opened
        # Only the explicit queue model proves no delivery; the stock wrapper's
        # failure by itself leaves ownership uncertain and retained.
        assert r.rr('sent',q,1)==16 and r.released(q)
        r.assert_ordinary()
    passed('actual_queue_send_failure_cancels_and_retains_ownership_until_non_delivery_confirmed')

    r=RequestRig();r.block();q=r.request();r.dispatch();r.block()
    before=r.raw(BR,r.blayout[0]);assert r.rr('dispatch',q)==12
    assert r.raw(BR,r.blayout[0])==before
    r.finish();r.validate(payload(64,128))
    # Wrong router/session object cannot dispatch or mark active request.
    r=RequestRig();r.block();q=r.request()
    wrong=ROUTER+0x40;r.m.uc.mem_write(wrong,struct.pack('<5I',BR,124,0,1,0))
    before=r.raw(BR,r.blayout[0])
    assert r.m.invoke(r.syms['rr_dispatch'],[wrong,q])==12
    assert r.m.invoke(r.syms['rr_mark'],[wrong,q,0])==12
    assert r.raw(BR,r.blayout[0])==before
    r.dispatch();r.block();r.finish();r.validate(payload(64,128))
    passed('replayed_completed_and_wrong_session_callbacks_cannot_publish_events')

    r=RequestRig();r.block();q=r.request();assert r.rr('dispatch',q)==0
    assert r.rr('complete',q)==16 and r.released(q)
    r.assert_failed()
    passed('callback_return_without_registration_checkpoint_cancels_optional_file')

    # Unknown transport outcome retains the request even after callback return.
    r=RequestRig();r.block();q=r.begin();r.seed_snapshot(q)
    assert r.rr('submit',q,3)==0 and r.rr('sent',q,2)==22
    assert not r.released(q);r.assert_failed()
    assert r.m.invoke(r.syms['bridge_retire_quiesced'],[BR,123])==11
    passed('unknown_send_outcome_retains_request_and_blocks_retirement',
           limitation='No recovery/release without definitive outcome or separately proven drain fence')

    r=RequestRig();r.block();q=r.begin();r.seed_snapshot(q)
    assert r.rr('submit',q,3)==0 and r.rr('dispatch',q)==0
    r.scope(q,1);r.admit();r.scope(0,1);r.rr('complete',q)
    assert r.rr('sent',q,1)==23 and r.released(q);r.assert_failed()
    passed('contradictory_not_queued_after_delivery_cancels_instead_of_accepting_file')

    # An actually accepted second start is unsupported, not silently assigned
    # to the old take. Busy/ignored requests above do not take this path.
    r=RequestRig();r.block();r.request();r.dispatch();r.block();q=r.request(0,0)
    r.assert_failed()
    assert not r.released(q)
    assert r.m.invoke(r.syms['bridge_retire_quiesced'],[BR,123])==11
    assert r.rr('dispatch',q)==0 and r.rr('complete',q)==16 and r.released(q)
    passed('overlapping_accepted_start_cancels_optional_capture_without_replacing_owner')

    r=RequestRig();r.block();q=r.begin();r.seed_snapshot(q)
    assert r.scope(q)==0 and r.scope(q)==11 and r.scope(0)==0
    assert r.rr('ignore',q)==0 and r.released(q)
    assert r.rr('begin',q)==12
    r.request();r.dispatch();r.block();r.finish();r.validate(payload(64,128))
    passed('scope_overlap_and_request_storage_reuse_are_rejected')

    r=RequestRig();r.block();q=r.request();r.block()
    ignored=r.request(0,1);assert r.released(ignored)
    assert word(r.m,START_SAVED)!=64
    r.dispatch();r.assert_failed()
    passed('changed_stock_start_cursor_before_admission_cancels_extra_instead_of_mismatching_stems',
           limitation='Stock saved-cursor updates are not redirected or restored')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        router_bytes=r.rlayout[0],request_bytes=r.rlayout[1],bridge_bytes=r.blayout[0],
        limitations=['Explicit serialized request/callback scopes; not real task-local context',
          'Owned request queue sidecars supplied by emulator, not installed stock message tags',
          'Callback registration and stop checkpoints execute; full callback bodies/SD/RTOS do not',
          'Legacy isolated bridge fixtures remain available with routing disabled',
          'No real repeated-session rearm, worker scheduling, RAM placement or device patch'])
    path=ROOT/'analysis/request_router_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))

if __name__=='__main__':main()
