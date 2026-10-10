#!/usr/bin/env python3
"""Prepare simplified-capture trial images locally. No device access.

tap  (experiment 19): startup, ring size, DSP tap/commit and the read-only
     status query. Recorder and storage hooks stay stock: no take, no file.
take (experiment 20): every capture site plus the query and a worker stack
     measurement. Each ordinary recording also writes an extra .TMP file.
"""
import argparse,io,json,struct,subprocess,tarfile,tempfile
from pathlib import Path
from build_deployment_probe import ROOT,SOURCE,STOCK_SHA,CHECKSUM_OFFSET,validate,digest,write_manifest
from capture_jump_patches import BIAS,SCATTER
from build_simple_capture import build
from plan_simple_capture import plan

OUT=ROOT/'deployment/19_simple_tap'
# Experiment 19 is installed: rebuild it from the sources it was built from.
PINNED_SOURCES=('src/capture/simple','src/capture/hook_macros.inc','src/capture/retention.h',
                'src/diagnostics/health_hooks.S','tests/fixtures/capture_source_reuse.ld')
MODES=dict(tap=dict(experiment=19,out=OUT,image='trial_simple_tap',files_created=False,pin='045b3ce'),
           take=dict(experiment=20,out=ROOT/'deployment/20_simple_take',image='trial_simple_take',files_created=True))

def require(condition,message):
    if not condition:raise ValueError(message)

def pinned_build(mode,commit):
    archive=subprocess.run(['git','archive',commit,*PINNED_SOURCES],cwd=ROOT,capture_output=True,check=True).stdout
    with tempfile.TemporaryDirectory(prefix='l6-pinned-') as tree:
        tarfile.open(fileobj=io.BytesIO(archive)).extractall(tree,filter='data')
        return build(trial=mode,root=Path(tree))

def trial(mode='tap'):
    m=MODES[mode]
    stock=SOURCE.read_bytes();require(digest(stock)==STOCK_SHA,'unsupported stock firmware')
    validate(stock);elf=pinned_build(mode,m['pin']) if 'pin' in m else build(trial=mode)
    t=plan(elf,trial=mode);p=t['pack']
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
    report=dict(experiment=m['experiment'],mode=mode,status='prepared_locally_not_staged',trial_sha256=digest(data),
        stock_sha256=STOCK_SHA,elf_sha256=digest(elf.read_bytes()),patches=t['patches'],
        DSP_patches=t['DSP_patches'],metadata_edits=p['edits'],code_bytes=len(p['code']),
        globals_bytes=t['globals_bytes'],spare_bytes=t['packing']['spare_bytes'],
        code_start=names['placement_code_start'],code_end=names['placement_load_end'],
        globals_start=names['placement_globals_start'],globals_end=names['placement_globals_end'],
        code_source=p['code_source'],state_bytes=state_bytes,state_allocation_bytes=state_bytes+31,worker_stack_words=4096,
        native_capacity_frames=223104,files_created=m['files_created'],
        protocol='6F/6E kind6 schema%d; fixed capture/worker/heap/publication words'%(2 if mode=='take' else 1),
        unchanged=(['Stock recorder start/stop, Main receive and SD paths'] if mode=='tap' else
                   ['Stock SD driver, stock recording files and stock pad assignment'])+
                  ['MAIN length, container descriptors, PANEL and AUDIOGUIDE regions'],
        limitations=(['First hardware run of the tap writing the eight shortened lane tails',
            'Scatter expands code with the stock decoder into the consumed DSP source span; '
            'experiments 15/16 exercised that span and an extended table, not this exact table',
            'No take starts: recorder hooks are not installed, so SD service under capture is not measured']
            if mode=='tap' else
            ['First hardware run of capture: an extra 384,000 B/s .TMP file per ordinary recording',
             'Admission timing, SD service under load and storage revocation are observed, not proven',
             'Worker stack is measured by painting 15 KiB below its entry frame'])+
            ['Early-hang recovery (experiment 18) is parked and unproven',
             'No installation, staging or installed-flash readback is performed by this builder'])
    return data,report,t

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('mode',nargs='?',choices=MODES,default='tap')
    mode=a.parse_args().mode;m=MODES[mode]
    data,report,_=trial(mode);path=m['out']/m['image']/'L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=data:raise SystemExit('Refusing to overwrite a different prepared image')
    if not path.exists():path.write_bytes(data)
    write_manifest(m['out']/'manifest.json',report)
    print(json.dumps({k:report[k] for k in ('trial_sha256','code_bytes','globals_bytes','spare_bytes')}))
if __name__=='__main__':main()
