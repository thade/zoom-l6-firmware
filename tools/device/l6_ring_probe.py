#!/usr/bin/env python3
"""Experiment 08 fixed ring queries; guard initialization is explicitly opt-in."""
import argparse,json
from pathlib import Path
from l6_health_probe import sample
CAP=223104
TOTAL_WORDS=12*(240000-CAP)
CHUNKS=396
GUARD_ATTEMPTS=3
GUARD_FIELDS=('schema','epoch_before','state','init_words','scan_word','sweeps',
    'bad_words','first_bad_address','expected','actual','layout_faults','busy_refusals','claim_skips',
    'record_base','play_base','record_capacity','play_capacity','cached_record_capacity',
    'cached_play_capacity','record_cursor','play_cursor','epoch_after','ticks')
SPAN_FIELDS=('schema','epoch_before','requests','overlaps','invalid_spans','first_operation',
    'first_address','first_bytes','first_tail_address','claim_skips','epoch_after','ticks')
BACKLOG_FIELDS=('schema','epoch_before','samples','unstable_samples','invalid_cursors',
    'active_mask','producer',*(f'max_sampled_lag_{i}' for i in range(12)),'epoch_after','ticks')
def request(kind,token):
    if kind not in range(1,6) or not 0<=token<128:raise ValueError('Invalid fixed ring query')
    return bytes((0xf0,0x52,0,0,0x75,kind,token,0xf7))
def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x74)):return None
    kind,token=packet[5:7]
    if kind not in range(1,6) or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):
        raise ValueError('Invalid ring reply')
    names=GUARD_FIELDS if kind<=3 else SPAN_FIELDS if kind==4 else BACKLOG_FIELDS
    if len(packet)!=8+5*len(names):raise ValueError('Ring reply length does not match schema 1')
    values=[]
    for p in range(7,len(packet)-1,5):
        if packet[p+4]>15:raise ValueError('Ring word exceeds uint32')
        values.append(sum(packet[p+i]<<(7*i) for i in range(5)))
    r=dict(kind=kind,token=token,**dict(zip(names,values)))
    if r['schema']!=1:raise ValueError('Unsupported ring layout')
    r['observer_consistent']=r['epoch_before']==r['epoch_after'] and not r['epoch_before']&1
    if kind<=3:
        if r['state']>3 or r['init_words']>TOTAL_WORDS or r['scan_word']>=TOTAL_WORDS:
            raise ValueError('Invalid guard state')
        r['layout_matches']=all(r[k]==CAP for k in ('record_capacity','play_capacity',
            'cached_record_capacity','cached_play_capacity')) and r['record_base']==r['play_base']==0x81429800
        r['guards_armed']=r['state']==2 and r['init_words']==TOTAL_WORDS
        r['guard_writes_completed']=r['init_words']*4
    if kind==5:r['limitation']='Sampled modulo distance; missed whole laps and unsampled peaks are invisible.'
    r['physical_completion_proven']=False
    return r

