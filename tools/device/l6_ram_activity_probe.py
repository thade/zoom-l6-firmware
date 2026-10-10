#!/usr/bin/env python3
"""Read fixed upper-gap fingerprints; no assignments, capture or memory writes.

Unchanged CPU-visible digests do not prove unused RAM or physical independence.
Requires diagnostic 13 and the connected official Editor session.
"""
import argparse
import json
import struct
from pathlib import Path
from l6_health_probe import sample

GAP_START=0x81f26000
PAGE_BYTES=1024
PAGE_COUNT=872
FIELDS=('schema','range_id','page','page_count','page_bytes','address','flags',
        'hash_before','sum_before','hash_after','sum_after','ticks_before','ticks_after',
        'mcr_before','br_before','refresh_before','mcr_after','br_after','refresh_after')

def request(page,token):
    if not 0<=page<PAGE_COUNT or not 0<=token<128:raise ValueError('Invalid fixed gap page/token')
    return bytes((0xf0,0x52,0,0,0x6f,2,token,page&127,page>>7,0xf7))

def acceptable(mcr,br,refresh):
    return not mcr&3 and br&0xfffff03f==0x8000001b and bool(refresh&1)

def decode(packet):
    if len(packet)<6 or packet[:5]!=bytes((0xf0,0x52,0,0,0x6e)) or packet[5]!=2:return None
    if len(packet)!=103 or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):raise ValueError('Invalid gap reply')
    values=[]
    for i in range(7,102,5):
        if packet[i+4]>15:raise ValueError('Gap word exceeds uint32')
        values.append(sum(packet[i+k]<<(7*k) for k in range(5)))
    r=dict(kind=2,token=packet[6],**dict(zip(FIELDS,values)))
    if (r['schema']!=1 or r['range_id']!=1 or not 0<=r['page']<PAGE_COUNT or
        r['page_count']!=PAGE_COUNT or r['page_bytes']!=PAGE_BYTES or
        r['address']!=GAP_START+r['page']*PAGE_BYTES or r['flags']&~15):
        raise ValueError('Unsupported fixed gap metadata')
    before=acceptable(r['mcr_before'],r['br_before'],r['refresh_before'])
    after=acceptable(r['mcr_after'],r['br_after'],r['refresh_after'])
    read=bool(r['flags']&1)
    hashes_agree=read and (r['hash_before'],r['sum_before'])==(r['hash_after'],r['sum_after'])
    config_agrees=all(r[k+'_before']==r[k+'_after'] for k in ('mcr','br','refresh'))
    expected=int(before)|int(hashes_agree)*2|int(config_agrees)*4|int(before and after)*8
    if r['flags']!=expected or not read and any(r[k] for k in ('hash_before','sum_before','hash_after','sum_after')):
        raise ValueError('Gap reply flags disagree with observations')
    r.update(read_performed=read,fingerprints_agree=hashes_agree,configuration_agrees=config_agrees,
        observer_consistent=r['flags']==15,elapsed_ticks=(r['ticks_after']-r['ticks_before'])&0xffffffff,
        unused_memory_proven=False,physical_address_independence_proven=False,
        observation='CPU-visible cached fingerprints only')
    return r

def reply_matches(reply,page,token):
    return reply['kind']==2 and reply['page']==page and reply['token']==token

def fingerprint(data):
    if len(data)!=PAGE_BYTES:raise ValueError('Fingerprint reference requires one complete fixed page')
    h=2166136261;s=0
    for (v,) in struct.iter_unpack('<I',data):h=((h^v)*16777619)&0xffffffff;s=(s+v)&0xffffffff
    return h,s

