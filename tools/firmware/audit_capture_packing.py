#!/usr/bin/env python3
"""Bounded references to the proposed table padding and packed source span.

Decode every halfword in stock MAIN's code/data prefix and copied DSP. Search
initialized bytes too. Indirect/derived consumers and the bootloader are not
proved absent. Nothing is edited and no firmware image is created.
"""
import hashlib,json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from capstone.arm import ARM_OP_IMM,ARM_OP_MEM,ARM_REG_PC
from build_deployment_probe import SOURCE,STOCK_SHA
from capture_jump_patches import ROOT,BIAS,SCATTER
from plan_capture_packing import TABLE_END,TABLE_END_LITERAL,TABLE_LIMIT,DECOMPRESS,ZERO
from scatter_codec import expand

INTERVALS=((TABLE_END,TABLE_END+32),(SCATTER[0],SCATTER[0]+SCATTER[2]))
# Raw four-byte values can coincide with Thumb instruction bytes. These sites
# were inspected as complete instructions; report that context rather than
# silently discard the raw candidates.
INSTRUCTION_CONTEXT={0x80024b43:0x80024b42,0x80024b87:0x80024b86,
    0x8004712a:0x8004712a,0x8004a3d5:0x8004a3d4,0x80067ffb:0x80067ffa,
    0x8006802f:0x8006802e,0x80068041:0x80068040,0x8006805d:0x8006805c,
    0x800680c3:0x800680c2,0x80068107:0x80068106,0x8006811f:0x8006811e,
    0x80068928:0x80068928,0x80068934:0x80068934}
REFERENCE_CONTEXT={0x8001f15c:0x8001f15a,0x8001f182:0x8001f180,
    0x8001f26a:0x8001f268,0x8001f46e:0x8001f46c,0x80023d42:0x80023d40,
    0x80023e88:0x80023e86,0x80023e92:0x80023e90,0x800343ba:0x800343b8}
DATA_CONTEXT={0x800a0b50:0x8005f351,0x800a1e2c:0x8002f211}

def inside(address):return any(a<=address<b for a,b in INTERVALS)
def overlap(address,size):return any(address<b and address+size>a for a,b in INTERVALS)

def audit():
    stock=SOURCE.read_bytes();assert hashlib.sha256(stock).hexdigest()==STOCK_SHA
    main=(0x80001000,stock[0x200:0xb5ce4]);initialized=[]
    for table in range(0x800a68dc,0x800a695c,16):
        source,dest,length,helper=struct.unpack_from('<4I',stock,table-BIAS)
        if helper==DECOMPRESS:data=expand(stock[source-BIAS:],length)[0]
        elif helper==0x80079498:data=stock[source-BIAS:source-BIAS+length]
        elif helper==ZERO:continue
        else:raise ValueError('unknown stock initializer')
        initialized.append((dest,data))
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.detail=True
    raw=[]
    known={TABLE_END_LITERAL:'original scatter table end literal',
           0x800a691c:'DSP copy source field',
           0x800a694c:'ignored source field of stock zero record'}
    for base,data in [main,*initialized]:
        for offset in range(len(data)-3):
            value=struct.unpack_from('<I',data,offset)[0]
            if not inside(value&~1):continue
            address=base+offset;row=dict(address=address,value=value)
            if address in known:row['context']=known[address]
            elif address in INSTRUCTION_CONTEXT:
                start=INSTRUCTION_CONTEXT[address]
                ins=next(md.disasm(stock[start-BIAS:start-BIAS+4],start,count=1))
                row.update(context='raw bytes overlap inspected instruction',
                           instruction_address=start,instruction=f'{ins.mnemonic} {ins.op_str}')
            else:row['context']='unresolved raw value'
            raw.append(row)
    references=[];split=[];decoded=0
    code_prefix=(main[0],main[1][:0x800a68dc-main[0]])
    ram_code=next(r for r in initialized if r[0]==SCATTER[1])
    for base,data in (code_prefix,ram_code):
        for offset in range(0,len(data)-1,2):
            ins=next(md.disasm(data[offset:offset+4],base+offset,count=1),None)
            if ins is None:continue
            decoded+=1
            for op in ins.operands:
                if op.type==ARM_OP_IMM and inside(op.imm&0xffffffff):
                    references.append(dict(address=ins.address,instruction=f'{ins.mnemonic} {ins.op_str}',kind='immediate'))
                if op.type==ARM_OP_MEM and op.mem.base==ARM_REG_PC:
                    address=((ins.address+4)&~3)+op.mem.disp
                    if overlap(address,16):
                        references.append(dict(address=ins.address,target=address,
                            instruction=f'{ins.mnemonic} {ins.op_str}',kind='PC-relative memory'))
            if ins.mnemonic!='movw':continue
            reg,low=ins.operands[0].reg,ins.operands[1].imm
            for later in md.disasm(data[offset+ins.size:offset+ins.size+32],ins.address+ins.size):
                if later.mnemonic=='movt' and later.operands[0].reg==reg:
                    value=(later.operands[1].imm<<16)|low
                    if inside(value):split.append(dict(address=ins.address,high_address=later.address,value=value))
                    break
    for row in references:
        address=row['address']
        if address in REFERENCE_CONTEXT:
            start=REFERENCE_CONTEXT[address]
            ins=next(md.disasm(stock[start-BIAS:start-BIAS+4],start,count=1))
            assert ins.size==4 and address==start+2
            row.update(context='candidate begins at second halfword of inspected instruction',
                       actual_address=start,actual_instruction=f'{ins.mnemonic} {ins.op_str}')
        elif address in DATA_CONTEXT:
            value=struct.unpack_from('<I',stock,address-BIAS)[0]
            assert value==DATA_CONTEXT[address] and not inside(value)
            row.update(context='data table word decoded as an instruction',stored_value=value)
        else:row['context']='unresolved decoded candidate'
    return dict(status='bounded_audit_not_ownership_approval',firmware_sha256=STOCK_SHA,
        intervals=[list(r) for r in INTERVALS],halfword_decodes=decoded,
        raw_candidates=raw,unresolved_raw_candidates=[r for r in raw if r['context']=='unresolved raw value'],
        decoded_reference_candidates=references,bounded_movw_movt_candidates=split,
        unresolved_decoded_candidates=[r for r in references if r['context']=='unresolved decoded candidate'],
        scanned_initialized_regions=[dict(start=b,bytes=len(d)) for b,d in initialized],
        limits=['MAIN prefix includes mixed code/data; every-halfword decoding can produce false candidates',
            'Only bounded immediate, PC-relative and 32-byte MOVW/MOVT constructions are examined',
            'Instruction context does not prove bytes cannot be read as data by an indirect consumer',
            'Calculated pointers, broader control flow, aliases, interrupts, DMA and bootloader consumers remain unproved',
            'No firmware image, checksum, source modification or device access'])

def main():
    r=audit();out=ROOT/'analysis/capture_packing_reference_audit.json'
    out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],halfword_decodes=r['halfword_decodes'],
        raw_candidates=len(r['raw_candidates']),unresolved_raw_candidates=len(r['unresolved_raw_candidates']),
        decoded_reference_candidates=len(r['decoded_reference_candidates']),
        unresolved_decoded_candidates=len(r['unresolved_decoded_candidates']),
        bounded_movw_movt_candidates=len(r['bounded_movw_movt_candidates']),report=str(out))))

if __name__=='__main__':main()
