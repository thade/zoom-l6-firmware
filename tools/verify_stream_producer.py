#!/usr/bin/env python3
"""Offline original stream producer -> ticket transport -> original worker.

Only emulator call-site redirection and synthetic queue/RTOS effects. No device
access, installed patch, real audio conversion or SD-card transfer.
"""
import hashlib
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_work_ownership import Rig, LEDGER, OK, BUSY, FULL, FAULT, P, F
from verify_scheduling_boundaries import BASE
from verify_firmware_workflow import put32
from verify_overdub_prototype import ELF
from verify_pad_protocol import ROOT, IMAGE

CONTEXT=0x21003900
SEND=0x210001c0


class ProducerRig(Rig):
    def __init__(self,pads=(0,)):
        super().__init__();m=self.m
        self.queue=[];self.events=[];self.entered=0;self.return_success=True
        self.deliver=True;self.early_worker=False;self.lock_after_send=False
        self.early_observations=[]
        put32(m,0x801f8f34,0x6500)
        for pad in pads:self.seed(pad)
        for fn in (0x8001aaa0,0x8001aab8,0x80005eb0):m.hooks[fn]=lambda a:0
        m.hooks[0x800763d8]=self.send
        def redirect(uc,address,size,unused):
            uc.reg_write(UC_ARM_REG_PC,m.symbols['od_emulator_stream_publish_trampoline'])
        def entry(uc,address,size,unused):self.entered+=1
        m.uc.hook_add(UC_HOOK_CODE,redirect,begin=0x8003664a,end=0x8003664a)
        m.uc.hook_add(UC_HOOK_CODE,entry,begin=0x80036508,end=0x80036508)

    def seed(self,pad,frames=8):
        state=BASE+pad*0x44
        self.m.uc.mem_write(state,b'\x01')
        for offset,value in ((4,0),(0x14,32),(0x18,frames),(0x20,0x12345678),(0x24,16)):
            put32(self.m,state+offset,value)

    def state(self,pad):return bytes(self.m.uc.mem_read(BASE+pad*0x44,0x44))

    def pending(self,pad):return self.state(pad)[0x1c]

    def requested(self,pad):return struct.unpack_from('<I',self.state(pad),0x20)[0]

    def send(self,a):
        assert a[:1]==[0x6500] and a[2:4]==[0xffffffff,0]
        raw=bytes(self.m.uc.mem_read(a[1],16))
        ticket,magic,z1,z2=struct.unpack('<4I',raw)
        assert (magic,z1,z2)==(0x4f445331,0,0)
        entry=next(e for e in self.entries() if e[0]==ticket)
        pad,frames,span,position=entry[8:12]
        assert entry[1] and entry[3]==2
        assert self.pending(pad)==1 and self.requested(pad)==frames
        assert self.word()&(P|0x3fffffff)
        self.events.append(dict(ticket=ticket,args=list(entry[8:12]),guard=self.word()))
        if self.deliver:self.queue.append((ticket,raw))
        if self.early_worker:
            self.run_worker(one=True)
            # Worker has finished; sender has not yet returned to its producer.
            entry=next(e for e in self.entries() if e[0]==ticket)
            assert entry[3]==5 and not entry[4] and not entry[5]
            assert self.word()&(P|0x3fffffff)
            self.early_observations.append(self.word())
        if self.lock_after_send:put32(self.m,LEDGER+4,1)
        return int(self.return_success)

    def run_worker(self,one=False):
        # Separate CPU context with shared-region copy-in/out. Models scheduling;
        # no nested execution/reinitialization of the producer CPU registers.
        w=Rig()
        for addr,size in ((LEDGER,self.size),(BASE,0x1000)):
            w.m.uc.mem_write(addr,bytes(self.m.uc.mem_read(addr,size)))
        items=self.queue[:1] if one else list(self.queue)
        self.queue=self.queue[len(items):]
        for ticket,raw in items:w.messages[ticket]=raw
        counts,executed=w.worker([(ticket,None) for ticket,raw in items],transport=True)
        for addr,size in ((LEDGER,self.size),(BASE,0x1000)):
            self.m.uc.mem_write(addr,bytes(w.m.uc.mem_read(addr,size)))
        return counts,executed

    def scan(self,parent=0):
        result=self.m.invoke(self.m.symbols['od_emulator_stream_scan'],[parent])
        if not self.lock_after_send:self.invariant()
        assert struct.unpack('<I',self.m.uc.mem_read(CONTEXT,4))[0]==0
        return result


