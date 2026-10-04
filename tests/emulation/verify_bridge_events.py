#!/usr/bin/env python3
"""Bounded queued control events and worker-owned optional-file cancellation.

Instruction interleavings and peer-CPU publications are scheduled explicitly.
Real RTOS wakeup, old callback exclusion and reclamation remain unbound.
"""
import hashlib,json,struct
from verify_emulator_bridge import BridgeRig,BR
from verify_extra_capture import STATE,ELF
from verify_extra_lifecycle import LIFE
from verify_block_exchange import P
from verify_history_capture import payload
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

STAMP=0x22019000

class QueueRig(BridgeRig):
    def __init__(self,count=16):
        super().__init__(count)
        self.qlayout=struct.unpack('<9I',self.raw(self.syms['bridge_queue_layout'],36))
    def qaddr(self,index):return BR+self.qlayout[index]
    def word(self,address):return struct.unpack('<I',self.raw(address,4))[0]
    def publish(self,kind,stamp=0,session=123):
        self.m.uc.mem_write(STAMP,struct.pack('<Q',stamp))
        return self.m.invoke(self.syms['bridge_publish'],[BR,session,kind,STAMP])
    def retire(self):return self.m.invoke(self.syms['bridge_retire_quiesced'],[BR,123])
    def peer_publish(self,peer,kind,stamp=0):
        # Separate CPU registers/stack; only shared bridge/mailbox copied back.
        peer.m.uc.mem_write(BR,self.raw(BR,self.blayout[0]))
        result=peer.publish(kind,stamp)
        self.m.uc.mem_write(BR,peer.raw(BR,self.blayout[0]))
        return result

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=QueueRig();r.block();r.start();r.admit()
    for _ in range(10):r.block()
    r.stop()
    assert r.word(r.qaddr(2))-r.word(r.qaddr(1))==3
    assert r.pump()==0;r.validate(payload(64,704))
    passed('delayed_start_admission_stop_delivery_preserves_event_time_tokens_across_multiple_stock_wraps')

    r=QueueRig();put32(r.m,r.qaddr(1),6);put32(r.m,r.qaddr(2),6)
    r.start();r.admit();r.block();r.stop()
    assert r.pump()==0;r.validate(payload(0,64))
    assert r.word(r.qaddr(1))==9 and r.word(r.qaddr(2))==9
    passed('mailbox_payload_wrap_preserves_FIFO_order')

    r=QueueRig();calls=len(r.calls)
    for _ in range(8):assert r.publish(3)==0
    assert r.publish(3)==21 and len(r.calls)==calls
    r.assert_failed()
    r=QueueRig();put32(r.m,r.qaddr(1),0xffffffff);put32(r.m,r.qaddr(2),0xffffffff)
    assert r.publish(3)==21;r.assert_failed()
    passed('full_queue_and_counter_exhaustion_latch_failure_without_hook_IO_or_silent_event_loss')

    for sequence in ((5,3),(3,3),(3,4),(3,5,4,4)):
        r=QueueRig()
        for kind in sequence:assert r.publish(kind,64 if kind==4 else 0)==0
        r.assert_failed()
    passed('out_of_order_and_duplicate_control_events_cancel_optional_take')

    r=QueueRig();put32(r.m,r.qaddr(0),1)
    before=r.raw(BR,r.blayout[0]);calls=len(r.calls)
    assert r.step()==11 and r.raw(BR,r.blayout[0])==before
    assert r.publish(3)==20 and len(r.calls)==calls
    put32(r.m,r.qaddr(0),0);r.assert_failed()
    passed('worker_defers_on_queue_contention_and_producer_contention_latches_cancellation')

    r=QueueRig();r.start();r.admit();r.block()
    put32(r.m,r.qaddr(3),1);calls=len(r.calls)
    assert r.step()==11 and len(r.calls)==calls
    put32(r.m,r.qaddr(3),0);r.stop();assert r.pump()==0
    passed('second_worker_cannot_enter_file_lifecycle_while_first_is_busy')

    # Cancellation published by another CPU while the worker is in file IO.
    for operation in ('audio','close_read'):
        r=QueueRig();peer=QueueRig();r.start();r.admit();r.block();r.stop()
        original=r.hit;published=[]
        def during_io(op):
            if op==operation and not published:
                published.append(r.peer_publish(peer,6))
            return original(op)
        r.hit=during_io
        r.assert_failed();assert published==[0]
        assert r.phase()==7 and not r.life('life_verified_path')
    passed('peer_CPU_cancellation_during_audio_write_or_final_read_close_revokes_all_file_eligibility')

    r=QueueRig();r.start();r.admit();r.block();r.stop()
    # Simulates a reserved hook paused before completion. The high bit closes
    # new admission, but the old reservation must drain before eligibility.
    put32(r.m,r.qaddr(8),1)
    assert r.pump()==11 and not r.eligible()
    assert r.word(r.qaddr(8))==0x80000001
    assert r.publish(6)==12
    put32(r.m,r.qaddr(8),0x80000000)
    assert r.pump()==0 and r.eligible()
    before=r.raw(BR,r.blayout[0]);assert r.publish(6)==12
    assert r.raw(BR,r.blayout[0])==before
    passed('completion_closes_admission_and_waits_for_prior_hook_reservations_before_exposing_path',
           limitation='Reservation pause injected into shared state; hardware preemption not reproduced')

    r=QueueRig();before=r.raw(BR,r.blayout[0])
    assert r.publish(3,session=122)==12 and r.raw(BR,r.blayout[0])==before
    assert r.retire()==11
    fresh=BR+0x300;put32(r.m,fresh+12,124)
    assert r.m.invoke(r.syms['bridge_bind'],[fresh,P,LIFE,STATE])==12
    r.start();r.admit();r.block();r.stop();assert r.pump()==0
    assert r.claim(0)[0]==0 and r.retire()==11
    assert r.release(0)==0
    # This test declares the emulator quiescent. It does NOT establish that the
    # real device's old queued callbacks or interrupts have been fenced.
    assert r.retire()==0 and r.step()==12 and not r.eligible()
    assert r.publish(3)==12
    assert r.m.invoke(r.syms['bridge_bind'],[BR,P,LIFE,STATE])==12
    assert r.m.invoke(r.syms['bridge_bind'],[fresh,P,LIFE,STATE])==0
    old=r.raw(fresh,r.blayout[0])
    r.m.uc.mem_write(STAMP,bytes(8))
    assert r.m.invoke(r.syms['bridge_publish'],[fresh,123,3,STAMP])==12
    assert r.raw(fresh,r.blayout[0])==old
    passed('retirement_requires_terminal_idle_unleased_state_and_fresh_binding_rejects_old_session_tokens',
           limitation='Fresh binding tested only; actual new file/pool preparation and external callback fence remain caller obligations')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        bridge_state_bytes=r.blayout[0],queue_slots=8,packet_bytes=r.qlayout[7],
        limitations=['Explicit emulator scheduling and peer-CPU state transfer; no real RTOS wakeup binding',
          'Queue contention cancels optional capture rather than waiting; real contention frequency unmeasured',
          'One audio producer and one file worker; control publishers use bounded try-lock admission',
          'Retirement function requires external full quiescence, including old stock queued callbacks',
          'No claim that retired storage is safe to reclaim without that missing external fence',
          'Hardware RAM/cache/performance, pad assignment and deployment remain unresolved'])
    target=ROOT/'analysis/bridge_events_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(target)),indent=2))

if __name__=='__main__':main()
