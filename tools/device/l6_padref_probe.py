#!/usr/bin/env python3
"""Read the master-reference trial's fixed status words; no control writes."""
FIELDS=('schema','marker','startup_status','task','admitted','stopped','stock_recording','stop_faults',
    'revoked','revoke_packet','file_open','polls','checked','refused','last_status','master_bytes',
    'handoff_state','handoff_result','handoff_serial','handoff_posts','stack_used',
    'free_bytes','minimum_free_bytes','ticks','ccr','code_start','code_end','globals_start','globals_end',
    'recorder_busy')
PATH_WORDS=16
STATUS=('ok','revoked','missing','split','io','format')
HANDOFF_STATES=('none','posted','assigned','skipped','failed','lost','superseded')
HEAP=(0x808e2fe0,0x8095ffd8)
PAINTED=7*1024
def request(token=0):
    if not 0<=token<=127:raise ValueError('token must be 7-bit')
    return bytes((0xf0,0x52,0,0,0x6f,7,token,0xf7))
def decode(packet):
    if len(packet)<6 or packet[:6]!=bytes((0xf0,0x52,0,0,0x6e,7)):return None
    words=len(FIELDS)+PATH_WORDS
    if len(packet)!=8+5*words or packet[-1]!=0xf7 or any(x>127 for x in packet[6:-1]):
        raise ValueError('invalid status reply length or encoding')
    values=[]
    for i in range(words):
        v=packet[7+5*i:12+5*i]
        if v[4]>15:raise ValueError('status word exceeds 32 bits')
        values.append(sum(b<<(7*j) for j,b in enumerate(v)))
    if values[:2]!=[1,0x4c4d01]:raise ValueError('unsupported status schema or marker')
    chars=[(w>>(7*k))&127 for w in values[len(FIELDS):] for k in range(4)]
    path=bytes(chars).split(b'\0')[0].decode('ascii')
    return dict(zip(FIELDS,values),assigned_path=path,token=packet[6])
def validate_samples(rows,manifest):
    """Strict acceptance for two idle samples after a normal boot."""
    if len(rows)!=2:raise ValueError('two observations are required')
    expected=dict(schema=1,marker=0x4c4d01,startup_status=4,admitted=0,stopped=0,stock_recording=0,
        stop_faults=0,file_open=0,checked=0,refused=0,handoff_state=0,handoff_serial=0,recorder_busy=0)
    expected.update({n:manifest[n] for n in ('code_start','code_end','globals_start','globals_end')})
    for row in rows:
        for n,v in expected.items():
            if row[n]!=v:raise ValueError(f'{n}: observed {row[n]}, expected {v}')
        if not HEAP[0]<=row['task']<HEAP[1]:raise ValueError('worker task falls outside the native heap')
        if row['ccr']&0x30000!=0x30000:raise ValueError('instruction/data caches are not both enabled')
        if not 0<row['minimum_free_bytes']<=row['free_bytes']<=0x7d000:raise ValueError('invalid heap observations')
        if not 128<=row['stack_used']<PAINTED:raise ValueError('worker stack measurement out of range')
    first,last=rows
    for n in ('task','free_bytes','revoked'):
        if first[n]!=last[n]:raise ValueError(f'{n} changed between idle samples')
    ticks=(last['ticks']-first['ticks'])&0xffffffff;polls=(last['polls']-first['polls'])&0xffffffff
    if not 0<ticks<0x80000000:raise ValueError('ticks did not advance')
    if not 0<polls<=ticks//25+2:raise ValueError('idle worker progress does not match elapsed ticks')
    return dict(normal_boot=True,ticks=ticks,worker_polls=polls,free_bytes=last['free_bytes'],
        minimum_free_bytes=last['minimum_free_bytes'],worker_stack_bytes=last['stack_used'],
        files_created=False,installed_flash_readback=False)
def validate_take(before,after):
    """One ordinary take between two samples, checked and assigned to pad 1."""
    if before['task']!=after['task']:raise ValueError('worker task changed across the take')
    for n in ('admitted','stopped','checked'):
        if after[n]!=before[n]+1:raise ValueError(f'expected exactly one take: {n} {before[n]} -> {after[n]}')
    if after['stop_faults']!=before['stop_faults']:raise ValueError('RecStop take folder was not usable')
    if after['last_status']:
        raise ValueError(f"master refused: {STATUS[after['last_status']] if after['last_status']<len(STATUS) else after['last_status']}")
    state=HANDOFF_STATES[after['handoff_state']] if after['handoff_state']<len(HANDOFF_STATES) else after['handoff_state']
    if state!='assigned' or after['handoff_serial']!=before['handoff_serial']+1:
        raise ValueError(f"handoff {state}, result {after['handoff_result']:#x}")
    path=after['assigned_path']
    if not (path.startswith('A:\\RECORDER\\') and path.endswith('\\MASTER.WAV')) or path==before['assigned_path']:
        raise ValueError(f'unexpected assigned path {path!r}')
    if after['file_open'] or after['stock_recording'] or after['master_bytes']<4096:
        raise ValueError('worker not idle or master too short')
    if not 128<=after['stack_used']<PAINTED:raise ValueError('worker stack measurement out of range')
    return dict(take_assigned=True,assigned_path=path,take_folder=path.split('\\')[2],
        master_bytes=after['master_bytes'],seconds_if_32bit_float=after['master_bytes']/384000,
        storage_packets_during_take=(after['revoked']-before['revoked'])&0xffffffff,
        worker_stack_bytes=after['stack_used'],minimum_free_bytes=after['minimum_free_bytes'])
def main():
    import argparse,json
    from pathlib import Path
    from l6_health_probe import sample
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--manifest',type=Path,help='Strictly validate two idle samples against this manifest')
    p.add_argument('--before-take',type=Path,help='Earlier log: validate one assigned take since its last sample')
    p.add_argument('--session',action='store_true',
                   help='Open an editor session first (use only while the official Editor is closed)')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.session:
        from l6_transfer_mode import session
        if not session([])['session']:raise SystemExit('No editor session: is the L6 connected and out of transfer mode?')
    tokens=iter((41,42))
    rows=sample(a.output,query_builder=lambda k,t:request(t),reply_decoder=decode,kinds=(7,7),
                reply_matcher=lambda d,k,t:d['token']==t,token_builder=lambda k:next(tokens),interval_s=1)
    result=dict(samples=rows)
    if a.manifest:result['validation']=validate_samples(rows,json.loads(a.manifest.read_text()))
    if a.before_take:
        earlier=[json.loads(l)['decoded'] for l in a.before_take.read_text().splitlines()
                 if json.loads(l).get('direction')=='device_to_probe']
        result['take']=validate_take(earlier[-1],rows[-1])
    print(json.dumps(result))
if __name__=='__main__':main()
