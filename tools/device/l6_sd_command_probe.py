#!/usr/bin/env python3
"""Three fixed read-only native SD command journal queries; no mixer commands."""
import argparse,json
from pathlib import Path
from l6_health_probe import sample
COMMON=('schema','epoch_before','skipped','programs','program_sites','commands','data_commands','waits','unmatched','anomalies','active')
SAMPLE=('sequence','unit','task','event','code','request','address','bytes',
 'program_sequence','program_site','program_task','program_address','program_raw','program_present',
 'entry_raw','entry_present','entry_system','irq_raw','irq_count','tc_count','command_status',
 'wait_site','wait_status','wait_flags','wait_present','wait_dma','reasons','skipped_before')
def request(kind,token):
    if kind not in (1,2,3) or not 0<=token<128:raise ValueError('Invalid fixed command journal query')
    return bytes((0xf0,0x52,0,0,0x71,kind,token,0xf7))
def decode(packet):
    if len(packet)<8 or packet[:5]!=bytes((0xf0,0x52,0,0,0x70)):return None
    kind,token=packet[5:7]
    if kind not in (1,2,3) or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):raise ValueError('Invalid command journal reply')
    names=COMMON+(SAMPLE if kind!=3 else ())+('epoch_after','ticks')
    if len(packet)!=8+5*len(names):raise ValueError('Command journal length mismatch')
    values=[]
    for i in range(7,len(packet)-1,5):
        if packet[i+4]>15:raise ValueError('Command journal word exceeds uint32')
        values.append(sum(packet[i+k]<<(7*k) for k in range(5)))
    r=dict(kind=kind,token=token,**dict(zip(names,values)))
    if r['schema']!=1:raise ValueError('Unsupported command journal schema')
    r['observer_consistent']=r['epoch_before']==r['epoch_after'] and not r['epoch_before']&1
    if kind!=3:
        r['sample_present']=bool(r['sequence'])
        r['preprogram_context_matches']=bool(r['sequence'] and not r['reasons']&1)
        r['raw_error_bits']=r['irq_raw']&0x157f0000
    r['physical_completion_proven']=False;r['transfer_owner_identified']=False
    return r
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    rows=sample(a.output,query_builder=request,reply_decoder=decode,kinds=(1,2,3))
    print(json.dumps(dict(samples=rows,limitation='Temporal command/buffer association does not join or exclude old physical sources.')))
if __name__=='__main__':main()
