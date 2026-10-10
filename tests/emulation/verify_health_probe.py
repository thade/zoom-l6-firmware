#!/usr/bin/env python3
"""Experiment 04 ABI, original DSP decoder, reply lifetime and native SD checks.
Kernel exclusion, MMIO/sector effects and error joins are fixtures, not hardware.
"""
import hashlib,json,struct,sys
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT,STACK,REGS,request as pad_query,assignment
from verify_memory_layout import HEAP_STATE,INITIAL_FREE
from verify_native_filesystem_sd import NativeFileSd,READ,WRITE,CLOSE,HANDLE,BUFFER,RESULT,word,put32,pattern,IO_ERROR
sys.path.insert(0,str(ROOT/'tools/firmware'));sys.path.insert(0,str(ROOT/'tools/device'))
from build_health_probe import OUT,ELF,ENTRY,END,DSP_SOURCE,DSP_DEST,DSP_BYTES,SCATTER,HOOKS,candidate
from build_deployment_probe import validate,digest,STOCK_SHA
from audit_capture_packing import audit
from scatter_codec import expand
from l6_health_probe import request,decode,HEAP_FIELDS,SD_FIELDS

TRIAL=(OUT/'trial_health_probe/L6.BIN').read_bytes()
with ELF.open('rb') as f:
    e=ELFFile(f);seg=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD');CODE=seg.data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
STATE=SYMS['health_sd_stats'];TICKS=0x801f9050

def load(m):m.uc.mem_write(0x80001000,TRIAL[0x200:0xb5ce4])
def overlay(m):
    # Keep this composition's explicit test-only SD join guards in place.
    # Full-container startup/decoder checks above do not use these guards.
    m.uc.mem_write(ENTRY,CODE)
    for site in HOOKS.values():m.uc.mem_write(site,TRIAL[site-BIAS:site-BIAS+4])
def machine(patched=True):
    m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True)
    if patched:load(m)
    m.events=[];m.replies=[]
    m.hooks[0x80020ca0]=lambda a:m.events.append(a[:5]) or 0
    m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    return m
def query(m,data,state=2):
    m.uc.mem_write(INPUT,struct.pack('<I',len(data))+data+bytes(16))
    m.uc.mem_write(0x80629b60,bytes([state]));return m.invoke(0x800301f0,[INPUT])
def stats(m,unit=1):return struct.unpack('<7I',m.uc.mem_read(STATE+28*(unit-1),28))

def startup(image,extra_helpers=()):
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for address,size in ((0x80000000,0x2000000),(0x20000000,0x40000),
                         (0x20210000,0x20000),(0,0x1000)):
        u.mem_map(address,size);u.mem_write(address,b'\xa5'*size)
    u.mem_write(0x80001000,image[0x200:0xb5ce4]);entered=[];helpers=[]
    def main(uc,pc,size,user):entered.append(pc);uc.emu_stop()
    def helper(uc,pc,size,user):
        helpers.append((pc,*[uc.reg_read(reg) for reg in
                      (A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2)]))
    u.hook_add(UC_HOOK_CODE,main,begin=0x80067a60,end=0x80067a60)
    for pc in (0x80001994,0x800794a8,0x80079498,*extra_helpers):
        u.hook_add(UC_HOOK_CODE,helper,begin=pc,end=pc)
    u.emu_start(0x80001401,0x80067a62,count=100000000)
    assert entered==[0x80067a60] and u.reg_read(A.UC_ARM_REG_SP)==0x2021fff0
    assert len(helpers)==8
    hashes=[]
    for table in range(0x800a68dc,0x800a695c,16):
        src,dest,length,method=struct.unpack_from('<4I',IMAGE,table-BIAS)
        data=bytes(u.mem_read(dest,length))
        if method==0x800794a8:assert data==bytes(length)
        elif method==0x80079498:assert data==IMAGE[src-BIAS:src-BIAS+length]
        else:assert data==expand(IMAGE[src-BIAS:],length)[0]
        hashes.append(dict(destination=dest,bytes=length,sha256=hashlib.sha256(data).hexdigest()))
    if image==TRIAL:
        assert bytes(u.mem_read(ENTRY,len(CODE)))==CODE
        assert bytes(u.mem_read(STATE,56))==bytes(56)
    return hashes,helpers

