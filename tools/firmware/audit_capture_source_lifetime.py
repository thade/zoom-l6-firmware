#!/usr/bin/env python3
"""Additional bounded derived-address leads for consumed DSP source reuse.

This supplements the existing immediate/PC-relative packing audit. Mixed
code/data, indirect pointers, bootloader consumers and physical effects remain
outside this scan. No firmware image or device access.
"""
import hashlib,json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from capstone import arm as A
from audit_ram_gap_consumers import initialized,trace_window,overlaps,MAX_BYTES,MAX_INSNS
from audit_capture_packing import audit as references
from build_deployment_probe import SOURCE,STOCK_SHA
from capture_jump_patches import ROOT,SCATTER,BIAS
from scatter_codec import expand

def audit():
    stock=SOURCE.read_bytes();assert hashlib.sha256(stock).hexdigest()==STOCK_SHA
    intervals=((SCATTER[0],SCATTER[0]+SCATTER[2]),)
    old=references()
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.detail=True
    rows=[];counts=[]
    for kind,base,data in initialized(stock):
        decoded=seeds=unknown=0
        for offset in range(0,len(data)-1,2):
            instruction=next(md.disasm(data[offset:offset+4],base+offset,count=1),None)
            if instruction is None:continue
            decoded+=1;name=instruction.mnemonic.split('.')[0];ops=instruction.operands
            seed=name in ('movw','adr') or name in ('mov','movs') and len(ops)==2 and ops[1].type==A.ARM_OP_IMM
            seed|=name=='ldr' and len(ops)==2 and ops[1].type==A.ARM_OP_MEM and ops[1].mem.base==A.ARM_REG_PC
            if not seed:continue
            seeds+=1;r=trace_window(md,data,base,offset,intervals=intervals)
            unknown+=r['unknown_memory_operands']
            if r['forms'] or r['accesses']:
                rows.append(dict(region=kind,seed=base+offset,
                    seed_inside_original_DSP_source=overlaps(base+offset,1,intervals),**r))
        counts.append(dict(region=kind,start=base,bytes=len(data),decoded=decoded,seeds=seeds,
                           unknown_memory_operands=unknown))
    consumers=[];stored_regions=[]
    for table in range(0x800a68dc,0x800a695c,16):
        src,dst,n,helper=struct.unpack_from('<4I',stock,table-BIAS)
        if helper==0x800794a8:continue # Zero helper ignores source field.
        consumed=expand(stock[src-BIAS:],n)[1] if helper==0x80001994 else n
        stored_regions.append(dict(table=table,source=src,end=src+consumed,
            destination=dst,bytes=n,helper=helper))
        if overlaps(src,consumed,intervals):consumers.append(dict(table=table,source=src,destination=dst,bytes=n,helper=helper))
    assert consumers==[dict(table=0x800a691c,source=SCATTER[0],destination=SCATTER[1],bytes=SCATTER[2],helper=SCATTER[3])]
    for row in rows:
        region=next((s for s in stored_regions if s['source']<=row['seed']<s['end']),None)
        if row['region']=='main' and region and region['helper']==0x80001994:
            row.update(context='compressed scatter input decoded as Thumb instructions',stored_region=region)
        elif row['region']=='main' and region and region['destination']==SCATTER[1]:
            row.update(context='stored DSP copy decoded at source instead of its linked execution address',stored_region=region)
        else:row['context']='unresolved derived lead'
    return dict(status='bounded_source_lifetime_evidence_not_exhaustive_proof',firmware_sha256=STOCK_SHA,
        original_source_interval=intervals[0],original_copy_consumer=consumers,
        existing_reference_audit=old,trace_bounds=dict(bytes=MAX_BYTES,instructions=MAX_INSNS),
        scanned_regions=counts,derived_leads=rows,
        unresolved_derived_leads=[r for r in rows if r['context']=='unresolved derived lead'],
        limits=['Mixed code/data and seeds inside conditional contexts may produce false leads; none is automatically dismissed.',
            'Constant arithmetic is bounded and stops at control flow; mutable inputs, unmodeled instructions and indirect consumers remain unresolved.',
            'The source copy finishing is necessary but cannot alone rule out a later consumer or scatter reentry.',
            'Stored-input classification explains these instruction decodes; it does not prove absence of indirect execution or later data reads.',
            'No physical alias, cache, bootloader, firmware-installation or source-permission claim.'])

if __name__=='__main__':
    r=audit();out=ROOT/'analysis/capture_source_lifetime_audit.json'
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(derived_leads=len(r['derived_leads']),
        unresolved_raw=len(r['existing_reference_audit']['unresolved_raw_candidates']),
        unresolved_decoded=len(r['existing_reference_audit']['unresolved_decoded_candidates']),
        unresolved_derived=len(r['unresolved_derived_leads']),
        report=str(out))))
