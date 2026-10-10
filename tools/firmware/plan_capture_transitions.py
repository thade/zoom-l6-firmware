#!/usr/bin/env python3
"""Offline Main receive binding and transition executor; JSON only, no image."""
import json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from capture_jump_patches import ROOT,BIAS,symbols
from build_deployment_probe import SOURCE
from build_added_code_probe import branch
from plan_capture_composed import plan as composed_plan
ELF=ROOT/'src/capture/capture-only-transitions.elf'
RECEIVERS=((0x8002c258,'f4f71afa'),(0x8002c39c,'f4f778f9'),
           (0x8002c3d4,'f4f75cf9'),(0x8002c408,'f4f742f9'),(0x8002c440,'f4f726f9'))

def receive_patch(stock,site,original,target,*,code_interval=(0x800b6b00,0x801f5400),
                  original_callee=0x80020690,adapter='storage_main_receive'):
    if not target&1 or not code_interval[0]<=target<code_interval[1]:
        raise ValueError('Main receive target must be candidate Thumb code')
    old=bytes.fromhex(original)
    if stock[site-BIAS:site-BIAS+4]!=old:raise ValueError('Main receive bytes differ')
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    before=list(md.disasm(old,site))
    if len(before)!=1 or before[0].mnemonic!='bl' or int(before[0].op_str[1:],0)!=original_callee:
        raise ValueError('Main site must call the expected original callee')
    first,second=struct.unpack('<2H',branch(site,target&~1))
    patch=struct.pack('<2H',first,second|0x4000) # BL uses B.W's signed displacement.
    after=list(md.disasm(patch,site))
    if len(after)!=1 or after[0].mnemonic!='bl' or int(after[0].op_str[1:],0)!=(target&~1):
        raise ValueError('Main BL encoding failed independent decode')
    return dict(site=site,original=old.hex(),patch=patch.hex(),bytes=4,
        adapter=adapter,target=target,resume=site+4,original_callee=original_callee)

def plan():
    p=composed_plan(ELF,0x809600e8,9887)
    stock=SOURCE.read_bytes();target=symbols(ELF)['storage_main_receive']
    p['patches'] += [receive_patch(stock,site,old,target) for site,old in RECEIVERS]
    ordered=sorted(p['patches'],key=lambda x:x['site'])
    if any(a['site']+len(bytes.fromhex(a['patch']))>b['site'] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('Main receive patches overlap an existing patch')
    p.update(status='offline_Main_transition_binding_not_deployable',
        storage_gate='one generation; close optional storage and retain all control objects until reboot',
        transition_executor='five Main receive calls retain request on original stack; one-tick yield while closing',
        native_transition_entries=[0x8000c220,0x8000c288,0x8000c2d8,0x80009b18,0x80009a40],
        limitations=p['limitations']+[
            'Stock callees cannot be replaced with this API: their callers ignore busy and resume effects',
            'Five Main receiver sites are bound offline; exhaustive event/indirect ingress and filesystem lock dependencies remain to qualify',
            'Main waits indefinitely on uncertain cleanup; no queue bypass, timeout into transition or memory reclamation',
            'Mount/directory admission, physical source joining and cache ownership remain unbound',
            'Retirement authorizes only optional capture exclusion, not successful native setup or hardware idle'])
    return p
def main():
    p=plan();out=ROOT/'analysis/capture_transition_plan.json'
    out.write_text(json.dumps(p,indent=2)+'\n')
    print(json.dumps(dict(status=p['status'],spare_bytes=p['packing']['spare_bytes'],report=str(out))))
if __name__=='__main__':main()
