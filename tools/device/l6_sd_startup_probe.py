#!/usr/bin/env python3
"""Read diagnostic14's frozen first SD startup observations. No state changes."""
import argparse,json
from pathlib import Path
from l6_health_probe import sample

SUMMARY=('attempts','active','done','result','card','owner','commands','codes_lo','codes_hi',
         'irqs','raw_union','raw_current','waits','pio_waits','omitted','errors')
RESET=('resets','system','present','raw','signal','irq_enabled','irq_pending','irq_active','unit_token')
PIO=('site','event','task','mask','mode','timeout','status','flags','raw','present','system','mix',
     'blocks','commands','irqs','sequence')
FIRST_COMMAND=RESET[1:]

def request(kind,token):
    if not 1<=kind<=11 or not 0<=token<128:raise ValueError('Invalid startup kind/token')
    return bytes((0xf0,0x52,0,0,0x6d,kind,token,0xf7))

def decode(packet):
    if len(packet)<5 or packet[:5]!=bytes((0xf0,0x52,0,0,0x6c)):return None
    if len(packet)<12:raise ValueError('Unsupported startup reply')
    schema=sum(packet[7+k]<<(7*k) for k in range(5))
    if schema not in (1,2):raise ValueError('Unsupported startup schema')
    kind=packet[5]
    if not 1<=kind<=(6 if schema==1 else 11):raise ValueError('Unsupported startup reply')
    fields=(SUMMARY if kind==1 else RESET if kind==2 else FIRST_COMMAND if kind==11 else
            PIO+(('code','argument') if schema==2 else ()))
    if len(packet)!=28+len(fields)*5 or packet[-1]!=0xf7 or any(b>127 for b in packet[1:-1]):
        raise ValueError('Malformed startup reply')
    words=[]
    for i in range(7,len(packet)-1,5):
        if packet[i+4]>15:raise ValueError('Startup word exceeds uint32')
        words.append(sum(packet[i+k]<<(7*k) for k in range(5)))
    r=dict(kind=kind,token=packet[6],schema=words[0],epoch_before=words[1],skipped=words[2],
           epoch_after=words[-1],**dict(zip(fields,words[3:-1])))
    r['observer_consistent']=r['epoch_before']==r['epoch_after'] and not r['epoch_before']&1
    r['physical_completion_proven']=False
    if kind==1:
        if r['active']>1 or r['done']>1:raise ValueError('Unsupported startup state')
        r['packet_codes']=[n for n in range(64) if r['codes_lo' if n<32 else 'codes_hi']&(1<<(n%32))]
    if 3<=kind<=10 and r['sequence'] not in (0,kind-2):raise ValueError('Wrong startup sample slot')
    return r

def summarize(rows):
    by_kind={r['kind']:r for r in rows}
    if len(by_kind)!=len(rows):raise ValueError('Repeated startup reply')
    schemas={r['schema'] for r in rows}
    schema=next(iter(schemas)) if len(schemas)==1 else None
    complete=schema in (1,2) and set(by_kind)==set(range(1,7 if schema==1 else 12))
    stable=complete and len({r['epoch_before'] for r in rows})==1 and all(r['observer_consistent'] for r in rows)
    s=by_kind.get(1,{});reset=by_kind.get(2,{})
    captured=[by_kind[k] for k in range(3,11) if k in by_kind and by_kind[k]['sequence']]
    first=(stable and not any(r['skipped'] for r in rows) and
        s['attempts']==1 and s['done']==1 and s['active']==0 and not s['omitted'] and
        s['pio_waits']==len(captured))
    first_command=by_kind.get(11,{})
    return dict(schema=schema,complete_reply_set=complete,stable_snapshot=stable,first_enumeration_observed=first,
        native_result=s.get('result'),startup_observer_errors=s.get('errors'),
        reset_count=reset.get('resets'),reset_bits_at_observation=(reset['system']&0x07000000) if reset else None,
        reset_bits_at_first_command=(first_command['system']&0x07000000) if first_command else None,
        pio_completions=len(captured),physical_completion_proven=False,
        limitation='Native status and temporally associated IRQs cannot establish physical source exclusion or authorize capture')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();summary=a.output.with_suffix('.summary.json')
    if a.output.resolve()==summary.resolve():p.error('Log and summary must differ')
    for path in (a.output,summary):
        if path.exists():raise FileExistsError(str(path))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    latest={}
    def receive(packet):
        r=decode(packet)
        if r:latest[r['kind']]=r
        return r
    def kinds():
        yield 1
        yield from range(2,7 if latest[1]['schema']==1 else 12)
    rows=sample(a.output,query_builder=request,reply_decoder=receive,kinds=kinds())
    result=summarize(rows)
    with summary.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(result,summary=str(summary))))
if __name__=='__main__':main()
