#!/usr/bin/env python3
"""Byte-checked MAIN audio/control/startup jumps, JSON only. No device image."""
import hashlib,json
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from capture_jump_patches import ROOT,BIAS,symbols
from build_deployment_probe import SOURCE,STOCK_SHA,validate
from build_added_code_probe import branch
from plan_capture_startup import SPECS as STARTUP_SPECS,make_patch as startup_patch
from plan_capture_packing import packing,report as packing_report

ELF=ROOT/'src/capture/capture-only-hooks.elf'
SPECS=(
    dict(site=0x8001078a,original='00b18047',adapter='emulator_audio_outer_hook',resume=0x8001078e,
         replay='CBZ null callback; otherwise BX callback with original LR=0x8001078f'),
    dict(site=0x8001078e,original='fff7dffc',adapter='emulator_audio_return_hook',resume=0x80010792,
         replay='branch to stock 0x80010150 with LR=0x80010793'),
    dict(site=0x80006908,original='40f6c852',adapter='emulator_start_hook',resume=0x8000690c,replay='movw r2,#0xdc8'),
    dict(site=0x80006918,original='40f6c852',adapter='emulator_stop_hook',resume=0x8000691c,replay='movw r2,#0xdc8'),
    dict(site=0x8000b158,original='40f20120',adapter='emulator_admit_hook',resume=0x8000b15c,replay='movw r0,#0x201'),
    dict(site=0x80034fc0,original='0620bde87040',adapter='emulator_reject_hook',resume=0x80034fc6,
         replay='movs r0,#6; pop.w {r4,r5,r6,lr}'),
    dict(site=0x8000b78c,original='00202cf083fb',adapter='emulator_recorder_drained_hook',resume=0x8000b792,
         replay='movs r0,#0; branch to stock 0x80037e98 with LR=0x8000b793'),
    dict(site=0x800483f8,original='10b54ff0ff32',adapter='ct_queue_send',resume=0x800483fe,
         replay='stock-send adapter: push {r4,lr}; mov.w r2,#-1'),
    dict(site=0x80034f40,original='70b50446',adapter='ct_record_request',resume=0x80034f44,
         replay='stock-request adapter: push {r4,r5,r6,lr}; mov r4,r0'),
    dict(site=0x80034d18,original='b0b588b0',adapter='ct_stop_request',resume=0x80034d1c,
         replay='stock-request adapter: push {r4,r5,r7,lr}; sub sp,#0x20'),
    dict(site=0x80034e58,original='f0b589b0',adapter='ct_play_request',resume=0x80034e5c,
         replay='stock-request adapter: push {r4,r5,r6,r7,lr}; sub sp,#0x24'),
    dict(site=0x80035038,original='70b588b0',adapter='ct_stop_argument',resume=0x8003503c,
         replay='stock-request adapter: push {r4,r5,r6,lr}; sub sp,#0x20'),
    dict(site=0x800350d8,original='b0b588b0',adapter='ct_stop_other',resume=0x800350dc,
         replay='stock-request adapter: push {r4,r5,r7,lr}; sub sp,#0x20'))

def make_patch(stock,spec,target):
    if not target&1 or not 0x800b6b00<=target<0x801f5400:
        raise ValueError('target must be Thumb code in the candidate interval')
    site=spec['site'];old=bytes.fromhex(spec['original'])
    if stock[site-BIAS:site-BIAS+len(old)]!=old:raise ValueError('stock hook bytes differ')
    decoded=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS).disasm(old,site))
    if sum(i.size for i in decoded)!=len(old) or site+len(old)!=spec['resume']:
        raise ValueError('patch must consume complete original instructions')
    if len(old)<4:raise ValueError('selected span cannot contain B.W')
    patch=branch(site,target&~1)+b'\x00\xbf'*((len(old)-4)//2)
    if len(patch)!=len(old):raise ValueError('invalid patch span')
    return dict(**spec,target=target,patch=patch.hex(),bytes=len(old),
                decoded_original=[f'{i.mnemonic} {i.op_str}' for i in decoded])

def plan(elf_path=ELF):
    stock=SOURCE.read_bytes()
    if hashlib.sha256(stock).hexdigest()!=STOCK_SHA:raise ValueError('unsupported stock firmware')
    validate(stock);names=symbols(elf_path)
    patches=[make_patch(stock,s,names[s['adapter']]) for s in SPECS]
    patches += [startup_patch(stock,s,names[s['adapter']]) for s in STARTUP_SPECS]
    ordered=sorted(patches,key=lambda x:x['site'])
    assert all(a['site']+len(bytes.fromhex(a['patch']))<=b['site'] for a,b in zip(ordered,ordered[1:]))
    p=packing(elf_path);start=p['jumps']['candidate_code_start'];end=p['jumps']['candidate_load_end']
    assert all(start<=x['target']<end for x in patches)
    # Retain bounded direct-entry evidence. This linear scan is not whole-
    # program pointer analysis and cannot exclude indirect interior entries.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True;interiors=[]
    for address,size,mnemonic,ops in md.disasm_lite(stock[0x200:0xb5ce4],0x80001000):
        if mnemonic.startswith('b') or mnemonic in ('cbz','cbnz'):
            try:target=int(ops.rsplit('#',1)[1],0)
            except (IndexError,ValueError):continue
            if any(x['site']<target<x['resume'] for x in patches[:len(SPECS)]):
                interiors.append(dict(site=address,target=target,instruction=f'{mnemonic} {ops}'))
    if interiors:raise ValueError('direct branch enters a displaced MAIN span: '+str(interiors))
    return dict(status='offline_hooks_fixture_not_deployable',firmware_sha256=STOCK_SHA,
        hooks_elf_sha256=hashlib.sha256(elf_path.read_bytes()).hexdigest(),patches=patches,
        DSP_patches=p['jumps']['patches'],packing=packing_report(p),
        direct_interior_branches=interiors,
        limitations=['JSON/memory patches only; no container, checksum, transfer or installed firmware',
            'Capture-only hooks use a separate fixture ELF; normal and prior startup profiles are unchanged',
            'Storage startup release, outer transitions and physical SD completion remain unbound',
            'Deep recording setup, RTOS scheduling and middle DSP effects remain fixtures',
            'Linear direct-branch scan does not establish exhaustive indirect entry or source ownership',
            'Physical RAM, cache/MPU/FPU/interrupt behavior and measured timing still need device evidence'])

def main():
    p=plan();out=ROOT/'analysis/capture_hooks_plan.json'
    out.write_text(json.dumps(p,indent=2)+'\n')
    print(json.dumps(dict(status=p['status'],MAIN_patches=len(p['patches']),
        DSP_patches=len(p['DSP_patches']),spare_bytes=p['packing']['spare_bytes'],report=str(out))))

if __name__=='__main__':main()
