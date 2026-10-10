#!/usr/bin/env python3
"""Passive upper-gap query, host coverage and retained exact-image diagnostics.

All memory/controller values and concurrent changes are fixtures. No physical
RAM, cache/DMA, RTOS timing, device safety or unused-space proof is supplied.
"""
import contextlib
import hashlib
import io
import json
import queue
import struct
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import patch

from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ
from unicorn import arm_const as A
from verify_pad_protocol import ROOT, INPUT, STACK, IMAGE
from verify_health_probe import query
from verify_memory_layout import word
from verify_firmware_workflow import put32
import verify_memory_capacity_probe as memory
from build_ram_activity_probe import ELF, ENTRY, OUT, STATES, trial
sys.path.insert(0,str(ROOT/'tools/device'))
import l6_health_probe as health
from l6_ram_activity_probe import FIELDS,GAP_START,PAGE_BYTES,PAGE_COUNT,request,decode,fingerprint,reply_matches,summarize,compare,read_log

with ELF.open('rb') as f:
    e=ELFFile(f);seg=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD');CODE=seg.data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    FUNCTIONS=[(s.name,s['st_value']&~1,s['st_size']) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type']=='STT_FUNC' and s['st_size']]
TRIAL,MANIFEST=trial(CODE,SYMS)
for key,val in dict(ELF=ELF,CODE=CODE,SYMS=SYMS,FUNCTIONS=FUNCTIONS,TRIAL=TRIAL,MANIFEST=MANIFEST,STATES=STATES).items():
    setattr(memory,key,val)

def machine(values=memory.CONTENTS):
    m=memory.machine(values);m.uc.mem_map(0x81000000,0x1000000)
    m.gap_reads=[];m.instructions=0
    def read(uc,k,a,n,v,s):m.gap_reads.append((a,n))
    m.uc.hook_add(UC_HOOK_MEM_READ,read,begin=GAP_START-PAGE_BYTES,end=0x82000000+PAGE_BYTES-1)
    def count(uc,pc,n,u):m.instructions+=1
    m.uc.hook_add(UC_HOOK_CODE,count)
    return m

def direct(m,data,state=2):
    m.uc.mem_write(INPUT,struct.pack('<I',len(data))+data+bytes(16))
    m.uc.mem_write(0x80629b60,bytes([state]))
    return m.invoke(SYMS['ram_activity_dispatch'],[INPUT])

def encode_reply(values,token=0,kind=2):
    result=bytearray((0xf0,0x52,0,0,0x6e,kind,token))
    for v in values:result.extend((v>>(7*k))&127 for k in range(5))
    return bytes(result+b'\xf7')

def transport_check(template):
    sent=[];records=[];freed=[];pauses=[];instances=[]
    midi=types.ModuleType('l6_midi_probe');session_module=types.ModuleType('l6_pad_fixture_test')
    midi.packet_init=lambda buf:1
    def add(buf,n,first,stamp,size,raw):
        import ctypes
        sent.append(ctypes.string_at(raw,size));return 1
    midi.packet_add=add;midi.check=lambda result:None;midi.client_free=lambda client:freed.append(client)
    class Session:
        def __init__(self,log):
            self.client=types.SimpleNamespace(value=1);self.log=io.StringIO()
            self.output=self.destination=1;self.events=queue.Queue();self.pending=bytearray();instances.append(self)
        def write(self,record):records.append(record)
    session_module.Session=Session
    def send(output,destination,buf):
        packet=sent[-1];s=instances[-1]
        if packet[4]==0x6f:
            page=packet[7]+(packet[8]<<7);values=[template[n] for n in FIELDS]
            values[2]=page;values[5]=GAP_START+page*PAGE_BYTES
            stale=list(values);stale[2]=0;stale[5]=GAP_START
            # Same token after wrapping: page identity must reject this reply.
            s.events.put((time.time(),encode_reply(stale,packet[6])+encode_reply(values,packet[6])))
        else:
            kind=packet[5];words=len(health.HEAP_FIELDS if kind==1 else health.SD_FIELDS)
            response=bytearray(encode_reply([0]*words,packet[6],kind));response[4]=0x7c
            s.events.put((time.time(),bytes(response)))
        return 0
    midi.send=send
    with patch.dict(sys.modules,{'l6_midi_probe':midi,'l6_pad_fixture_test':session_module}),patch.object(health.time,'sleep',pauses.append):
        rows=health.sample(ROOT/'analysis/not-created.jsonl',query_builder=request,reply_decoder=decode,
            kinds=(128,256),token_builder=lambda page:page&127,reply_matcher=reply_matches,interval_s=0.02)
        assert [r['page'] for r in rows]==[128,256] and sent==[request(128,0),request(256,0)]
        assert pauses==[0.02] and len(freed)==1 and instances[-1].log.closed
        sent.clear();rows=health.sample(ROOT/'analysis/not-created.jsonl')
        assert sent==[health.request(k,k) for k in (1,2,3)] and [r['kind'] for r in rows]==[1,2,3]
        assert len(freed)==2 and instances[-1].log.closed
        try:health.sample(ROOT/'analysis/not-created.jsonl',interval_s=1.1)
        except ValueError:pass
        else:raise AssertionError('Unbounded query interval accepted')
    return dict(stale_page_rejected=True,legacy_queries_unchanged=True,client_cleanup=True,pause=0.02)

