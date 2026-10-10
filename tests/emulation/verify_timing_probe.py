#!/usr/bin/env python3
"""Trial 05 exact image, native file/SD timing, protocol and failure ownership.

Offline only. Kernel scheduling, sector/DMA effects and physical joins are models.
"""
import hashlib,json,struct,sys
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT,STACK,request as pad_query,assignment
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_memory_layout import HEAP_STATE
from verify_native_filesystem_sd import READ,WRITE,HANDLE,BUFFER,RESULT,pattern,IO_ERROR
import verify_health_probe as health
sys.path[:0]=[str(ROOT/'tools/firmware'),str(ROOT/'tools/device')]
from build_timing_probe import OUT,ELF,ENTRY,END,HOOKS,STATE_BYTES,trial
from build_deployment_probe import validate,digest
from l6_timing_probe import request,decode,STATS_FIELDS,OP_FIELDS
from l6_health_probe import request as old_request,decode as old_decode

TRIAL=(OUT/'trial_timing_probe/L6.BIN').read_bytes()
with ELF.open('rb') as f:
    e=ELFFile(f);CODE=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD').data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
STATE=SYMS['timing_stats'];TICKS=health.TICKS
def overlay(m):
    m.uc.mem_write(ENTRY,CODE)
    for site in HOOKS.values():m.uc.mem_write(site,TRIAL[site-BIAS:site-BIAS+4])
def machine():
    m=health.machine(False);overlay(m);return m
def query(m,kind,token=1):
    health.query(m,request(kind,token));return decode(m.replies[-1])
