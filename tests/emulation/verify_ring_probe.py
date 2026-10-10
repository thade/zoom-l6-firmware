#!/usr/bin/env python3
"""Bounded experiment 08 checks; physical IO, kernel/ADC and timing are fixtures."""
import json,struct,sys
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,BIAS,STACK,request as pad_query,assignment
from verify_firmware_workflow import put32,get32
from verify_uncompressed_tap import B,RING,STRIDE
from verify_recording_writer import C
from verify_native_filesystem_sd import READ,WRITE,HANDLE,BUFFER,RESULT,pattern as file_pattern
import verify_health_probe as health
from verify_stock_ring_modes import initialized,configured,check_sizes,refill,SIZE_SITE,size_instruction
from verify_pad_reader_audit import TARGETS
sys.path[:0]=[str(ROOT/'tools/firmware'),str(ROOT/'tools/device')]
from build_ring_probe import OUT,ELF,ENTRY,END,HOOKS,CAP,STATE_SIZES,trial
from build_deployment_probe import validate,digest
from l6_ring_probe import request,decode,sequence,TOTAL_WORDS,CHUNKS
from l6_timing_probe import request as timing_request,decode as timing_decode
TRIAL=(OUT/'trial_ring_probe/L6.BIN').read_bytes()
with ELF.open('rb') as f:
    e=ELFFile(f);CODE=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD').data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
GUARDS=SYMS['ring_guards'];SPANS=SYMS['ring_spans'];TAIL_WORDS=240000-CAP
SAFE_STACK=0x2003f000
def overlay(m):
    m.uc.mem_write(ENTRY,CODE)
    for site in (*HOOKS.values(),SIZE_SITE):m.uc.mem_write(site,TRIAL[site-BIAS:site-BIAS+4])
def ready(m):
    for field in (B+0x53e0,B+0x53f0):put32(m,field,RING)
    for field in (B+0x53e8,B+0x53f8,C+0x50,C+0x1e94):put32(m,field,CAP)
    for field in (B+0x53e4,B+0x53f4,C+0x1e8c,C+0x440,C+0x1e88,B+0x53d0):put32(m,field,0)
    m.uc.mem_write(0x80578ebc,b'\0')
def machine():
    m=health.machine(False);m.uc.mem_map(0x81000000,0x1000000)
    m.stack=SAFE_STACK;overlay(m);ready(m);return m
def query(m,kind,token=1):
    health.query(m,request(kind,token));return decode(m.replies[-1])
def arm(m):
    # ARM MAX audio fixture cannot execute M-class IPSR; invoke the same
    # compiled guard body there. Full parser/protocol runs on M7 separately.
    if not hasattr(m,'replies'):
        for _ in range(CHUNKS):m.invoke(SYMS['guards'],[1])
        assert get32(m,GUARDS+4)==2 and get32(m,GUARDS+8)==TOTAL_WORDS
    else:
        for _ in range(CHUNKS):p=query(m,2)
        assert p['guards_armed'] and p['init_words']==TOTAL_WORDS
def full_scan(m):
    if not hasattr(m,'replies'):
        for _ in range(CHUNKS):m.invoke(SYMS['guards'],[0])
        return dict(bad_words=get32(m,GUARDS+20),state=get32(m,GUARDS+4))
    p=query(m,1);target=(p['sweeps']+1)&0xffffffff
    for _ in range(CHUNKS):
        p=query(m,3)
        if p['state']==3 or p['sweeps']==target:return p
    raise AssertionError('Incomplete scan')
def tail(lane=0):return RING+lane*STRIDE+CAP*4
def guards_bytes(m):return b''.join(bytes(m.uc.mem_read(tail(i),TAIL_WORDS*4)) for i in range(12))
def meter(m):
    d=dict(instructions=0,stack_bytes=0)
    def seen(uc,pc,size,_):
        d['instructions']+=1
        depth=getattr(m,'stack',STACK)-uc.reg_read(A.UC_ARM_REG_SP)
        assert 0<=depth<16384,(hex(pc),depth)
        d['stack_bytes']=max(d['stack_bytes'],depth)
    return d,m.uc.hook_add(UC_HOOK_CODE,seen)
