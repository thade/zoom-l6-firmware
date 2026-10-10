#!/usr/bin/env python3
"""Bounded stock-image capacity evidence; no device access or ownership claim."""
import hashlib,json,re,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from build_deployment_probe import SOURCE,STOCK_SHA
from build_health_probe import ROOT,BIAS
from scatter_codec import expand

SEMC=(0x402f0000,0x402f0140)

def audit():
    data=SOURCE.read_bytes();assert hashlib.sha256(data).hexdigest()==STOCK_SHA
    main_len=struct.unpack_from('<I',data,0x2851f8)[0]
    regions=[('main',0x80001000,data[0x200:0x200+main_len])];scatter=[]
    for address in range(0x800a68dc,0x800a695c,16):
        src,dst,n,fn=struct.unpack_from('<4I',data,address-BIAS)
        row=dict(table=hex(address),source=hex(src),destination=hex(dst),bytes=n,
                 end=hex(dst+n),helper=hex(fn));scatter.append(row)
        if fn&~1==0x80001994:
            content,used=expand(data[src-BIAS:],n);row['compressed_source_bytes']=used
            regions.append(('scatter_decompressed',dst,content))
        elif fn&~1==0x80079498:
            regions.append(('scatter_copied',dst,data[src-BIAS:src-BIAS+n]))
        else:assert fn&~1==0x800794a8
    raw=[];pairs=[];decoded=movw=0
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.detail=True
    for name,base,content in regions:
        for off in range(len(content)-3):
            value=struct.unpack_from('<I',content,off)[0]
            if SEMC[0]<=value<SEMC[1]:raw.append(dict(region=name,address=hex(base+off),
                offset=off,value=hex(value),aligned=off%4==0))
        # Every halfword is a candidate, not a recovered code map. Keeping
        # intervening clobbers makes matches leads rather than proven pointers.
        for off in range(0,len(content)-1,2):
            ins=next(md.disasm(content[off:off+4],base+off,count=1),None)
            if ins is None:continue
            decoded+=1
            if ins.mnemonic!='movw' or len(ins.operands)!=2:continue
            movw+=1;reg=ins.operands[0].reg;low=ins.operands[1].imm
            for later in md.disasm(content[off+ins.size:off+ins.size+32],ins.address+ins.size):
                if later.mnemonic=='movt' and later.operands[0].reg==reg:
                    value=(later.operands[1].imm<<16)|low
                    if SEMC[0]<=value<SEMC[1]:pairs.append(dict(region=name,
                        movw=hex(ins.address),movt=hex(later.address),value=hex(value)))
                    break
    highest=max(int(r['end'],16) for r in scatter if 0x80000000<=int(r['destination'],16)<0x82000000)
    return dict(status='physical_capacity_unconfirmed',firmware_sha256=STOCK_SHA,
        boot_descriptor_offset=struct.unpack_from('<I',data,0x6c)[0],
        boot_descriptor_bytes=struct.unpack_from('<I',data,0x70)[0],
        main_runtime_range=[hex(0x80001000),hex(0x80001000+main_len)],scatter=scatter,
        scanned_initialized_regions=[dict(kind=k,start=hex(a),bytes=len(c)) for k,a,c in regions],
        semc_register_interval=[hex(a) for a in SEMC],raw_semc_register_candidates=raw,
        bounded_movw_movt_semc_candidates=pairs,halfword_decodes=decoded,movw_candidates=movw,
        external_highest_scatter_end=hex(highest),external_address_extent_bytes=highest-0x80000000,
        mpu_region_bytes=32*1024*1024,possible_32MiB_end_gap_bytes=0x82000000-highest,
        apparent_scatter_gap=dict(start=hex(0x80960078),end=hex(0x80bb9400),bytes=0x80bb9400-0x80960078),
        limitations=[
         'Initialized byte scan and bounded MOVW/MOVT pairs only; mixed code/data is not a complete flow graph',
         'Indirect/derived addresses, wider constructions, other boot images and controller state are not resolved',
         'MPU size is from the separately verified stock MPU setup, not SEMC or physical detection',
         'Stock destination extent and gaps describe software intent, not physical capacity or ownership',
         'No device commands, memory writes, firmware image changes or deployment'])

def headers():
    names=('SEMC_BASE','SEMC_BR_VLD_MASK','SEMC_BR_MS_MASK','SEMC_BR_MS_SHIFT','SEMC_BR_BA_MASK',
        'SEMC_SDRAMCR0_PS_MASK','SEMC_SDRAMCR0_COL8_MASK','SEMC_SDRAMCR0_COL_MASK',
        'SEMC_SDRAMCR0_COL_SHIFT','SEMC_SDRAMCR0_BANK2_MASK','SEMC_SDRAMCR3_REN_MASK',
        'IOMUXC_GPR_BASE','IOMUXC_GPR_GPR16_FLEXRAM_BANK_CFG_SEL_MASK','USB_ANALOG_BASE')
    rows={}
    for chip in ('MIMXRT1041','MIMXRT1042','MIMXRT1062'):
        path=ROOT/'Reference/chipset_headers'/(chip+'.h');content=path.read_text();values={}
        for name in names:
            m=re.search(r'^#define\s+'+name+r'\s+\(?(0x[0-9a-fA-F]+|\d+)[Uu]?\)?',content,re.M)
            assert m,(chip,name);values[name]=int(m[1],0)
        rows[chip]=dict(header_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),values=values)
    assert rows['MIMXRT1041']['values']==rows['MIMXRT1042']['values']==rows['MIMXRT1062']['values']
    return dict(agrees=True,headers=rows,limitation='Agreement of selected fields does not identify fitted silicon')

def main():
    out=ROOT/'analysis';out.mkdir(exist_ok=True)
    r=audit();h=headers()
    (out/'physical_ram_capacity_audit.json').write_text(json.dumps(r,indent=2)+'\n')
    (out/'memory_capacity_header_comparison.json').write_text(json.dumps(h,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],raw_semc_candidates=len(r['raw_semc_register_candidates']),
        bounded_semc_pairs=len(r['bounded_movw_movt_semc_candidates']),
        external_address_extent_bytes=r['external_address_extent_bytes'],selected_headers_agree=h['agrees'])))
if __name__=='__main__':main()
