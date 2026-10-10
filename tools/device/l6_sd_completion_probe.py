#!/usr/bin/env python3
"""Experiment 09 fixed read-only chunk-completion queries; no mixer commands."""
import argparse,json
from pathlib import Path
from l6_health_probe import sample
FIELDS=('schema','epoch_before','waits','skipped','sites','anomalies',
    'site','event','task','timeout','status','flags','before_present','present',
    'system','protocol','mix','vendor2','dma_address_sample','epoch_after','ticks')
PATHS=('direct_read','bounce_read','direct_write','bounce_write')
SITES=(0x8006a06e,0x8006a1f8,0x8006ac72,0x8006ae14)
SUMMARY_FIELDS=FIELDS[:6]+tuple('wait_'+n for n in PATHS)+tuple('anomaly_'+n for n in PATHS)+tuple('reasons_'+n for n in PATHS)+('epoch_after','ticks')
def reason_names(value):
    named=((1,'wait_error'),(2,'missing_completion_flag'),(4,'fault_flags'),
           (8,'reset_active'),(16,'unexpected_controller_mode'),(32,'unexpected_wait_arguments'),
           (0x100,'command_inhibit'),(0x200,'data_inhibit'),(0x400,'data_line_active'),
           (0x10000,'write_transfer_active'),(0x20000,'read_transfer_active'))
    return [name for bit,name in named if value&bit]
def request(kind,token):
    if kind not in range(1,8) or not 0<=token<128:raise ValueError('Invalid completion query')
    return bytes((0xf0,0x52,0,0,0x73,kind,token,0xf7))
def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x72)):return None
    kind,token=packet[5:7]
    if kind not in range(1,8) or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):
        raise ValueError('Invalid completion reply')
    fields=SUMMARY_FIELDS if kind==3 else FIELDS
    if len(packet)!=8+5*len(fields):raise ValueError('Completion reply length mismatch')
    words=[]
    for p in range(7,len(packet)-1,5):
        if packet[p+4]>15:raise ValueError('Completion word exceeds uint32')
        words.append(sum(packet[p+i]<<(7*i) for i in range(5)))
    r=dict(kind=kind,token=token,**dict(zip(fields,words)))
    if r['schema']!=(2 if kind==3 else 1) or r['sites']&~15:raise ValueError('Unsupported completion schema')
    r['observer_consistent']=r['epoch_before']==r['epoch_after'] and not r['epoch_before']&1
    if kind==3:
        if any(r['reasons_'+n]&~0x3073f for n in PATHS):raise ValueError('Unknown completion reason bits')
        r['per_site']={n:dict(waits=r['wait_'+n],anomalies=r['anomaly_'+n],
            reason_union=r['reasons_'+n],reason_names=reason_names(r['reasons_'+n])) for n in PATHS}
    else:
        r['activity_bits']=r['present']&0x307;r['reset_bits']=r['system']&0x07000000
        if kind>=4:
            if r['site'] not in (0,SITES[kind-4]):raise ValueError('Completion site does not match requested path')
            r['sample_path']=PATHS[kind-4];r['sample_present']=r['site']!=0
    r['physical_completion_proven']=False
    return r
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New local JSONL log; existing files are not overwritten')
    p.add_argument('--detail',action='store_true',help='Also read per-site counters and latest anomalies; requires the detail firmware')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=request,reply_decoder=decode,kinds=tuple(range(1,8)) if a.detail else (1,2))
    print(json.dumps(dict(samples=rows,limitation='Passive snapshots do not join I/O or authorize capture.')))
if __name__=='__main__':main()
