#!/usr/bin/env python3
"""Fixed read-only task/token service observations for experiment 07."""
import argparse,json
from pathlib import Path
from l6_health_probe import sample
META_FIELDS=('schema','task_slots','lock_classes','heap_sentinel','free_bytes',
    'minimum_free_bytes','allocations','frees','claim_misses','slots_full',
    'context_skips','ambiguous_tokens','nested_takes','unpaired_gives','ticks')
FILE_FIELDS=('operation','handle','bytes','entry_tick','job','calls','errors',
    'last_result','last_ticks','max_ticks','peak_job','peak_operation','peak_handle',
    'peak_bytes','peak_state','peak_tick','nested_calls')
LOCK_FIELDS=('object','flags','phase_tick','held_job','held_operation','held_amount',
    'held_identity','held_state','calls','errors','last_wait','max_wait',
    'peak_wait_job','peak_wait_amount','peak_wait_identity','releases','release_errors',
    'last_held','max_held','peak_held_job','peak_held_amount','peak_held_identity',
    'peak_held_state','last_give_ticks','max_give_ticks')
CLASSES=('filesystem1','filesystem2','SD1','SD2')
def request(kind,token):
    if kind not in range(1,42) or not 0<=token<128:raise ValueError('Invalid fixed service query')
    return bytes((0xf0,0x52,0,0,0x77,kind,token,0xf7))
def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x76)):return None
    kind,token=packet[5:7]
    if kind not in range(1,42) or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):
        raise ValueError('Invalid service reply')
    names=META_FIELDS if kind==1 else ('owner','epoch_before',
        *(FILE_FIELDS if kind<10 else LOCK_FIELDS),'epoch_after','ticks')
    if len(packet)!=8+5*len(names):raise ValueError('Service reply length does not match schema 1')
    values=[]
    for p in range(7,len(packet)-1,5):
        if packet[p+4]>15:raise ValueError('Service word exceeds uint32')
        values.append(sum(packet[p+i]<<(7*i) for i in range(5)))
    result=dict(kind=kind,token=token,**dict(zip(names,values)))
    if kind==1:
        if result['schema']!=1 or result['task_slots']!=8 or result['lock_classes']!=4:
            raise ValueError('Unsupported service layout')
        result['heap_initialized']=result['heap_sentinel']==0x8095ffd0
    else:
        result.update(task_slot=kind-2 if kind<10 else (kind-10)//4,
            observer_consistent=result['epoch_before']==result['epoch_after'] and not result['epoch_before']&1,
            physical_completion_proven=False)
        if kind>=10:
            result.update(lock_class=CLASSES[(kind-10)%4],
                native_take_in_progress=bool(result['flags']&1),
                retained_acquisition=bool(result['flags']&2),
                native_give_in_progress=bool(result['flags']&4),
                held_measurement='Successful native take return to native give entry; lower bound including scheduling.',
                identity_kind='Parent public file handle',amount_unit='Parent public file bytes')
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New local JSONL log')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=request,reply_decoder=decode,kinds=range(1,42))
    print(json.dumps(dict(samples=rows,limitation='Pages are individual epoch snapshots, not one coherent multi-page state. No capture or physical completion proof.')))
if __name__=='__main__':main()
