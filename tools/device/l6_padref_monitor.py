#!/usr/bin/env python3
"""Poll the master-reference status query for a timeline; no control writes.

Sends only the fixed kind-7 status request (and, with --session, the editor
session opening) every --interval seconds for --seconds, logging each decoded
reply with its host time. Use it to time a stop, the recorder's finalization
(recorder_busy), the chain handoff and its loads (pads), and the next record
start (admitted)."""
import argparse,json,time
from pathlib import Path
from l6_health_probe import sample
import l6_padref_probe as status
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=45);p.add_argument('--interval',type=float,default=0.25)
    p.add_argument('--session',action='store_true')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.session:
        from l6_transfer_mode import session
        if not session([])['session']:raise SystemExit('No editor session')
    count=int(a.seconds/a.interval);tokens=iter(i%128 for i in range(count))
    rows=sample(a.output,query_builder=lambda k,t:status.request(t),reply_decoder=status.decode,kinds=(7,)*count,
                reply_matcher=lambda d,k,t:d['token']==t,token_builder=lambda k:next(tokens),interval_s=a.interval)
    keys=('ticks','admitted','stopped','stock_recording','recorder_busy','checked','handoff_state','handoff_serial','chain_mask','pads')
    last=None
    for r in rows:
        view={k:r[k] for k in keys if k!='ticks'}
        if view!=last:print(json.dumps(dict(ticks=r['ticks'],**view)));last=view
    print(json.dumps(dict(samples=len(rows),first_tick=rows[0]['ticks'],last_tick=rows[-1]['ticks'])))
if __name__=='__main__':main()
