#!/usr/bin/env python3
"""Experiment 07 task/token attribution beside original file/SD instructions.

Offline only: task switching, lock waits, sector/DMA effects and joins are
explicit fixtures. Held body is take RETURN to give ENTRY, not physical busy.
"""
import json,struct,sys
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT,STACK,RETURN,request as pad_query,assignment
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_memory_layout import HEAP_STATE
from verify_native_filesystem_sd import READ,WRITE,HANDLE,BUFFER,RESULT,pattern,IO_ERROR
from verify_capture_transitions import FS1,FS2
from verify_scheduling_boundaries import stop
import verify_health_probe as health
sys.path[:0]=[str(ROOT/'tools/firmware'),str(ROOT/'tools/device')]
from build_service_probe import OUT,ELF,ENTRY,END,HOOKS,trial
from build_deployment_probe import validate,digest
from l6_service_probe import request,decode,LOCK_FIELDS
from l6_timing_probe import request as timing_request,decode as timing_decode

TRIAL=(OUT/'trial_service_probe/L6.BIN').read_bytes()
with ELF.open('rb') as f:
    e=ELFFile(f);CODE=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD').data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
STATE=SYMS['service_stats'];STATE_BYTES=3832
TASK=0x808e291c;TICKS=health.TICKS
OWNERS=(0x21039000,0x21039100)
TOKENS=(0x7101,0x7102,0x7e20,0x7e22)
TOKEN_FIELDS=(0x801f8da4,0x801f8da8,0x801f5fc0,0x801f5fdc)

def overlay(m):
    m.uc.mem_write(ENTRY,CODE)
    for site in HOOKS.values():m.uc.mem_write(site,TRIAL[site-BIAS:site-BIAS+4])
def context(m,owner=OWNERS[0]):
    put32(m,TASK,owner);put32(m,0x801f9048,1)
def machine():
    m=health.machine(False);overlay(m);context(m)
    for field,token in zip(TOKEN_FIELDS,TOKENS):put32(m,field,token)
    m.hooks[0x80076950]=lambda a:1
    m.hooks[0x800763d8]=lambda a:1
    return m
def query(m,kind,token=1):
    health.query(m,request(kind,token));return decode(m.replies[-1])
def file_page(m,slot=0):return query(m,slot+2)
def lock_page(m,slot=0,kind=0):return query(m,10+slot*4+kind)
def advance(m,ticks):put32(m,TICKS,(word(m,TICKS)+ticks)&0xffffffff)
def stack_meter(m):
    observed={'instructions':0,'stack_bytes':0}
    def observe(uc,pc,size,user):
        observed['instructions']+=1
        depth=getattr(m,'stack',STACK)-uc.reg_read(A.UC_ARM_REG_SP)
        assert 0<=depth<16384,('Unexpected fixture stack',hex(pc),depth)
        observed['stack_bytes']=max(observed['stack_bytes'],depth)
    return observed,m.uc.hook_add(UC_HOOK_CODE,observe)
