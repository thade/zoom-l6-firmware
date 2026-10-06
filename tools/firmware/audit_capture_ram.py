#!/usr/bin/env python3
"""Bounded stock RAM evidence; raw candidates are retained, not ownership proof."""
import hashlib,json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from build_deployment_probe import SOURCE,STOCK_SHA
from capture_jump_patches import ROOT,BIAS,SCATTER
from plan_capture_packing import DECOMPRESS,ZERO
from scatter_codec import expand

GAP=(0x80960078,0x80bb9400)
STARTUP_OBJECTS=((0x80960080,0x809600e0),(0x80961d80,0x80962660))
HEAP=(0x808e2fe0,0x8095ffd8)

def inside(v,intervals):return any(a<=v<b for a,b in intervals)
def audit():
    stock=SOURCE.read_bytes();assert hashlib.sha256(stock).hexdigest()==STOCK_SHA
    initialized=[];scatter=[]
    for table in range(0x800a68dc,0x800a695c,16):
        source,dest,length,helper=struct.unpack_from('<4I',stock,table-BIAS)
        assert dest+length<=GAP[0] or dest>=GAP[1]
        scatter.append(dict(table=table,destination=dest,bytes=length,helper=helper))
        if helper==ZERO:continue
        data=expand(stock[source-BIAS:],length)[0] if helper==DECOMPRESS else stock[source-BIAS:source-BIAS+length]
        assert helper in (DECOMPRESS,0x80079498)
        initialized.append((dest,data))
    assert HEAP[1]<=GAP[0]
    main=(0x80001000,stock[0x200:0xb5ce4]);raw=[];regions=[]
    for base,data in [main,*initialized]:
        found=[]
        for off in range(len(data)-3):
            value=struct.unpack_from('<I',data,off)[0]
            if inside(value&~1,[GAP]):found.append(dict(address=base+off,value=value,
                within_startup_objects=inside(value&~1,STARTUP_OBJECTS)))
        raw.extend(found);regions.append(dict(start=base,bytes=len(data),raw_candidates=len(found)))
    # Every halfword, not a claimed code map. Pair only same-register MOVW/
    # MOVT within 32 subsequent bytes, retaining the bounded-scan limitation.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.detail=True
    pairs=[];decoded=0
    code=[(main[0],main[1][:0x800a68dc-main[0]]),next(r for r in initialized if r[0]==SCATTER[1])]
    for base,data in code:
        for off in range(0,len(data)-1,2):
            ins=next(md.disasm(data[off:off+4],base+off,count=1),None)
            if ins is None:continue
            decoded+=1
            if ins.mnemonic!='movw':continue
            reg,low=ins.operands[0].reg,ins.operands[1].imm
            for later in md.disasm(data[off+ins.size:off+ins.size+32],ins.address+ins.size):
                if later.mnemonic=='movt' and later.operands[0].reg==reg:
                    value=(later.operands[1].imm<<16)|low
                    if inside(value,[GAP]):pairs.append(dict(address=ins.address,high_address=later.address,value=value))
                    break
    return dict(status='physical_ownership_unresolved',firmware_sha256=STOCK_SHA,
        candidate_interval=list(GAP),startup_objects=[list(r) for r in STARTUP_OBJECTS],
        stock_scatter=scatter,bounded_stock_heap=list(HEAP),scanned_regions=regions,
        raw_candidates=raw,startup_object_raw_candidates=[r for r in raw if r['within_startup_objects']],
        halfword_decodes=decoded,bounded_movw_movt_candidates=pairs,
        interpretation='Scatter and this heap exclude the gap. Raw matches include mixed code/data and instruction byte overlaps; they remain candidates.',
        limitations=['No raw match is assumed to be a live pointer or dismissed as harmless',
            'No complete instruction/data map, pointer-flow analysis or indirect/derived address exclusion',
            'MOVW/MOVT scan does not trace register changes, wider constructions or runtime addresses',
            'Other allocators, aliases, bootloader, interrupt, DMA/cache and physical extent remain unresolved',
            'No live heap headroom, later stock allocation reserve or device RAM approval',
            'No firmware edits, image creation or device access'])

def main():
    r=audit();out=ROOT/'analysis/capture_ram_audit.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],raw_candidates=len(r['raw_candidates']),
        startup_object_raw_candidates=len(r['startup_object_raw_candidates']),
        bounded_movw_movt_candidates=len(r['bounded_movw_movt_candidates']),report=str(out))))

if __name__=='__main__':main()
