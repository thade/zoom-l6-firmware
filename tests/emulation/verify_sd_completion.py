#!/usr/bin/env python3
"""Stock SD clock/reset/error counterexamples; synthetic MMIO, no device I/O."""
import hashlib,json
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_R1
from verify_sd_transfer_lifetime import Sd,REQ,BUFFER,EVENT,native_commands
from verify_storage_readiness import word
from verify_storage_lifetimes import instructions
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

from sd_registers import (SD,PRESENT,PROTOCOL,SYSTEM,IRQ_STATUS,IRQ_ENABLE,
                         IRQ_SIGNAL,MIX,VENDOR,CLOCK_STABLE,RESET_ALL,RESETS,WAKE_CARD_IRQ)
ACTIVE=(1,2,4,0x100,0x200,0x107,0x207)

def observe_mmio(r):
    reads=[];writes=[]
    def read(uc,access,address,size,value,user):
        reads.append((uc.reg_read(UC_ARM_REG_PC),address,word(r.m,address)))
    def write(uc,access,address,size,value,user):
        assert size==4
        writes.append((uc.reg_read(UC_ARM_REG_PC),address,value))
    r.m.uc.hook_add(UC_HOOK_MEM_READ,read,begin=SD,end=SD+0xff)
    r.m.uc.hook_add(UC_HOOK_MEM_WRITE,write,begin=SD,end=SD+0xff)
    return reads,writes

def cleanup(present,system=0):
    r=Sd();m=r.m
    # Clock divider arithmetic and kernel event peek remain fixtures. The
    # previously stubbed clock helper now executes its actual instructions.
    def divider(a):put32(m,a[0],1);put32(m,a[1],1);return 0
    m.hooks[0x80069510]=divider
    m.hooks[0x80032878]=lambda a:put32(m,a[1],0) or 0
    put32(m,PRESENT,present);put32(m,SYSTEM,system)
    put32(m,PROTOCOL,6);put32(m,MIX,0x101);put32(m,VENDOR,0x101)
    put32(m,IRQ_ENABLE,0xffffffff);put32(m,IRQ_SIGNAL,0xffffffff)
    reads,writes=observe_mmio(r)
    result=r.request(op=5)
    return r,result,reads,writes

def command(flags=0x80,present=0x207,wait_result=0,clear_reset=False,clear_active=False):
    r=Sd();m=r.m;m.hooks.pop(0x8006a348)
    raw=bytearray(32);raw[0]=15
    raw[8:12]=BUFFER.to_bytes(4,'little');m.uc.mem_write(REQ,bytes(raw))
    put32(m,SD+0x10,0x100)
    reads,writes=observe_mmio(r)
    def wait(a):
        assert a[0]==EVENT and a[1]==0x183 and a[4]==5000
        # Inhibit/activity becomes visible after command submission. Seeding it
        # before entry would take the distinct pre-command busy-timeout path.
        put32(m,PRESENT,present);put32(m,a[3],flags)
        return wait_result
    def delay(a):
        r.events.append(('delay',a[0]))
        if clear_reset and word(m,SYSTEM)&RESET_ALL:
            put32(m,SYSTEM,word(m,SYSTEM)&~RESET_ALL)
            if clear_active:put32(m,PRESENT,0)
        return 0
    m.hooks[0x800328c0]=wait;m.hooks[0x80032250]=delay
    result=m.invoke(0x8006a348,[REQ,0])
    return r,result,reads,writes

