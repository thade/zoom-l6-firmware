#!/usr/bin/env python3
"""Continuous scatter -> original cache/MPU setup -> capture registration.

Kernel creation/scheduling and remaining board hardware are fixtures. Cache
geometry is seeded; maintenance register writes execute, cache effects do not.
No device access or capture release.
"""
import hashlib,json
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_capture_sd_retained import CombinedBoot,PACK,PLAN,N,ELF,GLOBALS
from verify_sd_cache_contract import CCR,CCSIDR,MPU_BASE,MPU_ATTRIBUTE,MPU_CONTROL,EXPECTED
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,RETURN
from verify_scheduling_boundaries import stop


def run(ccr,corrupt=False,*,boot_factory=CombinedBoot,pack=PACK,names=N,globals_range=GLOBALS):
    PACK,N,GLOBALS=pack,names,globals_range
    b=boot_factory();m=b.m;u=m.uc
    u.mem_map(0,0x1000);u.mem_map(0x81000000,0x1000000)
    start=PACK['jumps']['candidate_code_start']
    if PACK.get('source_reuse'):
        from capture_jump_patches import SCATTER
        u.mem_write(SCATTER[0],PACK['source_blob'])
    else:
        u.mem_write(start,b'\xa5'*len(PACK['code']))
        u.mem_write(GLOBALS[0],b'\xa5'*(GLOBALS[1]-GLOBALS[0]))
    b.writes.clear()
    if corrupt:u.mem_write(PACK['code_source'],b'\xff'*4)
    m.hooks.pop(0x8001b320) # Run the original cache/MPU routine, previously stubbed.
    put32(m,CCR,ccr);put32(m,CCSIDR,(1<<13)|(1<<3)|1) # Explicit 2-set/2-way fixture.
    events=[];pairs=[];base=None;code_writes=0;first_entry=None
    def write(u,kind,a,n,v,data):
        nonlocal base,code_writes
        pc=u.reg_read(A.UC_ARM_REG_PC)
        if start<=a<start+len(PACK['code']):
            assert a+n<=start+len(PACK['code'])
            code_writes+=n
            if not events or events[-1][0]!='code_write':events.append(('code_write',pc))
        elif 0xe000ed00<=a<=0xe000ef78:
            events.append(('system',a,v))
            if a==MPU_BASE:base=v
            if a==MPU_ATTRIBUTE:
                assert base is not None;pairs.append((base,v));base=None
    def entry(u,pc,n,data):
        nonlocal first_entry
        if first_entry is not None:return
        first_entry=pc
        assert code_writes==len(PACK['code'])
        assert bytes(u.mem_read(start,len(PACK['code'])))==PACK['code']
        assert b.word(CCR)&0x30000==0x30000 and b.word(MPU_CONTROL)==5
        assert pairs==EXPECTED
        events.append(('capture_entry',pc))
    u.hook_add(UC_HOOK_MEM_WRITE,write,begin=start,end=start+len(PACK['code'])-1)
    u.hook_add(UC_HOOK_MEM_WRITE,write,begin=0xe000ed00,end=0xe000ef78)
    u.hook_add(UC_HOOK_CODE,entry,begin=start,end=start+len(PACK['code'])-1)
    fail=PACK['names']['scatter_lz4_failed']&~1
    m.hooks[fail]=lambda a:events.append(('malformed_input',fail)) or stop(m)
    # Install the current fixture endpoints, then execute the ORIGINAL reset and
    # scatter sequence. No host expansion or separate invocation bridges stages.
    for pc in set(m.hooks)-m.installed:
        u.hook_add(UC_HOOK_CODE,m._hook,begin=pc,end=pc);m.installed.add(pc)
    m.reached_return=False
    u.emu_start(0x80001401,RETURN+2,count=150000000)
    assert m.reached_return
    if corrupt:
        assert not b.kernel_entered and first_entry is None and not pairs
        assert events==[('malformed_input',fail)]
        return dict(malformed_stopped_before_cache_and_capture=True)
    assert b.kernel_entered and b.optional_calls==1 and b.word(b.worker+8)==4
    assert all(b.word(N[name])==0 for name in
        ('sdp_source_port','sdp_chunk_admit_port','sdp_chunk_finish_port','sdp_cache_read_port'))
    b.guard()
    code_end=max(i for i,e in enumerate(events) if e[0]=='code_write')
    entry_at=next(i for i,e in enumerate(events) if e[0]=='capture_entry')
    # All compiled capture writes precede each cache operation below. The
    # original MPU setup cleans old D-cache only when it was already enabled.
    required=(0xe000ef50,0xe000ef60)+((0xe000ef74,) if ccr&0x10000 else ())
    for address in required:
        positions=[i for i,e in enumerate(events) if e[0]=='system' and e[1]==address]
        assert positions and all(code_end<i<entry_at for i in positions)
    return dict(initial_ccr=ccr,modeled_cache_ways=2,modeled_cache_sets=2,
                loaded_code_bytes=code_writes,first_capture_entry=hex(first_entry),
                mpu_pairs=len(pairs),original_tasks_and_idle=len(b.tasks),
                optional_registered=b.optional_calls,worker_waiting=True,
                capture_released=False,maintenance_before_first_capture_entry=True)


def main():
    cases=[run(0),run(0x30000),run(0x30000,corrupt=True)]
    out=ROOT/'analysis/capture_boot_cache_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),device_access=False,
        limitations=['One continuous instruction path through original scatter, cache/MPU and compiled registration.',
            'Cache geometry is a fixture; maintenance side effects and physical instruction visibility are not modeled.',
            'Remaining board hardware and kernel task creation/scheduling stay modeled; no whole-board boot.',
            'No extra-file IO, source lease, physical code/global ownership or worker release.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