def stats(m,scope=0):return struct.unpack('<37I',m.uc.mem_read(STATE+scope*148,148))

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    expected,manifest=trial(CODE,SYMS);assert expected==TRIAL;validate(TRIAL)
    assert ENTRY<=STATE and STATE+STATE_BYTES==ENTRY+len(CODE)<=END
    assert CODE[STATE-ENTRY:]==bytes(STATE_BYTES)
    allowed=[(0x1fc,0x200),(health.SCATTER-BIAS+12,health.SCATTER-BIAS+16),
             (health.DSP_SOURCE-BIAS,END-BIAS)]+[(p-BIAS,p-BIAS+4) for p in HOOKS.values()]
    assert all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(IMAGE,TRIAL)) if x!=y)
    assert len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    passed('exact_whitelisted_image_retains_container_regions_and_loaded_zero_state',code_bytes=len(CODE),state_bytes=STATE_BYTES)
    a,_=health.startup(IMAGE);b,_=health.startup(TRIAL);assert a==b
    passed('original_entry_and_all_eight_scatter_outputs_remain_byte_exact')
    with ELF.open('rb') as f:
        e=ELFFile(f);symbols=e.get_section_by_name('.symtab')
        names={s.name for s in symbols.iter_symbols()}
        assert not any(n.startswith(('extra_','native_worker','life_','manager_','__aeabi_f')) for n in names)
        for s in symbols.iter_symbols():
            if s['st_info']['type']!='STT_FUNC' or not s['st_size'] or not isinstance(s['st_shndx'],int):continue
            section=e.get_section(s['st_shndx']);offset=(s['st_value']&~1)-section['sh_addr']
            for i in Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(section.data()[offset:offset+s['st_size']],s['st_value']&~1):
                assert not i.mnemonic.startswith('v'),(s.name,i.mnemonic)
    passed('compiled_observers_are_integer_only_and_exclude_capture_or_extra_tasks')

    m=machine();calls=[];durations=iter((30,140,7,17))
    def original(a):
        packet=bytes(m.uc.mem_read(a[0],20));calls.append(packet)
        put32(m,TICKS,(word(m,TICKS)+next(durations))&0xffffffff)
        return 0xffffd8ef if len(calls)==2 else 0
    m.hooks[SYMS['health_sd_original']&~1]=original
    for op,unit,amount,sector in ((2,1,8,9),(3,1,8,10),(2,2,1,11),(3,1,16,12)):
        packet=struct.pack('<BBH4I',op,unit,0,0,BUFFER,amount,sector)
        m.uc.mem_write(INPUT,packet);result=m.invoke(HOOKS['health_sd'],[INPUT])
        assert result==(0xffffd8ef if len(calls)==2 else 0)
    read,write,other=query(m,2),query(m,3),query(m,4)
    assert read['calls']==1 and read['maximum_ticks']==30 and read['bin_17_64']==1
    assert write['calls']==2 and write['errors']==1 and write['first_error']==0xffffd8ef
    assert write['last_result']==0 and write['maximum_ticks']==140 and write['peak_amount']==8 and write['peak_id']==10
    assert write['largest_amount']==16 and write['bin_129_256']==1 and write['bin_17_64']==1
    assert other['calls']==1 and other['maximum_ticks']==7 and other['packet_unit']==2
    assert all(x['observer_consistent'] and not x['physical_completion_proven'] for x in (read,write,other))
    passed('separate_read_write_unit_peaks_sizes_sectors_first_error_and_histograms')

    m=machine();durations=iter((0,1,4,5,16,17,64,65,128,129,256,257,512,513))
    m.hooks[SYMS['health_sd_original']&~1]=lambda a:put32(m,TICKS,(word(m,TICKS)+next(durations))&0xffffffff) or 0
    packet=struct.pack('<BBH4I',2,1,0,0,BUFFER,8,99);m.uc.mem_write(INPUT,packet)
    put32(m,TICKS,0xfffffffe)
    for _ in range(14):assert m.invoke(HOOKS['health_sd'],[INPUT])==0
    d=query(m,2);assert [d[n] for n in OP_FIELDS[9:]]==[1,2,2,2,2,2,2,1]
    assert d['calls']==14 and d['maximum_ticks']==513 and d['last_ticks']==513
    passed('all_histogram_boundaries_and_unsigned_tick_wrap')

    m=machine();original_calls=[]
    m.hooks[SYMS['health_sd_original']&~1]=lambda a:original_calls.append(a[0]) or 19
    m.uc.mem_write(INPUT,packet);put32(m,STATE,3)
    assert m.invoke(HOOKS['health_sd'],[INPUT])==19
    assert stats(m)[:3]==(3,1,0) and not query(m,2)['observer_consistent']
    # Model a failed exclusive claim exactly at the one weak STREX. The guest
    # does not retry admission; the original operation still runs once.
    put32(m,STATE,4);m.uc.mem_write(INPUT,packet)
    # Identify STREX from function-sized disassembly; unrelated data not used.
    with ELF.open('rb') as f:
        e=ELFFile(f);s=next(s for s in e.get_section_by_name('.symtab').iter_symbols() if s.name=='health_sd')
        address=s['st_value']&~1;section=e.get_section(s['st_shndx']);offset=address-section['sh_addr']
        ds=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(section.data()[offset:offset+s['st_size']],address))
    strex=next(i for i in ds if i.mnemonic=='strex');miss=[]
    def fail_claim(uc,pc,size,user):
        # Explicit fixture interception models one failed store-exclusive result
        # and skips just that STREX. No firmware bytes are replaced.
        if not miss:
            miss.append(True);dest=strex.op_str.split(',')[0]
            uc.reg_write(getattr(A,'UC_ARM_REG_'+dest.upper()),1);uc.reg_write(A.UC_ARM_REG_PC,(pc+size)|1)
    h=m.uc.hook_add(UC_HOOK_CODE,fail_claim,begin=strex.address,end=strex.address)
    assert m.invoke(HOOKS['health_sd'],[INPUT])==19;m.uc.hook_del(h)
    assert miss and stats(m)[:3]==(4,1,1) and len(original_calls)==2
    assert query(m,2)['observer_consistent']
    before=stats(m)
    for op,unit in ((6,1),(2,0),(3,3)):
        m.uc.mem_write(INPUT,struct.pack('<BBH4I',op,unit,0,0,BUFFER,8,9))
        assert m.invoke(HOOKS['health_sd'],[INPUT])==19 and stats(m)==before
    passed('busy_and_failed_weak_claim_count_separately_preserve_original_call_without_retry')

    m=machine();file_calls=[]
    def file(a):
        file_calls.append(a[:4]);put32(m,TICKS,word(m,TICKS)+81)
        put32(m,a[3],a[2]-7);return 0xffffd825
    for name in ('timing_read_original','timing_write_original'):m.hooks[SYMS[name]&~1]=file
    for address in (READ,WRITE):
        assert m.invoke(address,[HANDLE,BUFFER,4096,RESULT])==0xffffd825
        assert word(m,RESULT)==4089
    for kind in (6,7):
        d=query(m,kind);assert d['calls']==d['errors']==1 and d['maximum_ticks']==81
        assert d['peak_amount']==4096 and d['peak_id']==HANDLE and d['amount_unit']=='bytes'
    assert file_calls==[[HANDLE,BUFFER,4096,RESULT]]*2
    passed('public_file_wrapper_preserves_four_arguments_short_actual_and_error_return')

    m=machine();before=bytes(m.uc.mem_read(STATE,STATE_BYTES));heap=bytes(m.uc.mem_read(HEAP_STATE,28))
    for kind in range(1,8):
        d=query(m,kind,127);assert d['kind']==kind and d['token']==127
        assert old_decode(m.replies[-1]) is None
    assert bytes(m.uc.mem_read(STATE,STATE_BYTES))==before and bytes(m.uc.mem_read(HEAP_STATE,28))==heap
    reply=m.replies[-1];invalid=[reply[:-1],reply+b'\0']
    for index,value in ((5,8),(6,128),(11,16),(7,128),(-1,0)):
        b=bytearray(reply);b[index]=value;invalid.append(bytes(b))
    for b in invalid:
        try:decode(b)
        except ValueError:pass
        else:raise AssertionError('Malformed reply accepted')
    assert decode(b'\xf0\x52\0\0\x7c\x01\x01\xf7') is None
    for kind,token in ((0,1),(8,1),(1,128),(1,-1)):
        try:request(kind,token)
        except ValueError:pass
        else:raise AssertionError('Malformed request accepted')
    passed('all_seven_fixed_host_schemas_validate_lengths_tokens_encoding_and_read_only_queries')

    for state in range(4):
        for message in (pad_query(0,0),pad_query(1,3,130),assignment(0,0,'TAKE_A.WAV'),old_request(1,4)):
            a=health.machine(False);b=machine();health.query(a,message,state);health.query(b,message,state)
            assert a.events==b.events and a.replies==b.replies and not b.replies
    for state in (0,1,3):
        m=machine();health.query(m,request(1,1),state);assert not m.replies
    m=machine();m.uc.reg_write(A.UC_ARM_REG_IPSR,3);health.query(m,request(1,1));assert not m.replies
    for size in (0,1,7,9):
        m=machine();health.query(m,(request(1,1)+b'\0')[:size]);assert not m.replies
    passed('stock_editor_messages_old_protocol_wrong_sessions_and_malformed_queries_are_unaffected')

    m=machine();m.hooks.pop(0x80031648);given=[];ring=0x8062ad84
    put32(m,0x8062cd84,8190);put32(m,0x8062cd8c,8192)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    health.query(m,request(7,17));packet=bytes(m.uc.mem_read(ring+8190,2))+bytes(m.uc.mem_read(ring,116))
    assert decode(packet)['token']==17 and word(m,0x8062cd84)==116 and given==[0x7111,0x7112]
    m.uc.mem_write(STACK-512,b'\x3c'*512)
    assert packet==bytes(m.uc.mem_read(ring+8190,2))+bytes(m.uc.mem_read(ring,116))
    passed('original_protected_MIDI_ring_copies_full_118_byte_stack_reply_before_return')

    # Public-file timing starts before native token acquisition, SD observation
    # starts later. Controlled lock-wait ticks prove the measurement boundary.
    rigs=[health.TimedSd(),health.TimedSd()];overlay(rigs[1].m)
    for r in rigs:
        original_take=r.m.hooks[0x80076950]
        def take(a,r=r,original_take=original_take):
            put32(r.m,TICKS,word(r.m,TICKS)+11);return original_take(a)
        r.m.hooks[0x80076950]=take
        assert r.io(READ,1024)==(0,1024)
        assert r.io(WRITE,1024,pattern(1024,37))==(0,1024)
        assert r.close()==0
    a,b=rigs;assert a.sectors==b.sectors and a.triples()==b.triples()
    assert len(a.requests)==len(b.requests)
    # Query with the fixture sender intercepted after all native operations.
    b.m.replies=[];b.m.hooks[0x80031648]=lambda a:b.m.replies.append(bytes(b.m.uc.mem_read(a[0],a[1]))) or 0
    sd,file=query(b.m,3),query(b.m,7)
    assert file['calls']==1 and file['maximum_ticks']>sd['maximum_ticks'] and file['peak_amount']==1024
    passed('native_file_SD_sectors_requests_and_results_match_baseline_public_timing_includes_locks',
           public_write_ticks=file['maximum_ticks'],SD_write_ticks=sd['maximum_ticks'])

    r=health.TimedSd();overlay(r.m);r.inject=(3,r.physical(2),'data')
    r.m.uc.mem_write(BUFFER,pattern(1024,37));put32(r.m,RESULT,0xdeadbeef)
    r.m.invoke(WRITE,[HANDLE,BUFFER,1024,RESULT]);assert r.stalled and stats(r.m)[0]&1 and stats(r.m,2)[0]&1
    frame=r.frame();requests=list(r.requests);before=bytes(r.m.uc.mem_read(STATE,STATE_BYTES))
    context=r.m.uc.context_save();saved_stack=getattr(r.m,'stack',STACK);r.m.replies=[]
    r.m.hooks[0x80031648]=lambda a:r.m.replies.append(bytes(r.m.uc.mem_read(a[0],a[1]))) or 0
    try:
        r.m.stack=0x20030000
        for kind in (3,7):assert not query(r.m,kind)['observer_consistent']
        assert bytes(r.m.uc.mem_read(STATE,STATE_BYTES))==before
    finally:r.m.uc.context_restore(context);r.m.stack=saved_stack
    assert r.frame()==frame and r.owner() and r.requests==requests
    r.stalled=False;r.resume();assert r.stalled and r.frame()==frame and r.requests==requests
    r.join_allowed=True;r.stalled=False;r.resume()
    assert r.m.uc.reg_read(A.UC_ARM_REG_R0)==IO_ERROR and not r.owner()
    assert stats(r.m)[0]%2==stats(r.m,2)[0]%2==0
    assert stats(r.m)[3+17+2]==0xffffd8ef # SD write first_error
    assert stats(r.m,2)[3+17+2]==IO_ERROR # public write first_error
    assert r.requests==requests
    passed('both_observers_retain_live_failure_stacks_and_tokens_until_explicit_MODELED_join')

    report=dict(passed=True,groups=len(cases),results=cases,trial_sha256=digest(TRIAL),
        limits=['No device operation; RTOS, sectors, DMA/cache and completion are fixtures',
          'Counters/histograms are modulo uint32 and skipped calls remain unmeasured',
          'No extra-capture load, physical timing/stack/heap reserve or completion proof'])
    (OUT/'offline_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases),trial_sha256=digest(TRIAL))))
if __name__=='__main__':main()