def main(report_path=None,prepared_image=None,retained_prefix='ram_activity_retained'):
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,passed=True,**kw))
    prepared=prepared_image or OUT/'trial_ram_activity/L6.BIN'
    if prepared.exists():assert prepared.read_bytes()==TRIAL
    assert len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert MANIFEST['native_capacity_frames']==223104 and MANIFEST['ram_activity_persistent_state_bytes']==0
    assert MANIFEST['read_only_gap_interval']==[GAP_START,0x82000000]
    assert not any(n.startswith(('extra_','sdp_','native_worker','storage_lease')) for n in SYMS)
    passed('exact_candidate_whitelist_no_capture_or_new_state_and_fixed_upper_interval',prepared_image_verified=prepared.exists())

    m=machine();page=0;payload=bytes((i*37+13)&255 for i in range(PAGE_BYTES))
    m.uc.mem_write(GAP_START,payload);before=[bytes(m.uc.mem_read(SYMS[n],size)) for n,size in STATES.items()]
    query(m,request(page,19));r=decode(m.replies[-1]);h,s=fingerprint(payload)
    assert (r['hash_before'],r['hash_after'],r['sum_before'],r['sum_after'])==(h,h,s,s)
    assert r['flags']==15 and r['token']==19 and r['observer_consistent']
    assert m.gap_reads==[(GAP_START+i,4) for i in range(0,PAGE_BYTES,4)]*2
    assert m.reads==[0x402f0000,0x402f0010,0x402f004c]*2
    assert before==[bytes(m.uc.mem_read(SYMS[n],size)) for n,size in STATES.items()]
    assert bytes(m.uc.mem_read(GAP_START,PAGE_BYTES))==payload
    assert all(STACK-512<=a and a+n<=STACK for a,n in m.writes)
    assert STACK-m.min_sp<=512 and m.instructions<16000
    passed('parser_detour_paired_fingerprints_exact_reads_stack_only_writes_and_bounded_work',
        gap_word_reads=len(m.gap_reads),software_stack_bytes=STACK-m.min_sp,modeled_instructions=m.instructions)

    m=machine();rows=[];maximum=0
    for page in range(PAGE_COUNT):
        address=GAP_START+page*PAGE_BYTES
        data=struct.pack('<256I',*[(page*0x01020304+i*0x10203)&0xffffffff for i in range(256)])
        m.uc.mem_write(address,data);m.gap_reads.clear();m.reads.clear();m.writes.clear();m.instructions=0
        assert direct(m,request(page,page&127))==1
        r=decode(m.replies[-1]);h,s=fingerprint(data)
        assert r['page']==page and r['address']==address and r['observer_consistent']
        assert (r['hash_before'],r['sum_before'])==(h,s)
        assert m.gap_reads==[(address+i,4) for i in range(0,PAGE_BYTES,4)]*2
        assert all(STACK-512<=a and a+n<=STACK for a,n in m.writes)
        maximum=max(maximum,m.instructions);rows.append(r)
    assert GAP_START+PAGE_COUNT*PAGE_BYTES==0x82000000
    assert summarize(rows)['complete_coverage'] and not summarize(rows)['unused_memory_proven']
    passed('all_872_pages_exact_bounds_and_oracle_fingerprints_including_both_endpoints',
        maximum_direct_instructions=maximum,last_read_end=m.gap_reads[-1][0]+4)

    for name,value,index in (('disabled',1,0),('reset',2,0),('invalid_BR',0,2),
                            ('16MiB',0x80000019,2),('64MiB',0x8000001d,2),
                            ('different_base',0x8100001b,2),('no_refresh',0,9)):
        values=list(memory.CONTENTS);values[index]=value;m=machine(values)
        assert direct(m,request(0,0))==1;r=decode(m.replies[-1])
        assert not m.gap_reads and not r['read_performed'] and r['flags']==4
        assert not r['observer_consistent'] and not r['unused_memory_proven']
    passed('seven_unsupported_controller_configurations_reply_without_any_gap_access')

    m=machine();hits=0
    def change_word(uc,k,a,n,v,s):
        nonlocal hits
        hits+=1
        if hits==2:put32(m,a,0x100)
    m.uc.hook_add(UC_HOOK_MEM_READ,change_word,begin=GAP_START+16,end=GAP_START+16)
    direct(m,request(0,1));r=decode(m.replies[-1])
    assert r['flags']==13 and not r['fingerprints_agree'] and len(m.gap_reads)==512
    passed('changed_page_between_reads_is_marked_unstable_without_retry')

    m=machine();hits=0
    def change_config(uc,k,a,n,v,s):
        nonlocal hits
        hits+=1
        if hits==2:put32(m,a,0x80000019)
    m.uc.hook_add(UC_HOOK_MEM_READ,change_config,begin=0x402f0010,end=0x402f0010)
    direct(m,request(0,1));r=decode(m.replies[-1])
    assert r['read_performed'] and r['flags']==3 and not r['observer_consistent']
    passed('controller_change_marks_completed_page_uncertain_without_retry')

    m=machine();data=request(0,1)
    bad=[data[:-1],data+b'\0']
    for index,value in ((0,0),(1,0),(2,1),(3,1),(4,0),(5,3),(6,128),(7,128),(8,128),(9,0)):
        b=bytearray(data);b[index]=value;bad.append(bytes(b))
    for page in (PAGE_COUNT,16383):
        b=bytearray(data);b[7]=page&127;b[8]=page>>7;bad.append(bytes(b))
    for packet in bad:assert direct(m,packet)==0
    for state in (0,1,3):assert direct(m,data,state)==0
    m.uc.reg_write(A.UC_ARM_REG_IPSR,16);assert direct(m,data)==0
    assert not m.gap_reads and not m.reads and not m.replies
    passed('invalid_pages_packets_editor_context_and_handler_context_never_read_gap')

    packet=encode_reply([rows[0][n] for n in FIELDS])
    for index,value in ((6,128),(7,2),(11,16),(12,2),(17,127),(27,1),(37,16),(-1,0)):
        b=bytearray(packet);b[index]=value
        try:decode(bytes(b))
        except ValueError:pass
        else:raise AssertionError(('Malformed reply accepted',index))
    for packet2 in (packet[:-1],packet+b'\0'):
        try:decode(packet2)
        except ValueError:pass
        else:raise AssertionError('Wrong length accepted')
    for page,token in ((-1,0),(PAGE_COUNT,0),(0,-1),(0,128)):
        try:request(page,token)
        except ValueError:pass
        else:raise AssertionError('Invalid page/token accepted')
    assert decode(encode_reply([1]*18,kind=1)) is None
    passed('host_rejects_bad_page_address_flags_encoding_lengths_and_tokens')

    unchanged=compare(rows,rows);assert unchanged['unchanged_full_fingerprints'] and not unchanged['unused_memory_proven']
    after=[dict(r) for r in rows];after[13]['hash_before']^=1;after[13]['hash_after']^=1
    assert compare(rows,after)['changed_pages']==[13]
    assert not compare(rows[:3],rows)['unchanged_full_fingerprints']
    after[15]['observer_consistent']=False
    assert not compare(rows,after)['complete_consistent_comparison']
    for x in (rows+[rows[0]],):
        try:summarize(x)
        except ValueError:pass
        else:raise AssertionError('Repeated page hidden')
    with tempfile.TemporaryDirectory(dir=ROOT/'analysis') as tmp:
        path=Path(tmp)/'snapshot.jsonl'
        path.write_text('\n'.join(json.dumps(dict(direction='device_to_probe',hex=encode_reply([r[n] for n in FIELDS],r['token']).hex())) for r in rows)+'\n')
        assert compare(rows,read_log(path))['unchanged_full_fingerprints']
    passed('host_full_partial_changed_unstable_repeated_and_raw_log_comparisons_never_grant_ownership')

    passed('transport_page_identity_token_wrap_pacing_cleanup_and_legacy_queries',**transport_check(rows[0]))

    m=machine();m.hooks.pop(0x80031648);ring=0x8062ad84;capacity=8192;index=capacity-3;given=[]
    put32(m,0x8062cd84,index);put32(m,0x8062cd8c,capacity)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    query(m,request(PAGE_COUNT-1,19))
    reply=bytes(m.uc.mem_read(ring+index,3))+bytes(m.uc.mem_read(ring,100))
    assert decode(reply)['page']==PAGE_COUNT-1 and word(m,0x8062cd84)==100 and given==[0x7111,0x7112]
    stack=STACK-m.min_sp;assert stack<=768
    m.uc.mem_write(STACK-768,bytes([0x3c])*768)
    assert reply==bytes(m.uc.mem_read(ring+index,3))+bytes(m.uc.mem_read(ring,100))
    passed('original_sender_copies_entire_stack_reply_through_wrap_before_return',
        software_stack_with_native_sender=stack,limitation='Semaphore scheduling and exception frames are not physical measurements')

    with tempfile.TemporaryDirectory(dir=ROOT/'analysis') as tmp:
        path=Path(tmp)/'L6.BIN';path.write_bytes(TRIAL)
        with contextlib.redirect_stdout(io.StringIO()):
            retained=memory.main(ROOT/'analysis'/(retained_prefix+'_capacity_verification.json'),
                tuple(ROOT/'analysis'/(retained_prefix+'_'+n+'_verification.json') for n in ('command','raw','detail')),
                prepared_image=path)
    assert retained['passed'] and retained['groups']==42
    passed('all_42_prior_capacity_command_raw_detail_health_groups_on_exact_new_image',retained_groups=42)
    report=dict(passed=True,groups=len(cases)-1+42,ram_activity_groups=len(cases)-1,retained_groups=42,
        results=cases,prepared_image_verified=prepared.exists(),trial_sha256=hashlib.sha256(TRIAL).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=MANIFEST['limitations'])
    out=report_path or ROOT/'analysis/ram_activity_probe_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=report['groups'],report=str(out))))
    return report
if __name__=='__main__':main()
