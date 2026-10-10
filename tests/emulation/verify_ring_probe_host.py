#!/usr/bin/env python3
"""Pure host sequencing checks. No emulation, MIDI or device access."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_ring_probe import sequence,CHUNKS,TOTAL_WORDS
class Fixture:
    def __init__(self,omissions=0):
        self.guard=dict(kind=1,observer_consistent=True,state=0,init_words=0,scan_word=0,
            sweeps=0,bad_words=0,layout_faults=0,layout_matches=True,record_cursor=0,
            play_cursor=0,guards_armed=False,busy_refusals=0,claim_skips=0)
        self.span=dict(kind=4,observer_consistent=True,overlaps=0,invalid_spans=0,
            claim_skips=omissions,requests=846,epoch_before=1692)
        self.last={};self.sent=[];self.inject=None
    def drive(self,initialize=False,scan=False):
        for kind in sequence(self.last,initialize,scan):
            self.sent.append(kind)
            if kind==2:
                self.guard.update(state=1,init_words=self.guard['init_words']+512)
                if self.guard['init_words']==TOTAL_WORDS:self.guard.update(state=2,guards_armed=True)
            if kind==3:
                n=self.guard['scan_word']+512
                self.guard.update(scan_word=n if n<TOTAL_WORDS else 0)
                if n==TOTAL_WORDS:self.guard['sweeps']+=1
            if self.inject:self.inject(self,kind)
            key='guard' if kind<=3 else 'span' if kind==4 else 'backlog'
            self.last[key]=dict(self.guard if kind<=3 else self.span if kind==4 else
                dict(observer_consistent=True,invalid_cursors=0))
        return self.last
def failure(f,substring,initialize=True,scan=False):
    try:f.drive(initialize,scan)
    except RuntimeError as e:assert substring in str(e),str(e)
    else:raise AssertionError('Fault did not halt sequence')
def main():
    results=[]
    def passed(case):results.append(dict(case=case,passed=True))
    f=Fixture(1);r=f.drive(True,True)
    assert f.sent[:3]==[1,4,2] and f.sent.count(2)==f.sent.count(3)==CHUNKS
    assert r['guard']['sweeps']==1 and r['source_window']['new_omissions']==0
    assert r['span']['claim_skips']==1 and r['source_window']['historical_omissions']==1
    assert r['source_window']['checked_interval_has_no_new_omissions']
    passed('preflight_precedes_writes_historical_omission_retained_and_full_interval_guard_scan_completes')
    for field in ('overlaps','invalid_spans'):
        f=Fixture();f.span[field]=1;failure(f,'no guard initialization')
        assert 2 not in f.sent and f.guard['init_words']==0
    f=Fixture();f.span['observer_consistent']=False;failure(f,'no guard initialization');assert 2 not in f.sent
    passed('conflicts_invalid_spans_or_odd_source_page_halt_before_first_guard_write')
    f=Fixture(1)
    def omit(f,kind):
        if kind==2:f.span['claim_skips']+=1
    f.inject=omit;failure(f,'omitted during')
    assert f.guard['init_words']==512 and f.sent.count(2)==1
    assert f.last['source_window']['new_omissions']==1 and not f.last['source_window']['checked_interval_has_no_new_omissions']
    passed('new_omission_stops_before_next_guard_chunk_without_erasing_history')
    for field in ('requests','claim_skips','epoch_before'):
        f=Fixture(1)
        def regress(f,kind,field=field):
            if kind==2:f.span[field]-=1
        f.inject=regress;failure(f,'regressed');assert f.sent.count(2)==1
    passed('decreasing_request_omission_or_epoch_counters_invalidate_interval')
    f=Fixture();f.guard.update(state=2,guards_armed=True,init_words=TOTAL_WORDS)
    def no_progress(f,kind):
        if kind==3:f.guard['scan_word']=0
    f.inject=no_progress;failure(f,'Unexpected guard scan progress',False,True)
    assert f.sent.count(3)==1
    passed('scan_with_no_progress_aborts_immediately')
    f=Fixture()
    def fault(f,kind):
        if kind==2:f.guard.update(state=3,bad_words=1)
    f.inject=fault;failure(f,'Latched guard');assert f.sent.count(2)==1
    passed('guard_fault_stops_before_next_write_or_source_read')
    # Model a missed guard claim BEFORE its body: no initialized/checked word.
    f=Fixture(1);missed=[]
    def missed_claim(f,kind):
        if kind==2 and not missed:
            f.guard['init_words']-=512;f.guard['claim_skips']+=1;missed.append(True)
    f.inject=missed_claim;r=f.drive(True,True)
    assert len(missed)==1 and f.sent.count(2)==CHUNKS+1 and f.sent.count(3)==CHUNKS
    assert r['guard']['claim_skips']==1 and r['source_window']['new_omissions']==0
    passed('one_missed_guard_claim_retries_same_chunk_and_remains_visible')
    f=Fixture();f.guard.update(state=2,guards_armed=True,init_words=TOTAL_WORDS,scan_word=512*183)
    start=f.guard['scan_word'];r=f.drive(scan=True)
    assert f.sent.count(3)==CHUNKS and r['guard']['scan_word']==start and r['guard']['sweeps']==1
    passed('nonzero_resume_position_still_checks_396_successful_chunks_for_a_full_cycle')
    f=Fixture();f.guard.update(state=2,guards_armed=True,init_words=TOTAL_WORDS)
    def always_miss(f,kind):
        if kind==3:f.guard['scan_word']-=512;f.guard['claim_skips']+=1
    f.inject=always_miss;failure(f,'retry limit',False,True)
    assert f.sent.count(3)==3 and f.guard['scan_word']==0
    passed('repeated_guard_claim_misses_stop_after_three_attempts')
    report=dict(passed=True,groups=len(results),results=results,device_access=False)
    (ROOT/'analysis/ring_probe_host_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(results))))
if __name__=='__main__':main()
