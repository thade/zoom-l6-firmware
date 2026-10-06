#!/usr/bin/env python3
"""Bounded UI-mutex and SD-event dependency inventory; no firmware changes."""
import hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
ROOT=Path(__file__).resolve().parents[2]
BIAS=0x80000e00
SHA='64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
UI_SLOT=0x80446810
TARGETS={'UI_cleanup':0x80020360,'UI_flush':0x80020438,'UI_delete':0x80020548,
         'UI_sender':0x8006e4b8,'SD_dispatch':0x80068378,
         'SD_event_wait':0x800328c0,'SD_event_post':0x80032828}

def inventory(targets=None):
    targets=TARGETS if targets is None else targets
    data=(ROOT/'Reference/L6_v1.10_E/L6.BIN').read_bytes()
    assert hashlib.sha256(data).hexdigest()==SHA
    source,dest,length,helper=struct.unpack_from('<4I',data,0x800a691c-BIAS)
    assert (source,dest,length,helper)==(0x800a9408,0x20220000,0xd6dc,0x80079498)
    regions=[('main_flash',0x80001000,data[0x200:0x800a1bd4-BIAS]),
             ('copied_ram',dest,data[source-BIAS:source-BIAS+length])]
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.detail=True;md.skipdata=True
    users=[];refs={k:[] for k in targets};reverse={a:k for k,a in targets.items()}
    for region,start,blob in regions:
        pending={}
        for ins in md.disasm(blob,start):
            if ins.mnemonic in ('bl','b','b.w') and ins.op_str.startswith('#'):
                target=int(ins.op_str[1:],16)
                if target in reverse:refs[reverse[target]].append(hex(ins.address))
            if ins.mnemonic=='movw' and len(ins.operands)==2:
                pending[ins.operands[0].reg]=(ins.address,ins.operands[1].imm)
            elif ins.mnemonic=='movt' and len(ins.operands)==2:
                reg=ins.operands[0].reg
                if reg in pending:
                    lo,value=pending.pop(reg)
                    if ins.address-lo<40 and value | (ins.operands[1].imm<<16)==UI_SLOT:
                        users.append(dict(region=region,movw=hex(lo),movt=hex(ins.address),register=ins.reg_name(reg)))
            elif ins.id:
                # Invalidate a saved low half on intervening register writes.
                _,writes=ins.regs_access()
                for reg in writes:pending.pop(reg,None)
    return dict(firmware_sha256=SHA,UI_mutex_slot=hex(UI_SLOT),constant_formations=users,
        targets={name:dict(entry=hex(addr),direct_references=refs[name]) for name,addr in targets.items()},
        limitations=['Linear Thumb disassembly and adjacent MOVW/MOVT tracking, not an exhaustive caller graph.',
                     'Other address construction, indirect callbacks, compressed driver dispatch and MMIO meanings are not resolved here.',
                     'The SD driver callback table is separately recovered/executed in the dependency tests.',
                     'No device hook, readiness decision, firmware image or physical DMA claim.'])
if __name__=='__main__':
    report=inventory();out=ROOT/'analysis/handoff_dependencies_inventory.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(UI_constant_formations=len(report['constant_formations']),
        direct_references=sum(len(v['direct_references']) for v in report['targets'].values()),report=str(out)),indent=2))
