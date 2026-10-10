#!/usr/bin/env python3
"""Read seven fixed observation queries from trial 05; no device mutations."""
import argparse,json
from pathlib import Path
from l6_health_probe import HEAP_FIELDS,sample
OP_FIELDS=('calls','errors','first_error','last_result','last_ticks','maximum_ticks',
    'peak_amount','peak_id','largest_amount','bin_0','bin_1_4','bin_5_16','bin_17_64',
    'bin_65_128','bin_129_256','bin_257_512','bin_513_plus')
STATS_FIELDS=('epoch_before','busy_skips','claim_skips',*OP_FIELDS,'epoch_after','ticks')
def request(kind,token):
    if kind not in range(1,8) or not 0<=token<128:raise ValueError('Invalid fixed timing query')
    return bytes((0xf0,0x52,0,0,0x7b,kind,token,0xf7))
def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x7a)):return None
    kind,token=packet[5:7]
    if kind not in range(1,8) or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):raise ValueError('Invalid timing reply')
    names=HEAP_FIELDS if kind==1 else STATS_FIELDS
    if len(packet)!=8+5*len(names):raise ValueError('Timing reply length does not match schema 1')
    values=[]
    for p in range(7,len(packet)-1,5):
        if packet[p+4]>15:raise ValueError('Timing word exceeds uint32')
        values.append(sum(packet[p+i]<<(7*i) for i in range(5)))
    result=dict(kind=kind,token=token,**dict(zip(names,values)))
    if kind==1:result['heap_initialized']=result['heap_sentinel']==0x8095ffd0
    else:
        result.update(scope='sd' if kind<6 else 'public_file',
            operation='read' if kind%2==0 else 'write',
            amount_unit='sectors' if kind<6 else 'bytes',
            peak_identity='starting_sector' if kind<6 else 'file_handle',
            observer_consistent=result['epoch_before']==result['epoch_after'] and not result['epoch_before']&1,
            physical_completion_proven=False)
        if kind<6:result['packet_unit']=(kind-2)//2+1
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New local JSONL log; never overwrite an existing log')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=request,reply_decoder=decode,kinds=range(1,8))
    print(json.dumps(dict(samples=rows,limitation='Ticks include scheduling and lock waits; skips are unmeasured calls. No extra-capture load or physical completion proof.')))
if __name__=='__main__':main()
