#!/usr/bin/env python3
"""Alternative startup packing budget. JSON only; never build an update image.

Requires optional host dependency lz4==4.4.5. The existing capture planners and
all device builds continue using the stock decoder. This experiment keeps the
original MAIN length but needs its own startup/cache/device qualification.
"""
import hashlib,json,struct
from elftools.elf.elffile import ELFFile
import lz4.block
from build_deployment_probe import SOURCE,STOCK_SHA,validate
from build_lz4_loader_fixture import compiled
from capture_jump_patches import ROOT,BIAS,SCATTER,plan as jump_plan
from plan_capture_packing import align4,TABLE_END_LITERAL,TABLE_END,TABLE_LIMIT,TABLE_TAIL,ZERO
ELF=ROOT/'src/capture/capture-only-transitions.elf'

def packing(elf_path=ELF,*,source_reuse=False,dsp_hooks=True):
    stock=SOURCE.read_bytes();assert hashlib.sha256(stock).hexdigest()==STOCK_SHA;validate(stock)
    loader,names=compiled(source_reuse=source_reuse);jumps=jump_plan(elf_path,source_reuse=source_reuse)
    source,destination,length,_=SCATTER
    assert source<=names['scatter_lz4']&~1<source+len(loader)
    assert TABLE_END+32<=TABLE_LIMIT
    assert struct.unpack_from('<I',stock,TABLE_END_LITERAL-BIAS)[0]==TABLE_END
    assert stock[TABLE_END-BIAS:TABLE_LIMIT-BIAS]==bytes(TABLE_LIMIT-TABLE_END)
    dsp=bytearray(stock[source-BIAS:source-BIAS+length])
    for p in jumps['patches'] if dsp_hooks else ():
        at=p['site']-destination;dsp[at:at+p['bytes']]=bytes.fromhex(p['patch'])
    dsp=bytes(dsp)
    with elf_path.open('rb') as f:
        elf=ELFFile(f);segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD' and s['p_filesz']]
        assert len(segments)==1 and segments[0]['p_vaddr']==jumps['candidate_code_start']
        code=segments[0].data()
    payloads=[]
    for data in (dsp,code):
        packed=lz4.block.compress(data,mode='high_compression',compression=12,store_size=False)
        assert lz4.block.decompress(packed,uncompressed_size=len(data))==data
        payloads.append(struct.pack('<I',len(packed))+packed)
    if source_reuse:
        from capture_source_reuse_layout import CODE_START
        assert source+len(loader)<=CODE_START
        dsp_source=CODE_START
    else:dsp_source=align4(source+len(loader))
    code_source=align4(dsp_source+len(payloads[0]))
    end=code_source+len(payloads[1])
    if end>source+length:raise ValueError('LZ4 loader and blocks exceed original MAIN source envelope')
    blob=bytearray(b'\xff'*length)
    for address,data in ((source,loader),(dsp_source,payloads[0]),(code_source,payloads[1])):
        blob[address-source:address-source+len(data)]=data
    def record(src,dst,n,helper):return struct.pack('<4I',src,dst,n,helper&~1)
    globals_record=record(0,jumps['globals_start'],jumps['globals_end']-jumps['globals_start'],ZERO)
    code_record=record(code_source,jumps['candidate_code_start'],len(code),names['scatter_lz4'])
    dsp_record=record(dsp_source,destination,length,names['scatter_lz4'])
    old=stock[TABLE_TAIL-BIAS:TABLE_END-BIAS]+bytes(32)
    if source_reuse:
        # The code/global destinations overlap only the DSP input, which the
        # first record consumes completely before either write is possible.
        assert dsp_source==jumps['candidate_code_start']
        assert jumps['candidate_load_end']<=jumps['globals_start']
        assert jumps['globals_end']<=code_source
        prefix=dsp_record+code_record+globals_record
    else:prefix=globals_record+code_record+dsp_record
    new=prefix+stock[TABLE_TAIL+16-BIAS:TABLE_END-BIAS]
    assert len(old)==len(new)==96
    edits=[dict(address=TABLE_END_LITERAL,old=struct.pack('<I',TABLE_END).hex(),new=struct.pack('<I',TABLE_END+32).hex()),
           dict(address=TABLE_TAIL,old=old.hex(),new=new.hex())]
    return dict(stock=stock,loader=loader,names=names,jumps=jumps,dsp=dsp,code=code,
                source_blob=bytes(blob),dsp_source=dsp_source,code_source=code_source,
                packed_dsp=payloads[0],packed_code=payloads[1],end=end,edits=edits,
                source_reuse=source_reuse,dsp_hooks=dsp_hooks)

def report(p):
    return dict(status='offline_alternative_loader_not_deployable',firmware_sha256=STOCK_SHA,
        capture_elf_sha256=p['jumps']['placement_elf_sha256'],loader_bytes=len(p['loader']),
        source_reuse=p.get('source_reuse',False),
        loader_sha256=hashlib.sha256(p['loader']).hexdigest(),loader_entry=p['names']['scatter_lz4'],
        dsp_compressed_bytes=len(p['packed_dsp'])-4,capture_compressed_bytes=len(p['packed_code'])-4,
        size_prefix_bytes=8,spare_bytes=SCATTER[0]+SCATTER[2]-p['end'],
        source_span=[SCATTER[0],SCATTER[0]+SCATTER[2]],metadata_edits=p['edits'],
        unchanged=['MAIN length and container descriptors','All original scatter destinations and lengths',
                   'Original payloads except the two already-planned capture DSP hooks'],
        limitations=['Independent packing experiment; no default planner or device build selects this decoder.',
            'No firmware image, checksum update, staging, device or bootloader operation.',
            'Original-startup and malformed-block checks are in verify_lz4_packing.py; packing alone is not verification.',
            'Executing a new helper from this loaded source span needs its own hardware/cache/startup qualification.',
            'Space savings do not establish memory ownership, SD completion, final feature fit or capture feasibility.'])

if __name__=='__main__':
    p=packing();r=report(p);out=ROOT/'analysis/capture_lz4_plan.json'
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(loader_bytes=r['loader_bytes'],spare_bytes=r['spare_bytes'],report=str(out))))
