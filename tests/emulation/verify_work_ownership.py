#!/usr/bin/env python3
"""Offline compiled ticket ledger + original stream worker. No device access."""
import hashlib
import itertools
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC
from verify_overdub_prototype import Emulator, ELF
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, IMAGE
from verify_scheduling_boundaries import BASE, stop

LEDGER=0x21020000
REQUEST=0x21007000
OUT=0x21007100
MESSAGE=0x21007200
CURRENT=0x21003810
OK,BUSY,STALE,CONFLICT,FAULT,FULL=range(6)
P=0x80000000
F=0x40000000


class Rig:
    def __init__(self):
        self.m=Emulator()
        self.size,self.entry_size,self.request_size=struct.unpack('<3I',
            self.m.uc.mem_read(self.m.symbols['od_owner_layout'],12))
        assert self.entry_size==48 and self.request_size==20
        self.messages={}

    def word(self,offset=0):return struct.unpack('<I',self.m.uc.mem_read(LEDGER+offset,4))[0]

    def entries(self):
        return [struct.unpack('<12I',self.m.uc.mem_read(LEDGER+12+i*self.entry_size,self.entry_size))
                for i in range(16) if self.word(12+i*self.entry_size)]

    def invariant(self):
        es=self.entries();tickets={e[0] for e in es}
        assert len(es)==len(tickets)
        for e in es:
            assert not e[1] or e[1] in tickets
            assert e[2]==sum(x[1]==e[0] for x in es)
        ordinary=sum(not e[1] and e[3]!=7 for e in es)
        promotion=sum(e[3]==7 for e in es)
        assert promotion<=1
        assert self.word()&0x3fffffff==ordinary
        assert bool(self.word()&P)==bool(promotion)
        assert self.word(4)==0

    def call(self,name,*args):
        status=self.m.invoke(self.m.symbols['od_own_'+name],[LEDGER,*args])
        self.invariant();return status

    def request(self,args=(0,0,0,0),kind=1):
        self.m.uc.mem_write(REQUEST,struct.pack('<5I',kind,*args));return REQUEST

    def reserve(self,args=(0,0,0,0),kind=1,parent=None):
        ptr=self.request(args,kind)
        status=self.call('reserve',ptr,OUT) if parent is None else self.call('child',parent,ptr,OUT)
        return status,struct.unpack('<I',self.m.uc.mem_read(OUT,4))[0]

    def promotion(self):
        result=self.call('promote',OUT)
        return result,struct.unpack('<I',self.m.uc.mem_read(OUT,4))[0]

    def queued(self,args=(0,0,0,0),parent=None):
        status,ticket=self.reserve(args,parent=parent);assert status==OK
        assert self.call('offer',ticket)==OK
        assert self.call('stream_message',ticket,MESSAGE)==OK
        self.messages[ticket]=bytes(self.m.uc.mem_read(MESSAGE,16))
        assert self.call('submitted',ticket,1)==OK
        assert self.call('producer_done',ticket,0)==OK
        return ticket

    def claim(self,ticket,args=(0,0,0,0),kind=1):
        return self.call('claim',ticket,self.request(args,kind))

    def worker(self,envelopes,transport=False):
        m=self.m;pending=list(envelopes);counts=[];executed=[]
        for fn in (0x8001aaa0,0x8001aab8):m.hooks[fn]=lambda a:0
        def receive(a):
            counts.append(self.word())
            if not pending:return stop(m)
            ticket,args=pending.pop(0)
            if transport:m.uc.mem_write(a[1],self.messages[ticket])
            else:
                # Direct callback-boundary injection for payload-negative tests.
                put32(m,CURRENT,ticket)
                m.uc.mem_write(a[1],struct.pack('<4I',*args))
            return 0
        def redirect(uc,address,size,unused):
            uc.reg_write(UC_ARM_REG_LR,0x80036c81)
            uc.reg_write(UC_ARM_REG_PC,m.symbols['od_emulator_owned_stream'])
        def observe(uc,address,size,unused):executed.append(self.word())
        m.hooks[0x800483a8]=receive
        if transport:
            def receive_redirect(uc,address,size,unused):
                uc.reg_write(UC_ARM_REG_LR,0x80036c75)
                uc.reg_write(UC_ARM_REG_PC,m.symbols['od_emulator_owned_receive'])
            m.uc.hook_add(UC_HOOK_CODE,receive_redirect,begin=0x80036c70,end=0x80036c70)
        m.uc.hook_add(UC_HOOK_CODE,redirect,begin=0x80036c7c,end=0x80036c7c)
        m.uc.hook_add(UC_HOOK_CODE,observe,begin=0x800369a8,end=0x800369a8)
        m.invoke(0x80036c60,[]);self.invariant()
        return counts,executed


