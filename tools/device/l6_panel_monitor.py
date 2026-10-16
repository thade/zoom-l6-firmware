#!/usr/bin/env python3
"""Record the panel switch diagnostics (experiment 37, status schema 6) for a
while and print the hold timeline; no control writes.

Sends only the fixed kind-7 status request every --interval seconds for
--seconds (open an editor session first with --session, Editor closed), then
merges the firmware's 32-entry event rings from every sample into one
timeline: key changes (a = first key, b = second: AUX1/AUX2 or PAN/LEVEL),
hold starts, restarts after 500 ms unseen, ignored misreads, releases and
toggles, with the time since the previous event. Also prints the counters,
poll intervals and the startup ticks (Main's first receive, the first gain
request, the worker's first poll)."""
import argparse,json
from pathlib import Path
from l6_health_probe import sample
import l6_padref_probe as status

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=120);p.add_argument('--interval',type=float,default=0.5)
    p.add_argument('--session',action='store_true')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.session:
        from l6_transfer_mode import session
        if not session([])['session']:raise SystemExit('No editor session')
    count=int(a.seconds/a.interval);tokens=iter(i%128 for i in range(count))
    rows=sample(a.output,query_builder=lambda k,t:status.request(t),reply_decoder=status.decode,kinds=(7,)*count,
                reply_matcher=lambda d,k,t:d['token']==t,token_builder=lambda k:next(tokens),interval_s=a.interval)
    if rows[-1]['schema']!=6:raise SystemExit('not the experiment 37 diagnostic build (schema 6)')
    events={}
    for r in rows:   # each ring lists its last min(32, ring_next) events, oldest first
        n=r['ring_next'];base=n-len(r['ring'])
        for k,e in enumerate(r['ring']):events[base+k]=e
    last=None
    for idx in sorted(events):
        e=events[idx];dt='' if last is None else f'+{(e["tick"]-last)&0xffffff} ms'
        print(f"{idx:5d} {e['tick']:9d} {dt:>10s}  {e['hold']:5s} {e['event']:8s} keys {e['a']}{e['b']}");last=e['tick']
    r=rows[-1]
    print(json.dumps({k:r[k] for k in r if k.startswith(('aux_','chain_','first_','max_poll','slow_polls'))},indent=1))
    missing=[i for i in range(min(events,default=0),max(events,default=-1)+1) if i not in events]
    if missing:print(f'{len(missing)} events overwritten between samples (sample faster)')
if __name__=='__main__':main()
