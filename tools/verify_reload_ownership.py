#!/usr/bin/env python3
"""Compiled two-branch reload ownership plus original stock reload/UI bodies.
The harness supplies tagged envelopes and task-local attribution; no queue patch.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from verify_work_ownership import Rig as LedgerRig,LEDGER,REQUEST,OUT,OK,BUSY,STALE,CONFLICT,FAULT,FULL,F
from verify_pad_reload import ReloadRig
from verify_firmware_workflow import put32
from verify_overdub_prototype import ELF
from verify_pad_protocol import ROOT,IMAGE
CTX=0x21022000;ENV=0x21023000
WORKER,UI=1,2
ACCEPTED,NOT_SENT,UNCERTAIN=1,2,3

class Protocol(LedgerRig):
    def __init__(self):
        super().__init__();put32(self.m,CTX,LEDGER)
        self.csize,self.jsize,self.esize=struct.unpack('<3I',self.m.uc.mem_read(self.m.symbols['rl_layout'],12))
        assert (self.csize,self.jsize,self.esize)==(404,48,16)
    def rl(self,name,*args):
        return self.m.invoke(self.m.symbols['rl_'+name],[CTX,*args])
    def begin(self,parent=0):
        r=self.rl('begin',parent,OUT);return r,int.from_bytes(self.m.uc.mem_read(OUT,4),'little')
    def envelope(self,id,role):
        assert self.rl('envelope',id,role,ENV)==OK
        return bytes(self.m.uc.mem_read(ENV,16))
    def on(self,name,e,*args):
        self.m.uc.mem_write(ENV,bytes(e));return self.rl(name,ENV,*args)
    def branches(self,id,early=False):
        w=self.envelope(id,WORKER)
        if not early:
            assert self.rl('sent',id,WORKER,ACCEPTED)==OK
            assert self.rl('producer_return',id)==OK
        assert self.on('claim',w)==OK and self.rl('prepare_ui',id)==OK
        u=self.envelope(id,UI);assert self.on('claim',u)==OK
        assert self.on('complete',u)==OK
        assert self.rl('sent',id,UI,ACCEPTED)==OK
        assert self.on('complete',w)==OK
        return w,u
    def finish(self,id):return self.rl('finish',id)

class Integrated(ReloadRig):
    def __init__(self):
        self.protocol=None;super().__init__();self.protocol=Protocol()
        self.tags=[];self.ui_tags=[];self.current=None;self.root=0;self.guarded_events=0
        def returned(uc,a,n,u):
            assert self.protocol.on('complete',self.current)==OK
            self.current=None
        self.m.uc.hook_add(UC_HOOK_CODE,returned,begin=0x800362b6,end=0x800362b6)
    def enqueue(self,a):
        e=self.protocol.envelope(self.root,WORKER)
        result=super().enqueue(a)
        if self.deliver:self.tags.append(e)
        assert self.protocol.rl('sent',self.root,WORKER,ACCEPTED if result==0 else UNCERTAIN)==OK
        return result
    def submit(self):
        status,self.root=self.protocol.begin();assert status==OK
        result=super().submit();assert self.protocol.rl('producer_return',self.root)==OK
        return result
    def dequeue(self,a):
        if self.messages:
            self.current=self.tags.pop(0);assert self.protocol.on('claim',self.current)==OK
        return super().dequeue(a)
    def event(self,a):
        owner=struct.unpack('<4I',self.current)[1]
        assert self.protocol.rl('prepare_ui',owner)==OK
        self.ui_tags.append(self.protocol.envelope(owner,UI))
        result=super().event(a)
        assert self.protocol.rl('sent',owner,UI,ACCEPTED if result==0 else UNCERTAIN)==OK
        return result
    def hit(self,op,**data):
        if self.protocol is not None:
            assert self.current is not None
            assert self.protocol.promotion()[0]==BUSY
            self.guarded_events+=1
        return super().hit(op,**data)
    def close(self,a):
        result=super().close(a)
        if result and self.protocol is not None:
            assert self.protocol.on('io_error',self.current,result)==OK
        return result
    def consume(self):
        self.current=self.ui_tags.pop(0);assert self.protocol.on('claim',self.current)==OK
        e=self.current
        super().consume();assert self.protocol.on('complete',e)==OK;self.current=None
    def verify(self):
        good=self.paths()==self.expected and all(self.snapshot(p)[0]==0 for p in range(4))
        assert self.protocol.rl('verify',self.root,1 if good else 2)==OK
        return good

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=Integrated();r.run();id=r.root
    assert r.protocol.finish(id)==BUSY and r.protocol.promotion()[0]==BUSY
    assert len(r.ui_tags)==1 and r.protocol.word()==1
    r.consume();assert r.protocol.finish(id)==BUSY
    assert r.verify() and r.protocol.finish(id)==OK and r.guarded_events>0
    assert r.protocol.word()==0 and r.protocol.promotion()[0]==OK
    passed('original_reload_and_second_UI_reload_keep_one_owner_through_actual_returns_and_postcondition_check')

    r=Integrated();r.run();r.fail=('close',r.counts['close']+1,'error');r.consume()
    assert r.verify() # Stock final state hides the failed close.
    assert r.protocol.finish(r.root)==FAULT and r.protocol.word()&F and r.protocol.entries()
    passed('second_stage_stock_unload_close_error_is_retained_even_when_final_snapshots_pass')

    r=Integrated();r.reject_load=True;r.run();r.consume()
    assert not r.verify() and r.protocol.finish(r.root)==FAULT and r.protocol.word()&F
    passed('late_load_failure_rejected_by_expected_path_postcondition_keeps_owner')

    p=Protocol();_,id=p.begin();w,u=p.branches(id,early=True)
    assert p.finish(id)==BUSY and p.word()==1
    assert p.rl('sent',id,WORKER,ACCEPTED)==OK and p.finish(id)==BUSY
    assert p.rl('producer_return',id)==OK and p.rl('verify',id,1)==OK and p.finish(id)==OK
    passed('UI_and_worker_can_finish_before_original_sender_returns_without_releasing_owner')

    p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
    p.rl('sent',id,WORKER,ACCEPTED);p.rl('producer_return',id);p.on('claim',w)
    assert p.on('complete',w)==BUSY and p.finish(id)==BUSY and p.word()==1
    assert p.rl('prepare_ui',id)==OK;u=p.envelope(id,UI)
    assert p.on('complete',w)==OK and p.finish(id)==BUSY
    assert p.on('claim',u)==OK and p.on('complete',u)==OK
    assert p.finish(id)==BUSY # UI sender has not returned yet.
    assert p.rl('sent',id,UI,ACCEPTED)==OK
    assert p.rl('verify',id,1)==OK and p.finish(id)==OK
    passed('worker_cannot_finish_without_reserved_UI_and_UI_return_does_not_overtake_event_sender')

    for role in (WORKER,UI):
        p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
        p.rl('sent',id,WORKER,UNCERTAIN if role==WORKER else ACCEPTED);p.rl('producer_return',id)
        if role==UI:
            p.on('claim',w);p.rl('prepare_ui',id);p.rl('sent',id,UI,UNCERTAIN);p.on('complete',w)
        assert p.finish(id)==BUSY and p.word()==1 and p.promotion()[0]==BUSY
    passed('uncertain_undelivered_worker_or_UI_event_never_times_out_into_release')

    p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
    p.rl('sent',id,WORKER,UNCERTAIN);p.rl('producer_return',id);p.on('claim',w);p.rl('prepare_ui',id)
    u=p.envelope(id,UI);p.rl('sent',id,UI,UNCERTAIN);p.on('complete',w)
    p.on('claim',u);p.on('complete',u);p.rl('verify',id,1)
    assert p.finish(id)==OK
    passed('positive_worker_and_UI_completion_resolve_ambiguous_send_outcomes')

    for role in (WORKER,UI):
        p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
        if role==WORKER:p.rl('sent',id,WORKER,NOT_SENT);p.rl('producer_return',id)
        else:
            p.rl('sent',id,WORKER,ACCEPTED);p.rl('producer_return',id);p.on('claim',w)
            p.rl('prepare_ui',id);p.rl('sent',id,UI,NOT_SENT);p.on('complete',w)
        assert p.finish(id)==FAULT and p.word()&F
    passed('definite_missing_required_branch_faults_and_retains_owner_instead_of_claiming_success')

    p=Protocol();_,old=p.begin();w,u=p.branches(old);p.rl('verify',old,1);assert p.finish(old)==OK
    _,new=p.begin();assert new>old;before=p.word()
    for e in (w,u):
        assert p.on('claim',e)==STALE and p.on('complete',e)==STALE
    assert p.finish(old)==STALE and p.word()==before and p.finish(new)==BUSY
    passed('late_old_worker_or_UI_delivery_cannot_release_a_new_reload_owner')

    p=Protocol();_,a=p.begin();_,b=p.begin();wa,ua=p.branches(a);wb,ub=p.branches(b)
    p.rl('verify',a,1);assert p.finish(a)==OK and p.word()==1
    assert p.on('complete',ua)==STALE and p.finish(b)==BUSY
    p.rl('verify',b,1);assert p.finish(b)==OK and p.word()==0
    passed('identical_reload_bodies_have_independent_tickets_and_out_of_order_retirement')

    p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
    p.rl('sent',id,WORKER,ACCEPTED);p.rl('producer_return',id)
    assert p.on('complete',w)==STALE and p.on('claim',w)==OK and p.on('claim',w)==STALE
    p.rl('prepare_ui',id);u=p.envelope(id,UI);p.rl('sent',id,UI,ACCEPTED)
    assert p.on('complete',w)==OK and p.on('complete',w)==STALE
    p.on('claim',u);p.on('complete',u);assert p.on('complete',u)==STALE
    passed('duplicate_claims_and_returns_never_execute_or_release_a_branch_twice')

    p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
    p.rl('sent',id,WORKER,ACCEPTED);p.rl('producer_return',id);p.on('claim',w)
    child=struct.unpack('<4I',w)[2]
    status,read=p.reserve(kind=2,parent=child);assert status==OK
    p.call('offer',read);p.call('submitted',read,ACCEPTED);p.claim(read,kind=2);p.call('producer_done',read,0)
    p.rl('prepare_ui',id);u=p.envelope(id,UI);p.rl('sent',id,UI,ACCEPTED)
    p.on('complete',w);p.on('claim',u);p.on('complete',u)
    assert p.rl('verify',id,1)==BUSY
    assert p.finish(id)==BUSY
    assert p.call('complete',read)==OK and p.finish(id)==BUSY
    assert p.rl('verify',id,1)==OK and p.finish(id)==OK
    passed('file_descendant_outliving_both_stock_bodies_still_blocks_owner_retirement')

    p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
    p.rl('sent',id,WORKER,ACCEPTED);p.rl('producer_return',id);p.on('claim',w)
    p.rl('prepare_ui',id);u=p.envelope(id,UI);p.rl('sent',id,UI,ACCEPTED);p.on('claim',u)
    child=struct.unpack('<4I',u)[2]
    status,read=p.reserve(kind=2,parent=child);assert status==OK
    p.call('offer',read);p.call('submitted',read,ACCEPTED);p.claim(read,kind=2);p.call('producer_done',read,0)
    p.on('complete',w);p.on('complete',u)
    assert p.rl('verify',id,1)==BUSY
    assert p.finish(id)==BUSY
    # Error is observed before the descendant gives up its remaining reference.
    assert p.on('io_error',u,0xffffd825)==OK and p.call('complete',read)==OK
    assert p.finish(id)==FAULT
    passed('late_attributed_IO_failure_cannot_be_erased_by_positive_final_state_verification')

    p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
    p.on('claim',w)
    assert p.rl('sent',id,WORKER,NOT_SENT)==FAULT and p.word()&F
    passed('not_sent_claim_contradicting_a_started_worker_faults_closed')

    p=Protocol();_,id=p.begin();w,u=p.branches(id)
    assert p.rl('verify',id,2)==OK and p.rl('verify',id,1)==CONFLICT
    assert p.finish(id)==FAULT
    passed('rejected_postcondition_cannot_be_overwritten_by_later_success')

    p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
    bad=bytearray(w);bad[0]^=1
    assert p.on('claim',bad)==CONFLICT
    bad=bytearray(w);struct.pack_into('<I',bad,8,0xffffffff)
    assert p.on('claim',bad)==STALE and p.finish(id)==BUSY and p.word()==1
    put32(p.m,CTX+4,1)
    assert p.on('claim',w)==BUSY and p.begin()[0]==BUSY
    put32(p.m,CTX+4,0);assert p.on('claim',w)==OK
    passed('malformed_or_contended_envelopes_do_not_run_stock_work_or_change_another_owner')

    p=Protocol();ids=[p.begin()[1] for _ in range(8)]
    assert len(set(ids))==8 and p.begin()[0]==FULL and p.word()==8
    p=Protocol();put32(p.m,LEDGER+8,0xffffffff)
    assert p.begin()[0]==FAULT and p.word()&F
    passed('bounded_capacity_and_nonwrapping_ledger_tickets_refuse_new_work_without_false_completion')

    p=Protocol();status,parent=p.reserve(kind=7);assert status==OK
    p.call('offer',parent);p.call('submitted',parent,ACCEPTED);p.claim(parent,kind=7)
    status,id=p.begin(parent);assert status==OK and p.word()==1
    p.branches(id);p.rl('verify',id,1)
    assert p.call('finish_session',parent)==BUSY
    assert p.finish(id)==OK and p.word()==1 and p.promotion()[0]==BUSY
    assert p.call('finish_session',parent)==OK and p.word()==0
    passed('reload_child_retirement_does_not_release_its_containing_storage_session')

    p=Protocol();_,id=p.begin();w=p.envelope(id,WORKER)
    p.rl('sent',id,WORKER,ACCEPTED);p.rl('producer_return',id);p.on('claim',w)
    for _ in range(14):assert p.reserve(kind=2)[0]==OK
    assert p.rl('prepare_ui',id)==FAULT and p.word()&F
    assert p.rl('envelope',id,UI,ENV)==CONFLICT
    assert p.on('complete',w)==BUSY and p.entries()
    passed('UI_capacity_failure_retains_attribution_and_never_publishes_an_unowned_continuation')

    out=ROOT/'analysis/reload_ownership_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      coordinator_bytes=p.csize,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=[
      'Proposed 16-byte envelope ABI and metadata operations compiled; harness supplies routing and task-local attribution, not installed queue/event hooks',
      'Original reload worker and UI bodies execute with inherited synthetic filesystem, settings, RTOS, stop and prefetch fixtures',
      'Close-error observer is harness-bound; complete stock file/read/write/save error instrumentation remains unfinished',
      'Verification remains explicitly unbound until caller supplies postcondition evidence; descendants require attributed ledger children',
      'Real containing USB/card/recorder lifetimes, queue retry scheduling, storage timing and hardware placement remain unbound',
      'No firmware installation or device changes']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
