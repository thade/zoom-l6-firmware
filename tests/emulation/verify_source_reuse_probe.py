#!/usr/bin/env python3
"""Exact source-reuse marker image and all retained passive diagnostics.

Original reset/scatter, cache routine, marker and query execute. Other board
hardware, scheduling and cache side effects remain modeled; no device access.
"""
import contextlib,hashlib,io,json,struct,sys
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from build_source_reuse_probe import ELF,OUT,ENTRY,STATES,MARKER,ZERO_BYTES,trial
from build_health_probe import DSP_SOURCE,DSP_DEST,DSP_BYTES,SCATTER,END
from capture_source_reuse_layout import CODE_START,GLOBALS_START
from build_deployment_probe import validate
from plan_capture_packing import DECOMPRESS,ZERO
from scatter_codec import expand
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT,RETURN,STACK
from verify_firmware_workflow import put32
from verify_sd_cache_contract import CCR,CCSIDR,MPU_BASE,MPU_ATTRIBUTE,EXPECTED
import verify_health_probe as health
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_source_reuse_probe import request,decode
import l6_loader_probe as legacy

with ELF.open('rb') as f:
    e=ELFFile(f);CODE=next(s.data() for s in e.iter_segments() if s['p_type']=='PT_LOAD')
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    FUNCTIONS=[(s.name,s['st_value']&~1,s['st_size']) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type']=='STT_FUNC' and s['st_size']]
TRIAL,MANIFEST=trial(CODE,SYMS)
HELPER=MANIFEST['loader_record'][3]

def boot(image,corrupt=None):
    m=health.machine(False);u=m.uc
    for a,n in ((0,0x1000),(0x81000000,0x1000000),(0x20210000,0x20000),(0xe000e000,0x1000)):
        u.mem_map(a,n)
    u.mem_write(0x80001000,image[0x200:0xb5ce4])
    u.mem_write(DSP_DEST,b'\xa5'*DSP_BYTES)
    entered=[];helpers=[]
    if corrupt:
        at,data=corrupt;u.mem_write(at,data)
    def enter(u,pc,n,x):entered.append(pc);u.emu_stop()
    handles=[u.hook_add(UC_HOOK_CODE,enter,begin=pc,end=pc) for pc in
             (0x80067a60,MANIFEST['loader_failed_entry'])]
    def helper(u,pc,n,x):helpers.append((pc,*[u.reg_read(r) for r in (A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2)]))
    handles.extend(u.hook_add(UC_HOOK_CODE,helper,begin=pc,end=pc) for pc in (DECOMPRESS,ZERO,0x80079498,HELPER))
    u.emu_start(0x80001401,0x80067a62,count=100000000)
    for h in handles:u.hook_del(h)
    if corrupt:
        assert entered==[MANIFEST['loader_failed_entry']]
        return m,[],helpers
    assert entered==[0x80067a60] and u.reg_read(A.UC_ARM_REG_SP)==0x2021fff0
    assert len(helpers)==(10 if image==TRIAL else 8)
    hashes=[]
    for table in range(0x800a68dc,0x800a695c,16):
        s,d,n,h=struct.unpack_from('<4I',IMAGE,table-BIAS)
        expected=bytes(n) if h==ZERO else expand(IMAGE[s-BIAS:],n)[0] if h==DECOMPRESS else IMAGE[s-BIAS:s-BIAS+n]
        actual=bytes(u.mem_read(d,n));assert actual==expected
        hashes.append(dict(destination=d,bytes=n,sha256=hashlib.sha256(actual).hexdigest()))
    if image==TRIAL:
        assert helpers[4:7]==[(q[3],*q[:3]) for q in MANIFEST['scatter_records']]
        expected=bytearray(TRIAL[DSP_SOURCE-BIAS:END-BIAS])
        expected[CODE_START-DSP_SOURCE:CODE_START-DSP_SOURCE+len(MARKER)]=MARKER
        expected[GLOBALS_START-DSP_SOURCE:GLOBALS_START-DSP_SOURCE+ZERO_BYTES]=bytes(ZERO_BYTES)
        assert bytes(u.mem_read(DSP_SOURCE,END-DSP_SOURCE))==expected
    return m,hashes,helpers

def retained_startup(image):
    _,hashes,helpers=boot(image)
    # Existing diagnostic checks compare the eight ORIGINAL records. The two
    # new records/order/full output are asserted in boot() before this view.
    if image==TRIAL:helpers=helpers[:5]+helpers[7:]
    return hashes,helpers

def direct(m,packet,state=2):
    m.uc.mem_write(INPUT,struct.pack('<I',len(packet))+packet+bytes(16))
    m.uc.mem_write(0x80629b60,bytes([state]))
    return m.invoke(SYMS['source_reuse_dispatch'],[INPUT])

def main():
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,**kw))
    assert (OUT/'trial_source_reuse/L6.BIN').read_bytes()==TRIAL
    validate(TRIAL);assert TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert MANIFEST['state_bytes']==1780 and MANIFEST['new_zeroed_bytes']==16
    assert MANIFEST['native_capacity_frames']==223104
    assert not any(n.startswith(('extra_','sdp_','native_worker','storage_lease')) for n in SYMS)
    old,old_hashes,old_helpers=boot(IMAGE);m,new_hashes,new_helpers=boot(TRIAL)
    assert new_hashes==old_hashes
    assert old_helpers[:4]==new_helpers[:4] and old_helpers[5:]==new_helpers[7:]
    passed('exact_image_original_eight_destinations_and_two_new_records_execute_in_DSP_code_zero_order',
           helpers=new_helpers,trial_sha256=hashlib.sha256(TRIAL).hexdigest())

    marker_source=MANIFEST['scatter_records'][1][0]
    failures=[(CODE_START,b'\xff'*4),(marker_source,b'\xff'*4),
              (marker_source,struct.pack('<I',1)+b'\xf0'),
              (SCATTER+16+4,struct.pack('<I',DSP_SOURCE)),
              (SCATTER+16+8,struct.pack('<I',marker_source-CODE_START+1))]
    for bad in failures:boot(TRIAL,bad)
    passed('bad_DSP_or_marker_input_and_live_helper_or_unread_input_overlap_stop_before_Main',cases=len(failures))

    for initial in (0,0x30000):
        m,_,_=boot(TRIAL);u=m.uc
        put32(m,CCR,initial);put32(m,CCSIDR,(1<<13)|(1<<3)|1)
        writes=[];pairs=[];base=None
        def system(u,k,a,n,v,x):
            nonlocal base
            writes.append((a,v))
            if a==MPU_BASE:base=v
            if a==MPU_ATTRIBUTE:pairs.append((base,v))
        h=u.hook_add(UC_HOOK_MEM_WRITE,system,begin=0xe000ed00,end=0xe000ef78)
        m.invoke(0x8001b320,[]);u.hook_del(h)
        assert pairs==EXPECTED
        assert all(any(a==needed for a,v in writes) for needed in (0xe000ef50,0xe000ef60))
        if initial:assert any(a==0xe000ef74 for a,v in writes)
        assert direct(m,request(19))==1
        r=decode(m.replies[-1]);assert r['marker']==0x4c36 and r['zero_or']==0 and r['ccr']&0x30000==0x30000
    passed('original_cache_setup_then_actual_marker_and_query_execute_in_same_memory_without_host_expansion',
           initial_ccr=[0,0x30000],physical_cache_effects_modeled=False)

    m,_,_=boot(TRIAL);u=m.uc;put32(m,CCR,0x30000)
    reads=[];writes=[];executed=[]
    u.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,x:reads.append((a,n)),begin=SCATTER,end=SCATTER+47)
    u.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,x:reads.append((a,n)),begin=GLOBALS_START,end=GLOBALS_START+15)
    u.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,x:writes.append((a,n)))
    u.hook_add(UC_HOOK_CODE,lambda u,a,n,x:executed.append(a),begin=CODE_START,end=CODE_START+len(MARKER)-1)
    before=bytes(u.mem_read(DSP_SOURCE,END-DSP_SOURCE))
    for token in (0,37,127):
        reads.clear();executed.clear();writes.clear()
        # Packet setup is host writes; Unicorn hooks observe CPU writes only.
        assert direct(m,request(token))==1
        r=decode(m.replies[-1]);assert r['token']==token and r['marker']==0x4c36 and r['zero_or']==0
        assert [r[k] for k in ('dsp_source','dsp_destination','dsp_bytes','dsp_helper')]==MANIFEST['scatter_records'][0]
        assert [r[k] for k in ('code_source','code_destination','code_bytes','code_helper')]==MANIFEST['scatter_records'][1]
        assert (r['zero_destination'],r['zero_bytes'])==(GLOBALS_START,ZERO_BYTES)
        assert executed==[CODE_START,CODE_START+4]
        assert sorted(reads)==sorted([(GLOBALS_START+4*i,4) for i in range(4)]+[(SCATTER+4*i,4) for i in (*range(8),9,10)])
        assert all(STACK-512<=a and a+n<=STACK for a,n in writes)
        assert bytes(u.mem_read(DSP_SOURCE,END-DSP_SOURCE))==before
    passed('query_executes_published_marker_reads_fixed_fields_and_only_writes_bounded_stack')

    put32(m,GLOBALS_START+8,0x12345678);direct(m,request(21))
    assert decode(m.replies[-1])['zero_or']==0x12345678
    put32(m,GLOBALS_START+8,0)
    assert direct(m,legacy.request(22))==1
    lr=legacy.decode(m.replies[-1]);assert [lr[k] for k in ('source','destination','bytes','helper')]==MANIFEST['loader_record']
    passed('zero_snapshot_reports_live_corruption_and_previous_kind3_identity_remains_compatible')

    packet=request(19);bad=[packet[:-1],packet+b'\0']
    for i,v in ((0,0),(1,0),(2,1),(3,1),(4,0),(5,5),(6,128),(7,0)):
        b=bytearray(packet);b[i]=v;bad.append(bytes(b))
    for p in bad:
        reads.clear();executed.clear();count=len(m.replies)
        assert direct(m,p)==0 and not reads and not executed and len(m.replies)==count
    for state,ipsr in ((0,0),(1,0),(3,0),(2,16)):
        u.reg_write(A.UC_ARM_REG_IPSR,ipsr);reads.clear();executed.clear()
        assert direct(m,packet,state)==0 and not reads and not executed
    u.reg_write(A.UC_ARM_REG_IPSR,0);direct(m,packet);reply=m.replies[-1]
    for changed in (reply[:-1],reply+b'\0'):
        try:decode(changed)
        except ValueError:pass
        else:raise AssertionError('bad reply length accepted')
    for i,v in ((6,128),(7,2),(11,16),(-1,0)):
        b=bytearray(reply);b[i]=v
        try:decode(bytes(b))
        except ValueError:pass
        else:raise AssertionError('bad reply accepted')
    for token in (-1,128):
        try:request(token)
        except ValueError:pass
        else:raise AssertionError('bad token accepted')
    passed('firmware_context_packet_and_host_decoder_checks_reject_invalid_inputs')

    m.hooks.pop(0x80031648);given=[];ring=0x8062ad84
    put32(m,0x8062cd84,8191);put32(m,0x8062cd8c,8192)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    health.query(m,request(19))
    actual=bytes(u.mem_read(ring+8191,1))+bytes(u.mem_read(ring,77))
    assert actual==reply and given==[0x7111,0x7112]
    passed('original_parser_and_sender_copy_complete_78_byte_reply_across_ring_wrap')

    sys.argv.append('--detail')
    import verify_sd_startup_probe as retained
    import verify_sd_completion_probe as completion
    retained_symbols=dict(SYMS,startup_dispatch=SYMS['source_reuse_dispatch'])
    for k,v in dict(ELF=ELF,OUT=OUT,CODE=CODE,SYMS=retained_symbols,FUNCTIONS=FUNCTIONS,
                   TRIAL=TRIAL,MANIFEST=MANIFEST,STATES=STATES,
                   STATE=SYMS['startup_trace'],PREFIX='source_reuse_retained',startup=retained_startup).items():
        setattr(retained,k,v)
    completion.startup=retained_startup
    with contextlib.redirect_stdout(io.StringIO()):retained.main()
    r=json.loads((ROOT/'analysis/source_reuse_retained_probe_verification.json').read_text())
    assert r['passed'] and r['groups']==66
    passed('all_66_expanded_startup_RAM_capacity_command_raw_detail_and_health_checks_pass_on_exact_image')
    report=dict(passed=True,groups=len(cases)-1+66,new_groups=len(cases)-1,retained_groups=66,
        results=cases,trial_sha256=hashlib.sha256(TRIAL).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=MANIFEST['limitations']+[
            'Marker executes after separately invoked original cache routine on the same emulated memory; this is not a complete device boot.',
            'Cache geometry is seeded; physical cache effects, exception timing, board devices and later indirect source users remain unqualified.'])
    out=ROOT/'analysis/source_reuse_probe_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=report['groups'],report=str(out))))
if __name__=='__main__':main()