def compiled_functions():
    with ELF.open('rb') as f:
        e=ELFFile(f)
        for s in e.get_section_by_name('.symtab').iter_symbols():
            if s['st_info']['type']!='STT_FUNC' or not s['st_size'] or not isinstance(s['st_shndx'],int):continue
            sec=e.get_section(s['st_shndx']);o=(s['st_value']&~1)-sec['sh_addr']
            ds=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS).disasm(sec.data()[o:o+s['st_size']],s['st_value']&~1))
            assert sum(i.size for i in ds)==s['st_size'],s.name
            yield s.name,ds
def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    expected,manifest=trial(CODE,SYMS);assert expected==TRIAL;validate(TRIAL)
    assert TRIAL[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]==size_instruction(CAP)
    assert ENTRY+len(CODE)<=END and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert struct.unpack('<7I',CODE[SYMS['ring_layout']-ENTRY:SYMS['ring_layout']-ENTRY+28])==(116,36,CAP,STRIDE,TAIL_WORDS,512,12)
    for name,size in STATE_SIZES.items():assert CODE[SYMS[name]-ENTRY:SYMS[name]-ENTRY+size]==bytes(size)
    passed('exact_builder_whitelist_original_container_integer_capacity_instruction_and_zero_fixed_state',code_and_state_bytes=len(CODE))

    a,_=health.startup(IMAGE);b,helpers=health.startup(TRIAL);assert a==b
    assert any(dest<=RING and dest+length>=RING+12*STRIDE and method==0x800794a8 for method,src,dest,length in helpers)
    m=machine();m.uc.mem_map(health.DSP_DEST,0xe000)
    m.uc.mem_write(0x80001000,TRIAL[0x200:0xb5ce4])
    s,d,n,helper=struct.unpack('<4I',m.uc.mem_read(health.SCATTER,16))
    assert m.invoke(helper,[s,d,n])==0
    assert bytes(m.uc.mem_read(d,n))==IMAGE[health.DSP_SOURCE-BIAS:health.DSP_SOURCE-BIAS+n]
    assert bytes(m.uc.mem_read(ENTRY,len(CODE)))==CODE
    passed('all_eight_original_cold_scatter_outputs_match_arena_is_cleared_and_exact_DSP_decode_preserves_probe')

    for mode in (0,1,2):
        r=initialized(CAP,mode);overlay(r.m)
        # Run full original initializers again from the actual prepared image.
        r.m.invoke(0x80011920,[48000]);r.m.invoke(0x8000ad48,[]);check_sizes(r,CAP)
        arm(r.m);before=guards_bytes(r.m)
        r.m.invoke(0x80011920,[48000]);r.m.invoke(0x8000ad48,[]);check_sizes(r,CAP)
        assert guards_bytes(r.m)==before
    passed('actual_image_full_audio_recorder_initialization_and_reinitialization_keep_four_sizes_and_armed_tails',mode_fixtures=[0,1,2])

    for name,ds in compiled_functions():
        assert not name.startswith(('extra_','manager_','native_worker','__aeabi_f'))
        assert all(not i.mnemonic.startswith('v') for i in ds),name
    passed('compiled_probe_integer_only_no_extra_capture_worker_heap_binding')

    m=machine();before=guards_bytes(m);state=bytes(m.uc.mem_read(GUARDS,116))
    for kind in (1,3,4,5):p=query(m,kind,127);assert p['observer_consistent'] and p['token']==127
    assert guards_bytes(m)==before
    assert query(m,1)['state']==0
    # Status reads change neither guards nor observer state.
    state=bytes(m.uc.mem_read(GUARDS,116));query(m,1);query(m,4)
    assert bytes(m.uc.mem_read(GUARDS,116))==state
    passed('status_and_unarmed_scan_never_write_guards_and_query_cannot_choose_addresses')

    m=machine();normal=[];writes=[]
    for i in range(12):m.uc.mem_write(RING+i*STRIDE,b'\x3c'*(CAP*4));normal.append(bytes(m.uc.mem_read(RING+i*STRIDE,CAP*4)))
    def observe(uc,access,a,n,v,_):writes.append((a,n))
    h=m.uc.hook_add(UC_HOOK_MEM_WRITE,observe,begin=RING,end=RING+12*STRIDE-1)
    measured,hm=meter(m);p=query(m,2);m.uc.hook_del(hm)
    assert p['init_words']==512 and p['state']==1
    for _ in range(CHUNKS-1):p=query(m,2)
    m.uc.hook_del(h)
    assert p['guards_armed'] and len(writes)==TOTAL_WORDS and len(set(a for a,n in writes))==TOTAL_WORDS
    assert all(n==4 and (a-RING)%STRIDE>=CAP*4 for a,n in writes)
    for i in range(12):
        assert bytes(m.uc.mem_read(RING+i*STRIDE,CAP*4))==normal[i]
        expected=b''.join(struct.pack('<I',(tail(i)+4*j)^0xa56c0d3b) for j in range(TAIL_WORDS))
        assert bytes(m.uc.mem_read(tail(i),TAIL_WORDS*4))==expected
    before=guards_bytes(m);query(m,2);assert guards_bytes(m)==before
    scan_meter,hm=meter(m);p=query(m,3);m.uc.hook_del(hm)
    assert p['scan_word']==512 and p['bad_words']==0
    for _ in range(CHUNKS-1):p=query(m,3)
    assert p['sweeps']==1 and p['scan_word']==0 and p['bad_words']==0
    assert guards_bytes(m)==before
    passed('396_bounded_chunks_cover_all_12_tails_exactly_once_preserve_native_prefixes_scan_and_cannot_rearm',
        guard_write_chunk_fixture=measured,guard_read_chunk_fixture=scan_meter)

    for lane in range(12):
        m=machine();arm(m);a=tail(lane)+TAIL_WORDS*4-4
        original=get32(m,a);put32(m,a,original^1)
        p=full_scan(m)
        assert p['state']==3 and p['bad_words']==1 and p['first_bad_address']==a
        assert p['expected']==original and p['actual']==original^1
        frozen=guards_bytes(m);query(m,2);query(m,3)
        assert guards_bytes(m)==frozen and query(m,1)['bad_words']==1
    passed('corruption_at_last_word_of_each_lane_latches_first_address_values_and_never_rewrites_evidence')

    # Original generic effect copies can accept computed destinations. These
    # are synthetic negative controls, not actual stock effect assignments.
    for fn in (0x8005b740,0x8005b790):
        m=machine();arm(m);put32(m,0x801f5f08,1)
        m.uc.mem_write(0x21030000,b'\x3c'*16)
        m.invoke(fn,[tail(0),0x21030000,16]);p=full_scan(m)
        assert p['state']==3 and p['bad_words']==4 and p['first_bad_address']==tail(0)
    passed('original_generic_effect_copies_to_synthetic_tails_are_detected_without_alias_exclusion_claim')

    for a in (B+0x53e0,B+0x53f0,B+0x53e8,B+0x53f8,C+0x50,C+0x1e94,B+0x53e4,B+0x53f4,C+0x1e8c):
        m=machine();put32(m,a,240000);before=guards_bytes(m);p=query(m,2)
        assert p['state']==3 and p['layout_faults']==1 and p['init_words']==0
        assert guards_bytes(m)==before and get32(m,a)==240000
    passed('each_incoherent_base_size_cache_or_cursor_refuses_guard_writes_without_live_repair')

    for a,byte,value in ((0x80578ebc,True,1),(C+0x440,False,1),(B+0x53d0,False,1),(C+0x1e88,False,2)):
        m=machine();m.uc.mem_write(a,bytes([value]) if byte else struct.pack('<I',value))
        before=guards_bytes(m);p=query(m,2)
        assert p['busy_refusals']==1 and p['init_words']==0 and p['state']==0 and guards_bytes(m)==before
    m=machine();query(m,2);put32(m,C+0x440,1);p=query(m,2)
    assert p['init_words']==512 and p['busy_refusals']==1
    put32(m,C+0x440,0);p=query(m,2);assert p['init_words']==1024
    passed('recording_and_recorded_song_activity_refuse_or_pause_initialization_preserving_partial_guards')

    m=machine();put32(m,GUARDS,1);before=guards_bytes(m);p=query(m,2)
    assert not p['observer_consistent'] and p['claim_skips']==1 and guards_bytes(m)==before
    # Induce one failed weak CAS at the actual guard claim instruction.
    m=machine();miss=[]
    claim_ds=next(ds for name,ds in compiled_functions() if name=='guards')
    ins=next(i for i in claim_ds if i.mnemonic=='strex')
    def fail(uc,pc,size,_):
        if not miss:
            miss.append(True);reg=ins.op_str.split(',')[0]
            uc.reg_write(getattr(A,'UC_ARM_REG_'+reg.upper()),1);uc.reg_write(A.UC_ARM_REG_PC,(pc+size)|1)
    h=m.uc.hook_add(UC_HOOK_CODE,fail,begin=ins.address,end=ins.address)
    p=query(m,2);m.uc.hook_del(h)
    assert miss and p['claim_skips']==1 and p['init_words']==0 and p['state']==0
    passed('busy_or_failed_single_weak_claim_skips_without_guard_write_retry_or_block')

    m=machine();put32(m,C+0x440,0xfff);put32(m,B+0x53e4,32)
    for i in range(12):put32(m,C+0x20+4*i,CAP-32-i)
    p=query(m,5);assert p['samples']==1 and all(p[f'max_sampled_lag_{i}']==64+i for i in range(12))
    put32(m,C+0x20,CAP);p=query(m,5);assert p['invalid_cursors']==1 and p['max_sampled_lag_0']==64
    # Native cursor remains unchanged: observation does not repair it.
    assert get32(m,C+0x20)==CAP
    passed('active_lanes_sample_modulo_lag_across_wrap_report_invalid_consumers_without_repair_or_whole_lap_claim')

    m=machine();calls=[]
    m.hooks[SYMS['timing_read_original']&~1]=lambda a:calls.append(('read',a[:4])) or put32(m,a[3],a[2]-1) or 17
    m.hooks[SYMS['timing_write_original']&~1]=lambda a:calls.append(('write',a[:4])) or 19
    assert m.invoke(READ,[HANDLE,tail(0)-1,1,RESULT])==17
    assert m.invoke(WRITE,[HANDLE,tail(0),0,RESULT])==19
    assert query(m,4)['overlaps']==0
    assert m.invoke(READ,[HANDLE,tail(0)-1,2,RESULT])==17
    p=query(m,4);assert p['overlaps']==1 and p['first_tail_address']==tail(0) and p['first_operation']==1
    assert get32(m,RESULT)==1
    assert m.invoke(WRITE,[HANDLE,0xfffffff0,32,RESULT])==19 and query(m,4)['invalid_spans']==1
    assert len(calls)==4
    passed('file_spans_handle_zero_length_exact_boundary_overlap_overflow_short_actual_and_errors_original_once')

    m=machine();native=[];packet=0x21030000
    m.hooks[SYMS['health_sd_original']&~1]=lambda a:native.append(bytes(m.uc.mem_read(a[0],20))) or 23
    for op,unit,buf,blocks in ((2,1,tail(11),1),(3,2,RING,0x800000),(4,1,tail(0),1),(2,3,tail(0),1)):
        raw=struct.pack('<BBH4I',op,unit,0,0,buf,blocks,7);m.uc.mem_write(packet,raw)
        assert m.invoke(HOOKS['ring_sd'],[packet])==23 and native[-1]==raw
    p=query(m,4);assert p['requests']==2 and p['overlaps']==1 and p['invalid_spans']==1 and p['first_operation']==3
    assert len(native)==4
    put32(m,SPANS,1)
    m.hooks[SYMS['timing_read_original']&~1]=lambda a:29
    assert m.invoke(READ,[HANDLE,tail(0),10,RESULT])==29 and query(m,4)['claim_skips']==1
    passed('SD_units_block_span_overflow_unknown_packets_and_busy_observer_preserve_native_packet_once')

    m=machine();calls=[]
    m.hooks[SYMS['timing_read_original']&~1]=lambda a:calls.append(a[:4]) or 17
    m.hooks[SYMS['timing_write_original']&~1]=lambda a:calls.append(a[:4]) or 19
    m.hooks[SYMS['health_sd_original']&~1]=lambda a:calls.append(a[:1]) or 23
    preserved=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(4,12)]
    fp=[getattr(A,'UC_ARM_REG_D'+str(i)) for i in range(8,16)]
    for reg in preserved:m.uc.reg_write(reg,0x12340000+reg)
    for reg in fp:m.uc.reg_write(reg,0x123456789abc0000+reg)
    m.uc.mem_write(0x21030000,struct.pack('<BBH4I',2,1,0,0,BUFFER,1,7))
    for entry,args,result in ((READ,[HANDLE,BUFFER,1024,RESULT],17),
        (WRITE,[HANDLE,BUFFER,1024,RESULT],19),(HOOKS['ring_sd'],[0x21030000],23)):
        assert m.invoke(entry,args)==result
        assert m.uc.reg_read(A.UC_ARM_REG_SP)==SAFE_STACK
        assert all(m.uc.reg_read(reg)==0x12340000+reg for reg in preserved)
        assert all(m.uc.reg_read(reg)==0x123456789abc0000+reg for reg in fp)
    assert calls==[[HANDLE,BUFFER,1024,RESULT],[HANDLE,BUFFER,1024,RESULT],[0x21030000]]
    passed('all_three_native_observers_preserve_arguments_results_stack_and_callee_saved_integer_FP_registers')

    for state in range(4):
        for data in (pad_query(0,0),pad_query(1,3,130),assignment(0,0,'TAKE_A.WAV')):
            a=health.machine(False);b=machine();health.query(a,data,state);health.query(b,data,state)
            assert a.events==b.events and a.replies==b.replies
    for state in (0,1,3):
        m=machine();before=guards_bytes(m);health.query(m,request(2,1),state)
        assert not m.replies and guards_bytes(m)==before
    m=machine();m.uc.reg_write(A.UC_ARM_REG_IPSR,3);health.query(m,request(2,1));assert not m.replies
    for size in (0,1,7,9):
        m=machine();health.query(m,(request(2,1)+b'\0')[:size]);assert not m.replies
    for i in range(8):
        raw=bytearray(request(2,1));raw[i]^=128;m=machine();health.query(m,raw);assert not m.replies
    m=machine()
    for kind in range(1,8):health.query(m,timing_request(kind,19));assert timing_decode(m.replies[-1])['token']==19
    passed('stock_editor_dispatch_legacy_timing_wrong_context_and_malformed_requests_keep_original_behavior')

    m=machine();r=query(m,1);raw=m.replies[-1]
    invalid=[raw[:-1],raw+b'\0']
    for i,v in ((5,6),(6,128),(7,128),(11,16),(-1,0)):
        b=bytearray(raw);b[i]=v;invalid.append(bytes(b))
    for b in invalid:
        try:decode(b)
        except ValueError:pass
        else:raise AssertionError('Malformed reply accepted')
    for kind,token in ((0,1),(6,1),(1,128),(1,-1)):
        try:request(kind,token)
        except ValueError:pass
        else:raise AssertionError('Malformed request accepted')
    def drive(m,initialize=False,scan=False):
        last={};kinds=[]
        for kind in sequence(last,initialize,scan):
            p=query(m,kind);last['guard' if kind<=3 else 'span' if kind==4 else 'backlog']=p;kinds.append(kind)
        return last,kinds
    m=machine();last,kinds=drive(m,True,True)
    assert kinds.count(2)==CHUNKS and kinds.count(3)==CHUNKS and last['guard']['sweeps']==1
    m=machine();put32(m,C+0x440,1)
    try:drive(m,True)
    except RuntimeError as e:assert 'active' in str(e)
    else:raise AssertionError('Busy mutation was retried')
    passed('strict_host_decoder_bounded_full_initialization_scan_and_abort_on_first_busy_refusal')

    m=machine();m.hooks.pop(0x80031648);given=[];ring=0x8062ad84
    put32(m,0x8062cd84,8190);put32(m,0x8062cd8c,8192)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x80076950]=lambda a:1
    m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    d,h=meter(m);health.query(m,request(1,17));m.uc.hook_del(h)
    packet=bytes(m.uc.mem_read(ring+8190,2))+bytes(m.uc.mem_read(ring,121))
    assert decode(packet)['token']==17 and get32(m,0x8062cd84)==121 and given==[0x7111,0x7112]
    m.uc.mem_write(SAFE_STACK-1024,b'\x3c'*1024)
    assert packet==bytes(m.uc.mem_read(ring+8190,2))+bytes(m.uc.mem_read(ring,121))
    passed('original_protected_wrapping_MIDI_ring_copies_largest_123_byte_reply_before_stack_reuse',modeled_query=d)

    rigs=[health.TimedSd(),health.TimedSd()];overlay(rigs[1].m);measurements=[]
    for r in rigs:
        d,h=meter(r.m)
        assert r.io(READ,1024)==(0,1024)
        assert r.io(WRITE,1024,file_pattern(1024,37))==(0,1024)
        assert r.close()==0;r.m.uc.hook_del(h);measurements.append(d)
    a,b=rigs
    assert a.sectors==b.sectors and a.triples()==b.triples() and len(a.requests)==len(b.requests)
    assert get32(b.m,SPANS+4)>0 and get32(b.m,SPANS+8)==get32(b.m,SPANS+12)==0
    passed('original_native_file_SD_requests_sectors_results_and_close_match_baseline',modeled_baseline=measurements[0],modeled_probe=measurements[1])

    for target in TARGETS:
        for playback in (0,1,2):
            a=configured(CAP,playback);b=configured(CAP,playback);overlay(b.m)
            # Seed guards while idle, then enable the fixture's playback.
            active=get32(b.m,B+0x53d0);put32(b.m,B+0x53d0,0)
            arm(b.m);put32(b.m,B+0x53d0,active)
            for _ in range(2):a.full(target);b.full(target)
            assert a.raw(B+0x10,0x53b8)==b.raw(B+0x10,0x53b8)
            assert full_scan(b.m)['bad_words']==0
    passed('all_four_complete_native_callbacks_cross_wrap_with_guarded_tails_and_identical_audio_fixture',effects='idle; ADC/delay synthetic')
    report=dict(passed=True,groups=len(cases),results=cases,trial_sha256=digest(TRIAL),
        limits=['No device operation or physical DMA/cache/source ownership proof.',
          'Kernel scheduling, ADC inputs, sectors, file completion and mode getter are fixtures.',
          'Guard scans detect writes; generic effect destinations and aliases are not exhausted.',
          'Backlog is sampled modulo distance; no extra consumer service budget or whole-lap detection.'])
    (OUT/'offline_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases),trial_sha256=digest(TRIAL))))
if __name__=='__main__':main()