def irq_observation(raw,signal=0x157f003f):
    r=Sd();m=r.m;sample=[];posts=[]
    put32(m,IRQ_STATUS,raw);put32(m,IRQ_SIGNAL,signal)
    # R1 contains the original status read here, before W1C acknowledgement and
    # before AND with the signal-enable mask. Observation only; no hook installed.
    def snapshot(uc,address,size,user):sample.append(uc.reg_read(UC_ARM_REG_R1))
    m.uc.hook_add(UC_HOOK_CODE,snapshot,begin=0x8006eab6,end=0x8006eab6)
    m.hooks[0x80032828]=lambda a:posts.append(tuple(a[:2])) or 0
    reads,writes=observe_mmio(r)
    m.invoke(0x8006ea90,[])
    return sample,posts,writes

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    for active in ACTIVE:
        r=Sd();put32(r.m,PRESENT,CLOCK_STABLE|active);put32(r.m,SYSTEM,RESETS)
        reads,writes=observe_mmio(r)
        assert r.m.invoke(0x8006a760,[])==0
        assert reads==[(0x8006a768,PRESENT,CLOCK_STABLE|active)] and not writes and not r.events
    passed('actual_clock_helper_succeeds_with_each_command_data_and_transfer_active_flag_and_reset_bits_set',
           activity_values=[hex(x) for x in ACTIVE],reset_value=hex(RESETS))

    r=Sd();put32(r.m,PRESENT,0)
    assert r.m.invoke(0x8006a760,[])==1 and r.events==[('delay',1)]*10
    passed('actual_clock_helper_reports_clock_failure_after_ten_modeled_delays')

    for active in ACTIVE:
        r,result,reads,writes=cleanup(CLOCK_STABLE|active)
        assert result==0 and not r.held and word(r.m,PRESENT)==CLOCK_STABLE|active
        assert word(r.m,PROTOCOL)==WAKE_CARD_IRQ and word(r.m,MIX)==0x101
        assert word(r.m,VENDOR)==1
        assert word(r.m,IRQ_ENABLE)==word(r.m,IRQ_SIGNAL)==0
        assert all(not (v&RESETS) for pc,a,v in writes if a==SYSTEM)
        assert any(a==PROTOCOL and v==WAKE_CARD_IRQ for pc,a,v in writes)
        assert [a for pc,a,v in reads if a in (PRESENT,SYSTEM)]==[SYSTEM,PRESENT,PRESENT]
        assert r.m.uc.mem_read(0x802142b4,1)==b'\0'
    passed('operation5_returns_success_with_active_flags_unchanged_without_requesting_reset_or_touching_actual_MIX_CTRL_DMA_enable',
           distinction='PROT_CTRL bit24 enables card-interrupt wakeup; SYS_CTRL bit24 requests reset; VEND_SPEC bit8 forces clock, distinct from MIX_CTRL at offset0x48')

    for system in (0,RESETS):
        r,result,reads,writes=cleanup(0x207,system)
        assert result==0 and not r.held and word(r.m,PRESENT)==0x207
        assert r.events.count(('delay',1))==10 and word(r.m,SYSTEM)==system
        assert not any(a==SYSTEM for pc,a,v in writes)
    passed('operation5_returns_success_on_actual_clock_failure_without_inspecting_or_resolving_reset_state')

    for flags,error in ((1,10),(0x80,3),(0x100,19)):
        for present in (1,2,0x207):
            r,result,reads,writes=command(flags,present)
            assert result==error and word(r.m,SYSTEM)&RESET_ALL and word(r.m,PRESENT)==present
            assert r.events==[('delay',1)]*10
            assert [(pc,a) for pc,a,v in writes if a==SYSTEM]==[(0x8006a62e,SYSTEM)]
        for present in (0,4,0x100,0x200):
            r,result,reads,writes=command(flags,present)
            assert result==error and not any(a==SYSTEM for pc,a,v in writes) and not r.events
    passed('actual_command_error_attempts_reset_only_for_inhibit_bits_and_returns_original_error_when_reset_stays_set',
           error_mapping={'1':10,'0x80':3,'0x100':19})

    for clear_active in (False,True):
        r,result,reads,writes=command(clear_reset=True,clear_active=clear_active)
        assert result==3 and not word(r.m,SYSTEM)&RESET_ALL and r.events==[('delay',1)]
        assert word(r.m,PRESENT)==(0 if clear_active else 0x207)
        assert not any(pc>=0x8006a630 and a==PRESENT for pc,a,v in reads)
    passed('actual_command_reset_poll_checks_reset_bit_but_does_not_recheck_transfer_activity',
           limitation='Reset self-clear and independently retained activity are synthetic MMIO cases, not hardware reset behavior')

    r,result,reads,writes=command(wait_result=0xffffffce)
    assert result==11 and word(r.m,PRESENT)==0x207
    assert not any(a==SYSTEM for pc,a,v in writes) and not r.events
    r=Sd();m=r.m;m.hooks.pop(0x8006a348)
    raw=bytearray(32);raw[0]=15;m.uc.mem_write(REQ,bytes(raw));put32(m,PRESENT,1)
    reads,writes=observe_mmio(r)
    assert m.invoke(0x8006a348,[REQ,0])==12 and r.events==[('delay',1)]*100
    assert not writes and word(m,PRESENT)==1
    passed('command_wait_timeout_and_precommand_busy_timeout_return_without_reset_or_idle_evidence')

    for op in (2,3):
        for flags in (1,0x80,0x100):
            # The shared lifetime fixture executes the real command/data/status
            # chain; the final reset register remains clear. Its modeled waits
            # do not simulate physical data, reset self-clear or W1C effects.
            r,result=native_commands(op,flags)
            assert result==0 and not r.held and not word(r.m,SYSTEM)&RESETS
    passed('original_read_write_return_success_for_data_error_events_without_command_reset',
           limitation='Final status response and wait events are injected; physical error timing remains unproved')

    cases=[(0x100002,0x157f003f,4),(0x200020,0x157f003f,8),
           (3,0x157f003f,2),(0x100002,2,4)]
    for raw,signal,event in cases:
        sample,posts,writes=irq_observation(raw,signal)
        assert sample==[raw] and posts==[(EVENT,event)]
        assert writes[0]==(0x8006eabc,IRQ_STATUS,signal&0x157f003f)
    passed('preacknowledgement_IRQ_snapshot_retains_error_or_completion_bits_lost_by_stock_mapping_or_masking',
           observation_pc=hex(0x8006eab6),cases=[dict(raw=hex(a),signal=hex(b),event=hex(c)) for a,b,c in cases])

    windows=[(0x8006a280,0x8006a340),(0x8006a348,0x8006a474),
             (0x8006a554,0x8006a710),(0x8006a748,0x8006a7f8),(0x8006ea98,0x8006eba8)]
    lines=[]
    for a,b in windows:
        lines.append(f'\n# {a:08x}..{b:08x}')
        lines.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(a,b))
    (ROOT/'analysis/sd_completion_disassembly.txt').write_text('\n'.join(lines)+'\n')
    out=ROOT/'analysis/sd_completion_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
      'Original firmware code executes; kernel waits, clock-divider arithmetic, registers and time are modeled',
      'Register correspondence to NXP USDHC is not proof of the installed processor or its applicable errata',
      'No physical reset, cancellation, bus-master idle, cache coherency or card persistence proof',
      'Raw IRQ observation point is not a bound hook and still needs request attribution and race/acknowledgement coverage',
      'No deployment image produced, installation, hardware access or native gate binding']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))

if __name__=='__main__':main()
