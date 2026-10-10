#!/usr/bin/env python3
"""Read the dormant full-payload trial's fixed observations; no control writes."""
FIELDS=('schema','marker','startup_status','boot_phase','arena','arena_bytes','worker_state',
    'worker_status','worker_task','manager_state','lease_control','free_bytes','minimum_free_bytes',
    'ticks','ccr','code_start','code_end','globals_start','globals_end','worker_polls','physical_ports_or','active_hooks_or')
def request(token=0):
    if not 0<=token<=127:raise ValueError('token must be 7-bit')
    return bytes((0xf0,0x52,0,0,0x6f,5,token,0xf7))
def decode(packet):
    if len(packet)<6 or packet[:6]!=bytes((0xf0,0x52,0,0,0x6e,5)):return None
    if len(packet)!=8+5*len(FIELDS) or packet[-1]!=0xf7 or any(x>127 for x in packet[6:-1]):
        raise ValueError('invalid boot reply length or encoding')
    values=[]
    for i in range(len(FIELDS)):
        v=packet[7+5*i:12+5*i]
        if v[4]>15:raise ValueError('boot word exceeds 32 bits')
        values.append(sum(b<<(7*j) for j,b in enumerate(v)))
    if values[:2]!=[1,0x4c3701]:raise ValueError('unsupported boot schema or marker')
    return dict(zip(FIELDS,values),token=packet[6],installed_flash_readback=False,capture_expected_disabled=True)
def validate_samples(rows,manifest):
    """Strict normal-cold-boot acceptance; observations are not flash readback."""
    if len(rows)!=2:raise ValueError('two observations are required')
    expected=dict(schema=1,marker=0x4c3701,startup_status=3,boot_phase=9,arena_bytes=9887,
        worker_state=4,worker_status=0,manager_state=4,lease_control=0,
        physical_ports_or=0,active_hooks_or=0)
    expected.update({n:manifest[n] for n in ('code_start','code_end','globals_start','globals_end')})
    for row in rows:
        for n,v in expected.items():
            if row[n]!=v:raise ValueError(f'{n}: observed {row[n]}, expected {v}')
        if any(not 0x808e2fe0<=row[n]<0x8095ffd8 for n in ('arena','worker_task')) or row['arena']==row['worker_task']:
            raise ValueError('arena/task observations fall outside the native heap or alias')
        if row['ccr']&0x30000!=0x30000:raise ValueError('instruction/data caches are not both enabled')
        if not 0<row['minimum_free_bytes']<=row['free_bytes']<=0x7d000:
            raise ValueError('invalid heap observations')
    first,last=rows
    for n in ('arena','worker_task','free_bytes'):
        if first[n]!=last[n]:raise ValueError(f'{n} changed between idle samples')
    tick_delta=(last['ticks']-first['ticks'])&0xffffffff
    poll_delta=(last['worker_polls']-first['worker_polls'])&0xffffffff
    if not 0<poll_delta<=tick_delta//25+2 or tick_delta>=0x80000000:
        raise ValueError('sleeping-worker progress does not match elapsed ticks')
    return dict(normal_boot_witness=True,worker_waiting=True,worker_poll_delta=poll_delta,
        tick_delta=tick_delta,free_bytes=last['free_bytes'],minimum_free_bytes=last['minimum_free_bytes'],
        capture_enabled=False,physical_storage_admission=False,installed_flash_readback=False)
def main():
    import argparse,json
    from pathlib import Path
    from l6_health_probe import sample
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--manifest',type=Path,help='Validate two idle samples against this prepared-image manifest')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    tokens=iter((31,32))
    rows=sample(a.output,query_builder=lambda k,t:request(t),reply_decoder=decode,kinds=(5,5),
                reply_matcher=lambda d,k,t:d['token']==t,token_builder=lambda k:next(tokens),interval_s=1)
    result=dict(samples=rows)
    if a.manifest:result['validation']=validate_samples(rows,json.loads(a.manifest.read_text()))
    print(json.dumps(result))
if __name__=='__main__':main()