class TimedSd(NativeFileSd):
    def data_deliver(self,a):
        result=super().data_deliver(a)
        put32(self.m,TICKS,(word(self.m,TICKS)+7)&0xffffffff);return result

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    expected,_=candidate(CODE,SYMS);assert TRIAL==expected;validate(TRIAL)
    assert digest(IMAGE)==STOCK_SHA and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert ENTRY<=STATE and STATE+56<=ENTRY+len(CODE)<=END
    assert bytes(CODE[STATE-ENTRY:STATE-ENTRY+56])==bytes(56)
    passed('exact_whitelisted_image_original_lengths_regions_and_loaded_zero_observer_state')

    m=machine();m.uc.mem_map(DSP_DEST,0xe000)
    m.uc.mem_write(DSP_DEST,b'\xa5'*(DSP_BYTES+16))
    s,d,n,helper=struct.unpack('<4I',m.uc.mem_read(SCATTER,16))
    assert (s,d,n,helper)==(DSP_SOURCE,DSP_DEST,DSP_BYTES,0x80001994)
    assert m.invoke(helper,[s,d,n])==0
    assert bytes(m.uc.mem_read(d,n))==IMAGE[DSP_SOURCE-BIAS:DSP_SOURCE-BIAS+n]
    assert bytes(m.uc.mem_read(d+n,16))==b'\xa5'*16
    assert bytes(m.uc.mem_read(ENTRY,len(CODE)))==CODE
    passed('original_startup_decoder_restores_entire_stock_DSP_byte_exact_and_does_not_touch_probe')

    stock_outputs,stock_helpers=startup(IMAGE);trial_outputs,trial_helpers=startup(TRIAL)
    assert stock_outputs==trial_outputs
    assert trial_helpers[:4]==stock_helpers[:4] and trial_helpers[5:]==stock_helpers[5:]
    assert trial_helpers[4]==(0x80001994,DSP_SOURCE,DSP_DEST,DSP_BYTES)
    passed('actual_entry_and_all_eight_scatter_helpers_preserve_original_startup_outputs_and_loaded_probe',
           original_outputs=trial_outputs)

    r=audit();assert not r['unresolved_raw_candidates'] and not r['unresolved_decoded_candidates'] and not r['bounded_movw_movt_candidates']
    passed('bounded_existing_DSP_source_reference_audit_has_no_unresolved_candidates',halfword_decodes=r['halfword_decodes'])

    m=machine();m.hooks[0x80074780]=m.hooks[0x80077540]=lambda a:0
    pointers=[m.invoke(0x8006de78,[n]) for n in (16,4096,65536)];assert all(pointers)
    m.invoke(0x80073f48,[pointers[1]])
    expected_heap=struct.unpack('<5I',m.uc.mem_read(HEAP_STATE,20))
    assert expected_heap[0]==0x8095ffd0 and expected_heap[1]<INITIAL_FREE
    before=bytes(m.uc.mem_read(HEAP_STATE,28));writes=[]
    h=m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda uc,k,p,n,v,u:writes.append((p,n)))
    for token in (0,1,127):
        query(m,request(1,token));d=decode(m.replies[-1])
        assert tuple(d[name] for name in HEAP_FIELDS[:5])==expected_heap and d['token']==token and d['heap_initialized']
    m.uc.hook_del(h)
    assert bytes(m.uc.mem_read(HEAP_STATE,28))==before and stats(m)==(0,)*7
    assert all(STACK-256<=p and p+n<=STACK for p,n in writes)
    passed('reports_original_allocator_live_counters_with_no_heap_observer_or_nonstack_writes',heap_words=list(expected_heap))

    reply=m.replies[-1];invalid=[reply[:-1],reply[:-1]+b'\0\xf7']
    for index,value in ((5,4),(6,128),(11,16),(7,128),(-1,0)):
        data=bytearray(reply);data[index]=value;invalid.append(bytes(data))
    for data in invalid:
        try:decode(data)
        except ValueError:pass
        else:raise AssertionError('Malformed diagnostic reply accepted')
    assert decode(b'\xf0\x52\0\0\x45\0\0\xf7') is None
    for kind,token in ((0,0),(4,0),(1,-1),(1,128)):
        try:request(kind,token)
        except ValueError:pass
        else:raise AssertionError('Invalid diagnostic request accepted')
    passed('host_schema_rejects_bad_length_kind_token_7bit_encoding_uint32_overflow_and_terminator')

    for state in range(4):
        messages=[pad_query(0,0),pad_query(1,3,130),pad_query(2,1),assignment(0,0,'TAKE_A.WAV')]
        for data in messages:
            a=machine(False);b=machine();query(a,data,state);query(b,data,state)
            assert a.events==b.events and a.replies==b.replies and not b.replies
            assert bytes(a.uc.mem_read(0x80629b58,16))==bytes(b.uc.mem_read(0x80629b58,16))
    passed('original_count_filename_assignment_and_session_dispatch_preserved')

    data=request(1,4)
    invalid=[data[:n] for n in (0,1,7)]+[data+b'\0']
    for i in range(8):
        b=bytearray(data);b[i]^=128;invalid.append(bytes(b))
    for data in invalid:
        a=machine(False);b=machine();query(a,data);query(b,data)
        assert a.events==b.events and a.replies==b.replies
    for state in (0,1,3):
        m=machine();query(m,request(1,1),state);assert not m.replies
    m=machine();m.uc.reg_write(A.UC_ARM_REG_IPSR,3);query(m,request(1,1));assert not m.replies
    passed('malformed_length_bytes_wrong_session_and_handler_context_do_not_answer_diagnostics')

    m=machine();m.hooks.pop(0x80031648)
    ring=0x8062ad84;capacity=8192;index=capacity-3;given=[]
    put32(m,0x8062cd84,index);put32(m,0x8062cd8c,capacity)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x80076950]=lambda a:1
    m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    query(m,request(1,17))
    packet=bytes(m.uc.mem_read(ring+index,3))+bytes(m.uc.mem_read(ring,70))
    assert decode(packet)['token']==17 and word(m,0x8062cd84)==70
    assert given==[0x7111,0x7112]
    m.uc.mem_write(STACK-256,b'\x3c'*256)
    assert packet==bytes(m.uc.mem_read(ring+index,3))+bytes(m.uc.mem_read(ring,70))
    passed('original_sender_copies_stack_reply_into_protected_wrapping_editor_ring_before_return')

    m=machine();calls=[];durations=[30,10,7]
    def original(a):
        calls.append(bytes(m.uc.mem_read(a[0],20)));put32(m,TICKS,(word(m,TICKS)+durations.pop(0))&0xffffffff);return 17
    m.hooks[SYMS['health_sd_original']&~1]=original
    for op,unit in ((2,1),(3,1),(2,2)):
        m.uc.mem_write(INPUT,bytes((op,unit))+bytes(18));assert m.invoke(0x80068378,[INPUT])==17
    assert stats(m)==(4,1,1,0,17,10,30) and stats(m,2)==(2,1,0,0,17,7,7)
    query(m,request(2,5));d=decode(m.replies[-1]);assert d['observer_consistent'] and d['maximum_ticks']==30
    query(m,request(3,6));assert decode(m.replies[-1])['packet_unit']==2
    assert len(calls)==3
    passed('one_original_SD_call_per_observation_result_duration_maximum_and_two_unit_attribution')

    m=machine();calls=[]
    def original(a):calls.append(a[0]);put32(m,TICKS,(word(m,TICKS)+9)&0xffffffff);return 0x12345678
    m.hooks[SYMS['health_sd_original']&~1]=original
    put32(m,TICKS,0xfffffffc);m.uc.mem_write(INPUT,b'\x03\x01'+bytes(18))
    assert m.invoke(0x80068378,[INPUT])==0x12345678 and stats(m)[5:]==(9,9)
    put32(m,STATE,3);m.invoke(0x80068378,[INPUT]);assert stats(m)[0]==3 and stats(m)[3]==1
    query(m,request(2,3));assert not decode(m.replies[-1])['observer_consistent']
    snapshot=stats(m)
    for op,unit in ((6,1),(2,0),(3,3)):
        m.uc.mem_write(INPUT,bytes((op,unit))+bytes(18));assert m.invoke(0x80068378,[INPUT])==0x12345678
        assert stats(m)==snapshot
    assert len(calls)==5
    passed('tick_wrap_busy_observer_and_nondata_requests_preserve_stock_call_without_wait_reset_or_retry')

    baseline=TimedSd();patched=TimedSd();overlay(patched.m)
    payload=pattern(1024,37)
    for r in (baseline,patched):
        assert r.io(READ,1024)==(0,1024)
        assert r.io(WRITE,1024,payload)==(0,1024)
        assert r.close()==0
    assert baseline.sectors==patched.sectors and baseline.triples()==patched.triples()
    s=stats(patched.m);assert s[0]%2==0 and s[1]+s[2]==sum(q['op'] in (2,3) for q in patched.requests)
    assert s[5]>=7 and s[6]>=7 and s[3]==0
    passed('original_files_SD_DMA_and_close_behavior_matches_unpatched_baseline_with_no_extra_requests',observed_transfers=s[1]+s[2])

    r=TimedSd();overlay(r.m);r.inject=(3,r.physical(2),'data')
    # io() asserts completed lock release; this call intentionally stays live.
    r.m.uc.mem_write(BUFFER,payload);put32(r.m,RESULT,0xdeadbeef)
    r.m.invoke(WRITE,[HANDLE,BUFFER,1024,RESULT]);assert r.stalled and stats(r.m)[0]&1
    frame=r.frame();requests=list(r.requests)
    # A concurrent editor task can observe an incomplete call without touching
    # its live SD/file stack, counters or tokens. Scheduling remains modeled.
    context=r.m.uc.context_save();saved_stack=getattr(r.m,'stack',STACK)
    before=stats(r.m);replies=[]
    r.m.hooks[0x80031648]=lambda a:replies.append(bytes(r.m.uc.mem_read(a[0],a[1]))) or 0
    try:
        r.m.stack=0x20030000;query(r.m,request(2,31))
        assert not decode(replies[-1])['observer_consistent'] and stats(r.m)==before
    finally:
        r.m.uc.context_restore(context);r.m.stack=saved_stack
    assert r.frame()==frame and r.owner() and r.requests==requests
    r.stalled=False;r.resume();assert r.stalled and r.frame()==frame and r.requests==requests
    assert stats(r.m)[0]&1
    r.join_allowed=True;r.stalled=False;r.resume()
    assert r.m.uc.reg_read(A.UC_ARM_REG_R0)==IO_ERROR and stats(r.m)[0]%2==0
    assert stats(r.m)[4]==0xffffd8ef # native SD -10001, public file -10201
    assert r.requests==requests and not r.owner()
    passed('observer_does_not_unwind_or_retry_retained_native_SD_failure_before_MODELED_join')

    report=dict(passed=True,groups=len(cases),results=cases,trial_sha256=digest(TRIAL),
        limitations=['Offline partial execution with controlled heap, tasks, sectors, DMA, IRQ/cache and completion ports.',
            'Reference audit is bounded and cannot exclude all computed/bootloader users of retired source bytes.',
            'Native return/duration is observational; physical completion and live stack/timing remain unmeasured.',
            'No capture or device operation performed by this verification.'])
    (OUT/'offline_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases),trial_sha256=digest(TRIAL))))
if __name__=='__main__':main()