def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))

    schedules=[]
    for outcome in (1,3):
        for order in itertools.permutations('spcd'):
            if order.index('s')>order.index('p') or order.index('c')>order.index('d'):continue
            r=Rig();status,t=r.reserve();assert status==OK
            assert r.call('offer',t)==OK
            for n,event in enumerate(order):
                if event=='s':status=r.call('submitted',t,outcome)
                elif event=='p':status=r.call('producer_done',t,0)
                elif event=='c':status=r.claim(t)
                else:status=r.call('complete',t)
                assert status==OK
                assert r.word()==(0 if n==3 else 1)
            schedules.append(dict(outcome=outcome,order=''.join(order)))
    assert len(schedules)==12
    passed('worker_can_finish_before_publication_ack_or_producer_cleanup',schedules=schedules)

    r=Rig();a=r.queued();b=r.queued()
    assert r.claim(b)==OK and r.call('complete',b)==OK and r.word()==1
    assert r.call('complete',b)==STALE and r.word()==1
    assert r.claim(a)==OK and r.call('complete',a)==OK and r.word()==0
    status,new=r.reserve();assert status==OK and new not in (a,b)
    assert r.call('complete',a)==STALE and r.word()==1
    passed('out_of_order_duplicate_and_reused_slot_completions_do_not_release_other_work')

    r=Rig();status,t=r.reserve();assert status==OK
    assert r.call('offer',t)==OK and r.call('submitted',t,1)==OK
    assert r.call('producer_done',t,1)==OK and r.word()==1
    assert r.promotion()[0]==BUSY
    assert r.claim(t)==OK and r.call('complete',t)==OK and r.word()==0
    passed('failed_wait_retains_ticket_until_actual_worker_completion')

    r=Rig();status,t=r.reserve();assert status==OK
    assert r.call('offer',t)==OK and r.call('submitted',t,2)==OK
    assert r.word()==1  # producer still needs to unwind its earlier side effects
    assert r.call('producer_done',t,0)==OK and r.word()==0
    assert r.claim(t)==STALE
    passed('definitely_not_sent_releases_only_after_producer_cleanup')

    r=Rig();status,t=r.reserve();assert status==OK
    assert r.call('offer',t)==OK and r.call('submitted',t,3)==OK
    assert r.call('producer_done',t,1)==OK and r.word()==1
    assert r.call('cancel_prepared',t)==CONFLICT and r.word()==1
    assert r.promotion()[0]==BUSY
    passed('uncertain_publication_without_completion_remains_reserved')

    r=Rig();status,t=r.reserve();assert status==OK
    assert r.call('offer',t)==OK and r.claim(t)==OK
    assert r.call('submitted',t,2)==FAULT and r.word()==F|1
    assert r.promotion()[0]==FAULT
    passed('rejection_contradicting_worker_claim_latches_fault')

    for kind,args in ((2,(0,0,0,0)),(1,(1,0,0,0)),(1,(0,1,0,0)),
                      (1,(0,0,1,0)),(1,(0,0,0,1))):
        r=Rig();t=r.queued()
        assert r.claim(t,args,kind)==FAULT and r.word()==F|1
    passed('wrong_domain_or_any_changed_job_argument_is_rejected')

    r=Rig();root=r.queued();assert r.claim(root)==OK
    status,child=r.reserve(parent=root);assert status==OK
    assert r.call('offer',child)==OK and r.call('submitted',child,1)==OK
    assert r.call('producer_done',child,0)==OK
    assert r.call('complete',root)==OK and r.word()==1
    assert r.call('complete',root)==CONFLICT and r.word()==1
    assert r.reserve(parent=root)[0]==CONFLICT
    assert r.claim(child)==OK and r.call('complete',child)==OK and r.word()==0
    passed('ordinary_parent_remains_reserved_until_last_child_finishes')

    r=Rig();status,p=r.promotion();assert status==OK
    child=r.queued(parent=p);assert r.word()==P
    assert r.reserve()[0]==BUSY
    assert r.call('promote_end',p,0)==BUSY and r.word()==P
    assert r.claim(child)==OK and r.call('complete',child)==OK and r.word()==P
    assert r.call('promote_end',p,0)==OK and r.word()==0
    assert r.call('promote_end',p,0)==STALE
    passed('promotion_owned_children_do_not_open_gate_to_unrelated_work')

    r=Rig();status,p=r.promotion();assert status==OK
    assert r.call('promote_end',p,1)==OK and r.word()==F
    assert r.reserve()[0]==FAULT
    passed('promotion_failure_stays_latched_after_ticket_retirement')

    r=Rig();tickets=[]
    for i in range(16):
        status,t=r.reserve((i,0,0,0));assert status==OK;tickets.append(t)
    assert r.reserve()[0]==FULL and r.word()==16
    for t in tickets:assert r.call('cancel_prepared',t)==OK
    assert r.word()==0
    for i in range(100):
        status,t=r.reserve();assert status==OK and t not in tickets
        tickets.append(t);assert r.call('cancel_prepared',t)==OK
    passed('bounded_capacity_and_116_unique_tickets_without_reuse')

    r=Rig();status,t=r.reserve();assert status==OK
    put32(r.m,LEDGER+8,0xffffffff)
    assert r.reserve()[0]==FAULT and r.word()==F|1
    assert r.call('cancel_prepared',t)==OK and r.word()==F
    passed('ticket_exhaustion_fails_closed_instead_of_wrapping')

    r=Rig();put32(r.m,LEDGER+4,1);r.request()
    before=bytes(r.m.uc.mem_read(LEDGER,r.size))
    assert r.m.invoke(r.m.symbols['od_own_reserve'],[LEDGER,REQUEST,OUT])==BUSY
    assert bytes(r.m.uc.mem_read(LEDGER,r.size))==before
    put32(r.m,LEDGER+4,0);assert r.reserve()[0]==OK
    passed('contended_ledger_returns_busy_without_mutating_ownership')

    r=Rig();a=r.queued();b=r.queued((1,0,0,0))
    r.m.uc.mem_write(BASE+0x330,b'\x01')
    counts,executed=r.worker([(a,(0,0,0,0)),(b,(1,0,0,0))])
    assert counts==[2,1,0] and executed==[2,1]
    passed('original_stream_worker_uses_tickets_for_cancel_and_completion',counts=counts)

    r=Rig();a=r.queued();b=r.queued((1,0,0,0))
    counts,executed=r.worker([(a,(0,0,0,0)),(a,(0,0,0,0)),(b,(1,0,0,0))])
    assert counts==[2,1,F|1,F|1] and executed==[2]
    passed('replayed_worker_envelope_does_not_execute_or_release_new_work',counts=counts)

    r=Rig();a=r.queued()
    counts,executed=r.worker([(a,(1,0,0,0))])
    assert counts==[1,F|1] and executed==[]
    passed('worker_rejects_mismatched_payload_before_stock_execution')

    r=Rig();status,p=r.promotion();assert status==OK
    child=r.queued(parent=p)
    counts,executed=r.worker([(child,(0,0,0,0))])
    assert counts==[P,P] and executed==[P]
    assert r.call('promote_end',p,0)==OK
    passed('original_stream_child_completes_under_promotion_ownership')

    r=Rig();a=r.queued();b=r.queued((1,0,0,0))
    counts,executed=r.worker([(b,None),(a,None)],transport=True)
    assert counts==[2,1,0] and executed==[2,1]
    passed('compiled_16_byte_ticket_decoder_feeds_original_worker_out_of_order')

    r=Rig();a=r.queued();b=r.queued((1,0,0,0))
    counts,executed=r.worker([(a,None),(a,None),(b,None)],transport=True)
    assert counts==[2,1,F|1,F|1] and executed==[2]
    passed('ticket_transport_replay_rejected_before_worker_callback')

    for bad in ((1,0,0,0),(1,0x4f445331,1,0),(1,0x4f445331,0,1)):
        r=Rig();a=r.queued();r.messages[a]=struct.pack('<4I',*bad)
        counts,executed=r.worker([(a,None)],transport=True)
        assert counts==[1,F|1] and executed==[]
    passed('old_format_or_malformed_ticket_message_is_not_treated_as_a_job')

    # Execute original initialization with task/queue allocation intercepted.
    m=Emulator();allocations={};next_handle=0x21008000
    m.hooks[0x80076c60]=lambda a:1
    m.hooks[0x80076318]=lambda a:0x2100f000
    def create_queue(a):
        nonlocal next_handle
        h=next_handle;next_handle+=0x100;allocations[h]=a[:3];return h
    m.hooks[0x80076348]=create_queue
    assert m.invoke(0x80048248,[])==0
    handle=struct.unpack('<I',m.uc.mem_read(0x801f8f34,4))[0]
    assert allocations[handle]==[8,16,0]
    passed('original_stream_queue_allocation_is_eight_16_byte_messages')

    # Original low-level semaphore success is 1. Wrapper queue success is 0.
    m=Emulator();semaphore=0x21008000
    put32(m,semaphore,0x21009000);put32(m,semaphore+0x38,1)
    for fn in (0x80073ec8,0x80073f18):m.hooks[fn]=lambda a:0
    m.hooks[0x800770f8]=lambda a:1
    assert m.invoke(0x80076950,[semaphore,0])==1
    assert struct.unpack('<I',m.uc.mem_read(semaphore+0x38,4))[0]==0
    assert m.invoke(0x80076950,[semaphore,0])==0
    for result,expected in ((1,0),(0,0xffffffff)):
        m=Emulator();m.hooks[0x800763d8]=lambda a,result=result:result
        assert m.invoke(0x800483f8,[semaphore,REQUEST])==expected
        assert struct.unpack('<I',m.uc.mem_read(0x806b2f20,4))[0]==result
    passed('original_semaphore_and_queue_wrapper_have_different_success_conventions')

    report=dict(passed_groups=len(results),results=results,
        ledger_bytes=r.size,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['No installed firmware changes or device communication',
          'Ledger admission, producer result and ticket transport are supplied by harness',
          'Ticket envelope retains 16-byte size but changes meaning; both queue endpoints must change together with old queue drained',
          'Queue rejection is positively not-sent evidence, not an assumed meaning of a raw error',
          'Caller must handle BUSY before proceeding; no real-time retry/recovery strategy installed',
          'Original stream worker runs; RTOS effects and queue delivery remain modeled',
          'Payload copy owns integer arguments, not memory pointed to by a buffer/path argument',
          'Card readiness evidence and complete producer/caller coverage are still unbound'])
    path=ROOT/'analysis/work_ownership_verification.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),ledger_bytes=r.size,report=str(path)),indent=2))


if __name__=='__main__':main()
