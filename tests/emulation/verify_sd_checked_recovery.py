#!/usr/bin/env python3
"""Compiled abort/RSTD/drain checks with explicit MODEL permissions; offline only.

Original transfer, command, IRQ, event-post, wait and peek instructions execute.
W1C and selected reset effects below are fixtures, not a physical device model.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_R4
from verify_sd_card_recovery import StopProbe,STOP_ROW
from verify_sd_transfer_probe import Probe,ELF,install,patch,FIELDS as PROBE_FIELDS
from verify_sd_transfer_lifetime import HOST,EVENT,BUFFER
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_pad_protocol import ROOT,IMAGE,BIAS,REGS,RETURN
from verify_scheduling_boundaries import stop
from sd_registers import (DMA_ADDRESS,COMMAND,PRESENT,PROTOCOL,SYSTEM,IRQ_STATUS,
                         IRQ_SIGNAL,VENDOR2,RESETS,RESET_ALL,RESET_DATA,
                         CLOCK_STABLE,DAT0_HIGH)

QUIET_BEFORE,KERNEL_BEFORE,PERMIT,QUIET_AFTER,KERNEL_AFTER,SAFE,QUIET_ADMIT,KERNEL_ADMIT=range(1,9)
START,STOP,PERMIT_PHASE,RESET,CLEAN,VERIFY,DONE,BLOCKED=range(8)
EVENT_CHANGED,DIRTY_HW,DIRTY_SW,NOT_ABORT,STOP_FAILED,NO_FRESH_CC,RESET_STALLED,STILL_ACTIVE,DAT0_BUSY,CONFIG_CHANGED,CLOCK_UNSTABLE=range(1,12)
FIELDS='unit event phase fault admitted drains resets polls raw_before flags_before protocol vendor2 clock admit_calls join_calls'.split()
HEAD='70b588b044f2b426'

class RecoveryPorts:
    """Explicit providers of contracts not recovered or verified on hardware."""
    def configure(self,abort=True):
        m=self.m
        self.decisions={};self.model_trace=[];self.holds=[];self.dma_trace=[];self.writes=[]
        self.sem_count=0;self.w1c=True;self.kernel_drain=True;self.pending_ack=None
        self.verify_dma_clean=True # Counterfactual source tests may deliberately violate QUIET.
        self.reset_after=1;self.reset_delays=0;self.reset_status=0x100002
        self.reset_active=0;self.reset_busy=False;self.reset_clock=True
        self.reset_other=0;self.reset_change=None;self.safe_card=True;self.safe_cache=True
        self.late_kernel={};self.late_ack={};self.late_safe=None;self.last_quiet=None
        self.stop_fault=None;self.stale_stop=False
        put32(m,HOST+4,EVENT);put32(m,EVENT+4,1) # synthetic auto-clear event mode
        put32(m,PRESENT,DAT0_HIGH|CLOCK_STABLE);put32(m,PROTOCOL,0x22)
        put32(m,SYSTEM,0x000e003c);put32(m,VENDOR2,0x20)
        if abort:put32(m,STOP_ROW+4,word(m,STOP_ROW+4)|0xc00000)
        for addr,name in ((0x8006b1e0,'sdp_admit_read'),(0x8006b248,'sdp_admit_write')):
            assert IMAGE[addr-BIAS:addr-BIAS+8].hex()==HEAD
            patch(m,addr,self.syms[name],8)
        put32(m,self.syms['sdp_admit_port'],self.syms['sdp_recovery_admit']|1)
        put32(m,self.syms['sdp_join_port'],self.syms['sdp_recovery_join']|1)
        m.hooks[0x2102bb00]=self.model;m.hooks[0x2102bd04]=self.deliver
        m.hooks[0x80032250]=self.delay;m.hooks.pop(0x80032828,None)
        m.hooks.pop(0x80032878,None) # run original read-only event peek
        m.hooks[0x80076628]=self.irq_post
        original_take=m.hooks[0x80076950]
        def take(a):
            if a[0]!=word(m,EVENT):return original_take(a)
            value=int(self.sem_count>0)
            if value:self.sem_count-=1
            return value
        m.hooks[0x80076950]=take
        # Upper handoff fixture used an unexpired deadline; missing-event cases
        # here explicitly expire it, without requiring Main or another task.
        m.hooks[0x80076bc8]=lambda a:1
        def written(uc,access,address,size,value,user):
            assert size==4
            self.writes.append((uc.reg_read(UC_ARM_REG_PC),address,value))
            if address==IRQ_STATUS and self.w1c:
                old=word(m,IRQ_STATUS)
                injected=self.late_ack.pop(self.last_quiet,0)
                self.pending_ack=(old&~value)|injected
            if address==DMA_ADDRESS:
                assert self.owner() and self.rec()['admitted']
                raw,flags=word(m,IRQ_STATUS),word(m,EVENT+8)
                if self.verify_dma_clean:assert raw==0 and flags==0
                self.dma_trace.append(dict(value=value,state=self.rec(),tokens=self.sem_count,raw=raw,flags=flags))
            if address==SYSTEM and value&RESET_DATA:
                assert self.owner() and self.rec()['phase']==RESET
                assert PERMIT in [t['step'] for t in self.model_trace]
        def applied(uc,pc,size,user):
            # Unicorn's write hook runs before its memory store. Apply W1C on
            # the NEXT instruction, before any compiled readback can execute.
            if self.pending_ack is not None:
                put32(m,IRQ_STATUS,self.pending_ack);self.pending_ack=None
        m.uc.hook_add(UC_HOOK_MEM_WRITE,written,begin=0x402c0000,end=0x402c00ff)
        m.uc.hook_add(UC_HOOK_CODE,applied)
    def rec(self):
        return dict(zip(FIELDS,struct.unpack('<15I',self.m.uc.mem_read(self.syms['sdp_recovery_state'],60))))
    def probe(self):
        return dict(zip(PROBE_FIELDS,struct.unpack('<14I',self.m.uc.mem_read(self.syms['sdp_state'],56))))
    def irq_post(self,a):
        assert a[0]==word(self.m,EVENT);self.sem_count+=1;return 0
    def model(self,a):
        step,unit,event=a[:3]
        assert self.owner() and unit==0 and event==EVENT and self.probe()['active']
        state=self.rec();self.model_trace.append(dict(step=step,state=state))
        if step in (QUIET_BEFORE,QUIET_AFTER,QUIET_ADMIT):
            assert word(self.m,IRQ_SIGNAL)==0;self.last_quiet=step
        reply=self.decisions.get(step,1)
        if step==SAFE and (not self.safe_card or not self.safe_cache):reply=0
        if reply!=1:
            self.holds.append(dict(step=step,state=state));stop(self.m);return reply
        if step in (KERNEL_BEFORE,KERNEL_AFTER,KERNEL_ADMIT):
            if self.kernel_drain:
                put32(self.m,EVENT+8,0);self.sem_count=0
            if step in self.late_kernel:put32(self.m,EVENT+8,self.late_kernel.pop(step))
        if step==SAFE and self.late_safe:
            address,value=self.late_safe;put32(self.m,address,value)
        return 1
    def delay(self,a):
        state=self.rec()
        if state['fault']:
            assert self.owner() and self.probe()['active'] and not self.probe()['finished']
            self.holds.append(dict(fault=state['fault'],state=state));return stop(self.m)
        if state['phase']==RESET and word(self.m,SYSTEM)&RESET_DATA:
            self.reset_delays+=1
            if self.reset_after is not None and self.reset_delays>=self.reset_after:
                # Explicit MODEL reset effect, independent from the CPU write.
                put32(self.m,SYSTEM,(word(self.m,SYSTEM)&~RESET_DATA)|self.reset_other)
                put32(self.m,PRESENT,self.reset_active|(0 if self.reset_busy else DAT0_HIGH)|
                                      (CLOCK_STABLE if self.reset_clock else 0))
                put32(self.m,IRQ_STATUS,self.reset_status)
                put32(self.m,EVENT+8,0x184);self.sem_count=3
                if self.reset_change:
                    address,value=self.reset_change;put32(self.m,address,value)
        return 0
    def deliver(self,a):
        if not self.stop_state()['active']:return self.data_deliver(a)
        assert self.owner() and a[0]==EVENT and a[1]==0x183
        raw=0 if self.stop_fault=='timeout' or self.stale_stop else 0x20000 if self.stop_fault=='error' else 1
        put32(self.m,EVENT+8,2 if self.stale_stop else 0)
        put32(self.m,IRQ_STATUS,raw);put32(self.m,PRESENT,0x206|CLOCK_STABLE)
        return int(bool(raw))
    def resume(self):
        m=self.m;m.reached_return=False
        m.uc.emu_start(m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
        assert m.reached_return
        return m.uc.reg_read(REGS[0])
    def retained(self,fault=None):
        assert self.owner() and self.probe()['active'] and not self.probe()['finished']
        assert not self.probe()['joined']
        if fault is not None:assert self.rec()['fault']==fault,self.rec()
    def reset_writes(self):
        return [v for pc,a,v in self.writes if a==SYSTEM and v&RESETS]

class RecoveryProbe(RecoveryPorts,StopProbe):
    def __init__(self,abort=True):
        StopProbe.__init__(self,abort=False);self.configure(abort)
    def owner(self):return self.held
    def data_deliver(self,a):
        faulty=self.fault and self.fault[0]==a[1] and self.fault_once
        result=Probe.deliver(self,a)
        put32(self.m,PRESENT,CLOCK_STABLE|(0x206 if faulty else DAT0_HIGH))
        return result

def handoff_case(passed):
    from verify_handoff_dependencies import Dependencies,FS1,SCRATCH
    class HandoffRecovery(RecoveryPorts,Dependencies):
        def __init__(self):
            Dependencies.__init__(self);install(self.m,self.syms)
            self.configure();self.inject=True;self.commands=[]
            self.decisions[SAFE]=0
            def command(uc,pc,size,user):
                assert self.owner();self.commands.append(uc.reg_read(UC_ARM_REG_R4))
            self.m.uc.hook_add(UC_HOOK_CODE,command,begin=0x8006a350,end=0x8006a350)
        def owner(self):
            return self.unit_held and FS1 in self.tokens
        def stop_state(self):
            from verify_sd_card_recovery import STOP_FIELDS
            return dict(zip(STOP_FIELDS,struct.unpack('<10I',self.m.uc.mem_read(self.syms['sdp_stop_state'],40))))
        def data_deliver(self,a):
            assert self.owner()
            initial=self.current_io and 0x80735b80<=self.current_io[1]<0x8077c580
            faulty=self.inject and initial and a[1]==0x185
            raw=1 if a[1]==0x183 else 2
            if faulty:raw|=0x100000;self.inject=False
            put32(self.m,EVENT+8,0);put32(self.m,IRQ_STATUS,raw)
            put32(self.m,PRESENT,CLOCK_STABLE|(0x206 if faulty else DAT0_HIGH));return 1
    r=HandoffRecovery();r.step();r.retained()
    assert r.tokens=={FS1,SCRATCH} and r.locked
    assert r.rec()['phase']==VERIFY and r.rec()['resets']==1 and r.commands.count(14)==1
    assert not r.ui_attempts and not any(t[0]=='leave' for t in r.trace)
    r.decisions[SAFE]=1
    assert r.resume()==7 and not r.unit_held and not r.tokens and not r.locked
    assert r.commands.count(14)==1 and not r.ui_attempts and r.dma_trace
    passed('whole_handoff_keeps_gate_filesystem_scratch_and_SD_token_after_checked_reset_until_MODEL_card_cache_validity')

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    for a in (0x8006b1e0,0x8006b248):assert IMAGE[a-BIAS:a-BIAS+8].hex()==HEAD
    passed('additional_data_entry_trampolines_pin_original_eight_bytes_and_run_admission_after_SD_lock')

    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(9,1)):
            r=RecoveryProbe();r.fault=None
            put32(r.m,IRQ_STATUS,0x100003);put32(r.m,EVENT+8,0x186);r.sem_count=4
            assert r.request(op,blocks,offset)==0 and not r.owner()
            assert r.dma_trace and not r.rec()['fault'] and not r.rec()['resets']
            assert [t['step'] for t in r.model_trace]==[QUIET_ADMIT,KERNEL_ADMIT]
    passed('normal_direct_and_bounce_read_write_drain_prior_hardware_flags_software_events_and_kernel_tokens_before_DMA')

    for step in (QUIET_ADMIT,KERNEL_ADMIT):
        r=RecoveryProbe();r.fault=None;r.decisions[step]=0
        r.request();r.retained()
        assert not r.dma_trace and not r.native_commands and not r.rec()['admitted']
        r.decisions[step]=1;assert r.resume()==0 and not r.owner()
    passed('pending_admission_retains_registered_parent_and_SD_token_before_first_DMA_address_then_resumes_same_stack')

    for step in (QUIET_BEFORE,KERNEL_BEFORE,QUIET_AFTER,KERNEL_AFTER):
        r=RecoveryProbe();r.decisions[step]=2;r.request();r.retained()
        stops=step in (QUIET_AFTER,KERNEL_AFTER)
        assert r.rec()['resets']==int(stops) and r.stop_state()['attempted']==int(stops)
        r.decisions[step]=1
        assert r.resume()==0xffffd8ef and not r.owner() and len(r.reset_writes())==1
        assert r.native_commands==[23,14]
    passed('pending_preabort_or_postreset_serialization_and_kernel_drain_resume_without_repeating_stop_or_reset')

    r=RecoveryProbe(abort=False);r.request();r.retained(NOT_ABORT)
    assert not r.stop_state()['attempted'] and not r.reset_writes() and r.native_commands==[23]
    passed('unmodified_normal_CMD12_table_row_cannot_silently_authorize_checked_abort_or_reset')

    for reply in (0,2,0xffffffce):
        r=RecoveryProbe();r.decisions[PERMIT]=reply;r.request();r.retained()
        assert r.rec()['phase']==PERMIT_PHASE and not r.reset_writes()
        assert r.stop_state()['attempted'] and r.native_commands==[23,14]
        r.decisions[PERMIT]=1
        assert r.resume()==0xffffd8ef and not r.owner() and r.rec()['resets']==1
        assert r.native_commands==[23,14] and r.rec()['phase']==DONE
    passed('stop_success_never_requests_data_reset_without_explicit_MODEL_abort_acceptance_and_reset_permission')

    for after in (1,10):
        for op in (2,3):
            for blocks,offset in ((1,0),(2,0),(9,1)):
                r=RecoveryProbe();r.reset_after=after
                assert r.request(op,blocks,offset)==0xffffd8ef and not r.owner()
                assert r.rec()['phase']==DONE and r.rec()['polls']==after and r.rec()['resets']==1
                assert r.reset_writes()==[0x040e003c] and word(r.m,HOST+4)==EVENT
                assert r.rec()['drains']==3 and not word(r.m,IRQ_STATUS) and not word(r.m,EVENT+8)
                assert len(r.native_commands)==2 and r.native_commands[-1]==14
    passed('checked_RSTD_self_clear_and_postreset_idle_drain_preserve_existing_event_identity_and_failed_read_write_data')

    for after,other in ((None,0),(1,RESET_ALL)):
        r=RecoveryProbe();r.reset_after=after;r.reset_other=other;r.request();r.retained(RESET_STALLED)
        assert r.rec()['polls']==10 and len(r.reset_writes())==1 and not r.copies
        r.resume();r.retained(RESET_STALLED);assert len(r.reset_writes())==1
    passed('reset_stuck_or_another_reset_bit_remaining_retains_stack_without_repeating_stop_or_reset')

    for active in (1,2,4,0x100,0x200):
        r=RecoveryProbe();r.reset_active=active;r.request();r.retained(STILL_ACTIVE)
        assert not word(r.m,SYSTEM)&RESETS and r.rec()['resets']==1
    r=RecoveryProbe();r.reset_busy=True;r.request();r.retained(DAT0_BUSY)
    r=RecoveryProbe();r.reset_clock=False;r.request();r.retained(CLOCK_UNSTABLE)
    passed('reset_self_clear_is_insufficient_when_command_data_activity_DAT0_busy_or_unstable_clock_remains')

    for address,value,fault in ((PROTOCOL,0x20,CONFIG_CHANGED),(VENDOR2,0x1000,CONFIG_CHANGED),
                                (SYSTEM,0x000e003d,CONFIG_CHANGED),(HOST+4,0,EVENT_CHANGED)):
        r=RecoveryProbe();r.reset_change=(address,value);r.request();r.retained(fault)
        assert SAFE not in [t['step'] for t in r.model_trace]
    passed('reset_mode_clock_or_event_identity_changes_cannot_pass_final_unwind_validation')

    r=RecoveryProbe();put32(r.m,PROTOCOL,0x20022);r.reset_change=(PROTOCOL,0x22)
    assert r.request()==0xffffd8ef and not r.owner() and r.rec()['phase']==DONE
    for address,value in ((PROTOCOL,0x122),(PROTOCOL,0x2),(PROTOCOL,0x24),(VENDOR2,0x1000)):
        r=RecoveryProbe();put32(r.m,address,value);r.request();r.retained(CONFIG_CHANGED)
        assert not r.dma_trace and not r.native_commands

    for where in (QUIET_BEFORE,QUIET_AFTER):
        r=RecoveryProbe();r.late_ack[where]=2;r.request();r.retained(DIRTY_HW)
    r=RecoveryProbe();r.reset_status=0x40;r.request();r.retained(DIRTY_HW)
    r=RecoveryProbe();r.late_kernel[KERNEL_AFTER]=2;r.request();r.retained(DIRTY_SW)
    r=RecoveryProbe();r.kernel_drain=False;put32(r.m,EVENT+8,2)
    r.request();r.retained(DIRTY_SW);assert not r.dma_trace
    passed('dirty_W1C_readback_unknown_status_or_late_software_post_is_rejected_before_submission_or_unwind')

    for stop_fault,stale,fault in (('error',False,STOP_FAILED),('timeout',False,STOP_FAILED),(None,True,NO_FRESH_CC)):
        r=RecoveryProbe();r.stop_fault=stop_fault;r.stale_stop=stale;r.request();r.retained(fault)
        assert not r.reset_writes() and PERMIT not in [t['step'] for t in r.model_trace]
    passed('stop_error_timeout_or_software_completion_without_new_raw_command_IRQ_cannot_authorize_reset')

    for which in ('card','cache'):
        r=RecoveryProbe();setattr(r,'safe_'+which,False);r.request();r.retained()
        assert r.rec()['phase']==VERIFY and r.rec()['resets']==1 and not word(r.m,SYSTEM)&RESETS
        setattr(r,'safe_'+which,True)
        assert r.resume()==0xffffd8ef and not r.owner() and len(r.reset_writes())==1
        assert r.native_commands==[23,14]
    for address,value,fault in ((IRQ_STATUS,2,DIRTY_HW),(EVENT+8,2,DIRTY_SW),(PRESENT,0x206,STILL_ACTIVE)):
        r=RecoveryProbe();r.late_safe=(address,value);r.request();r.retained(fault)
    passed('MODEL_card_cache_permission_and_final_compiled_readback_are_both_required_without_repeating_reset')

    r=RecoveryProbe();assert r.request()==0xffffd8ef;first=len(r.dma_trace)
    r.fault=None;put32(r.m,IRQ_STATUS,2);put32(r.m,EVENT+8,2);r.sem_count=2
    r.decisions[QUIET_ADMIT]=0;r.request();r.retained()
    assert len(r.dma_trace)==first and not r.rec()['resets'] and not r.rec()['admitted']
    r.decisions[QUIET_ADMIT]=1;assert r.resume()==0 and len(r.dma_trace)>first and not r.owner()
    passed('next_registered_transfer_requires_new_serialized_drain_before_reprogramming_DMA_even_after_prior_checked_recovery')

    r=RecoveryProbe()
    assert r.m.invoke(r.syms['sdp_recovery_join'],[0,BUFFER,1024,1])==0
    assert r.m.invoke(r.syms['sdp_recovery_admit'],[0,EVENT])==0
    r.seed(active=1,failed=1,unit=0,event=EVENT,buffer=BUFFER,bytes=1024)
    for args in ([1,BUFFER,1024,1],[0,BUFFER+4,1024,1],[0,BUFFER,512,1]):
        assert r.m.invoke(r.syms['sdp_recovery_join'],args)==0
    assert not r.model_trace and not r.writes
    passed('inactive_or_mismatched_recovery_scope_cannot_touch_controller_or_call_MODEL_providers')

    handoff_case(passed)
    out=ROOT/'analysis/sd_checked_recovery_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),test_elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Counterfactual abort table row changed in emulator memory only',
      'Reset permission, IRQ/post exclusion, kernel token drain and cache/card/filesystem validity are explicit MODEL contracts',
      'W1C and selected RSTD effects synthetic; no DMA/cache/bus/NVIC/card timing or persistence model',
      'Auto-clear event mode is a fixture; original post/wait/peek instructions execute with modeled kernel endpoints',
      'No recovery/gate binding, device/card access, deployment image or installation']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))

if __name__=='__main__':main()
