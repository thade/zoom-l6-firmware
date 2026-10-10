#!/usr/bin/env python3
"""Original scatter startup loads packed capture code inside unchanged MAIN.

All edits are emulator-memory edits. No image, checksum or device access.
Physical RAM, cache/interrupt behavior and storage integration remain unbound.
"""
import hashlib,itertools,json,random,struct,sys
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,BIAS,RETURN
from verify_capture_integration import IntegrationRig,record
from verify_capture_placement import PlacementRig
from verify_session_manager import STOPPED
sys.path.insert(0,str(ROOT/'tools/firmware'))
from plan_capture_packing import packing,report,DECOMPRESS,ZERO,TABLE_END
from scatter_codec import compress,expand
from audit_capture_packing import audit

PACK=packing();ELF=ROOT/'src/capture/capture-only-placement.elf'
SOURCE,DEST,LENGTH,_=0x800a9408,0x20220000,0xd6dc,0x80079498

def edit_memory(uc,pack=PACK):
    uc.mem_write(SOURCE,b'\xff'*LENGTH)
    if 'loader' in pack:
        uc.mem_write(SOURCE,pack['source_blob'])
    else:
        uc.mem_write(SOURCE,pack['packed_dsp'])
        uc.mem_write(pack['code_source'],pack['packed_code'])
    for e in pack['edits']:
        assert bytes(uc.mem_read(e['address'],len(bytes.fromhex(e['old']))))==bytes.fromhex(e['old'])
        uc.mem_write(e['address'],bytes.fromhex(e['new']))

def expand_payloads(m,pack):
    """Run the selected compiled helper, never copy decoded ELF payloads."""
    j=pack['jumps'];helper=pack['names']['scatter_lz4'] if 'loader' in pack else DECOMPRESS
    dsp_source=pack['dsp_source'] if 'loader' in pack else SOURCE
    if pack.get('source_reuse'):
        # Match the explicit scatter order; earlier zeroing/code expansion would
        # destroy DSP input which is still needed by its original destination.
        for args in ((dsp_source,DEST,LENGTH),
                     (pack['code_source'],j['candidate_code_start'],len(pack['code']))):
            assert m.invoke(helper,list(args))==0
        m.invoke(ZERO,[0,j['globals_start'],j['globals_end']-j['globals_start']])
        return
    m.invoke(ZERO,[0,j['globals_start'],j['globals_end']-j['globals_start']])
    for args in ((pack['code_source'],j['candidate_code_start'],len(pack['code'])),
                 (dsp_source,DEST,LENGTH)):
        assert m.invoke(helper,list(args))==0

def native_expand(packed,size):
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    u.mem_map(0x80000000,0x1000000);u.mem_write(0x80001000,IMAGE[0x200:0xb5ce4])
    u.mem_map(0x20000000,0x40000);u.mem_map(0x21000000,0x40000)
    source=0x21000010;dest=0x21020010
    assert len(packed)<0x1fff0 and size<0x1fff0
    u.mem_write(source-16,b'\x5a'*(len(packed)+32));u.mem_write(source,packed)
    u.mem_write(dest-16,b'\xa5'*(size+32));reads=[];writes=[]
    u.hook_add(UC_HOOK_MEM_READ,lambda uc,k,a,n,v,x:reads.append((a,n)),
               begin=source-16,end=source+len(packed)+15)
    u.hook_add(UC_HOOK_MEM_WRITE,lambda uc,k,a,n,v,x:writes.append((a,n)),
               begin=dest-16,end=dest+size+15)
    u.reg_write(A.UC_ARM_REG_R0,source);u.reg_write(A.UC_ARM_REG_R1,dest)
    u.reg_write(A.UC_ARM_REG_R2,size);u.reg_write(A.UC_ARM_REG_SP,0x20010000)
    u.reg_write(A.UC_ARM_REG_LR,RETURN|1)
    u.emu_start(DECOMPRESS|1,RETURN,count=5000000)
    assert u.reg_read(A.UC_ARM_REG_PC)==RETURN and u.reg_read(A.UC_ARM_REG_R0)==0
    assert all(source<=a and a+n<=source+len(packed) for a,n in reads)
    assert reads and max(a+n for a,n in reads)==source+len(packed)
    assert all(dest<=a and a+n<=dest+size for a,n in writes)
    assert sum(n for a,n in writes)==size
    assert bytes(u.mem_read(dest-16,16))==bytes(u.mem_read(dest+size,16))==b'\xa5'*16
    return bytes(u.mem_read(dest,size))

