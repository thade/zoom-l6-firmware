#!/usr/bin/env python3
"""Exact experiment 06 image and original allocator/scheduler nesting offline.

Interrupts, task execution, critical sections and physical heap/audio are not
emulated. Original alloc/free/suspend/resume bodies execute with no ready tasks.
"""
import json,struct,sys
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT,RETURN,STACK,request as pad_request,assignment
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_memory_layout import HEAP_STATE,HEAP_START,HEAP_END,INITIAL_FREE
import verify_health_probe as health
sys.path[:0]=[str(ROOT/'tools/firmware'),str(ROOT/'tools/device')]
from build_reservation_probe import OUT,ELF,HEAP_ELF,ENTRY,END,HOOKS,budget,trial
from build_deployment_probe import validate,digest
from l6_reservation_probe import request,decode,FIELDS
from l6_timing_probe import request as timing_request,decode as timing_decode

TRIAL=(OUT/'trial_reservation_probe/L6.BIN').read_bytes()
with ELF.open('rb') as f:
    elf=ELFFile(f);CODE=next(s for s in elf.iter_segments() if s['p_type']=='PT_LOAD').data()
    SYMS={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
STATE=SYMS['reservation_stats'];ALLOC=0x8006de78;FREE=0x80073f48
SUSPEND_DEPTH=0x801f904c

def overlay(m):
    m.uc.mem_write(ENTRY,CODE)
    for site in HOOKS.values():m.uc.mem_write(site,TRIAL[site-BIAS:site-BIAS+4])
def machine():
    m=health.machine(False);overlay(m);return m
def query(m,kind=1,token=1):
    health.query(m,request(kind,token));return decode(m.replies[-1])

class Heap:
    def __init__(self,free=163104):
        self.m=machine();m=self.m
        m.uc.mem_map(0xe000e000,0x1000)
        # Original scheduler helpers run; BASEPRI critical section helpers and
        # the list of ready/pending tasks are explicit fixture inputs.
        m.hooks[0x80073ec8]=lambda a:0;m.hooks[0x80073f18]=lambda a:0
        assert m.invoke(ALLOC,[0])==0
        assert word(m,HEAP_STATE+4)==INITIAL_FREE
        self.occupied=[]
        if free is not None:
            n=INITIAL_FREE-free-16
            if n:
                p=m.invoke(ALLOC,[n]);assert p
                m.uc.mem_write(p,b'\x3c'*n);self.occupied.append((p,n))
            assert word(m,HEAP_STATE+4)==free
        put32(m,0x801f9048,1);put32(m,0x801f9044,1);put32(m,0x808e291c,0x20022000)
        self.alloc_calls=[];self.free_calls=[];self.depths=[];self.fail=None
        def allocate(uc,pc,size,user):
            self.alloc_calls.append(uc.reg_read(A.UC_ARM_REG_R0))
            self.depths.append(word(m,SUSPEND_DEPTH))
            if self.fail==len(self.alloc_calls):
                uc.reg_write(A.UC_ARM_REG_R0,0);uc.reg_write(A.UC_ARM_REG_PC,uc.reg_read(A.UC_ARM_REG_LR))
        def free_call(uc,pc,size,user):self.free_calls.append(uc.reg_read(A.UC_ARM_REG_R0))
        m.uc.hook_add(UC_HOOK_CODE,allocate,begin=ALLOC,end=ALLOC)
        m.uc.hook_add(UC_HOOK_CODE,free_call,begin=FREE,end=FREE)
    def check_occupied(self):
        for p,n in self.occupied:assert bytes(self.m.uc.mem_read(p,n))==b'\x3c'*n

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    b=budget();expected,r=trial(CODE,SYMS,b);assert expected==TRIAL;validate(TRIAL)
    assert r['code_bytes']==len(CODE) and ENTRY+len(CODE)<=END
    assert SYMS['timing_stats']+444<=STATE and STATE+32==ENTRY+len(CODE)
    assert CODE[SYMS['timing_stats']-ENTRY:]==bytes(r['state_bytes'])
    allowed=[(0x1fc,0x200),(health.SCATTER-BIAS+12,health.SCATTER-BIAS+16),
             (health.DSP_SOURCE-BIAS,END-BIAS)]+[(p-BIAS,p-BIAS+4) for p in HOOKS.values()]
    assert all(any(a<=i<c for a,c in allowed) for i,(x,y) in enumerate(zip(IMAGE,TRIAL)) if x!=y)
    assert len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    a,_=health.startup(IMAGE);c,_=health.startup(TRIAL);assert a==c
    passed('exact_whitelisted_image_zero_state_unchanged_MAIN_length_and_all_eight_startup_outputs',
           code_bytes=len(CODE),state_bytes=r['state_bytes'])

    m=machine()
    m.uc.mem_map(0x10010000,0x10000)
    with HEAP_ELF.open('rb') as f:
        e=ELFFile(f)
        for seg in e.iter_segments():
            if seg['p_type']=='PT_LOAD' and seg['p_filesz']:m.uc.mem_write(seg['p_vaddr'],seg.data())
        names={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    assert m.invoke(names['native_arena_bytes'],[128])==b['arena_request_bytes']==77279
    assert b['expected_split_charge_bytes']==93848 and b['preflight_required_free_bytes']==159432
    with ELF.open('rb') as f:
        e=ELFFile(f);symbols=list(e.get_section_by_name('.symtab').iter_symbols())
        assert not any(s.name.startswith(('extra_','native_worker','manager_','life_','__aeabi_f')) for s in symbols)
        for s in symbols:
            if s['st_info']['type']!='STT_FUNC' or not s['st_size'] or not isinstance(s['st_shndx'],int):continue
            section=e.get_section(s['st_shndx']);offset=(s['st_value']&~1)-section['sh_addr']
            for i in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(section.data()[offset:offset+s['st_size']],s['st_value']&~1):
                assert not i.mnemonic.startswith('v'),(s.name,i.mnemonic)
    passed('budget_matches_actual_compiled_arena_ABI_and_trial_has_no_capture_worker_or_FP')

    h=Heap();m=h.m;heap=bytes(m.uc.mem_read(HEAP_STATE,28));state=bytes(m.uc.mem_read(STATE,32))
    d=query(m);assert d['status']=='untried' and d['observer_consistent'] and not d['reservation_held']
    assert heap==bytes(m.uc.mem_read(HEAP_STATE,28)) and state==bytes(m.uc.mem_read(STATE,32))
    assert not h.alloc_calls and not h.free_calls
    passed('status_query_is_read_only_and_never_arms_reservation')

    writes=[]
    hook=m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda uc,access,address,size,value,user:writes.append((address,size)),
                       begin=HEAP_START,end=HEAP_END-1)
    d=query(m,2);m.uc.hook_del(hook)
    assert d['reservation_held'] and d['free_before']==163104
    assert d['free_after']==69256 and d['actual_charge_bytes']==93848
    assert h.alloc_calls==[77279,16384,148] and h.depths==[1,1,1] and not h.free_calls
    assert word(m,SUSPEND_DEPTH)==d['scheduler_suspend_depth']==0
    pointers=[d[n] for n in ('arena_pointer','stack_pointer','task_pointer')]
    assert all(p and p%8==0 for p in pointers)
    assert all(HEAP_START<=p-8<p+n<=HEAP_END-8 for p,n in zip(pointers,h.alloc_calls))
    assert all(address+size<=p or address>=p+n for address,size in writes for p,n in zip(pointers,h.alloc_calls))
    after=bytes(m.uc.mem_read(HEAP_STATE,28));held=bytes(m.uc.mem_read(STATE,32))
    for _ in range(3):assert query(m,2)['reservation_held'] and query(m)['reservation_held']
    assert h.alloc_calls==[77279,16384,148] and not h.free_calls
    assert after==bytes(m.uc.mem_read(HEAP_STATE,28)) and held==bytes(m.uc.mem_read(STATE,32))
    h.check_occupied()
    passed('original_allocator_holds_exact_three_blocks_preserves_other_payloads_and_never_retries',
           free_before=163104,free_after=69256,actual_charge_bytes=93848)

    for free,status in ((159424,'headroom_refused'),(159432,'held')):
        h=Heap(free);d=query(h.m,2);assert d['status']==status
        assert d['free_after']>=65536 and word(h.m,SUSPEND_DEPTH)==0
        if status=='headroom_refused':assert not h.alloc_calls and d['actual_charge_bytes']==0
        h.check_occupied()
    passed('headroom_guard_rejects_before_allocation_and_accepts_exact_guard_boundary')

    # Native allocations consume a whole free block when a split would leave
    # only 16 bytes. Construct that worst case separately for all three sizes.
    h=Heap(None);m=h.m;chunks=[]
    for charge in (77304,16416,176):
        chunks.append(m.invoke(ALLOC,[charge-16]));assert chunks[-1]
        assert m.invoke(ALLOC,[64]) # Keep free chunks separate after release.
    remaining=word(m,HEAP_STATE+4)
    assert m.invoke(ALLOC,[remaining-65536-16])
    for p in chunks:m.invoke(FREE,[p])
    assert word(m,HEAP_STATE+4)==159432
    h.alloc_calls.clear();h.free_calls.clear();h.depths.clear()
    d=query(m,2);assert d['reservation_held'] and d['actual_charge_bytes']==93896
    assert d['free_after']==65536 and word(m,SUSPEND_DEPTH)==0
    passed('all_three_native_unsplittable_remainders_consume_48_extra_bytes_without_breaching_floor')

    for fail in (1,2,3):
        h=Heap();h.fail=fail;d=query(h.m,2)
        assert d['status']=='allocation_failed' and d['observer_consistent']
        assert d['free_before']==d['free_after']==163104 and not d['actual_charge_bytes']
        assert not any(d[n] for n in ('arena_pointer','stack_pointer','task_pointer'))
        assert len(h.free_calls)==fail-1 and word(h.m,SUSPEND_DEPTH)==0
        old_calls=len(h.alloc_calls);assert query(h.m,2)['status']=='allocation_failed'
        assert len(h.alloc_calls)==old_calls;h.check_occupied()
    passed('failure_at_each_allocation_rolls_back_native_blocks_and_does_not_retry',
           limitation='Null at selected allocation is injected; other alloc/free bodies execute')

    h=Heap(None);m=h.m
    chunks=[m.invoke(ALLOC,[30000]) for _ in range(16)];assert all(chunks)
    for p in chunks[::2]:m.invoke(FREE,[p])
    before=word(m,HEAP_STATE+4);assert before>=159432
    h.alloc_calls.clear();h.free_calls.clear();h.depths.clear()
    d=query(m,2);assert d['status']=='allocation_failed' and h.alloc_calls==[77279]
    assert d['free_before']==d['free_after']==before and not h.free_calls
    passed('actual_native_fragmentation_refuses_arena_despite_sufficient_aggregate_free_heap',aggregate_free_bytes=before)

    for address,value in ((0x801f9048,0),(HEAP_STATE,0),(SUSPEND_DEPTH,1),(0x808e291c,0)):
        h=Heap();put32(h.m,address,value);d=query(h.m,2)
        assert d['status']=='context_refused' and not h.alloc_calls and not h.free_calls
        assert not d['actual_charge_bytes']
    for reg,value in ((A.UC_ARM_REG_BASEPRI,32),(A.UC_ARM_REG_PRIMASK,1)):
        h=Heap();h.m.uc.reg_write(reg,value);d=query(h.m,2)
        assert d['status']=='context_refused' and not h.alloc_calls and not h.free_calls
        assert h.m.uc.reg_read(reg)==value
    passed('missing_scheduler_heap_task_or_existing_scheduler_hold_CPU_mask_refuses_without_allocation')

    h=Heap();m=h.m
    with ELF.open('rb') as f:
        e=ELFFile(f);s=next(s for s in e.get_section_by_name('.symtab').iter_symbols() if s.name=='reservation_dispatch')
        section=e.get_section(s['st_shndx']);offset=(s['st_value']&~1)-section['sh_addr']
        ds=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(section.data()[offset:offset+s['st_size']],s['st_value']&~1))
    # Zig may outline the reservation helper; search only actual function bodies.
    if not any(i.mnemonic=='strex' for i in ds):
        with ELF.open('rb') as f:
            e=ELFFile(f);s=next(s for s in e.get_section_by_name('.symtab').iter_symbols() if s.name=='reserve')
            section=e.get_section(s['st_shndx']);offset=(s['st_value']&~1)-section['sh_addr']
            ds=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(section.data()[offset:offset+s['st_size']],s['st_value']&~1))
    strex=next(i for i in ds if i.mnemonic=='strex');hits=[]
    def miss(uc,pc,size,user):
        hits.append(pc);dest=strex.op_str.split(',')[0]
        uc.reg_write(getattr(A,'UC_ARM_REG_'+dest.upper()),1);uc.reg_write(A.UC_ARM_REG_PC,(pc+size)|1)
    hook=m.uc.hook_add(UC_HOOK_CODE,miss,begin=strex.address,end=strex.address)
    assert query(m,2)['status']=='untried' and len(hits)==1 and not h.alloc_calls
    m.uc.hook_del(hook);assert query(m,2)['reservation_held']
    passed('failed_weak_claim_does_not_spin_or_allocate_and_explicit_retry_can_arm')

    h=Heap();m=h.m
    def pause(uc,pc,size,user):m.reached_return=True;uc.emu_stop()
    hook=m.uc.hook_add(UC_HOOK_CODE,pause,begin=ALLOC,end=ALLOC)
    health.query(m,request(2,19));context=m.uc.context_save();pc=m.uc.reg_read(A.UC_ARM_REG_PC)
    assert word(m,STATE)==1 and word(m,SUSPEND_DEPTH)==1
    m.uc.hook_del(hook);m.stack=0x20030000
    assert query(m)['status']=='busy' and not m.replies[-1]==b''
    assert not decode(m.replies[-1])['observer_consistent']
    m.uc.context_restore(context);m.stack=STACK;m.reached_return=False
    m.uc.emu_start(pc|1,RETURN+2,count=1000000);assert m.reached_return
    assert decode(m.replies[-1])['reservation_held'] and word(m,SUSPEND_DEPTH)==0
    passed('interleaved_status_reports_busy_without_consuming_partial_pointers',
           limitation='Second thread/query is a saved-context fixture; no real preemption')

    h=Heap();put32(h.m,0x801f905c,1);d=query(h.m,2)
    assert d['reservation_held'] and word(h.m,0xe000ed04)==0x10000000 and word(h.m,SUSPEND_DEPTH)==0
    passed('original_outer_resume_preserves_pending_PendSV_request',limitation='MMIO-backed register, no exception delivery')

    messages=[pad_request(0,0),pad_request(1,3,130),assignment(0,0,'TAKE_A.WAV')]
    for state in range(4):
        for message in messages:
            a=health.machine(False);c=machine();health.query(a,message,state);health.query(c,message,state)
            assert a.events==c.events and a.replies==c.replies and not c.replies
    for state in (0,1,3):
        h=Heap();health.query(h.m,request(2,1),state);assert not h.m.replies and not h.alloc_calls
    valid=request(2,1)
    bad=[valid[:-1],valid+b'\0']
    for index,value in ((0,0),(1,0),(2,1),(3,1),(4,0),(5,0),(5,3),(6,128),(7,0)):
        p=bytearray(valid);p[index]=value;bad.append(bytes(p))
    for message in bad:
        h=Heap();health.query(h.m,message)
        assert not h.m.replies and not h.alloc_calls and word(h.m,STATE)==0
    h=Heap();h.m.uc.reg_write(A.UC_ARM_REG_IPSR,3);health.query(h.m,request(2,1))
    assert not h.m.replies and not h.alloc_calls and word(h.m,STATE)==0
    for kind in range(1,8):
        m=machine();health.query(m,timing_request(kind,127));d=timing_decode(m.replies[-1]);assert d['kind']==kind
    m=machine();d=query(m,1,127);reply=m.replies[-1]
    for malformed in (reply[:-1],reply+b'\0',reply[:5]+bytes((3,))+reply[6:],reply[:11]+bytes((16,))+reply[12:]):
        try:decode(malformed)
        except ValueError:pass
        else:raise AssertionError('Malformed reservation reply accepted')
    for kind,token in ((0,1),(3,1),(1,-1),(1,128)):
        try:request(kind,token)
        except ValueError:pass
        else:raise AssertionError('Invalid fixed reservation request accepted')
    passed('ordinary_editor_and_existing_timing_queries_preserved_with_strict_new_host_schema_and_context')

    m=machine();m.hooks.pop(0x80031648);given=[];ring=0x8062ad84
    put32(m,0x8062cd84,8190);put32(m,0x8062cd8c,8192)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    health.query(m,request(1,17));packet=bytes(m.uc.mem_read(ring+8190,2))+bytes(m.uc.mem_read(ring,86))
    assert decode(packet)['token']==17 and word(m,0x8062cd84)==86 and given==[0x7111,0x7112]
    m.uc.mem_write(STACK-512,b'\x3c'*512)
    assert packet==bytes(m.uc.mem_read(ring+8190,2))+bytes(m.uc.mem_read(ring,86))
    passed('original_protected_MIDI_sender_copies_full_88_byte_reply_before_stack_expires')

    rigs=[health.TimedSd(),health.TimedSd()];overlay(rigs[1].m)
    from verify_native_filesystem_sd import READ,WRITE,pattern
    for rig in rigs:
        assert rig.io(READ,1024)==(0,1024)
        assert rig.io(WRITE,1024,pattern(1024,37))==(0,1024)
        assert rig.close()==0
    assert rigs[0].sectors==rigs[1].sectors and rigs[0].triples()==rigs[1].triples()
    assert len(rigs[0].requests)==len(rigs[1].requests)
    passed('native_file_SD_requests_sectors_and_results_remain_exact_with_new_dispatch_image')

    report=dict(passed=True,groups=len(cases),trial_sha256=digest(TRIAL),budget=b,results=cases,
        limitations=['Native allocation/free/suspend/resume execute, with critical sections/ready tasks and preemption fixtures.',
          'No physical device, MIDI, SD card or firmware installation operation.',
          'Memory reservation holds unused capacity, not a working extra recorder or worker stack test.',
          'The 64-KiB floor and 128 slots remain experimental; no guaranteed later reserve, latency or completion.'])
    (OUT/'offline_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases),trial_sha256=digest(TRIAL))))
if __name__=='__main__':main()
