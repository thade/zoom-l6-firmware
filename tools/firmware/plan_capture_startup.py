#!/usr/bin/env python3
"""Specify offline startup jumps for the separate fixture ELF; JSON only."""
import hashlib,json
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from build_deployment_probe import SOURCE,STOCK_SHA,validate
from build_added_code_probe import branch
from capture_jump_patches import ROOT,BIAS,symbols
from plan_capture_packing import packing,report as packing_report

ELF=ROOT/'src/capture/capture-only-startup.elf'
SPECS=(dict(site=0x80067a84,original='0cf098fd',adapter='startup_init_hook',
            continuation=0x800745b8,replay='branch to stock scheduler with LR=0x80067a89'),
       dict(site=0x800745e8,original='4ff02000',adapter='startup_idle_hook',
            continuation=0x800745ec,replay='mov.w r0,#0x20'))

def make_patch(stock,spec,target,*,code_interval=(0x800b6b00,0x801f5400)):
    if not target&1 or not code_interval[0]<=target<code_interval[1]:
        raise ValueError('target must be Thumb code in candidate interval')
    site=spec['site'];old=bytes.fromhex(spec['original'])
    if stock[site-BIAS:site-BIAS+4]!=old:raise ValueError('stock startup bytes differ')
    decoded=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS).disasm(old,site))
    if len(decoded)!=1 or decoded[0].size!=4:raise ValueError('incomplete instruction')
    return dict(**spec,target=target,patch=branch(site,target&~1).hex(),
                decoded_original=f'{decoded[0].mnemonic} {decoded[0].op_str}')

def plan():
    stock=SOURCE.read_bytes()
    if hashlib.sha256(stock).hexdigest()!=STOCK_SHA:raise ValueError('unsupported stock firmware')
    validate(stock);names=symbols(ELF)
    patches=[make_patch(stock,s,names[s['adapter']]) for s in SPECS]
    p=packing_report(packing(ELF))
    assert p['spare_bytes']>=0
    assert p['globals']==[0x80960080,0x809600e0]
    return dict(status='offline_startup_fixture_not_deployable',firmware_sha256=STOCK_SHA,
        startup_elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),patches=patches,
        packing=p,candidate_manager=[0x80961de0,0x80962680],
        candidate_worker=[0x80962680,0x809626c0],
        descriptor_and_configuration='local registration inputs copied by compiled manager/worker',
        limitations=['Candidate RAM addresses are unapproved for the device',
            'Two startup jumps only; audio/control/storage integration remains incomplete',
            'Worker remains W_WAITING; no storage release or pad publication',
            'Stack/heap capacity, interrupts, physical FPU/cache/MPU and bootloader behavior remain unverified',
            'No image construction, staging, device access or deployment'])

def main():
    p=plan();out=ROOT/'analysis/capture_startup_plan.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(p,indent=2)+'\n')
    print(json.dumps(dict(status=p['status'],patches=len(p['patches']),
        spare_bytes=p['packing']['spare_bytes'],report=str(out))))

if __name__=='__main__':main()
