#!/usr/bin/env python3
"""Stock event constructor/flag/binary-token instructions, offline only.

NVIC W1S/W1C effects are explicit fixtures. QUIET/reset/card/cache permissions
remain MODEL contracts; this does not emulate interrupt arbitration or DMA.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
import unicorn.arm_const as arm
from verify_sd_checked_recovery import (RecoveryPorts,RecoveryProbe,QUIET_BEFORE,
    QUIET_AFTER,QUIET_ADMIT,KERNEL_BEFORE,KERNEL_AFTER,KERNEL_ADMIT,SAFE,RESET,
    VERIFY,DONE,DIRTY_SW)
from verify_sd_transfer_probe import ELF,install
from verify_sd_transfer_lifetime import HOST,EVENT,BUFFER
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_storage_lifetimes import instructions
from verify_pad_protocol import ROOT,IMAGE,REGS
from sd_registers import IRQ_STATUS,IRQ_SIGNAL,SYSTEM,RESET_DATA

SEM=0x21009100;DESCRIPTOR=0x800a07b0;BIT=1<<14;OTHER=1<<2
ISER,ICER,ISPR,ICPR,IABR=0xe000e10c,0xe000e18c,0xe000e20c,0xe000e28c,0xe000e30c
CONTEXT,IRQ,IDENTITY,SCHEMA,HARDWARE,FLAGS,TOKEN,PENDING,REARM=range(1,10)
NEST=0x801f6090
FIELDS='calls fault takes disabled rearmed flags_before'.split()

class KernelHooks(dict):
    """Run stock nonblocking takes for SEM; other RTOS objects remain fixtures.

    Machine's preexisting address hook consults this mapping on each entry.
    A false membership result lets the original instruction execute normally.
    No native take, constructor, count/flag or critical instruction is replaced.
    """
    def __init__(self,m):super().__init__(m.hooks);self.m=m
    def __contains__(self,address):
        if address==0x80076950 and self.m.uc.reg_read(REGS[0])==SEM and self.m.uc.reg_read(REGS[1])==0:
            return False
        return super().__contains__(address)

class NativePorts:
    def native_setup(self):
        m=self.m
        self.nvic_writes=[];self.pending_nvic=[];self.executed=set();self.allocations=[]
        self.disable_works=True;self.enable_works=True;self.reassert_pending=False
        self.active_on_disable=False;self.pending_on_enable=False;self.inject=None
        self.native_entries=0
        for reg in (arm.UC_ARM_REG_BASEPRI,arm.UC_ARM_REG_PRIMASK,arm.UC_ARM_REG_CONTROL):
            m.uc.reg_write(reg,0)
        put32(m,NEST,0);put32(m,0xe000ed04,0)
        m.uc.mem_write(0x801f9014,b'\x20');put32(m,0x801f9018,0x700)
        put32(m,ISER,BIT|OTHER);put32(m,ISPR,BIT|OTHER);put32(m,IABR,0)
        m.uc.mem_write(0xe000e46e,b'\x50')
        for addr in (0x80073ec8,0x80073f18,0x80076628,0x80032828,0x80032878):
            m.hooks.pop(addr,None)
        m.hooks=KernelHooks(m)
        def allocate(a):
            size=a[0];self.allocations.append(size)
            address=EVENT if size==12 else SEM if size==0x50 else 0
            assert address,size
            m.uc.mem_write(address,bytes(size));return address
        saved=m.hooks.get(0x8006de78)
        m.hooks[0x8006de78]=allocate
        def code(uc,pc,size,user):
            # Apply modeled NVIC write-one effects before the next instruction.
            for address,value in self.pending_nvic:put32(m,address,value)
            self.pending_nvic=[]
            if 0x80032000<=pc<0x80034000 or 0x80073000<=pc<0x80078000:
                self.executed.add(pc)
            if pc==0x80076950 and uc.reg_read(REGS[0])==SEM and not uc.reg_read(REGS[1]):
                self.native_entries+=1
            if self.inject:self.inject(pc)
        m.uc.hook_add(UC_HOOK_CODE,code)
        assert m.invoke(0x800321b8,[DESCRIPTOR])==EVENT
        if saved is None:m.hooks.pop(0x8006de78)
        else:m.hooks[0x8006de78]=saved
        put32(m,HOST+4,EVENT)
        def nvic(uc,access,address,size,value,user):
            assert size==4
            if address not in (ISER,ICER,ISPR,ICPR):return
            self.nvic_writes.append((address,value))
            enabled=word(m,ISER);pending=word(m,ISPR)
            if address==ICER:
                if self.disable_works:enabled&=~value
                if self.active_on_disable:self.pending_nvic.append((IABR,BIT))
            if address==ISER:
                if self.enable_works:enabled|=value
                if self.pending_on_enable:pending|=BIT
            if address==ICPR:
                pending&=~value
                if self.reassert_pending:pending|=BIT
            if address==ISPR:pending|=value
            self.pending_nvic.extend(((ISER,enabled),(ICER,enabled),(ISPR,pending),(ICPR,pending)))
        m.uc.hook_add(UC_HOOK_MEM_WRITE,nvic,begin=0xe000e100,end=0xe000e30f)
        put32(m,self.syms['sdp_kernel_port'],self.syms['sdp_event_drain']|1)
    def ev(self):
        return dict(zip(FIELDS,struct.unpack('<6I',self.m.uc.mem_read(self.syms['sdp_event_state'],24))))
    def tokens(self):return word(self.m,SEM+0x38)
    def drain(self):
        return self.m.invoke(self.syms['sdp_event_drain'],[0,EVENT])
    def post_native(self,mask):
        return self.m.invoke(0x80032828,[EVENT,mask])
    def model(self,a):
        assert a[0] not in (KERNEL_BEFORE,KERNEL_AFTER,KERNEL_ADMIT),'native drain called MODEL kernel clearing'
        return RecoveryPorts.model(self,a)
    def delay(self,a):
        result=RecoveryPorts.delay(self,a)
        # Replace the old fixture's impossible binary count of three with the
        # actual object's single queued token. Reset behavior remains synthetic.
        if self.rec()['phase']==RESET and not word(self.m,SYSTEM)&RESET_DATA:
            put32(self.m,SEM+0x38,1);self.sem_count=0
        return result

class NativeRecovery(NativePorts,RecoveryProbe):
    def __init__(self):RecoveryProbe.__init__(self);self.native_setup()

def handoff(passed):
    from verify_handoff_dependencies import Dependencies,FS1,SCRATCH
    from verify_sd_card_recovery import STOP_FIELDS
    class NativeHandoff(NativePorts,RecoveryPorts,Dependencies):
        def __init__(self):
            Dependencies.__init__(self);install(self.m,self.syms)
            self.configure();self.native_setup();self.fail_once=True
            self.decisions[SAFE]=0
        def owner(self):return self.unit_held and FS1 in self.tokens
        def stop_state(self):
            return dict(zip(STOP_FIELDS,struct.unpack('<10I',self.m.uc.mem_read(self.syms['sdp_stop_state'],40))))
        def data_deliver(self,a):
            assert self.owner() and word(self.m,ISER)&BIT
            initial=self.current_io and 0x80735b80<=self.current_io[1]<0x8077c580
            faulty=self.fail_once and initial and a[1]==0x185
            raw=1 if a[1]==0x183 else 2
            if faulty:raw|=0x100000;self.fail_once=False
            put32(self.m,EVENT+8,0);put32(self.m,IRQ_STATUS,raw)
            from sd_registers import PRESENT,CLOCK_STABLE,DAT0_HIGH
            put32(self.m,PRESENT,CLOCK_STABLE|(0x206 if faulty else DAT0_HIGH));return 1
    r=NativeHandoff();r.step();r.retained()
    assert r.tokens=={FS1,SCRATCH} and r.locked and r.rec()['phase']==VERIFY
    assert r.rec()['resets']==1 and r.ev()['rearmed'] and word(r.m,SEM+0x38)==0
    assert not r.ui_attempts and not any(t[0]=='leave' for t in r.trace)
    r.decisions[SAFE]=1
    assert r.resume()==7 and not r.tokens and not r.locked and not r.unit_held
    assert not r.ui_attempts and r.native_entries and 0x80076958 in r.executed
    assert all(t['step'] not in (KERNEL_BEFORE,KERNEL_AFTER,KERNEL_ADMIT) for t in r.model_trace)
    passed('whole_handoff_native_event_drain_retains_gate_filesystem_scratch_and_SD_ownership_until_MODEL_validity')

def main():
    checks=[]
    def passed(case):checks.append(dict(case=case,passed=True))
    assert hashlib.sha256(IMAGE).hexdigest()=='64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
    r=NativeRecovery();m=r.m
    assert bytes(m.uc.mem_read(DESCRIPTOR,12))==struct.pack('<3I',4,0,0)
    assert r.allocations==[12,0x50] and word(m,EVENT)==SEM and word(m,EVENT+4)==1
    assert word(m,EVENT+8)==0 and r.tokens()==0 and word(m,SEM+0x3c)==1
    assert word(m,SEM+0x40)==0 and word(m,SEM)==SEM
    assert not word(m,SEM+0x10) and not word(m,SEM+0x24)
    assert 0x80076348 in r.executed and not word(m,NEST)
    passed('stock_SD_descriptor_and_original_constructor_create_auto_clear_event_with_binary_semaphore')

    r=NativeRecovery();r.post_native(2);r.post_native(4);r.post_native(0x180)
    assert word(r.m,EVENT+8)==0x186 and r.tokens()==1
    assert r.m.invoke(0x80032208,[EVENT,0])==0
    assert word(r.m,EVENT+8)==0 and r.tokens()==1
    assert r.m.invoke(0x80076950,[SEM,0])==1 and r.tokens()==0
    assert r.m.invoke(0x80076950,[SEM,0])==0
    assert r.m.invoke(0x80073dd0,[SEM])==0
    assert {0x800324b0,0x80076628,0x80032368,0x80076958,0x80073dd0}<=r.executed
    passed('native_posts_coalesce_to_one_token_and_flag_clear_alone_does_not_drain_it')

    r=NativeRecovery();m=r.m
    m.uc.reg_write(arm.UC_ARM_REG_IPSR,126) # IRQ110 + sixteen exception slots
    m.uc.reg_write(arm.UC_ARM_REG_BASEPRI,0x40)
    for flag in (2,4):
        assert r.post_native(flag)==0 and m.uc.reg_read(arm.UC_ARM_REG_BASEPRI)==0x40
    assert r.tokens()==1 and word(m,EVENT+8)==6 and 0x80074058 in r.executed
    assert not word(m,NEST)
    m.uc.reg_write(arm.UC_ARM_REG_IPSR,0);m.uc.reg_write(arm.UC_ARM_REG_BASEPRI,0)
    assert r.drain()==1 and not r.tokens()
    passed('stock_ISR_post_checks_IRQ_context_and_preserves_prior_BASEPRI_while_coalescing_binary_wakeup')

    for token in (0,1):
        r=NativeRecovery();put32(r.m,EVENT+8,0x186);put32(r.m,SEM+0x38,token)
        assert r.drain()==1 and r.ev()['takes']==token and r.ev()['rearmed']
        assert not r.tokens() and not word(r.m,EVENT+8)
        assert r.ev()['flags_before']==0x186
        assert word(r.m,ISER)==BIT|OTHER and word(r.m,ISPR)==OTHER
        assert r.nvic_writes==[(ICER,BIT),(ICPR,BIT),(ISER,BIT)]
        assert not word(r.m,NEST) and not r.m.uc.reg_read(arm.UC_ARM_REG_BASEPRI)
        assert {0x80033e08,0x80033e38,0x80073dd0,0x80076958}<=r.executed
    passed('native_drain_clears_flags_binary_token_and_pending_IRQ_then_rearms_only_target_bit')

    for reg,value in ((arm.UC_ARM_REG_BASEPRI,0x40),(arm.UC_ARM_REG_PRIMASK,1),
                      (arm.UC_ARM_REG_CONTROL,1),(arm.UC_ARM_REG_IPSR,20)):
        r=NativeRecovery();put32(r.m,EVENT+8,2);r.m.uc.reg_write(reg,value)
        assert r.drain()==0 and r.ev()['fault']==CONTEXT
        assert not r.nvic_writes and word(r.m,EVENT+8)==2
        assert r.m.uc.reg_read(reg)==value
    r=NativeRecovery();put32(r.m,NEST,1)
    assert r.drain()==0 and r.ev()['fault']==CONTEXT and word(r.m,NEST)==1
    passed('unsupported_interrupt_privilege_or_prior_critical_context_is_refused_without_mask_mutation')

    for priority,enabled,active in ((0x10,BIT,0),(0x31,BIT,0),(0x50,OTHER,0),(0x50,BIT,BIT)):
        r=NativeRecovery();r.m.uc.mem_write(0xe000e46e,bytes([priority]))
        put32(r.m,ISER,enabled);put32(r.m,IABR,active)
        assert r.drain()==0 and r.ev()['fault']==IRQ and not r.nvic_writes
    passed('unsupported_priority_previously_disabled_or_active_target_IRQ_is_refused')

    for unit,event in ((1,EVENT),(0,0),(0,EVENT+4),(0,EVENT+1)):
        r=NativeRecovery()
        assert r.m.invoke(r.syms['sdp_event_drain'],[unit,event])==0
        assert r.ev()['fault']==IDENTITY and not r.nvic_writes
    r=NativeRecovery();put32(r.m,EVENT+4,0)
    assert not r.drain() and r.ev()['fault']==IDENTITY
    passed('wrong_unit_handle_alignment_or_event_mode_cannot_clear_an_unrelated_event')

    for address,value in ((SEM,0),(SEM+0x3c,2),(SEM+0x40,4),(SEM+0x38,2),
                          (SEM+0x10,1),(SEM+0x24,1)):
        r=NativeRecovery();put32(r.m,address,value)
        assert not r.drain() and r.ev()['fault']==SCHEMA
        assert not word(r.m,ISER)&BIT and not r.ev()['rearmed'] and not r.native_entries
        assert not word(r.m,NEST) and not r.m.uc.reg_read(arm.UC_ARM_REG_BASEPRI)
    passed('nonbinary_objects_corrupt_counts_or_kernel_waiters_fail_before_native_take_or_scheduler_path')

    for broken,active in ((True,False),(False,True)):
        r=NativeRecovery();r.disable_works=not broken;r.active_on_disable=active
        assert not r.drain() and r.ev()['fault']==IRQ
        assert not r.ev()['rearmed'] and not word(r.m,NEST)
    passed('disable_acknowledgement_and_active_IRQ_are_checked_before_event_mutation')

    for register in (IRQ_SIGNAL,IRQ_STATUS):
        r=NativeRecovery();put32(r.m,register,2)
        assert not r.drain() and r.ev()['fault']==HARDWARE
        assert not word(r.m,ISER)&BIT and not r.native_entries
    passed('live_controller_signal_or_status_refuses_software_only_drain')

    r=NativeRecovery();r.reassert_pending=True
    assert not r.drain() and r.ev()['fault']==PENDING and not word(r.m,ISER)&BIT
    passed('reasserted_pending_IRQ_is_rejected_after_write_one_clear')

    for address,value,fault in ((EVENT+8,2,FLAGS),(SEM+0x38,1,TOKEN),
                                (IRQ_STATUS,2,HARDWARE),(ISPR,BIT,PENDING),(HOST+4,0,IDENTITY)):
        r=NativeRecovery();fired=[]
        def inject(pc):
            if pc==0x80032878 and not fired:
                fired.append(True);put32(r.m,address,value)
        r.inject=inject
        assert not r.drain() and r.ev()['fault']==fault,(address,r.ev())
        assert not word(r.m,ISER)&BIT and not word(r.m,NEST)
    passed('late_flags_token_status_pending_or_handle_change_is_detected_without_rearming')

    r=NativeRecovery();put32(r.m,SEM+0x38,1)
    def late_token(pc):
        if pc==0x80076950 and r.native_entries==2:put32(r.m,SEM+0x38,1)
    r.inject=late_token
    assert not r.drain() and r.ev()['fault']==TOKEN and r.ev()['takes']==2
    assert not word(r.m,ISER)&BIT
    passed('token_post_between_two_nonblocking_takes_violates_exclusion_and_retains_disabled_IRQ')

    for enabled,pending in ((False,False),(True,True)):
        r=NativeRecovery();r.enable_works=enabled;r.pending_on_enable=pending
        assert not r.drain() and r.ev()['fault']==REARM
        assert not r.ev()['rearmed']
        assert not word(r.m,ISER)&BIT and r.nvic_writes[-1]==(ICER,BIT)
        assert not word(r.m,NEST)
    passed('failed_enable_or_pending_on_rearm_disables_target_again_and_returns_failure')

    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(9,1)):
            r=NativeRecovery();r.fault=None;r.post_native(0x186)
            assert r.request(op,blocks,offset)==0 and not r.owner()
            assert r.dma_trace and not r.rec()['fault'] and r.rec()['drains']==1
            assert not r.tokens() and word(r.m,ISER)&BIT
            assert [t['step'] for t in r.model_trace]==[QUIET_ADMIT]
    passed('normal_direct_and_bounce_read_write_use_native_event_drain_before_DMA_without_MODEL_kernel_port')

    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(9,1)):
            r=NativeRecovery()
            assert r.request(op,blocks,offset)==0xffffd8ef and not r.owner()
            assert r.rec()['phase']==DONE and r.rec()['drains']==3 and r.rec()['resets']==1
            assert not r.tokens() and not word(r.m,EVENT+8) and r.ev()['rearmed']
            assert not any(t['step'] in (KERNEL_BEFORE,KERNEL_AFTER,KERNEL_ADMIT) for t in r.model_trace)
    passed('failed_read_write_retained_stack_runs_stock_abort_and_checked_reset_with_native_binary_event_drains')

    r=NativeRecovery();r.reassert_pending=True;r.request();r.retained(DIRTY_SW)
    assert not r.dma_trace and not word(r.m,ISER)&BIT
    passed('native_drain_fault_latches_recovery_failure_and_keeps_parent_transfer_and_token_before_DMA')

    r=NativeRecovery();r.m.uc.reg_write(arm.UC_ARM_REG_BASEPRI,0x40)
    r.request();r.retained(DIRTY_SW)
    assert r.ev()['fault']==CONTEXT and not r.dma_trace and not r.nvic_writes
    assert r.m.uc.reg_read(arm.UC_ARM_REG_BASEPRI)==0x40
    assert 0x80032530 not in r.executed
    passed('recovery_integration_checks_prior_mask_before_stock_flag_peek_can_overwrite_it')

    r=NativeRecovery();original=r.m.hooks[0x2102bb00]
    def bad_context(a):
        result=original(a)
        if a[0]==SAFE:r.m.uc.reg_write(arm.UC_ARM_REG_BASEPRI,0x40)
        return result
    r.m.hooks[0x2102bb00]=bad_context
    r.request();r.retained(DIRTY_SW)
    assert r.m.uc.reg_read(arm.UC_ARM_REG_BASEPRI)==0x40 and r.rec()['phase']!=DONE
    r.resume();r.retained(DIRTY_SW)
    assert r.m.uc.reg_read(arm.UC_ARM_REG_BASEPRI)==0x40
    passed('final_validity_provider_cannot_change_caller_mask_and_bypass_native_context_revalidation')

    handoff(passed)
    lines=[]
    for first,last in ((0x80032270,0x800322d8),(0x80032368,0x800323a0),
                       (0x800324b0,0x8003258c),(0x80033d88,0x80033e68),
                       (0x80073dd0,0x80073e24),(0x80073ec8,0x80073f48),
                       (0x80076348,0x800763d8),(0x80076628,0x800767e0),
                       (0x80076950,0x80076bb8)):
        lines.append(f'\n# {first:08x}..{last:08x}')
        lines.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(first,last))
    (ROOT/'analysis/sd_native_event_disassembly.txt').write_text('\n'.join(lines)+'\n')
    out=ROOT/'analysis/sd_native_event_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),test_elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Original constructor, critical, flag clear/peek, ISR post, binary nonblocking take and count instructions execute',
      'Allocator and non-event RTOS objects, scheduler/time, files/sector translation and SD/NVIC side effects remain fixtures',
      'NVIC write-one semantics explicitly simulated; no interrupt arbitration, bus timing, physical DMA/cache/card validity or persistence proof',
      'QUIET still pins all event users and excludes old controller/IRQ/task posts through admission; disabling IRQ does not provide this contract',
      'Counterfactual abort row and reset permission remain MODEL; no device gate/recovery binding, card access, deployment image or installation']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))

if __name__=='__main__':main()
