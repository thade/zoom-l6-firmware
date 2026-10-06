#!/usr/bin/env python3
"""Compiled read evidence/ownership coupled to original reload/read control flow.
Attribution and ticket transfer are explicit harness bindings, not native hooks.
"""
import json
import struct
from verify_reload_prefetch import PrefetchRig
from verify_reload_ownership import Protocol, WORKER, UI, ACCEPTED, ENV, CTX
from verify_work_ownership import OK, BUSY, STALE, CONFLICT, FAULT, LEDGER
from verify_scheduling_boundaries import stop
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT

READ=0x21027000
ARGS=READ+0x100
SHORT=0xffff0003


class Reads(Protocol):
    def rr(self,fn,*args):
        prefix=[] if fn=='observe' else [CTX]
        return self.m.invoke(self.m.symbols['rr_'+fn],[*prefix,READ,*args])
    def begin_read(self,tag,args=(0,0x80735b80,8192)):
        self.m.uc.mem_write(ENV,bytes(tag));self.m.uc.mem_write(ARGS,struct.pack('<3I',*args))
        return self.rr('begin',ENV,ARGS)
    def ticket(self):return int.from_bytes(self.m.uc.mem_read(READ+8,4),'little')
    def prepare(self):
        _,owner=self.begin();tag=self.envelope(owner,WORKER)
        assert self.rl('sent',owner,WORKER,ACCEPTED)==OK
        assert self.rl('producer_return',owner)==OK and self.on('claim',tag)==OK
        assert self.rl('prepare_ui',owner)==OK
        return owner,tag
    def returned(self,owner,tag):
        ui=self.envelope(owner,UI)
        assert self.rl('sent',owner,UI,ACCEPTED)==OK and self.on('claim',ui)==OK
        assert self.on('complete',tag)==OK and self.on('complete',ui)==OK


class Tracked(PrefetchRig):
    def __init__(self):
        super().__init__();self.p=Reads();self.current=None;self.owner=0
        self.read_tickets=[];self.observation=True
    def submit(self):
        status,self.owner=self.p.begin();assert status==OK
        result=super().submit()
        assert self.p.rl('sent',self.owner,WORKER,ACCEPTED)==OK
        assert self.p.rl('producer_return',self.owner)==OK
        return result
    def dispatch(self):
        self.current=self.p.envelope(self.owner,WORKER)
        assert self.p.on('claim',self.current)==OK
        result=super().dispatch()
        if self.callback_returns:assert self.p.on('complete',self.current)==OK
        self.current=None;return result
    def event(self,a):
        assert self.p.rl('prepare_ui',self.owner)==OK
        result=super().event(a)
        assert self.p.rl('sent',self.owner,UI,ACCEPTED)==OK
        return result
    def consume(self):
        self.current=self.p.envelope(self.owner,UI)
        assert self.p.on('claim',self.current)==OK
        super().consume()
        assert self.p.on('complete',self.current)==OK
        self.current=None
    def send(self,a):
        from verify_reload_prefetch import FILE_QUEUE
        if a[0]==FILE_QUEUE:
            _,pad,buffer,size=struct.unpack('<4I',self.m.uc.mem_read(a[1],16))
            assert self.p.begin_read(self.current,(pad,buffer,size))==OK
            ticket=self.p.ticket();assert self.p.rr('ready',ticket)==OK
            self.read_tickets.append((ticket,struct.unpack('<4I',self.current)[3]))
        return super().send(a)
    def read_samples(self,a):
        result=super().read_samples(a)
        actual=int.from_bytes(self.io_cpu.uc.mem_read(a[3],4),'little')
        if self.observation:
            assert self.p.rr('observe',self.p.ticket(),result,actual)==OK
        return result
    def wait(self,a):
        from verify_reload_prefetch import READ_SEM
        result=super().wait(a)
        if a[0]==READ_SEM and self.trace[-1]==('wait_return',):
            status=self.p.rr('finish',self.p.ticket())
            if status==BUSY:return stop(self.m)
            assert status==OK
        return result
    def finish(self):
        assert self.p.rl('verify',self.owner,1)==OK
        return self.p.finish(self.owner)


