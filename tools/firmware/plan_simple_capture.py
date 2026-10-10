#!/usr/bin/env python3
"""Byte-checked patch plan for the simplified capture. JSON only, no image."""
import hashlib,json
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from build_deployment_probe import SOURCE,STOCK_SHA,validate
from capture_jump_patches import ROOT,BIAS,SCATTER,symbols
from plan_capture_hooks import make_patch as main_patch
from plan_capture_startup import SPECS as STARTUP_SPECS,make_patch as startup_patch
from plan_capture_transitions import RECEIVERS,receive_patch
from plan_capture_composed import SIZE_SITE
from plan_capture_packing import packing,report as packing_report

ELF=ROOT/'src/capture/simple/simple-capture.elf'
RECORDER_SPECS=(
    dict(site=0x8000b158,original='40f20120',adapter='sc_admit_hook',resume=0x8000b15c,
         replay='movw r0,#0x201',purpose='stock recorder admitted its seven streams'),
    dict(site=0x80006918,original='40f6c852',adapter='sc_stop_hook',resume=0x8000691c,
         replay='movw r2,#0xdc8',purpose='stock stop cursor setter, r0 = final cursor'))
SIZE_PATCH=dict(site=SIZE_SITE,original='4af68011',patch='46f28071',bytes=4,
    purpose='native ring capacity 223104 frames, freeing eight 67,584-byte lane tails')
GLOBALS=(0x80960080,0x809600e0)

def interior_branches(stock,patches):
    """Direct branches into any displaced span, over the final patch list."""
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True;found=[]
    spans=[(p['site'],p['site']+len(bytes.fromhex(p['patch']))) for p in patches]
    regions=[(stock[0x200:0xb5ce4],0x80001000),
             (stock[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]],SCATTER[1])]
    for code,base in regions:
        for address,size,mnemonic,ops in md.disasm_lite(code,base):
            if mnemonic.startswith('b') or mnemonic in ('cbz','cbnz'):
                try:target=int(ops.rsplit('#',1)[1],0)
                except (IndexError,ValueError):continue
                if any(a<target<b for a,b in spans):found.append(dict(site=address,target=target))
    return found

def plan(elf_path=ELF):
    stock=SOURCE.read_bytes()
    if hashlib.sha256(stock).hexdigest()!=STOCK_SHA:raise ValueError('unsupported stock firmware')
    validate(stock);names=symbols(elf_path)
    p=packing(elf_path)
    if p['jumps']['globals_start']!=GLOBALS[0] or p['jumps']['globals_end']>GLOBALS[1]:
        raise ValueError('globals exceed the proposed 96-byte range')
    patches=[startup_patch(stock,s,names[s['adapter']]) for s in STARTUP_SPECS]
    patches+=[main_patch(stock,s,names[s['adapter']]) for s in RECORDER_SPECS]
    if stock[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]!=bytes.fromhex(SIZE_PATCH['original']):
        raise ValueError('stock ring capacity instruction differs')
    patches.append(dict(SIZE_PATCH))
    patches+=[receive_patch(stock,site,old,names['sc_main_receive'],adapter='sc_main_receive')
              for site,old in RECEIVERS]
    ordered=sorted(patches,key=lambda x:x['site'])
    for a,b in zip(ordered,ordered[1:]):
        if a['site']+len(bytes.fromhex(a['patch']))>b['site']:raise ValueError('MAIN patches overlap')
    # Replayed instructions are re-executed at a new address: none may read PC.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.detail=True
    for q in patches+p['jumps']['patches']:
        if 'adapter' not in q or q['adapter'].startswith('startup_') or q['adapter']=='sc_main_receive':continue
        for i in md.disasm(bytes.fromhex(q['original']),q['site']):
            if 'pc' in i.op_str:raise ValueError(f"displaced PC-relative instruction at {q['site']:#x}")
    interiors=interior_branches(stock,patches+p['jumps']['patches'])
    if interiors:raise ValueError('direct branch enters a displaced span: '+str(interiors))
    pack=packing_report(p)
    return dict(status='offline_simple_capture_plan_not_deployable',firmware_sha256=STOCK_SHA,
        elf_sha256=hashlib.sha256(elf_path.read_bytes()).hexdigest(),
        patches=ordered,DSP_patches=p['jumps']['patches'],packing=pack,
        code_bytes=len(p['code']),globals_bytes=p['jumps']['globals_end']-p['jumps']['globals_start'],
        patch_sites=len(patches)+len(p['jumps']['patches']),
        history=dict(blocks=1024,frames=65536,seconds=65536/48000,bytes=1024*512),
        limitations=['JSON only; no container, checksum, staging or installation',
            'Code/globals placement and lane-tail ownership carry the same evidence and gaps as the earlier composition',
            'Worker stack (16 KiB) and SD service under the extra 384,000 B/s are unmeasured on hardware',
            'Linear direct-branch scan cannot exclude indirect entries into displaced spans'])

def main():
    r=plan();out=ROOT/'analysis/simple_capture_plan.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(patch_sites=r['patch_sites'],code_bytes=r['code_bytes'],
        globals_bytes=r['globals_bytes'],spare_bytes=r['packing']['spare_bytes'],report=str(out))))
if __name__=='__main__':main()
