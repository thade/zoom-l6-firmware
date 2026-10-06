#!/usr/bin/env python3
"""Plan two compressed blocks inside stock MAIN length; JSON only, no image.

Original RAM-code source becomes two packed streams. Existing stock scatter
helpers expand both; two extra records fit in the table's zero padding. This
still requires reference/ownership, startup and hardware verification.
"""
import hashlib,json,struct
from elftools.elf.elffile import ELFFile
from build_deployment_probe import SOURCE,STOCK_SHA,validate
from capture_jump_patches import ROOT,ELF,BIAS,SCATTER,plan as jump_plan
from scatter_codec import compress,expand

TABLE_END_LITERAL=0x80001990
TABLE_END=0x800a695c
TABLE_LIMIT=0x800a6980
TABLE_TAIL=0x800a691c
DECOMPRESS=0x80001994
ZERO=0x800794a8

def align4(n):return (n+3)&~3

def packing(elf_path=ELF):
    stock=SOURCE.read_bytes();assert hashlib.sha256(stock).hexdigest()==STOCK_SHA;validate(stock)
    jumps=jump_plan(elf_path);source,dest,length,_=SCATTER
    assert source+length==jumps['original_loaded_end']
    assert struct.unpack_from('<I',stock,TABLE_END_LITERAL-BIAS)[0]==TABLE_END
    assert stock[TABLE_END-BIAS:TABLE_LIMIT-BIAS]==bytes(TABLE_LIMIT-TABLE_END)
    dsp=bytearray(stock[source-BIAS:source-BIAS+length])
    for p in jumps['patches']:
        off=p['site']-dest;dsp[off:off+p['bytes']]=bytes.fromhex(p['patch'])
    with elf_path.open('rb') as f:
        e=ELFFile(f)
        code_segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD' and s['p_filesz']]
        assert len(code_segments)==1
        seg=code_segments[0];code=seg.data();assert seg['p_vaddr']==jumps['candidate_code_start']
        assert len(code)==jumps['candidate_load_end']-jumps['candidate_code_start']
        assert all(not s['p_filesz'] for s in e.iter_segments()
                   if s['p_type']=='PT_LOAD' and s['p_vaddr']==jumps['globals_start'])
    dsp=bytes(dsp);packed_dsp=compress(dsp);packed_code=compress(code)
    assert expand(packed_dsp,len(dsp))==(dsp,len(packed_dsp))
    assert expand(packed_code,len(code))==(code,len(packed_code))
    code_source=align4(source+len(packed_dsp));packed_end=code_source+len(packed_code)
    if packed_end>source+length:raise ValueError('packed streams exceed the existing loaded source span')
    assert TABLE_END+32<=TABLE_LIMIT
    globals_record=struct.pack('<4I',0,jumps['globals_start'],jumps['globals_end']-jumps['globals_start'],ZERO)
    code_record=struct.pack('<4I',code_source,jumps['candidate_code_start'],len(code),DECOMPRESS)
    dsp_record=struct.pack('<4I',source,dest,length,DECOMPRESS)
    # Make code and zeroed globals available before the patched DSP is exposed.
    # Keep the first four records and the three remaining stock zeros in order.
    old_tail=stock[TABLE_TAIL-BIAS:TABLE_END-BIAS]+bytes(32)
    new_tail=globals_record+code_record+dsp_record+stock[TABLE_TAIL+16-BIAS:TABLE_END-BIAS]
    assert len(old_tail)==len(new_tail)==96
    edits=[dict(address=TABLE_END_LITERAL,old=struct.pack('<I',TABLE_END).hex(),
                new=struct.pack('<I',TABLE_END+32).hex(),purpose='extend application scatter table'),
           dict(address=TABLE_TAIL,old=old_tail.hex(),new=new_tail.hex(),
                purpose='zero globals, expand capture, then patched DSP, followed by original zeros')]
    return dict(stock=stock,dsp=dsp,code=code,packed_dsp=packed_dsp,packed_code=packed_code,
                code_source=code_source,packed_end=packed_end,jumps=jumps,edits=edits)

def report(p):
    source,dest,length,_=SCATTER;j=p['jumps']
    return dict(status='offline_packing_proposal_not_deployable',firmware_sha256=STOCK_SHA,
        placement_elf_sha256=j['placement_elf_sha256'],
        source_span=[source,source+length],dsp_destination=dest,
        dsp=dict(original_bytes=len(p['dsp']),packed_bytes=len(p['packed_dsp']),
                 sha256=hashlib.sha256(p['dsp']).hexdigest()),
        capture=dict(destination=j['candidate_code_start'],source=p['code_source'],
                     original_bytes=len(p['code']),packed_bytes=len(p['packed_code']),
                     sha256=hashlib.sha256(p['code']).hexdigest()),
        spare_bytes=source+length-p['packed_end'],
        table=dict(original_end=TABLE_END,candidate_end=TABLE_END+32,padding_limit=TABLE_LIMIT),
        startup_order=['four original initialized regions','zero capture globals',
                       'expand capture code','expand patched DSP','three original zero regions'],
        globals=[j['globals_start'],j['globals_end']],metadata_edits=p['edits'],
        unchanged=['MAIN payload length, descriptor and container size',
            'All eight original scatter destinations and lengths',
            'DSP output outside the two already-specified audio hook spans'],
        limitations=['Writes JSON only; no patched container, checksum, device transfer or installation',
            'Packing is an alternative to loader-length extension, not a deployed loading result',
            'Table padding and packed source consumers require reference audits; indirect uses remain uncertain',
            'Candidate destinations lack physical ownership, cache/MPU and interrupt verification',
            'Only permanent globals are initialized here; manager/worker registration and storage/native I/O joins remain unbound',
            'Small spare margin must be rechecked after every build; expansion time is not measured on hardware'])

def main():
    p=packing();r=report(p);out=ROOT/'analysis/capture_packing_plan.json'
    out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],dsp_packed_bytes=r['dsp']['packed_bytes'],
        capture_packed_bytes=r['capture']['packed_bytes'],spare_bytes=r['spare_bytes'],report=str(out))))

if __name__=='__main__':main()