def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))

    r=ProducerRig((0,1,2,3));assert r.scan()==OK
    assert r.entered==1 and len(r.queue)==4 and r.word()==1
    assert [e['args'] for e in r.events]==[[pad,8,32,0] for pad in range(4)]
    assert all(r.pending(p)==1 for p in range(4))
    root=next(e for e in r.entries() if e[1]==0)
    assert root[2]==4 and root[3]==5 and root[5]==1
    counts,executed=r.run_worker()
    assert counts==[1,1,1,1,0] and executed==[1,1,1,1]
    assert all(r.pending(p)==0 for p in range(4)) and not r.entries()
    passed('original_four_pad_scan_through_compiled_publication_and_worker',events=r.events,counts=counts)

    r=ProducerRig();status,p=r.promotion();assert status==OK
    before=r.state(0)
    assert r.scan()==BUSY and r.entered==0 and not r.queue and r.state(0)==before
    assert r.word()==P
    passed('unrelated_promotion_blocks_before_original_producer_mutates_state')

    r=ProducerRig((0,1));status,p=r.promotion();assert status==OK
    assert r.scan(p)==OK and r.word()==P
    assert r.call('promote_end',p,0)==BUSY
    counts,executed=r.run_worker()
    assert counts==[P,P,P] and executed==[P,P]
    assert r.call('promote_end',p,0)==OK and r.word()==0
    passed('explicit_promotion_parent_protects_scan_and_all_refill_children')

    r=ProducerRig((0,1,2,3));r.early_worker=True
    assert r.scan()==OK and r.word()==0 and not r.entries()
    assert r.early_observations==[1]*4
    passed('worker_can_finish_inside_submission_without_releasing_running_scan')

    r=ProducerRig();before=r.requested(0)
    def reject(a):
        assert r.pending(0)==1 and r.word()==1
        return 2  # positive no-publication fixture; it never invokes send
    r.m.hooks[SEND]=reject;put32(r.m,CONTEXT+4,SEND|1)
    assert r.scan()==BUSY and r.word()==0 and r.pending(0)==0
    assert r.requested(0)==before and not r.queue and not r.entries()
    # Retry after the rejected request can now use the normal publisher.
    put32(r.m,CONTEXT+4,0)
    assert r.scan()==OK and len(r.queue)==1
    r.run_worker();assert r.word()==0
    passed('definite_nonpublication_restores_pending_state_and_allows_retry',
           evidence='Injected publisher that returned before sending, not a stock failure-code interpretation')

    r=ProducerRig();r.return_success=False;r.deliver=False
    assert r.scan()==BUSY and r.word()==1 and r.pending(0)==1
    assert not r.queue and len(r.entries())==2
    child=next(e for e in r.entries() if e[1])
    assert child[3]==2 and child[4]==3 and child[5]==1
    assert r.promotion()[0]==BUSY
    passed('stock_wrapper_failure_preserves_uncertain_request_and_blocks_promotion')

    r=ProducerRig();r.return_success=False
    assert r.scan()==BUSY and r.word()==1
    counts,executed=r.run_worker()
    assert counts==[1,0] and executed==[1] and r.pending(0)==0
    passed('uncertain_submission_can_be_resolved_by_later_real_worker_completion',
           evidence='Delivery plus failure indication is deliberately injected, not observed stock RTOS behavior')

    r=ProducerRig();r.return_success=False;r.early_worker=True
    assert r.scan()==BUSY and r.word()==0 and r.pending(0)==0
    passed('uncertain_result_after_worker_finished_does_not_restore_old_pending_flag')

    r=ProducerRig()
    def contradictory(a):
        r.send([a[0],a[1],0xffffffff,0]);r.run_worker()
        return 2  # wrong claim: the worker has already run
    r.m.hooks[SEND]=contradictory;put32(r.m,CONTEXT+4,SEND|1)
    assert r.scan()==FAULT and r.word()==F|1 and r.pending(0)==0
    assert len(r.entries())==2
    passed('claimed_nonpublication_after_worker_completion_faults_without_state_rollback')

    r=ProducerRig();before=r.state(0)
    for _ in range(16):assert r.reserve(kind=2)[0]==OK
    assert r.scan()==FULL and r.entered==0 and r.state(0)==before
    passed('full_ledger_rejects_scan_before_any_original_instructions')

    r=ProducerRig();old=r.requested(0)
    for _ in range(15):assert r.reserve(kind=2)[0]==OK
    assert r.scan()==FULL and r.entered==1 and r.word()==15
    assert r.pending(0)==0 and r.requested(0)==old and not r.queue
    passed('child_ticket_exhaustion_skips_pending_and_requested_count_changes')

    r=ProducerRig();r.seed(0,frames=0)
    assert r.scan()==OK and r.requested(0)==0 and r.pending(0)==0
    assert r.word()==0 and not r.queue
    passed('zero_work_uses_no_child_ticket_and_finishes_scan')

    r=ProducerRig();r.m.uc.mem_write(BASE+0x1c,b'\x01');before=r.requested(0)
    assert r.scan()==OK and not r.queue and r.pending(0)==1 and r.requested(0)==before
    passed('already_pending_pad_is_not_published_twice',
           limitation='Preexisting pending work must already have its own ownership before integration is enabled')

    r=ProducerRig();r.lock_after_send=True
    assert r.scan()==BUSY and r.word()==F|1 and r.pending(0)==1
    put32(r.m,LEDGER+4,0);r.invariant()
    assert len(r.entries())==2
    passed('post_publication_bookkeeping_contention_latches_fault_and_retains_ownership')

    r=ProducerRig();put32(r.m,LEDGER+4,1);before=r.state(0)
    result=r.m.invoke(r.m.symbols['od_emulator_stream_scan'],[0])
    assert result==BUSY and r.entered==0 and r.state(0)==before
    put32(r.m,LEDGER+4,0);r.invariant()
    passed('entry_lock_contention_leaves_original_producer_untouched')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        real_execution=['original whole producer scan 0x80036508','compiled outer admission and child publication',
          'original queue-send wrapper 0x800483f8','compiled ticket decoder and worker bridge',
          'original stream worker and zero-source completion path'],
        limitations=['Emulator-only call-site interception; no installed patch or device communication',
          'RTOS enqueue/delivery, critical sections and scheduler effects modeled',
          'Early worker uses separate CPU with copy-in/out of shared regions, not instruction-level preemption',
          'Positive nonpublication is injected evidence; default stock adapter treats nonzero send status as uncertain',
          'Only this scan/publication route is covered; all callers and prefetch routes remain to audit',
          'Producer context needs actual task-local storage and verified placement',
          'Continuous playback lifetime and USB/card readiness remain separate required owners',
          'No latency/watchdog/SD/audio hardware validation or automatic fault recovery'])
    path=ROOT/'analysis/stream_producer_verification.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))


if __name__=='__main__':main()