def summarize(rows):
    pages={}
    for r in rows:
        if r['page'] in pages:raise ValueError('Repeated page in one snapshot')
        pages[r['page']]=r
    expected=set(range(PAGE_COUNT));present=set(pages)
    return dict(schema=1,range_id=1,gap_start=GAP_START,gap_end=GAP_START+PAGE_BYTES*PAGE_COUNT,
        pages_received=len(rows),page_count=PAGE_COUNT,page_bytes=PAGE_BYTES,
        complete_coverage=present==expected,
        all_observers_consistent=bool(rows) and all(r['observer_consistent'] for r in rows),
        missing_pages=sorted(expected-present),
        unstable_pages=sorted(p for p,r in pages.items() if r['read_performed'] and not r['fingerprints_agree']),
        configuration_uncertain_pages=sorted(p for p,r in pages.items() if r['flags']&12!=12),
        unread_pages=sorted(p for p,r in pages.items() if not r['read_performed']),
        maximum_query_ticks=max((r['elapsed_ticks'] for r in rows),default=None),
        unused_memory_proven=False,physical_address_independence_proven=False)

def compare(before,after):
    b={r['page']:r for r in before};a={r['page']:r for r in after}
    # Reject repeats rather than let a dictionary silently hide them.
    bs=summarize(before);ss=summarize(after)
    usable={p for p in b.keys()&a.keys() if b[p]['observer_consistent'] and a[p]['observer_consistent']}
    changed=sorted(p for p in usable if
        (b[p]['hash_before'],b[p]['sum_before'])!=(a[p]['hash_before'],a[p]['sum_before']))
    complete=bs['complete_coverage'] and ss['complete_coverage'] and len(usable)==PAGE_COUNT
    return dict(comparable_pages=len(usable),complete_consistent_comparison=complete,changed_pages=changed,
        unchanged_full_fingerprints=complete and not changed,unused_memory_proven=False,
        limitation='Sequential CPU-visible non-cryptographic digests; stable results can miss DMA, transient writes, read-only uses and collisions')

def read_log(path):
    rows=[]
    for line in path.read_text().splitlines():
        r=json.loads(line)
        if r.get('direction')=='device_to_probe':
            decoded=decode(bytes.fromhex(r['hex']))
            if decoded:rows.append(decoded)
    summarize(rows)
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New JSONL snapshot; existing files are never overwritten')
    p.add_argument('--summary',type=Path,help='New summary JSON; default is the log with .summary.json suffix')
    p.add_argument('--baseline',type=Path,help='Earlier full raw JSONL snapshot to compare')
    p.add_argument('--quick',action='store_true',help='Only first/middle/last pages; never claim complete coverage')
    p.add_argument('--interval',type=float,default=0.02,help='Minimum pause between queries, 0.01..1 seconds')
    a=p.parse_args()
    if not 0.01<=a.interval<=1:p.error('interval must be between 0.01 and 1 second')
    summary=a.summary or a.output.with_suffix('.summary.json')
    if a.output.resolve()==summary.resolve():p.error('log and summary must be different paths')
    for path in (a.output,summary):
        if path.exists():raise FileExistsError(str(path))
    baseline=read_log(a.baseline) if a.baseline else None
    if baseline is not None and not summarize(baseline)['complete_coverage']:
        p.error('baseline must cover every fixed page')
    a.output.parent.mkdir(parents=True,exist_ok=True);summary.parent.mkdir(parents=True,exist_ok=True)
    pages=(0,PAGE_COUNT//2,PAGE_COUNT-1) if a.quick else range(PAGE_COUNT)
    rows=sample(a.output,query_builder=request,reply_decoder=decode,kinds=pages,
        token_builder=lambda page:page&127,reply_matcher=reply_matches,interval_s=a.interval)
    result=summarize(rows)
    if baseline is not None:result['comparison']=compare(baseline,rows)
    with summary.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(pages_received=len(rows),complete_coverage=result['complete_coverage'],
        all_observers_consistent=result['all_observers_consistent'],
        changed_pages=result.get('comparison',{}).get('changed_pages'),summary=str(summary),
        unused_memory_proven=False)))
if __name__=='__main__':main()
