#!/usr/bin/env python3
"""One offline minimal startup/arena/hooks proposal. JSON only, no device image."""
import json
from capture_jump_patches import ROOT,BIAS
from build_deployment_probe import SOURCE
from plan_capture_hooks import plan as hooks_plan

ELF=ROOT/'src/capture/capture-only-composed.elf'
CAP=223104
RING=0x81429800
STRIDE=960000
SIZE_SITE=0x800121ce

def plan(elf_path=ELF,globals_end=0x809600e4,heap_requested=9855):
    p=hooks_plan(elf_path)
    stock=SOURCE.read_bytes()
    old=bytes.fromhex('4af68011');new=bytes.fromhex('46f28071')
    if stock[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]!=old:
        raise ValueError('stock ring capacity instruction differs')
    p['patches'].append(dict(site=SIZE_SITE,original=old.hex(),patch=new.hex(),bytes=4,
        purpose='native startup capacity 223104 frames; existing MOVT supplies high half'))
    ordered=sorted(p['patches'],key=lambda x:x['site'])
    if any(a['site']+len(bytes.fromhex(a['patch']))>b['site'] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('composed MAIN patches overlap')
    if p['packing']['globals']!=[0x80960080,globals_end]:
        raise ValueError('composed global proposal changed')
    p.update(status='offline_composed_fixture_not_deployable',
        runtime_objects='one native heap allocation, retained until reboot',
        heap_requested_bytes=heap_requested,worker_stack_bytes=4096*4,
        worker_creation_metadata_bytes=148,
        globals_proposal_bytes=globals_end-0x80960080,native_capacity_frames=CAP,
        history=dict(slots=1024,frames=65536,seconds=65536/48000,bytes=540672,
            spans=[[RING+i*STRIDE+CAP*4,RING+(i+1)*STRIDE] for i in range(8)]),
        worker_after_startup='W_WAITING; no history accesses, files or hook activation',
        limitations=p['limitations']+[
            f'{globals_end-0x809600e0} extra proposed global bytes hold permanent composition pointers; no physical ownership inferred',
            'Heap/request and stack figures are prototype accounting, not safe headroom or service measurements',
            'Ring tails become usable only after native capacity initialization and verified transition exclusions',
            'No production storage admission/release or physical completion provider; no ready-to-install BIN'])
    return p

def main():
    p=plan();out=ROOT/'analysis/capture_composed_plan.json'
    out.write_text(json.dumps(p,indent=2)+'\n')
    print(json.dumps(dict(status=p['status'],MAIN_patches=len(p['patches']),
        DSP_patches=len(p['DSP_patches']),spare_bytes=p['packing']['spare_bytes'],report=str(out))))

if __name__=='__main__':main()