def startup(candidate,pack=PACK):
    # Execute entry and every original initializer/helper until Main entry.
    # Selective hooks leave the large stock zero/decompress loops native.
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    u.mem_map(0x80000000,0x2000000);u.mem_write(0x80000000,b'\xa5'*0x2000000)
    u.mem_map(0x20000000,0x40000);u.mem_write(0x20000000,b'\xa5'*0x40000)
    u.mem_map(0x20210000,0x20000);u.mem_write(0x20210000,b'\xa5'*0x20000)
    u.mem_map(0,0x1000);u.mem_write(0,b'\xa5'*0x1000)
    u.mem_write(0x80001000,IMAGE[0x200:0xb5ce4]) # unchanged stock length only
    if candidate:edit_memory(u,pack)
    entered=[];helpers=[]
    def main(uc,a,n,x):entered.append(a);uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,main,begin=0x80067a60,end=0x80067a60)
    def helper(uc,a,n,x):helpers.append((a,*[uc.reg_read(r) for r in
                         (A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2)]))
    for address in (DECOMPRESS,ZERO,0x80079498):
        u.hook_add(UC_HOOK_CODE,helper,begin=address,end=address)
    u.emu_start(0x80001401,0x80067a62,count=100000000)
    assert entered==[0x80067a60]
    assert u.reg_read(A.UC_ARM_REG_SP)==0x2021fff0
    assert len(helpers)==(10 if candidate else 8)
    hashes=[]
    for table in range(0x800a68dc,0x800a695c,16):
        src,dest,length,method=struct.unpack_from('<4I',IMAGE,table-BIAS)
        data=bytes(u.mem_read(dest,length))
        expected=(pack['dsp'] if candidate else IMAGE[SOURCE-BIAS:SOURCE-BIAS+LENGTH]) if dest==DEST else None
        if method==ZERO:assert data==bytes(length)
        elif expected is not None:assert data==expected
        elif method==0x80079498:assert data==IMAGE[src-BIAS:src-BIAS+length]
        else:assert expand(IMAGE[src-BIAS:],length)[0]==data
        hashes.append(dict(destination=dest,bytes=length,sha256=hashlib.sha256(data).hexdigest()))
    j=pack['jumps'];start=j['candidate_code_start'];end=j['candidate_load_end']
    globals_bytes=j['globals_end']-j['globals_start']
    if candidate:
        assert bytes(u.mem_read(start,len(pack['code'])))==pack['code']
        assert bytes(u.mem_read(j['globals_start'],globals_bytes))==bytes(globals_bytes)
        assert helpers[4:7]==[(ZERO,0,j['globals_start'],globals_bytes),
            (DECOMPRESS,pack['code_source'],start,len(pack['code'])),
            (DECOMPRESS,SOURCE,DEST,LENGTH)]
    else:
        assert bytes(u.mem_read(start,end-start))==b'\xa5'*(end-start)
        assert bytes(u.mem_read(j['globals_start'],globals_bytes))==b'\xa5'*globals_bytes
    assert bytes(u.mem_read(start-16,16))==bytes(u.mem_read(end,16))==b'\xa5'*16
    assert bytes(u.mem_read(j['globals_start']-8,8))==b'\xa5'*8
    assert bytes(u.mem_read(j['globals_end'],16))==b'\xa5'*16
    return hashes,helpers

class PackedRig(PlacementRig):
    elf_path=ELF
    def __init__(self,**kw):
        # Skip PlacementRig's raw RAM copier: this subclass loads packed input.
        IntegrationRig.__init__(self,**kw)
    def load_capture_elf(self,elf):
        # Read ELF metadata only. Poison destinations and load bytes solely
        # through the actual stock decompressor/zero helper before extra_init.
        u=self.m.uc;j=PACK['jumps'];edit_memory(u)
        u.mem_write(DEST,b'\xa5'*LENGTH)
        u.mem_write(j['candidate_code_start'],b'\xa5'*len(PACK['code']))
        u.mem_write(j['globals_start'],b'\xa5'*92)
        self.m.invoke(ZERO,[0,j['globals_start'],92])
        for args in ((PACK['code_source'],j['candidate_code_start'],len(PACK['code'])),(SOURCE,DEST,LENGTH)):
            assert self.m.invoke(DECOMPRESS,list(args))==0
        assert self.raw(DEST,LENGTH)==PACK['dsp']
        assert self.raw(j['candidate_code_start'],len(PACK['code']))==PACK['code']
        assert self.raw(j['globals_start'],92)==bytes(92)