def sequence(last,initialize=False,scan=False):
    """Bounded transport iterator; validates each page before the next mutation."""
    yield 1
    def status():
        r=last.get('guard')
        if not r or not r['observer_consistent']:raise RuntimeError('Guard observer is incomplete; retry status')
        if r['state']==3 or r['bad_words'] or r['layout_faults']:
            raise RuntimeError('Latched guard/layout fault: stop trial and preserve this log')
        if not r['layout_matches'] or r['record_cursor']>=CAP or r['play_cursor']>=CAP:
            raise RuntimeError('Native layout is not coherent; no guard initialization')
        return r
    status()
    # Establish this interval BEFORE any guard write. Historical omissions
    # remain visible; they cannot become a claim of complete boot coverage.
    yield 4
    baseline=last.get('span')
    if not baseline or not baseline['observer_consistent'] or baseline['overlaps'] or baseline['invalid_spans']:
        raise RuntimeError('IO span conflict or incomplete snapshot; no guard initialization')
    baseline=dict(baseline)
    last['source_window']=dict(start=baseline,end=baseline,
        observed_requests=0,new_omissions=0,
        historical_omissions=baseline['claim_skips'],
        checked_interval_has_no_new_omissions=True)
    def spans():
        r=last.get('span')
        if not r or not r['observer_consistent'] or r['overlaps'] or r['invalid_spans']:
            raise RuntimeError('IO span conflict or incomplete snapshot; preserve this log')
        if any(r[k]<baseline[k] for k in ('requests','claim_skips','epoch_before')):
            raise RuntimeError('IO span counters regressed; reboot/reset/wrap invalidates this interval')
        window=last['source_window']
        window.update(end=dict(r),observed_requests=r['requests']-baseline['requests'],
            new_omissions=r['claim_skips']-baseline['claim_skips'],
            checked_interval_has_no_new_omissions=r['claim_skips']==baseline['claim_skips'])
        if window['new_omissions']:
            raise RuntimeError('New IO span observation omitted during this interval; preserve this log')
    if initialize:
        r=status()
        for _ in range(CHUNKS):
            if r['guards_armed']:break
            previous=r['init_words'];refusals=r['busy_refusals'];misses=r['claim_skips']
            for attempt in range(GUARD_ATTEMPTS):
                yield 2;r=status()
                if r['busy_refusals']!=refusals:raise RuntimeError('Mixer is active: stop recording/playback before guard initialization')
                yield 4;spans()
                if r['init_words']==previous+512 and r['claim_skips']==misses:break
                if r['init_words']!=previous or r['claim_skips']<=misses:
                    raise RuntimeError('Unexpected guard initialization progress; preserve this log')
                # A consistent nonadvancing page with a new missed claim means
                # this command never entered the guard body. Retry it only.
                misses=r['claim_skips']
            else:raise RuntimeError('Guard initialization claim retry limit reached')
        if not r['guards_armed']:raise RuntimeError('Guard initialization did not complete')
    if scan:
        r=status()
        if not r['guards_armed']:raise RuntimeError('Initialize guards while idle before scanning')
        # Always check 396 successful chunks, even when resuming at a nonzero
        # scan position. Reaching the next boundary alone is only a partial scan.
        for _ in range(CHUNKS):
            previous=r['scan_word'];sweep=r['sweeps'];misses=r['claim_skips']
            expected_word=(previous+512)%TOTAL_WORDS
            expected_sweep=(sweep+int(expected_word==0))&0xffffffff
            for attempt in range(GUARD_ATTEMPTS):
                yield 3;r=status()
                yield 4;spans()
                if r['scan_word']==expected_word and r['sweeps']==expected_sweep and r['claim_skips']==misses:break
                if r['scan_word']!=previous or r['sweeps']!=sweep or r['claim_skips']<=misses:
                    raise RuntimeError('Unexpected guard scan progress; preserve this log')
                misses=r['claim_skips']
            else:raise RuntimeError('Guard scan claim retry limit reached')
    yield 4
    spans()
    yield 5
    r=last.get('backlog')
    if not r or not r['observer_consistent'] or r['invalid_cursors']:
        raise RuntimeError('Backlog snapshot is incomplete or has invalid cursors; preserve this log')
    yield 1
    status()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New local JSONL log; never overwritten')
    p.add_argument('--initialize-guards',action='store_true',help='Explicitly write fixed guard chunks; mixer must be idle')
    p.add_argument('--scan',action='store_true',help='Read/check one full guard sweep; no guard writes')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    last={}
    def receive(packet):
        r=decode(packet)
        if r:last['guard' if r['kind']<=3 else 'span' if r['kind']==4 else 'backlog']=r
        return r
    summary=a.output.with_suffix('.summary.json')
    if summary.exists():raise FileExistsError('Refusing to overwrite an existing summary')
    rows=sample(a.output,query_builder=request,reply_decoder=receive,
        kinds=sequence(last,a.initialize_guards,a.scan))
    report=dict(queries=len(rows),latest=last,
        limitation='Fixed-layout interval only; historical omissions remain unknown. No complete memory, boot, timing or physical IO proof.')
    with summary.open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps(report))
if __name__=='__main__':main()
