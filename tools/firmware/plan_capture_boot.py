#!/usr/bin/env python3
"""Concrete logical cold-start observations, JSON only; no admission or image."""
import json
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from capture_jump_patches import ROOT,BIAS,symbols
from build_deployment_probe import SOURCE
from capture_source_reuse_layout import CODE_INTERVAL
from plan_capture_source_reuse import plan as reuse_plan
from plan_capture_hooks import make_patch
from plan_capture_transitions import receive_patch

ELF=ROOT/'src/capture/capture-only-boot-witness.elf'
SPECS=tuple(dict(site=a,original=b,adapter=n,resume=a+len(bytes.fromhex(b))) for a,b,n in (
    (0x80009ab4,'fcf744fb','storage_boot_mount_hook'),
    (0x8003b87a,'c6e90154','storage_boot_request_hook'),
    (0x80045d5e,'d8e9014bc8e901aa','storage_boot_consume_hook'),
    (0x80046cc4,'d8f80c00','storage_boot_ack_hook')))
CALLS=((0x8002c1f0,'ddf726fc',0x80009a40,'storage_boot_card'),
       (0x8002c344,'dff76cff',0x8000c220,'storage_boot_usb'))

def plan(pack=None,*,elf_path=ELF):
    p=reuse_plan(pack,elf_path=elf_path);stock=SOURCE.read_bytes();n=symbols(elf_path)
    added=[make_patch(stock,s,n[s['adapter']],code_interval=CODE_INTERVAL) for s in SPECS]
    added += [receive_patch(stock,a,b,n[name],code_interval=CODE_INTERVAL,
                           original_callee=callee,adapter=name) for a,b,callee,name in CALLS]
    p['patches']+=added
    ordered=sorted(p['patches'],key=lambda q:q['site'])
    assert all(a['site']+len(bytes.fromhex(a['patch']))<=b['site'] for a,b in zip(ordered,ordered[1:]))
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True
    for a,size,mn,op in md.disasm_lite(stock[0x200:0xb5ce4],0x80001000):
        if mn.startswith('b') or mn in ('cbz','cbnz'):
            try:target=int(op.rsplit('#',1)[1],0)
            except (IndexError,ValueError):continue
            assert not any(s['site']<target<s['resume'] for s in added),(hex(a),hex(target))
    p.update(status='offline_logical_boot_witness_not_physical_admission',
        boot_patches=added,boot_state_bytes=12,
        limitations=p['limitations']+[
            'The first normal Main card/directory and matched audio-only USB request/consume/ACK are observed, without waiting or changing native calls.',
            'A stale ACK, missing witness, prior SD mode or later Main storage transition irreversibly revokes readiness.',
            'Logical readiness does not admit a lease, bind physical source/cache ports, release a worker or authorize an extra file.',
            'The complete bootstrap and hardware memory/IRQ/task timing remain unqualified.'])
    return p

if __name__=='__main__':
    p=plan();out=ROOT/'analysis/capture_boot_plan.json';out.write_text(json.dumps(p,indent=2)+'\n')
    print(json.dumps(dict(raw_code_bytes=p['raw_code_bytes'],globals_bytes=p['globals_bytes'],
        spare_bytes=p['packing']['spare_bytes'],report=str(out))))
