#!/usr/bin/env python3
"""Prepare a dormant full-capture-payload trial locally. No device access.

Install only startup/witness/Main-closure/query hooks. DSP stays stock; SD guards,
recording/control hooks and worker release are not connected. Stock seven-file
recording is therefore the only recording path in this trial.
"""
import json,struct,subprocess,sys
from capture_jump_patches import ROOT,BIAS,SCATTER,symbols
from build_deployment_probe import SOURCE,STOCK_SHA,validate,digest,write_manifest
from plan_capture_lz4 import packing
from plan_capture_boot import plan
from plan_capture_hooks import make_patch
from plan_capture_composed import SIZE_SITE
from capture_source_reuse_layout import CODE_INTERVAL

ELF=ROOT/'src/capture/capture-only-boot-probe.elf'
OUT=ROOT/'deployment/17_dormant_boot'
ENABLED={'startup_init_hook','startup_idle_hook','storage_boot_mount_hook',
         'storage_boot_request_hook','storage_boot_consume_hook','storage_boot_ack_hook',
         'storage_boot_card','storage_boot_usb','storage_main_receive'}

def trial():
    stock=SOURCE.read_bytes();assert digest(stock)==STOCK_SHA
    p=packing(ELF,source_reuse=True,dsp_hooks=False);full=plan(p,elf_path=ELF);n=symbols(ELF)
    selected=[q for q in full['patches'] if q.get('adapter') in ENABLED or q['site']==SIZE_SITE]
    assert len(selected)==14 and {q.get('adapter') for q in selected if 'adapter' in q}==ENABLED
    selected.append(make_patch(stock,dict(site=0x800301f0,original='2de9f047',
        resume=0x800301f4,adapter='health_parser'),n['health_parser'],code_interval=CODE_INTERVAL))
    data=bytearray(stock);allowed=[(0x1fc,0x200),(SCATTER[0]-BIAS,SCATTER[0]-BIAS+SCATTER[2])]
    data[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]]=p['source_blob']
    for q in p['edits']:
        at=q['address']-BIAS;old=bytes.fromhex(q['old']);new=bytes.fromhex(q['new'])
        assert data[at:at+len(old)]==old and len(old)==len(new)
        data[at:at+len(old)]=new;allowed.append((at,at+len(new)))
    for q in selected:
        at=q['site']-BIAS;old=bytes.fromhex(q['original']);new=bytes.fromhex(q['patch'])
        assert data[at:at+len(old)]==old and len(old)==len(new)
        data[at:at+len(old)]=new;allowed.append((at,at+len(new)))
    struct.pack_into('>I',data,0x1fc,sum(data[0x200:])&0xffffffff)
    data=bytes(data);validate(data)
    assert len(data)==len(stock) and data[0x2851f8:]==stock[0x2851f8:]
    assert all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(data,stock)) if x!=y)
    assert p['dsp']==stock[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]]
    report=dict(experiment=17,status='prepared_locally_not_staged',trial_sha256=digest(data),
        stock_sha256=STOCK_SHA,elf_sha256=digest(ELF.read_bytes()),patches=selected,
        code_bytes=len(p['code']),globals_bytes=full['globals_bytes'],
        spare_bytes=full['packing']['spare_bytes'],loader_sha256=digest(p['loader']),
        code_start=n['placement_code_start'],code_end=n['placement_load_end'],
        globals_start=n['placement_globals_start'],globals_end=n['placement_globals_end'],
        source_blob_sha256=digest(p['source_blob']),worker_stack_bytes=16384,arena_requested_bytes=9887,
        native_arena_allocation_bytes=9896,native_stack_allocation_bytes=16400,
        native_task_allocation_bytes=160,native_extra_heap_bytes=26456,
        native_capacity_frames=223104,capture_enabled=False,SD_guards_enabled=False,
        protocol='6F/6E kind5 schema1; fixed boot/witness/worker/heap/publication observations',
        limitations=[
            'Full payload publication and one dormant worker/arena are new hardware behavior and need a physical update/reboot trial.',
            'Original DSP/audio/control/SD code is unhooked; native ring capacity retains the already-tried223104 geometry.',
            'The startup witness is only logical readiness; no physical source permission, lease admission or release caller is installed.',
            'The query replaces earlier passive diagnostic queries; original editor/pad messages remain routed to stock.',
            'Worker poll count is liveness only; it does not measure loaded service latency, stack margin or audio integrity.',
            'No installation, SD staging, mixer-mode change or installed-flash readback is performed by this builder.'])
    return data,report,p,full

def main():
    result=subprocess.run([sys.executable,str(ROOT/'tools/firmware/build_extra_capture.py'),'--boot-probe-fixture'],
                          cwd=ROOT,text=True,capture_output=True)
    if result.returncode:sys.exit(result.stdout+result.stderr)
    data,r,_,_=trial();path=OUT/'trial_dormant_boot/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to overwrite a different prepared image'
    else:path.write_bytes(data)
    write_manifest(OUT/'manifest.json',r)
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','globals_bytes','spare_bytes')}))
if __name__=='__main__':main()