def resume(m,context_saved,owner,stack=STACK,result=None):
    m.uc.context_restore(context_saved);m.stack=stack;context(m,owner)
    if result is not None:m.uc.reg_write(A.UC_ARM_REG_R0,result)
    m.reached_return=False
    m.uc.emu_start(m.uc.reg_read(A.UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
    assert m.reached_return
    return m.uc.reg_read(A.UC_ARM_REG_R0)
def instructions():
    with ELF.open('rb') as f:
        e=ELFFile(f)
        for s in e.get_section_by_name('.symtab').iter_symbols():
            if s['st_info']['type']!='STT_FUNC' or not s['st_size'] or not isinstance(s['st_shndx'],int):continue
            section=e.get_section(s['st_shndx']);offset=(s['st_value']&~1)-section['sh_addr']
            ds=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS).disasm(section.data()[offset:offset+s['st_size']],s['st_value']&~1))
            assert sum(i.size for i in ds)==s['st_size'],('Incomplete function disassembly',s.name)
            yield s.name,ds

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    expected,manifest=trial(CODE,SYMS);assert expected==TRIAL;validate(TRIAL)
    assert ENTRY+len(CODE)<=END
    assert struct.unpack('<6I',CODE[SYMS['service_layout']-ENTRY:SYMS['service_layout']-ENTRY+24])==(3832,476,17,25,8,4)
    allowed=[(0x1fc,0x200),(health.SCATTER-BIAS+12,health.SCATTER-BIAS+16),
             (health.DSP_SOURCE-BIAS,END-BIAS)]+[(p-BIAS,p-BIAS+4) for p in HOOKS.values()]
    assert all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(IMAGE,TRIAL)) if x!=y)
    assert len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert CODE[manifest['state']-ENTRY:manifest['state']-ENTRY+manifest['state_bytes']]==bytes(manifest['state_bytes'])
    passed('exact_whitelisted_image_fixed_layout_container_regions_and_loaded_zero_state',
           code_and_state_bytes=len(CODE),state_bytes=manifest['state_bytes'])
    a,_=health.startup(IMAGE);b,_=health.startup(TRIAL);assert a==b
    m=machine();m.uc.mem_map(health.DSP_DEST,0xe000)
    s,d,n,helper=struct.unpack('<4I',m.uc.mem_read(health.SCATTER,16))
    # Load the packed source/scatter from the actual container for this check.
    m.uc.mem_write(0x80001000,TRIAL[0x200:0xb5ce4])
    s,d,n,helper=struct.unpack('<4I',m.uc.mem_read(health.SCATTER,16))
    assert helper==0x80001994 and m.invoke(helper,[s,d,n])==0
    assert bytes(m.uc.mem_read(d,n))==IMAGE[health.DSP_SOURCE-BIAS:health.DSP_SOURCE-BIAS+n]
    assert bytes(m.uc.mem_read(ENTRY,len(CODE)))==CODE
    passed('original_entry_all_eight_scatter_outputs_and_complete_DSP_decode_preserve_loaded_probe')
    disassembly=list(instructions())
    for name,ds in disassembly:
        assert not name.startswith(('extra_','native_worker','life_','manager_','__aeabi_f'))
        assert all(not i.mnemonic.startswith('v') for i in ds),(name,'FP instruction')
    passed('compiled_observation_is_integer_only_no_capture_worker_or_allocator_binding')

    m=machine();calls=[]
    def take(a):calls.append(('take',a[:2]));advance(m,31);return 1
    def give(a):calls.append(('give',a[0]));advance(m,13);return 1
    m.hooks[0x80076950]=take;m.hooks[0x800763d8]=give
    m.uc.mem_write(0x80578ebc,b'\x01');m.uc.mem_write(0x801f8c50,b'\x01')
    preserved=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(4,12)]
    for reg in preserved:m.uc.reg_write(reg,0x12340000+reg)
    fp=[getattr(A,'UC_ARM_REG_D'+str(i)) for i in range(8,16)]
    for reg in fp:m.uc.reg_write(reg,0x123456789abc0000+reg)
    assert m.invoke(HOOKS['service_take'],[TOKENS[0]])==0
    assert lock_page(m)['flags']==2;advance(m,79)
    assert m.invoke(HOOKS['service_give'],[TOKENS[0]])==0
    p=lock_page(m)
    assert p['last_wait']==p['max_wait']==31 and p['last_held']==p['max_held']==79
    assert p['last_give_ticks']==p['max_give_ticks']==13 and p['flags']==0
    assert p['calls']==p['releases']==1 and p['peak_held_state']==0x101
    assert calls==[('take',[TOKENS[0],0xffffffff]),('give',TOKENS[0])]
    assert m.uc.reg_read(A.UC_ARM_REG_SP)==STACK
    assert all(m.uc.reg_read(reg)==0x12340000+reg for reg in preserved)
    assert all(m.uc.reg_read(reg)==0x123456789abc0000+reg for reg in fp)
    passed('original_tail_shims_native_success_normalization_wait_held_give_split_and_preserved_ABI')

    m=machine();m.hooks[0x80076950]=lambda a:advance(m,9) or 0
    assert m.invoke(HOOKS['service_take'],[TOKENS[0]])==0xffffffce
    p=lock_page(m);assert p['errors']==1 and p['flags']==0 and p['last_wait']==9
    m.hooks[0x80076950]=lambda a:advance(m,7) or 1
    put32(m,TICKS,0xfffffffc)
    assert m.invoke(HOOKS['service_take'],[TOKENS[0]])==0
    advance(m,17);m.hooks[0x800763d8]=lambda a:advance(m,11) or 0
    assert m.invoke(HOOKS['service_give'],[TOKENS[0]])==0xffffffd5
    p=lock_page(m);assert p['flags']==2 and p['release_errors']==1 and p['last_held']==17
    assert p['last_wait']==7 and p['last_give_ticks']==11
    # A changed native handle slot cannot erase the retained original identity.
    put32(m,TOKEN_FIELDS[0],0x7999);m.hooks[0x800763d8]=lambda a:1
    assert m.invoke(HOOKS['service_give'],[TOKENS[0]])==0
    assert lock_page(m)['flags']==0 and lock_page(m)['releases']==2
    passed('native_take_failure_never_claims_held_failed_give_retains_identity_changed_slot_and_tick_wrap')

    m=machine();m.invoke(HOOKS['service_take'],[TOKENS[0]])
    retained=lock_page(m);m.invoke(HOOKS['service_take'],[TOKENS[0]])
    p=lock_page(m)
    assert query(m,1)['nested_takes']==1 and all(p[k]==retained[k] for k in LOCK_FIELDS)
    m.invoke(HOOKS['service_give'],[TOKENS[0]]);m.invoke(HOOKS['service_give'],[TOKENS[0]])
    assert query(m,1)['unpaired_gives']==1
    before=bytes(m.uc.mem_read(STATE,STATE_BYTES));native=[]
    m.hooks[0x80076950]=lambda a:native.append(a[:2]) or 1
    assert m.invoke(HOOKS['service_take'],[0x7888])==0
    assert bytes(m.uc.mem_read(STATE,STATE_BYTES))==before and native==[[0x7888,0xffffffff]]
    put32(m,TOKEN_FIELDS[1],TOKENS[0]);assert m.invoke(HOOKS['service_take'],[TOKENS[0]])==0
    assert query(m,1)['ambiguous_tokens']==1 and len(native)==2
    passed('nested_unpaired_unrecognized_and_ambiguous_tokens_preserve_original_once_without_false_ownership')

    # Explicitly suspended native take while an independent task gives the token.
    # No actual kernel scheduler or physical acquisition is simulated here.
    m=machine();context(m,OWNERS[1]);m.invoke(HOOKS['service_take'],[TOKENS[0]])
    context(m,OWNERS[0]);m.hooks[0x80076950]=lambda a:stop(m)
    m.invoke(HOOKS['service_take'],[TOKENS[0]]);waiting=m.uc.context_save()
    frame=bytes(m.uc.mem_read(m.uc.reg_read(A.UC_ARM_REG_SP),STACK-m.uc.reg_read(A.UC_ARM_REG_SP)))
    m.stack=0x20030000;context(m,OWNERS[1]);advance(m,103)
    assert lock_page(m,1)['flags']==1 and lock_page(m,1)['observer_consistent']
    assert lock_page(m,0)['flags']==2 and lock_page(m,0)['observer_consistent']
    m.invoke(HOOKS['service_give'],[TOKENS[0]])
    assert lock_page(m,0)['max_held']==103
    assert bytes(m.uc.mem_read(waiting.reg_read(A.UC_ARM_REG_SP),len(frame)))==frame
    assert resume(m,waiting,OWNERS[0],result=1)==0
    advance(m,47);m.invoke(HOOKS['service_give'],[TOKENS[0]])
    assert lock_page(m,1)['last_wait']==103 and lock_page(m,1)['last_held']==47
    assert lock_page(m,0)['last_wait']==0 and lock_page(m,0)['max_held']==103
    passed('independent_TCB_slots_publish_consistent_wait_and_held_states_across_MODELED_context_switch')

    m=machine();m.invoke(HOOKS['service_take'],[TOKENS[0]]);advance(m,23)
    m.hooks[0x800763d8]=lambda a:stop(m)
    m.invoke(HOOKS['service_give'],[TOKENS[0]]);pending=m.uc.context_save()
    m.stack=0x20030000;context(m,OWNERS[1])
    p=lock_page(m);assert p['flags']==6 and p['last_held']==23 and p['observer_consistent']
    advance(m,57);assert resume(m,pending,OWNERS[0],result=1)==0
    p=lock_page(m);assert p['flags']==0 and p['last_give_ticks']==57 and p['last_held']==23
    passed('native_give_in_progress_is_queryable_and_post_release_scheduling_stays_separate_from_held_body')

    m=machine();calls=[]
    def paused(a):calls.append(('read',a[:4]));return stop(m)
    def write(a):calls.append(('write',a[:4]));advance(m,77);put32(m,a[3],a[2]-7);return 0xffffd825
    m.hooks[SYMS['timing_read_original']&~1]=paused
    m.hooks[SYMS['timing_write_original']&~1]=write
    m.invoke(READ,[HANDLE,BUFFER,4096,RESULT]);pending=m.uc.context_save()
    m.stack=0x20030000;context(m,OWNERS[1]);advance(m,51)
    assert m.invoke(WRITE,[HANDLE+4,BUFFER,8192,RESULT])==0xffffd825
    assert word(m,RESULT)==8185
    a,b=file_page(m,0),file_page(m,1)
    assert a['operation']==1 and a['observer_consistent'] and b['calls']==b['errors']==1
    assert b['max_ticks']==77 and b['peak_operation']==2 and b['peak_handle']==HANDLE+4
    assert resume(m,pending,OWNERS[0],result=0)==0
    a=file_page(m,0);assert a['operation']==0 and a['max_ticks']==128 and a['calls']==1
    assert calls==[('read',[HANDLE,BUFFER,4096,RESULT]),('write',[HANDLE+4,BUFFER,8192,RESULT])]
    # Legacy shared public observer can skip B, while per-task attribution does not.
    health.query(m,timing_request(7,1));assert timing_decode(m.replies[-1])['busy_skips']==1
    passed('concurrent_public_calls_preserve_arguments_short_actual_errors_and_separate_TCB_job_peaks')

    m=machine();calls=[]
    m.hooks[SYMS['timing_read_original']&~1]=lambda a:calls.append(a[:4]) or stop(m)
    m.invoke(READ,[HANDLE,BUFFER,4096,RESULT]);pending=m.uc.context_save()
    m.stack=0x20030000
    m.hooks[SYMS['timing_write_original']&~1]=lambda a:calls.append(a[:4]) or 0
    m.invoke(WRITE,[HANDLE+4,BUFFER,7,RESULT]);p=file_page(m)
    assert p['nested_calls']==1 and p['operation']==1 and p['job']==p['calls']==1
    assert p['handle']==HANDLE and p['bytes']==4096
    assert resume(m,pending,OWNERS[0],result=0)==0 and file_page(m)['operation']==0
    assert len(calls)==2
    passed('MODELED_nested_public_entry_counts_omission_without_overwriting_outer_job')

    m=machine();calls=[]
    m.hooks[SYMS['timing_read_original']&~1]=lambda a:calls.append(a[:4]) or 0
    for i in range(8):context(m,0x21038000+256*i);m.invoke(READ,[HANDLE,BUFFER,64,RESULT])
    context(m,0x2103f000);m.invoke(READ,[HANDLE,BUFFER,64,RESULT])
    p=query(m,1);assert p['slots_full']==1 and len(calls)==9
    for i in range(8):assert file_page(m,i)['owner']==0x21038000+256*i and file_page(m,i)['calls']==1
    for owner,running,ipsr in ((0,1,0),(OWNERS[0],0,0),(OWNERS[0],1,3)):
        context(m,owner);put32(m,0x801f9048,running);m.uc.reg_write(A.UC_ARM_REG_IPSR,ipsr)
        m.invoke(READ,[HANDLE,BUFFER,64,RESULT])
    m.uc.reg_write(A.UC_ARM_REG_IPSR,0);context(m)
    assert query(m,1)['context_skips']==3 and len(calls)==12
    passed('eight_fixed_slots_report_exhaustion_and_invalid_contexts_without_blocking_original_calls')

    m=machine();native=[]
    m.hooks[SYMS['timing_read_original']&~1]=lambda a:native.append(a[:4]) or 17
    ds=next(ds for name,ds in disassembly if name=='task')
    strex=next(i for i in ds if i.mnemonic=='strex');miss=[]
    def fail_claim(uc,pc,size,user):
        if not miss:
            miss.append(True);reg=strex.op_str.split(',')[0]
            uc.reg_write(getattr(A,'UC_ARM_REG_'+reg.upper()),1);uc.reg_write(A.UC_ARM_REG_PC,(pc+size)|1)
    h=m.uc.hook_add(UC_HOOK_CODE,fail_claim,begin=strex.address,end=strex.address)
    assert m.invoke(READ,[HANDLE,BUFFER,64,RESULT])==17;m.uc.hook_del(h)
    assert miss and query(m,1)['claim_misses']==1 and file_page(m)['owner']==0 and len(native)==1
    passed('one_failed_weak_slot_claim_is_counted_without_retry_or_suppressing_original_call')

    m=machine();before=bytes(m.uc.mem_read(STATE,STATE_BYTES));heap=bytes(m.uc.mem_read(HEAP_STATE,28))
    for kind in range(1,42):
        p=query(m,kind,127);assert p['kind']==kind and p['token']==127
        if kind>1:assert p['observer_consistent'] and not p['physical_completion_proven']
    assert bytes(m.uc.mem_read(STATE,STATE_BYTES))==before and bytes(m.uc.mem_read(HEAP_STATE,28))==heap
    put32(m,STATE+24+4,1);assert not file_page(m)['observer_consistent'];put32(m,STATE+24+4,2)
    reply=m.replies[-1];invalid=[reply[:-1],reply+b'\0']
    for index,value in ((5,42),(6,128),(11,16),(7,128),(-1,0)):
        b=bytearray(reply);b[index]=value;invalid.append(bytes(b))
    for b in invalid:
        try:decode(b)
        except ValueError:pass
        else:raise AssertionError('Malformed service reply accepted')
    for kind,token in ((0,1),(42,1),(1,128),(1,-1)):
        try:request(kind,token)
        except ValueError:pass
        else:raise AssertionError('Malformed service request accepted')
    passed('all_41_fixed_pages_are_read_only_strictly_decoded_and_odd_epochs_are_not_completed_snapshots')

    for state in range(4):
        for message in (pad_query(0,0),pad_query(1,3,130),assignment(0,0,'TAKE_A.WAV')):
            a=health.machine(False);b=machine();health.query(a,message,state);health.query(b,message,state)
            assert a.events==b.events and a.replies==b.replies and not b.replies
    m=machine()
    for kind in range(1,8):
        health.query(m,timing_request(kind,19));assert timing_decode(m.replies[-1])['token']==19
    for state in (0,1,3):
        m=machine();health.query(m,request(1,1),state);assert not m.replies
    m=machine();m.uc.reg_write(A.UC_ARM_REG_IPSR,3);health.query(m,request(1,1));assert not m.replies
    for size in (0,1,7,9):
        m=machine();health.query(m,(request(1,1)+b'\0')[:size]);assert not m.replies
    for index in range(8):
        packet=bytearray(request(1,1));packet[index]^=128
        m=machine();health.query(m,packet);assert not m.replies
    passed('original_editor_dispatch_legacy_timing_wrong_sessions_and_invalid_requests_remain_unchanged')

    m=machine();m.hooks.pop(0x80031648);given=[];ring=0x8062ad84
    put32(m,0x8062cd84,8190);put32(m,0x8062cd8c,8192)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    meter,h=stack_meter(m)
    health.query(m,request(41,17));m.uc.hook_del(h)
    packet=bytes(m.uc.mem_read(ring+8190,2))+bytes(m.uc.mem_read(ring,151))
    assert decode(packet)['token']==17 and word(m,0x8062cd84)==151 and given==[0x7111,0x7112]
    m.uc.mem_write(STACK-1024,b'\x3c'*1024)
    assert packet==bytes(m.uc.mem_read(ring+8190,2))+bytes(m.uc.mem_read(ring,151))
    passed('original_protected_wrapping_MIDI_ring_copies_largest_153_byte_stack_reply_before_return',
           modeled_query_stack_bytes=meter['stack_bytes'],modeled_query_instructions=meter['instructions'])

    rigs=[health.TimedSd(),health.TimedSd()];overlay(rigs[1].m)
    meters=[];file_lock_before_close=None
    for r in rigs:
        context(r.m,r.task)
        native_take=r.m.hooks[0x80076950];native_give=r.m.hooks[0x800763d8]
        def take(a,r=r,native_take=native_take):advance(r.m,11);return native_take(a)
        def give(a,r=r,native_give=native_give):advance(r.m,3);return native_give(a)
        r.m.hooks[0x80076950]=take;r.m.hooks[0x800763d8]=give
        meter,h=stack_meter(r.m)
        assert r.io(READ,1024)==(0,1024)
        assert r.io(WRITE,1024,pattern(1024,37))==(0,1024)
        if r is rigs[1]:
            file_lock_before_close=dict(zip(LOCK_FIELDS,struct.unpack('<25I',r.m.uc.mem_read(STATE+100,100))))
        assert r.close()==0
        r.m.uc.hook_del(h);meters.append(meter)
    a,b=rigs;assert a.sectors==b.sectors and a.triples()==b.triples() and len(a.requests)==len(b.requests)
    b.m.replies=[];b.m.hooks[0x80031648]=lambda a:b.m.replies.append(bytes(b.m.uc.mem_read(a[0],a[1]))) or 0
    p=file_page(b.m);fs,sd=lock_page(b.m),lock_page(b.m,kind=2)
    assert p['calls']==2 and p['errors']==0,p
    assert fs['calls']>=2 and fs['max_wait']==11 and fs['max_give_ticks']==3
    assert fs['max_held']>sd['max_held']>=7
    c=file_lock_before_close
    assert c['peak_held_job'] in (1,2) and c['peak_held_amount']==1024 and c['peak_held_identity']==HANDLE,c
    # CLOSE can have the largest held interval; it has no parent READ/WRITE job.
    assert fs['peak_held_job']==fs['peak_held_amount']==fs['peak_held_identity']==0
    assert fs['flags']==sd['flags']==0
    passed('original_native_file_SD_sectors_requests_results_and_close_match_baseline_with_parent_job_attribution',
           public_file_peak=p['max_ticks'],public_peak_operation=p['peak_operation'],
           filesystem_held_lower_bound=fs['max_held'],SD_held_lower_bound=sd['max_held'],
           file_lock_before_close=file_lock_before_close,
           modeled_baseline=meters[0],modeled_probe=meters[1],
           modeled_stack_difference=meters[1]['stack_bytes']-meters[0]['stack_bytes'])

    r=health.TimedSd();overlay(r.m);context(r.m,r.task);r.inject=(3,r.physical(2),'data')
    r.m.uc.mem_write(BUFFER,pattern(1024,37));put32(r.m,RESULT,0xdeadbeef)
    r.m.invoke(WRITE,[HANDLE,BUFFER,1024,RESULT]);assert r.stalled
    frame=r.frame();requests=list(r.requests);before=bytes(r.m.uc.mem_read(STATE,STATE_BYTES))
    pending=r.m.uc.context_save();saved_stack=getattr(r.m,'stack',STACK);r.m.replies=[]
    r.m.hooks[0x80031648]=lambda a:r.m.replies.append(bytes(r.m.uc.mem_read(a[0],a[1]))) or 0
    try:
        r.m.stack=0x20030000;context(r.m,OWNERS[1])
        assert file_page(r.m)['operation']==2 and file_page(r.m)['observer_consistent']
        assert lock_page(r.m)['flags']==2 and lock_page(r.m,kind=2)['flags']==2
        assert bytes(r.m.uc.mem_read(STATE,STATE_BYTES))==before
    finally:r.m.uc.context_restore(pending);r.m.stack=saved_stack;context(r.m,r.task)
    assert r.frame()==frame and r.owner() and r.requests==requests
    r.stalled=False;r.resume();assert r.stalled and r.frame()==frame and r.requests==requests
    r.join_allowed=True;r.stalled=False;r.resume()
    assert r.m.uc.reg_read(A.UC_ARM_REG_R0)==IO_ERROR and not r.owner()
    assert file_page(r.m)['errors']==1 and file_page(r.m)['last_result']==IO_ERROR
    assert lock_page(r.m)['flags']==lock_page(r.m,kind=2)['flags']==0
    assert r.requests==requests
    passed('queryable_pending_task_and_tokens_preserve_native_failure_stack_until_explicit_MODELED_join')

    report=dict(passed=True,groups=len(cases),results=cases,trial_sha256=digest(TRIAL),
        limits=['No device operation; kernel scheduling, sectors, DMA/cache and completion are fixtures.',
          'Held body starts at successful take return and ends at give entry; a lower bound, including scheduling.',
          'Eight permanent stable-TCB slots; task deletion/reuse and nested acquisition are unsupported observations.',
          'Pages are independent snapshots; no added consumer blackout, physical timing/stack reserve or completion proof.'])
    (OUT/'offline_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases),trial_sha256=digest(TRIAL))))
if __name__=='__main__':main()
