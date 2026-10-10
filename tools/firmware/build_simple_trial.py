#!/usr/bin/env python3
"""Prepare the simplified-capture tap trial image locally. No device access.

Installs startup, ring-size, DSP tap/commit and the read-only status query.
The recorder and storage hooks stay stock, so no take starts and no file is
created: the worker only polls, while the tap fills history continuously.
"""
import json,struct
from build_deployment_probe import ROOT,SOURCE,STOCK_SHA,CHECKSUM_OFFSET,validate,digest,write_manifest
from capture_jump_patches import BIAS,SCATTER
from build_simple_capture import build
from plan_simple_capture import plan

OUT=ROOT/'deployment/19_simple_tap'

def require(condition,message):
    if not condition:raise ValueError(message)

def trial():
    stock=SOURCE.read_bytes();require(digest(stock)==STOCK_SHA,'unsupported stock firmware')
    validate(stock);elf=build(trial=True);t=plan(elf,trial=True);p=t['pack']
    source,dest,length,_=SCATTER;data=bytearray(stock)
    span=bytearray(b'\xff'*length);span[:len(p['packed_dsp'])]=p['packed_dsp']
    at=p['code_source']-source;span[at:at+len(p['packed_code'])]=p['packed_code']
    data[source-BIAS:source-BIAS+length]=span
    allowed=[(CHECKSUM_OFFSET,CHECKSUM_OFFSET+4),(source-BIAS,source-BIAS+length)]
    for change in p['edits']+t['patches']:
        site=change.get('address',change.get('site'));at=site-BIAS
        old=bytes.fromhex(change.get('old',change.get('original')))
        new=bytes.fromhex(change.get('new',change.get('patch')))
        require(data[at:at+len(old)]==old and len(old)==len(new),f'unexpected stock bytes at {site:#x}')
        data[at:at+len(new)]=new;allowed.append((at,at+len(new)))
    struct.pack_into('>I',data,CHECKSUM_OFFSET,sum(data[0x200:])&0xffffffff)
    data=bytes(data);validate(data)
    require(len(data)==len(stock) and data[0x2851f8:]==stock[0x2851f8:],'panel/voice regions changed')
    require(all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(data,stock)) if x!=y),
            'a byte changed outside the planned spans')
    names=p['names'];at=names['sc_layout']-names['placement_code_start']
    state_bytes=struct.unpack_from('<I',p['code'],at)[0]
    report=dict(experiment=19,status='prepared_locally_not_staged',trial_sha256=digest(data),
        stock_sha256=STOCK_SHA,elf_sha256=digest(elf.read_bytes()),patches=t['patches'],
        DSP_patches=t['DSP_patches'],metadata_edits=p['edits'],code_bytes=len(p['code']),
        globals_bytes=t['globals_bytes'],spare_bytes=t['packing']['spare_bytes'],
        code_start=names['placement_code_start'],code_end=names['placement_load_end'],
        globals_start=names['placement_globals_start'],globals_end=names['placement_globals_end'],
        code_source=p['code_source'],state_bytes=state_bytes,state_allocation_bytes=state_bytes+31,worker_stack_words=4096,
        native_capacity_frames=223104,files_created=False,
        protocol='6F/6E kind6 schema1; fixed capture/worker/heap/publication words',
        unchanged=['Stock recorder start/stop, Main receive and SD paths',
                   'MAIN length, container descriptors, PANEL and AUDIOGUIDE regions'],
        limitations=['First hardware run of the tap writing the eight shortened lane tails',
            'Scatter expands code with the stock decoder into the consumed DSP source span; '
            'experiments 15/16 exercised that span and an extended table, not this exact table',
            'Early-hang recovery (experiment 18) is parked and unproven',
            'No take starts: recorder hooks are not installed, so SD service under capture is not measured',
            'No installation, staging or installed-flash readback is performed by this builder'])
    return data,report,t

def main():
    data,report,_=trial();path=OUT/'trial_simple_tap/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=data:raise SystemExit('Refusing to overwrite a different prepared image')
    if not path.exists():path.write_bytes(data)
    write_manifest(OUT/'manifest.json',report)
    print(json.dumps({k:report[k] for k in ('trial_sha256','code_bytes','globals_bytes','spare_bytes')}))
if __name__=='__main__':main()
