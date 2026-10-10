#!/usr/bin/env python3
"""Read experiment 06 status; --reserve explicitly holds fixed memory until reboot.

No arbitrary size/address, release, playback, record, file or firmware operation.
Use only after updating to this trial and connecting the official Editor.
"""
import argparse,json
from pathlib import Path
from l6_health_probe import sample

FIELDS=('status_before','arena_request_bytes','stack_request_bytes','task_request_bytes',
        'expected_split_charge_bytes','minimum_free_floor_bytes','free_before','free_after',
        'actual_charge_bytes','arena_pointer','stack_pointer','task_pointer','elapsed_ticks',
        'status_after','ticks','scheduler_suspend_depth')
STATUSES=('untried','busy','held','headroom_refused','allocation_failed','context_refused')
def request(kind,token):
    if kind not in (1,2) or not 0<=token<128:raise ValueError('Invalid fixed reservation request')
    return bytes((0xf0,0x52,0,0,0x79,kind,token,0xf7))
def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x78)):return None
    kind,token=packet[5:7]
    if kind not in (1,2) or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):raise ValueError('Invalid reservation reply')
    if len(packet)!=8+5*len(FIELDS):raise ValueError('Reservation reply length does not match schema 1')
    values=[]
    for p in range(7,len(packet)-1,5):
        if packet[p+4]>15:raise ValueError('Reservation word exceeds uint32')
        values.append(sum(packet[p+i]<<(7*i) for i in range(5)))
    r=dict(kind=kind,token=token,**dict(zip(FIELDS,values)))
    if r['status_before']>=len(STATUSES) or r['status_after']>=len(STATUSES):raise ValueError('Unknown reservation status')
    r['status']=STATUSES[r['status_after']]
    r['observer_consistent']=r['status_before']==r['status_after'] and r['status_after']!=1
    r['reservation_held']=r['observer_consistent'] and r['status_after']==2
    r['worker_created']=r['capture_enabled']=False
    return r
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New JSONL log; existing logs are never overwritten')
    p.add_argument('--reserve',action='store_true',help='Explicitly reserve the fixed arena/stack/task budget once; held until reboot')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=request,reply_decoder=decode,kinds=(1,2) if a.reserve else (1,))
    print(json.dumps(dict(samples=rows,requested_reservation=a.reserve,
        limitation='Memory capacity only; no worker, capture, physical I/O or final reserve guarantee.')))
if __name__=='__main__':main()
