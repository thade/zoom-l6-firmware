#!/usr/bin/env python3
"""Fixed read-only raw-IRQ queries for experiment 10; no mixer commands."""
import argparse,json
from pathlib import Path
from l6_health_probe import sample
COMMON=('schema','epoch_before','irqs','skipped','tc','errors')
FIELDS=COMMON+('unit','raw','signal','present','system','protocol','mix',
               'dma_address_sample','interrupted_task','event','ccr','dtcm','itcm','epoch_after','ticks')
SUMMARY=COMMON+('tc_errors','dma_tc','units','latest_ccr','latest_dtcm','latest_itcm','epoch_after','ticks')
def request(kind,token):
    if kind not in range(1,5) or not 0<=token<128:raise ValueError('Invalid raw-IRQ query')
    return bytes((0xf0,0x52,0,0,0x75,kind,token,0xf7))
def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x74)):return None
    kind,token=packet[5:7]
    if kind not in range(1,5) or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):
        raise ValueError('Invalid raw-IRQ reply')
    fields=SUMMARY if kind==4 else FIELDS
    if len(packet)!=8+5*len(fields):raise ValueError('Raw-IRQ reply length mismatch')
    words=[]
    for p in range(7,len(packet)-1,5):
        if packet[p+4]>15:raise ValueError('Raw-IRQ word exceeds uint32')
        words.append(sum(packet[p+i]<<(7*i) for i in range(5)))
    r=dict(kind=kind,token=token,**dict(zip(fields,words)))
    if r['schema']!=(2 if kind==4 else 1):raise ValueError('Unsupported raw-IRQ schema')
    r['observer_consistent']=r['epoch_before']==r['epoch_after'] and not r['epoch_before']&1
    if kind!=4:
        r['raw_error_bits']=r['raw']&0x157f0000;r['raw_tc']=bool(r['raw']&2)
        r['sample_present']=bool(r['raw']);r['activity_bits']=r['present']&0x307
        r['ccr_dcache_enabled']=bool(r['ccr']&0x10000)
        r['dtcm_enabled']=bool(r['dtcm']&1);r['itcm_enabled']=bool(r['itcm']&1)
    r['physical_completion_proven']=False;r['transfer_owner_identified']=False
    return r
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New JSONL log; existing logs are never overwritten')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=request,reply_decoder=decode,kinds=(1,2,3,4))
    print(json.dumps(dict(samples=rows,limitation='Raw IRQ observation does not supply transfer joining or cache ownership.')))
if __name__=='__main__':main()