def main():
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,**kw))
    rng=random.Random(610)
    streams=[bytes(n) for n in (1,15,16,255,256,600)]+[
        b'A'*700,b'AB'*300,b'ABAB',bytes(range(254)),bytes(range(256))*3,
        bytes(range(255))*3,b'\x00\x01'*300]
    streams += [bytes(rng.randrange(256) for _ in range(n)) for n in (1,6,7,254,255,509,1024)]
    streams += [bytes(x) for n in range(1,7) for x in itertools.product((0,1),repeat=n)]
    for data in streams:
        encoded=compress(data)
        assert expand(encoded,len(data))==(data,len(encoded))
        assert native_expand(encoded,len(data))==data
    passed('encoder_matches_original_Thumb_decoder_across_literals_zeros_distances_and_overlapping_copies',
           streams=len(streams))

    for encoded,size in ((b'',1),(b'\x00\x00\x00',1),(b'\x01\x00',1),
                         (b'\x09\x00\x01',2),(b'\xf1',1),(b'\x02\x00',1)):
        try:expand(encoded,size)
        except ValueError:pass
        else:raise AssertionError('malformed packed stream accepted')
    try:compress(b'')
    except ValueError:pass
    else:raise AssertionError('empty scatter output accepted')
    passed('host_format_model_rejects_truncation_counter_underflow_no_progress_invalid_copy_and_overrun')

    assert native_expand(PACK['packed_dsp'],len(PACK['dsp']))==PACK['dsp']
    assert native_expand(PACK['packed_code'],len(PACK['code']))==PACK['code']
    assert PACK['packed_end']<=SOURCE+LENGTH and PACK['code_source']%4==0
    passed('both_complete_real_blocks_decode_exactly_inside_existing_MAIN_source_span',
           dsp_packed_bytes=len(PACK['packed_dsp']),capture_packed_bytes=len(PACK['packed_code']),
           spare_bytes=SOURCE+LENGTH-PACK['packed_end'])

    stock,stock_helpers=startup(False);candidate,helpers=startup(True)
    assert [r for r in stock if r['destination']!=DEST]==[r for r in candidate if r['destination']!=DEST]
    assert candidate[4]['sha256']==hashlib.sha256(PACK['dsp']).hexdigest()
    assert helpers[:4]==stock_helpers[:4] and helpers[7:10]==stock_helpers[5:8]
    passed('actual_entry_and_scatter_initializer_load_both_blocks_and_zero_globals_before_Main',
           original_regions=len(stock),candidate_records=len(helpers),
           unchanged_original_regions=7,original_outputs=candidate)

    # Edits are confined to source data and two specified metadata spans.
    # The table changes neither original destinations nor their lengths.
    for e in PACK['edits']:
        assert len(bytes.fromhex(e['old']))==len(bytes.fromhex(e['new']))
        assert e['address']+len(bytes.fromhex(e['new']))<=SOURCE
    assert struct.unpack_from('<I',IMAGE,0x2851f8)[0]==0xb5ae4
    assert TABLE_END+32<=0x800a6980
    passed('two_extra_records_fit_table_padding_without_MAIN_length_or_original_destination_changes')

    refs=audit()
    assert not refs['unresolved_raw_candidates'] and not refs['unresolved_decoded_candidates']
    assert not refs['bounded_movw_movt_candidates']
    assert len(refs['raw_candidates'])==16 and len(refs['decoded_reference_candidates'])==10
    assert any(r['address']==0x800a691c and r['value']==SOURCE for r in refs['raw_candidates'])
    assert any(r['address']==0x800a694c and r['value']==SOURCE for r in refs['raw_candidates'])
    assert any(r['address']==0x80068928 and 'instruction' in r for r in refs['raw_candidates'])
    assert any(r['address']==0x800a0b50 and r['stored_value']==0x8005f351 for r in refs['decoded_reference_candidates'])
    (ROOT/'analysis/capture_packing_reference_audit.json').write_text(json.dumps(refs,indent=2)+'\n')
    passed('bounded_source_and_table_reference_audit_retains_and_explains_all_candidates',
           halfword_decodes=refs['halfword_decodes'],raw_candidates=16,decoded_candidates=10,
           limitation='No whole-program or indirect ownership proof')

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2)
    r=PackedRig();assert r.boot(release=True)==0;r.ready();r.sequence=0
    result=record(r,delay=2);extra=r.completed_extra()
    assert result==ordinary and extra[512:]!=result[7][512:]
    assert 'emulator_tap_hook' not in r.entries and 'emulator_commit_hook' not in r.entries
    passed('capture_code_loaded_only_by_stock_decoder_produces_exact_extra_and_seven_unchanged_recordings',
           frames=24*64,stock_files=7)

    r=PackedRig(create_failure=True);assert r.boot()==13 and not r.calls
    assert record(r,delay=2)==ordinary and not r.disk
    r=PackedRig();assert r.boot(release=True)==0;r.ready();r.sequence=0
    r.inject=('audio',1,'short');assert record(r,delay=2)==ordinary
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False);assert r.result()==12 and not r.opened
    passed('packed_code_optional_creation_and_short_write_failures_preserve_ordinary_recordings')

    out=ROOT/'analysis/capture_packing_verification.json'
    result=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        placement_elf_sha256=PACK['jumps']['placement_elf_sha256'],packing=report(PACK),
        limitations=['Stock-length bytes are loaded by emulator, not the vendor bootloader',
            'Actual entry and all scatter helpers execute; stop before Main board/cache/task setup',
            'No physical memory, cache, MPU, IRQ, timing or deployed startup claim',
            'Recording fixtures still model public files, queues, task identities and Main storage authorization',
            'Reference/source ownership audit, manager/worker initialization and native I/O joins remain prerequisites',
            'No image construction, flash output, storage-card transfer or device access'])
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
