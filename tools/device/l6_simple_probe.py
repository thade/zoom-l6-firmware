#!/usr/bin/env python3
"""Read the simplified-capture trial's fixed status words; no control writes."""
FIELDS=('schema','marker','startup_status','state','task','frames','epoch','capacity','age',
    'take','skipped','event_faults','revoked','worker_state','file_open','completed','failed',
    'last_status','polls','free_bytes','minimum_free_bytes','ticks','ccr',
    'code_start','code_end','globals_start','globals_end')
TAKE_FIELDS=FIELDS+('stack_used','bytes','start','stop','revoke_packet')   # schema 2 (experiment 20)
HEAP=(0x808e2fe0,0x8095ffd8)
PAINTED=15*1024
def request(token=0):
    if not 0<=token<=127:raise ValueError('token must be 7-bit')
    return bytes((0xf0,0x52,0,0,0x6f,6,token,0xf7))
def decode(packet):
    if len(packet)<6 or packet[:6]!=bytes((0xf0,0x52,0,0,0x6e,6)):return None
    fields=TAKE_FIELDS if len(packet)==8+5*len(TAKE_FIELDS) else FIELDS
    if len(packet)!=8+5*len(fields) or packet[-1]!=0xf7 or any(x>127 for x in packet[6:-1]):
        raise ValueError('invalid status reply length or encoding')
    values=[]
    for i in range(len(fields)):
        v=packet[7+5*i:12+5*i]
        if v[4]>15:raise ValueError('status word exceeds 32 bits')
        values.append(sum(b<<(7*j) for j,b in enumerate(v)))
    if values[:2]!=[1 if fields is FIELDS else 2,0x4c3901]:raise ValueError('unsupported status schema or marker')
    return dict(zip(fields,values),token=packet[6])
def rate(first,last):
    """Frames published per kernel tick between two samples (48.0 at 1 kHz)."""
    ticks=(last['ticks']-first['ticks'])&0xffffffff
    frames=(last['frames']-first['frames'])&0xffffffff
    if not ticks or ticks>=0x80000000:raise ValueError('ticks did not advance')
    return frames/ticks,frames,ticks
def validate_samples(rows,manifest):
    """Strict acceptance for two idle samples after a normal boot."""
    if len(rows)!=2:raise ValueError('two observations are required')
    take=manifest.get('mode')=='take'
    expected=dict(schema=2 if take else 1,marker=0x4c3901,startup_status=4,capacity=223104,take=0,skipped=0,
        event_faults=0,worker_state=0,file_open=0,completed=0,failed=0,last_status=0)
    # Boot-time card/USB packets may revoke in the take image; no take is open then.
    if not take:expected['revoked']=0
    expected.update({n:manifest[n] for n in ('code_start','code_end','globals_start','globals_end')})
    for row in rows:
        for n,v in expected.items():
            if row[n]!=v:raise ValueError(f'{n}: observed {row[n]}, expected {v}')
        if any(not HEAP[0]<=row[n]<HEAP[1] for n in ('state','task')) or row['state']%32:
            raise ValueError('state/task observations fall outside the native heap')
        if row['ccr']&0x30000!=0x30000:raise ValueError('instruction/data caches are not both enabled')
        if not 0<row['minimum_free_bytes']<=row['free_bytes']<=0x7d000:raise ValueError('invalid heap observations')
        if take and not 128<=row['stack_used']<PAINTED:raise ValueError('worker stack measurement out of range')
    first,last=rows
    for n in ('state','task','free_bytes','epoch','revoked'):
        if first[n]!=last[n]:raise ValueError(f'{n} changed between idle samples')
    per_tick,frames,ticks=rate(first,last)
    if not 46<=per_tick<=50:raise ValueError(f'tap published {per_tick:.2f} frames per tick, expected 48')
    polls=(last['polls']-first['polls'])&0xffffffff
    if not 0<polls<=ticks//25+2:raise ValueError('idle worker progress does not match elapsed ticks')
    return dict(normal_boot=True,frames_per_tick=per_tick,frames=frames,ticks=ticks,epoch=last['epoch'],
        worker_polls=polls,free_bytes=last['free_bytes'],minimum_free_bytes=last['minimum_free_bytes'],
        files_created=False,installed_flash_readback=False)
def validate_take(before,after):
    """One finished capture take between two samples (schema 2)."""
    for n in ('state','task','epoch'):
        if before[n]!=after[n]:raise ValueError(f'{n} changed across the take')
    revoked=(after['revoked']-before['revoked'])&0xffffffff
    if after['take']!=before['take']+1:raise ValueError('expected exactly one admitted take')
    if after['last_status']==1:raise ValueError(f"take revoked by packet {after['revoke_packet']:06x}")
    if after['completed']!=before['completed']+1 or after['failed']!=before['failed'] or after['last_status']:
        raise ValueError(f"take did not complete: status {after['last_status']}")
    if after['worker_state'] or after['file_open'] or after['skipped']!=before['skipped'] or after['event_faults']!=before['event_faults']:
        raise ValueError('worker not idle or events faulted')
    frames=(after['stop']-after['start'])&0xffffffff
    if not frames or after['bytes']!=frames*8:raise ValueError('file payload does not match the take frames')
    if not 128<=after['stack_used']<PAINTED:raise ValueError('worker stack measurement out of range')
    return dict(take_completed=True,frames=frames,seconds=frames/48000,payload_bytes=after['bytes'],
        storage_packets_during_take=revoked,
        worker_stack_bytes=after['stack_used'],minimum_free_bytes=after['minimum_free_bytes'])
def main():
    import argparse,json
    from pathlib import Path
    from l6_health_probe import sample
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--manifest',type=Path,help='Strictly validate two idle samples against this manifest')
    p.add_argument('--before-take',type=Path,help='Earlier log: validate one finished take since its last sample')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    tokens=iter((41,42))
    rows=sample(a.output,query_builder=lambda k,t:request(t),reply_decoder=decode,kinds=(6,6),
                reply_matcher=lambda d,k,t:d['token']==t,token_builder=lambda k:next(tokens),interval_s=1)
    result=dict(samples=rows,frames_per_tick=rate(*rows)[0],epoch_change=rows[1]['epoch']-rows[0]['epoch'])
    if a.manifest:result['validation']=validate_samples(rows,json.loads(a.manifest.read_text()))
    if a.before_take:
        earlier=[json.loads(l)['decoded'] for l in a.before_take.read_text().splitlines()
                 if json.loads(l).get('direction')=='device_to_probe']
        result['take']=validate_take(earlier[-1],rows[-1])
    print(json.dumps(result))
if __name__=='__main__':main()
