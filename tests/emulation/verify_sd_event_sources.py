#!/usr/bin/env python3
"""Original SD signal-source paths and exclusion counterexamples; offline only.

Scheduling/source arrival, register side effects and physical recovery remain
fixtures. Controlled late signals deliberately violate MODEL QUIET to expose
what software clearing and registered transfer scopes cannot guarantee.
"""
import hashlib,json,struct,sys
from unicorn import UC_HOOK_CODE
import unicorn.arm_const as arm
from verify_pad_protocol import ROOT,IMAGE,REGS
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_storage_lifetimes import instructions
from verify_sd_native_event import NativeRecovery,KernelHooks,SEM,BIT,ISER,NEST
from verify_sd_checked_recovery import SAFE,VERIFY,DONE,STOP_FAILED
from verify_sd_transfer_lifetime import HOST,EVENT
from verify_sd_transfer_probe import ELF
from sd_registers import IRQ_STATUS,IRQ_SIGNAL,PRESENT,ACTIVITY

sys.path.insert(0,str(ROOT/'tools/firmware'))
from audit_sd_event_sources import inventory,SD_IRQ_POSTS
CALLBACK_SLOT=0x802350e4;CALLBACK=0x2102b900
OTHER_EVENT=0x21009200;OTHER_SEM=0x21009300

class SourceHooks(KernelHooks):
    def __contains__(self,address):
        if address==0x800763d8 and self.m.uc.reg_read(REGS[0])==SEM and not self.m.uc.reg_read(REGS[2]):
            return False # original zero-timeout task give for the real SD object
        return super().__contains__(address)

