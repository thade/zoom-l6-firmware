#!/usr/bin/env python3
"""Offline admission close / control FIFO acknowledgement; not a reclaim fence."""
import hashlib,json,struct
from verify_auto_requests import AutoRig
from verify_control_transport import T,TASK,PRODUCER,WORKER,OTHER,DEPTH,QHANDLE
from verify_request_router import ROUTER
from verify_record_scheduler import word
from verify_history_capture import payload
from verify_extra_capture import ELF
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32

MUTEX=0x21033300
class DrainRig(AutoRig):
    def __init__(self):
        super().__init__()
        put32(self.m,0x80446dc0,WORKER);put32(self.m,0x80446894,MUTEX)
        self.dlayout=struct.unpack('<5I',self.raw(self.syms['ct_drain_layout'],20))
    def close(self,session=123):return self.m.invoke(self.syms['ct_close_admission'],[T,session])
    def poll(self,session=123):return self.m.invoke(self.syms['ct_drain_poll'],[T,session])
    def field(self,i):return word(self.m,T+self.dlayout[i])
    def marker(self,words,task=WORKER):
        address=0x21034000;self.m.uc.mem_write(address,struct.pack('<4I',*words))
        put32(self.m,TASK,task);self.m.invoke(self.syms['ct_drain_marker'],[address]);put32(self.m,TASK,PRODUCER)

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=DrainRig();r.block();r.request();r.dispatch_all();r.block();q=r.request(1)
    assert r.close()==0 and r.poll()==11 and not r.released(q)
    r.dispatch_all();assert r.pump()==0
    assert r.poll()==10;count=len(r.sent);assert r.poll()==11 and len(r.sent)==count
    r.dispatch_all();assert r.poll()==0;r.validate(payload(64,128));r.idle_scopes()
    passed('queued_stop_must_finish_then_marker_must_arrive_before_acknowledgement',frames=64)

    r=DrainRig();r.block();r.request();r.dispatch_all();r.block()
    q=r.begin();assert r.scope(q)==0;assert r.close()==0 and r.poll()==11
    # Resume an already admitted producer after admission closes.
    r.m.invoke(0x8004b718,[0]);assert r.poll()==11
    assert r.scope(0)==0;r.rr('finish_request',q);assert r.poll()==11
    r.dispatch_all();assert r.pump()==0 and r.poll()==10
    r.dispatch_all();assert r.poll()==0;r.validate(payload(64,128))
    passed('earlier_admitted_request_can_submit_after_close_and_blocks_marker_until_complete')

    r=DrainRig();q=r.begin();assert r.close()==0 and r.poll()==11
    assert r.rr('finish_request',q)==0 and r.poll()==10
    r.dispatch_all();assert r.poll()==0
    passed('unsubmitted_earlier_request_blocks_until_its_ignored_return')

    r=DrainRig();assert r.close()==0;cutoff=r.field(1);assert r.poll()==10
    count=len(r.sent);r.request(0,entry=0x80034e58)
    assert word(r.m,ROUTER+8)==cutoff and word(r.m,T+16)==0
    assert len(r.sent)==count+1 and struct.unpack_from('<I',r.sent[-1])[0]==0x8004b891
    # Deliver only the marker via the real worker; retain a later stock message.
    later=r.wire.pop();r.dispatch_all();r.wire.append(later)
    assert r.poll()==0 and len(r.wire)==1 and r.close()==0 and r.field(1)==cutoff
    r.request(1);assert struct.unpack_from('<I',r.sent[-1])[0]==0x8004ba41
    put32(r.m,TASK,OTHER);r.request(1);put32(r.m,TASK,PRODUCER)
    assert word(r.m,ROUTER+8)==cutoff and word(r.m,T+16)==0
    passed('new_stock_requests_continue_after_close_and_ack_is_not_queue_empty')

    r=DrainRig();assert r.poll()==12 and r.close(122)==12
    put32(r.m,0x80446dc0,0);assert r.close()==12 and r.field(0)==0
    put32(r.m,0x80446dc0,WORKER);assert r.close()==0 and r.poll(122)==12
    put32(r.m,TASK,WORKER);assert r.poll()==12;put32(r.m,TASK,PRODUCER)
    assert r.rr('begin',0x2201a900)==12 and r.poll()==10
    valid=[T,123,r.field(1),0x4c364452]
    for i in range(4):
        bad=valid.copy();bad[i]^=1;r.marker(bad);assert r.field(3)==0
    r.marker(valid,OTHER);assert r.field(3)==0 and r.poll()==11
    r.dispatch_all();assert r.poll()==0
    passed('wrong_session_missing_worker_self_wait_new_admission_and_bad_markers_are_rejected')

    r=DrainRig();r.block();r.send_result=0xffffffff;r.request()
    assert r.close()==0;count=len(r.sent)
    assert r.poll()==11 and r.poll()==11 and len(r.sent)==count
    passed('uncertain_earlier_send_retains_ownership_and_prevents_marker')

    for failure in ('send','acquire','release'):
        r=DrainRig();assert r.close()==0;calls=[]
        def wait(a):
            assert word(r.m,DEPTH)==0 and a[0]==MUTEX
            calls.append('acquire');return 0 if failure=='acquire' else 1
        def send(a):
            assert word(r.m,DEPTH)==0
            if a[0]==MUTEX:calls.append('release');return 0 if failure=='release' else 1
            calls.append('send');return r.kernel_send(a)
        r.m.hooks[0x80076950]=wait;r.m.hooks[0x800763d8]=send
        if failure=='send':r.send_result=0xffffffff
        assert r.poll()==30 and r.poll()==30
        assert calls==(['acquire'] if failure=='acquire' else ['acquire','send','release'])
        # Even hypothetical late delivery cannot convert an uncertain outcome to success.
        r.marker([T,123,r.field(1),0x4c364452]);assert r.poll()==30
    passed('acquire_send_and_release_failure_are_sticky_without_retry_or_premature_ack')

    for final_send_ok in (True,False):
        r=DrainRig();assert r.close()==0;observations=[]
        def send_with_early_delivery(a):
            if a[0]!=QHANDLE:return 1
            assert word(r.m,DEPTH)==0
            wire=bytes(r.m.uc.mem_read(a[1],32));r.sent.append(wire)
            # Independent CPU avoids recursive Unicorn emulation. Only Transport
            # bytes move back; Router/Bridge are idle and unchanged in this case.
            peer=DrainRig();peer.m.uc.mem_write(T,r.raw(T,r.tlayout[0]));peer.wire=[wire]
            assert peer.field(2)==1 and peer.poll()==11
            peer.dispatch_all();assert peer.field(3)==1 and peer.poll()==11
            observations.append(True);r.m.uc.mem_write(T,peer.raw(T,peer.tlayout[0]))
            return 1 if final_send_ok else 0
        r.m.hooks[0x800763d8]=send_with_early_delivery
        expected=0 if final_send_ok else 30
        assert r.poll()==expected and r.poll()==expected and observations==[True]
    passed('marker_before_send_returns_waits_for_confirmed_send_and_release_on_independent_cpu')

    r=DrainRig();assert r.close()==0
    slot=r.slots()[0];put32(r.m,slot+64,1)
    assert r.poll()==11 and not r.sent
    put32(r.m,slot+64,0);assert r.poll()==10
    r.dispatch_all();assert r.poll()==0
    passed('live_entry_cookie_blocks_marker_even_when_router_pending_is_zero')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      transport_bytes=r.tlayout[0],
      limitations=['Control FIFO prefix acknowledgement only; later stock work may still be queued',
        'Kernel queue/task switching and mutex results are controlled fixtures; not full RTOS scheduling',
        'Early callback interleaving uses two CPUs with explicit Transport state transfer',
        'Close must follow admission of the capture stop request; it does not stop or finalize audio',
        'No audio-hook or filesystem lifetime fence, memory reclaim, session reset/rearm or device writes'])
    path=ROOT/'analysis/control_drain_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))
if __name__=='__main__':main()