def main():
    results=[]
    def passed(case):results.append(dict(case=case))
    r=Tracked();r.run();assert r.p.finish(r.owner)==BUSY
    r.consume();assert r.finish()==OK and r.p.word()==0
    tickets=[t for t,role in r.read_tickets]
    assert len(tickets)==8 and len(set(tickets))==8 and tickets==sorted(tickets)
    assert [role for t,role in r.read_tickets]==[WORKER]*4+[UI]*4
    passed('eight_exact_reads_have_distinct_compiled_scopes_under_correct_reload_branches')

    for mode,error in (('error',0xffffd825),('short',SHORT)):
        for phase in ('worker','UI'):
            r=Tracked()
            if phase=='worker':r.read_mode=mode
            r.run()
            if phase=='UI':r.read_mode=mode
            r.consume();assert r.paths()==r.expected and r.finish()==FAULT
            # RlJob.error retains the first failure even though paths look good.
            assert int.from_bytes(r.p.m.uc.mem_read(CTX+8+40,4),'little')==error
    passed('raw_errors_and_short_reads_in_either_stock_reload_branch_prevent_retirement')

    for missing in ('result','delivery'):
        r=Tracked()
        if missing=='result':r.observation=False
        else:r.reject_send=True
        r.run();assert not r.callback_returns and r.p.finish(r.owner)==BUSY
        assert r.p.rr('finish',r.p.ticket())==BUSY and r.p.word()==1
    passed('missing_read_evidence_or_undelivered_request_retains_scope_and_root')

    p=Reads();owner,tag=p.prepare();assert p.begin_read(tag)==OK;t=p.ticket()
    assert p.rr('ready',t)==OK
    p.returned(owner,tag)
    assert p.rl('verify',owner,1)==BUSY and p.finish(owner)==BUSY
    assert p.rr('observe',t,0,8192)==OK and p.rr('finish',t)==OK
    assert p.rl('verify',owner,1)==OK and p.finish(owner)==OK
    passed('even_returned_reload_bodies_cannot_verify_until_read_observation_and_join')

    p=Reads();owner,tag=p.prepare();assert p.begin_read(tag)==OK;t=p.ticket()
    put32(p.m,LEDGER+4,1) # OwnLedger lock, after its 4-byte gate.
    assert p.rr('ready',t)==BUSY
    put32(p.m,LEDGER+4,0);assert p.rr('ready',t)==OK
    assert p.rr('observe',t,0,8191)==OK
    put32(p.m,CTX+4,1);assert p.rr('finish',t)==BUSY
    put32(p.m,CTX+4,0)
    put32(p.m,LEDGER+4,1);assert p.rr('finish',t)==BUSY
    put32(p.m,LEDGER+4,0);assert p.rr('finish',t)==OK
    p.returned(owner,tag);assert p.rl('verify',owner,1)==OK and p.finish(owner)==FAULT
    passed('contention_retries_metadata_without_reobserving_or_losing_first_error')

    p=Reads();owner,tag=p.prepare();assert p.begin_read(tag)==OK;t=p.ticket()
    for fn in ('ready','finish'):
        assert p.m.invoke(p.m.symbols['rr_'+fn],[CTX+0x1000,READ,t])==CONFLICT
    assert p.rr('observe',t,0,8192)==CONFLICT and p.rr('ready',t)==OK
    assert p.rr('observe',t+1,0,8192)==STALE
    assert p.rr('observe',t,0,8192)==OK
    assert p.rr('observe',t,0xffffd825,0)==CONFLICT
    assert p.rr('finish',t)==OK and p.rr('finish',t)==CONFLICT
    assert p.begin_read(tag)==OK;new=p.ticket();assert new>t
    assert p.rr('observe',t,0,8192)==STALE and p.rr('finish',t)==STALE
    assert p.rr('ready',new)==OK and p.rr('observe',new,0,8192)==OK
    assert p.rr('finish',new)==OK
    p.returned(owner,tag);assert p.begin_read(tag)==CONFLICT
    assert p.rl('verify',owner,1)==OK and p.finish(owner)==OK
    passed('early_duplicate_stale_and_returned_branch_observations_cannot_authorize_new_reads')

    for status,count in ((0xffffd759,8192),(0,8193),(0,0)):
        p=Reads();owner,tag=p.prepare();assert p.begin_read(tag)==OK;t=p.ticket()
        assert p.rr('ready',t)==OK and p.rr('observe',t,status,count)==OK
        assert p.rr('finish',t)==OK
        p.returned(owner,tag);assert p.rl('verify',owner,1)==OK and p.finish(owner)==FAULT
    passed('EOF_overcount_and_zero_count_are_not_exempted_for_exact_initial_reads')

    p=Reads();owner,tag=p.prepare()
    for args in ((4,0x1000,1),(0,0,1),(0,0x1000,0),(0,0xfffffffc,8)):
        assert p.begin_read(tag,args)==CONFLICT
    wrong=bytearray(tag);wrong[8]^=1
    assert p.begin_read(wrong)==STALE
    passed('invalid_ranges_pads_and_branch_tags_rejected_before_read_admission')

    out=ROOT/'analysis/reload_read_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(results),results=results,limitations=[
        'Read tickets and branch attribution cross emulator CPUs through explicit harness calls',
        'Native queue ticket transport, task-context bindings and startup release are not installed',
        'Exact initial reads only; intentional EOF padding and periodic refill require separate policy',
        'Parser/converter/public read and RTOS scheduling remain fixtures; no device access']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(results))))


if __name__=='__main__':main()