class Sources(NativeRecovery):
    def __init__(self):
        super().__init__();self.m.hooks=SourceHooks(self.m)
        self.post_trace=[];self.callbacks=[];self.mixed=None;self.stop_mixed=False
        self.fault=None
        def posted(uc,pc,size,user):
            self.post_trace.append(dict(pc=hex(pc),event=uc.reg_read(REGS[0]),
                flags=uc.reg_read(REGS[1]),ipsr=uc.reg_read(arm.UC_ARM_REG_IPSR)))
        for pc in (0x80032828,0x80032888):
            self.m.uc.hook_add(UC_HOOK_CODE,posted,begin=pc,end=pc)
        def callback(a):self.callbacks.append(a[:2]);return 0
        self.m.hooks[CALLBACK]=callback
        put32(self.m,CALLBACK_SLOT,CALLBACK|1)
    def notify(self,unit=0):return self.m.invoke(0x80068508,[unit])
    def outer(self,a,b):return self.m.invoke(0x80036c98,[a,b])
    def data_deliver(self,a):
        result=super().data_deliver(a)
        if self.mixed and a[1]==self.mixed[0]:
            put32(self.m,EVENT+8,self.mixed[1]);self.mixed=None
            # Exact signal coexistence is a timing fixture; original post and
            # ANY predicate execute and combine these bits with raw completion.
        return result
    def deliver(self,a):
        result=super().deliver(a)
        if self.stop_mixed and self.stop_state()['active']:
            put32(self.m,EVENT+8,0x100);self.stop_mixed=False
        return result

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    audit=inventory();refs=audit['targets']
    assert len(refs['post_ISR']['direct_references'])==13
    assert len(refs['post_task']['direct_references'])==13
    assert refs['notify_SD']['direct_references']==['0x80036cca']
    assert refs['notify_storage']['direct_references']==['0x80045d46','0x8005fd00','0x80062292']
    assert set(map(hex,SD_IRQ_POSTS))<=set(refs['post_ISR']['direct_references'])
    assert audit['IRQ_descriptors']==[dict(callback='0x8006ea91',irq=110),dict(callback='0x80053b81',irq=111)]
    (ROOT/'analysis/sd_event_sources_inventory.json').write_text(json.dumps(audit,indent=2)+'\n')
    passed('pinned_bounded_inventory_separates_controller_and_software_notification_sources_and_outer_callers')

    for held in (False,True):
        r=Sources();r.held=held;put32(r.m,ISER,0);put32(r.m,IRQ_SIGNAL,0)
        assert r.notify()==0 and word(r.m,EVENT+8)==0x100 and r.tokens()==1
        assert r.held==held and not r.events and not word(r.m,NEST)
        assert r.post_trace==[dict(pc='0x80032888',event=EVENT,flags=0x100,ipsr=0)]
        assert {0x80032550,0x800763d8}<=r.executed
    passed('stock_task_notification_posts_binary_SD_wakeup_without_SD_lock_even_with_target_IRQ_disabled')

    r=Sources();put32(r.m,ISER,0)
    r.m.uc.reg_write(arm.UC_ARM_REG_IPSR,36)
    r.m.uc.mem_write(0xe000e3f0+36,b'\x50')
    assert r.notify()==0 and word(r.m,EVENT+8)==0x100 and r.tokens()==1
    assert r.post_trace==[dict(pc='0x80032828',event=EVENT,flags=0x100,ipsr=36)]
    r.m.uc.reg_write(arm.UC_ARM_REG_IPSR,0)
    passed('software_notification_selects_ISR_post_for_other_exception_context_independently_of_SD_IRQ_mask')

    for first,second,expected in ((0,1,0x100),(1,1,0),(0,2,0)):
        r=Sources();r.outer(first,second)
        assert word(r.m,EVENT+8)==expected and r.tokens()==int(bool(expected))
        assert r.callbacks==([[1,int(bool(first))]] if second==1 else [])
    r=Sources();put32(r.m,CALLBACK_SLOT,0);r.outer(0,1)
    assert not word(r.m,EVENT+8) and not r.post_trace and not r.callbacks
    passed('outer_notification_posts_before_nonnull_callback_only_for_examined_zero_one_branch')

    r=Sources();r.held=True;put32(r.m,ISER,0);put32(r.m,PRESENT,0x206)
    filesystem=0x801f8f58
    r.m.uc.mem_write(filesystem,b'\x01');put32(r.m,filesystem+4,0x12345678)
    seen=[]
    def detach_callback(a):
        seen.append(dict(args=a[:2],registration=word(r.m,filesystem+4),
                         flags=word(r.m,EVENT+8),busy=word(r.m,PRESENT)))
        r.m.uc.mem_write(filesystem,b'\0');return 0 # modeled transition acknowledgement
    r.m.hooks[CALLBACK]=detach_callback;r.m.hooks[0x80077686]=lambda a:0
    assert r.m.invoke(0x80062230,[0x41])==1
    assert seen==[dict(args=[1,0],registration=0,flags=0x100,busy=0x206)]
    assert r.held and word(r.m,PRESENT)&ACTIVITY and word(r.m,EVENT+8)==0x100
    passed('original_detach_mutates_registration_and_posts_while_SD_owned_without_establishing_physical_idle')

    for mask in (0x183,0x185):
        for flag in (1,0x80,0x100):
            r=Sources();r.mixed=(mask,flag);r.decisions[SAFE]=0
            r.request();r.retained()
            assert r.probe()['reasons']&2 and not r.probe()['errors']
            assert r.rec()['phase']==VERIFY and r.rec()['resets']==1
            r.decisions[SAFE]=1
            assert r.resume()==0xffffd8ef and not r.owner() and r.rec()['phase']==DONE
    passed('compiled_guard_rejects_mixed_command_or_data_success_and_error_software_wakeup_bits_until_checked_join')

    r=Sources();r.fault=(0x185,'hidden_error');r.stop_mixed=True
    r.request();r.retained(STOP_FAILED)
    assert r.stop_state()['raw']==1 and not r.reset_writes() and not r.stop_state()['errors']
    passed('fresh_raw_stop_completion_cannot_override_mixed_software_wakeup_or_authorize_reset')

    r=Sources();r.verify_dma_clean=False;fired=[]
    def late_status(pc):
        if pc==(r.syms['sdp_stock_data_read']&~1) and not fired:
            assert r.rec()['admitted'];fired.append(True);put32(r.m,IRQ_STATUS,2)
    r.inject=late_status
    assert r.request()==0 and not r.owner()
    assert fired and r.dma_trace[0]['raw']==2 and not r.dma_trace[0]['flags']
    assert not r.rec()['fault'] and not r.rec()['resets']
    passed('counterexample_old_source_can_reassert_TC_after_checked_admission_before_actual_DMA_address_write',
           limitation='Deliberately false QUIET contract; source timing and W1C effects are synthetic')

    r=Sources();r.origin='previous transfer: intentionally violated QUIET'
    assert r.request()==0 and not r.owner() and not r.rec()['resets']
    assert (2,r.origin) in r.irq_origins and not r.probe()['errors']
    passed('counterexample_old_data_completion_has_no_hardware_request_identity_and_passes_a_new_software_scope',
           limitation='Origin is fixture metadata; native code cannot read it. Physical prior join/source exclusion remains required')

    r=Sources();put32(r.m,IRQ_STATUS,2);put32(r.m,IRQ_SIGNAL,0)
    r.m.uc.reg_write(arm.UC_ARM_REG_IPSR,126)
    r.m.invoke(0x8006ea90,[])
    assert word(r.m,IRQ_STATUS)==2 and not word(r.m,EVENT+8) and not r.tokens()
    put32(r.m,IRQ_SIGNAL,2);r.m.invoke(0x8006ea90,[])
    assert not word(r.m,IRQ_STATUS) and word(r.m,EVENT+8)==4 and r.tokens()==1
    r.m.uc.reg_write(arm.UC_ARM_REG_IPSR,0)
    passed('original_masked_IRQ_keeps_TC_status_which_posts_as_completion_after_signal_mask_reopens')

    r=Sources();m=r.m
    def allocate(a):return OTHER_EVENT if a[0]==12 else OTHER_SEM if a[0]==0x50 else 0
    m.uc.mem_write(OTHER_EVENT,bytes(12));m.uc.mem_write(OTHER_SEM,bytes(0x50))
    m.hooks[0x8006de78]=allocate
    assert m.invoke(0x800321b8,[0x800a07b0])==OTHER_EVENT
    m.hooks.pop(0x8006de78);put32(m,HOST+20,OTHER_EVENT)
    put32(m,IRQ_STATUS,2);put32(m,IRQ_SIGNAL,2)
    m.uc.mem_write(0xe000e46f,b'\x50');m.uc.reg_write(arm.UC_ARM_REG_IPSR,127)
    m.invoke(0x80053b80,[])
    assert not word(m,IRQ_STATUS) and not word(m,EVENT+8) and not r.tokens()
    assert word(m,OTHER_EVENT+8)==4 and word(m,OTHER_SEM+0x38)==1
    m.uc.reg_write(arm.UC_ARM_REG_IPSR,0)
    passed('second_registered_unit_wrapper_reaches_same_MMIO_acknowledgement_but_a_different_event_slot',
           limitation='Synthetic unit1 setup; its actual enable/configuration on the L6 is not established')

    lines=[]
    for first,last in ((0x80036c98,0x80036cda),(0x80068508,0x80068538),
                       (0x80032550,0x800325dc),(0x8006ea90,0x8006eba8),
                       (0x80053b80,0x80053b86),(0x80062230,0x800622ac)):
        lines.append(f'\n# {first:08x}..{last:08x}')
        lines.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(first,last))
    (ROOT/'analysis/sd_event_sources_disassembly.txt').write_text('\n'.join(lines)+'\n')
    out=ROOT/'analysis/sd_event_sources_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
      test_elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Original notification/context/event/kernel/IRQ/detach paths execute with modeled acknowledgement and MMIO',
      'Mixed flag coexistence and late hardware arrivals are controlled timing fixtures, not reproduced mixer faults',
      'Bounded direct-reference inventory is not exhaustive; aliases/indirect callers and runtime unit1 configuration remain open',
      'QUIET must exclude old hardware and conflicting software mutations through submission/unwind; it remains MODEL',
      'No native gate, physical reset/DMA/cache/card proof, device access, firmware image or installation']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))

if __name__=='__main__':main()
