#!/usr/bin/env python3
"""Retained startup PIO failures in the combined offline artifact.

Original cold setup, enumeration, command, FIFO, IRQ and event-wait instructions
execute. Card/IRQ timing, W1C/reset effects, scheduler and event-post endpoints
are fixtures. This closes an event-validation hole; it does not grant physical
source permission or release capture. No device access or firmware BIN.
"""
import hashlib,json,struct
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_sd_cold_start import Cold,high_speed_card,PIO_READ_WAIT
from verify_sd_transfer_lifetime import EVENT,CARD,HOST
from verify_pad_protocol import ROOT,IMAGE,REGS,RETURN
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_scheduling_boundaries import stop
from plan_capture_sd_retained import ELF,plan
from capture_jump_patches import symbols
from sd_registers import SD,IRQ_STATUS,PROTOCOL,PRESENT,SYSTEM,MIX,BLOCKS

N=symbols(ELF);PLAN=plan();TASK=0x21039000;IRQ_RETURN=0x2103d000

class Enumeration(Cold):
    elf_path=ELF;names=N;patch_plan=PLAN
    def __init__(self,guard=True):
        super().__init__();m=self.m
        with self.elf_path.open('rb') as f:
            for s in ELFFile(f).iter_segments():
                if s['p_type']=='PT_LOAD':
                    m.uc.mem_write(s['p_vaddr'],s.data()+bytes(s['p_memsz']-s['p_filesz']))
        if guard:
            for p in self.patch_plan['patches']:
                if p.get('adapter','').startswith('sdp_'):
                    m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
        self.guard=guard;self.w1c=[];self.mmio=[];self.current_site=0
        self.irq_context=None;self.irq_returning=False;self.injection=None
        self.retained=False;self.stop_delays=False;self.pio_number=0
        self.pause_wait=False;self.paused=False
        self.entry_sp=None;self.command_entries=[]
        put32(m,0x808e291c,TASK)
        # Original IRQ computes the posted bits; only the RTOS post endpoint
        # and scheduler are modeled. Native ANY/auto-clear wait code executes.
        m.hooks[0x80032828]=lambda a:put32(m,a[0]+8,word(m,a[0]+8)|a[1]) or 0
        m.uc.mem_write(IRQ_RETURN,b'\x00\xbf')
        def write(u,k,p,n,v,x):
            self.mmio.append((p,n,v))
            if p==IRQ_STATUS:self.w1c.append(word(m,p)&~v)
        m.uc.hook_add(UC_HOOK_MEM_WRITE,write,begin=SD,end=SD+0xfff)
        def code(u,pc,n,x):
            if self.w1c:put32(m,IRQ_STATUS,self.w1c.pop(0))
            if pc==0x800688d0:self.entry_sp=u.reg_read(A.UC_ARM_REG_SP)
            if pc==0x8006a348:self.command_entries.append(bytes(u.mem_read(u.reg_read(REGS[0]),24)).hex())
            if pc==0x800328c0:self.current_site=(u.reg_read(A.UC_ARM_REG_LR)&~1)-4
            if pc==IRQ_RETURN:
                assert self.irq_context is not None
                u.context_restore(self.irq_context);self.irq_context=None
                u.reg_write(A.UC_ARM_REG_PC,u.reg_read(A.UC_ARM_REG_PC)|1)
                self.irq_returning=True
            elif pc==0x800326c0:
                if self.irq_returning:self.irq_returning=False;return
                args=[u.reg_read(r) for r in REGS[:4]]
                assert args[0]==EVENT and self.held
                mask=args[1];raw={0x183:1,0x185:2,4:2,8:0x20,0x10:0x10}[mask]
                if mask==0x185:self.pio_number+=1
                flags=0
                if self.injection:raw,flags=self.injection(mask,raw)
                self.waits.append(dict(site=hex(self.current_site),mask=mask,raw=raw,flags=flags))
                put32(m,EVENT+8,flags);put32(m,IRQ_STATUS,raw)
                if raw:
                    self.irq_context=u.context_save()
                    u.reg_write(REGS[0],0);u.reg_write(A.UC_ARM_REG_LR,IRQ_RETURN|1)
                    u.reg_write(A.UC_ARM_REG_PC,0x8006ea99)
        m.uc.hook_add(UC_HOOK_CODE,code)

    def at_wait(self,*args):pass # Never inject success in place of the IRQ.
    def created(self,name,value):
        result=super().created(name,value)
        if name=='controller_event' and value:put32(self.m,value+4,1)
        return result
    def delay(self,a):
        if self.stop_delays and self.state()['failed']:
            self.retained=True;return stop(self.m)
        if self.pause_wait and self.pio_number:
            self.paused=True;return stop(self.m)
        return super().delay(a)
    def state(self):
        return dict(zip('active unit event buffer bytes raw errors failed reasons waits commands join_calls joined finished'.split(),
                        struct.unpack('<14I',self.m.uc.mem_read(self.names['sdp_state'],56))))
    def resume_fault(self):
        self.m.reached_return=False
        self.m.uc.emu_start(self.m.uc.reg_read(A.UC_ARM_REG_PC)|1,RETURN+2,count=1000000)
        assert self.m.reached_return and self.retained
    def held_fault(self):
        assert self.held and self.retained and self.state()['failed']
        assert self.state()['active']==2 and not self.state()['finished']
        assert self.m.uc.reg_read(A.UC_ARM_REG_SP)<self.entry_sp
        assert self.m.uc.mem_read(CARD+5,1)!=b'\x02'
        before=(list(self.commands),list(self.fifo_reads),list(self.dma),list(self.mmio))
        # No later clearing of registers may unwind/retry this owned failure.
        put32(self.m,IRQ_STATUS,0);put32(self.m,PROTOCOL,0x22)
        put32(self.m,PRESENT,0x01000008);put32(self.m,SYSTEM,0x008f801f)
        for _ in range(3):self.resume_fault()
        assert before==(self.commands,self.fifo_reads,self.dma,self.mmio)
        assert self.held and not self.state()['joined']

def main():
    checks=[]
    def passed(case,**extra):checks.append(dict(case=case,**extra))
    for fast in (False,True):
        old=Enumeration(False);new=Enumeration()
        if fast:high_speed_card(old);high_speed_card(new)
        assert old.enumerate()==new.enumerate()==0
        assert old.commands==new.commands and old.fifo_reads==new.fifo_reads
        assert old.mmio==new.mmio and not new.dma
        assert not new.held and new.state()['finished'] and not new.state()['active']
        assert new.pio_number==(6 if fast else 2)
        assert not any(word(new.m,N[name]) for name in
            ('sdp_source_port','sdp_chunk_admit_port','sdp_chunk_finish_port','sdp_cache_read_port'))
    passed('default_and_high_speed_original_enumeration_preserve_commands_FIFO_and_MMIO_without_granting_source_permission')

    for fast in (False,True):
        for flag in (1,0x80,0x100,0x104):
            r=Enumeration();r.stop_delays=True
            if fast:high_speed_card(r)
            r.injection=lambda mask,raw,flag=flag:(0,flag) if mask==0x185 else (raw,0)
            r.enumerate();r.held_fault()
            assert len(r.fifo_reads)==16 and r.pio_number==1
    passed('eight_pure_or_mixed_error_notifications_retain_first_PIO_and_enumeration_frames_before_card_ready')

    # The first startup read's TC must not satisfy a later read with only a
    # synthetic success flag. This is software latch freshness, not provenance.
    for number in (1,2,6):
        r=high_speed_card(Enumeration());r.stop_delays=True
        r.injection=lambda mask,raw,r=r,number=number:(0,4) if mask==0x185 and r.pio_number==number else (raw,0)
        r.enumerate();r.held_fault();assert r.pio_number==number
    passed('each_PIO_requires_its_own_raw_TC_latch_including_late_CMD6_read')

    for kind in ('raw_error','block_gap','stop_request','continue_request','dma_mode','block_size','owner','event','irq111'):
        r=high_speed_card(Enumeration());r.stop_delays=True
        def inject(mask,raw,r=r,kind=kind):
            if mask!=0x185:return raw,0
            if kind=='raw_error':raw|=0x100000
            elif kind=='block_gap':raw|=4
            elif kind=='stop_request':put32(r.m,PROTOCOL,word(r.m,PROTOCOL)|0x10000)
            elif kind=='continue_request':put32(r.m,PROTOCOL,word(r.m,PROTOCOL)|0x20000)
            elif kind=='dma_mode':put32(r.m,MIX,word(r.m,MIX)|1)
            elif kind=='block_size':put32(r.m,BLOCKS,0x10020)
            elif kind=='owner':put32(r.m,0x808e291c,TASK+4)
            elif kind=='event':put32(r.m,HOST+4,EVENT+0x100)
            elif kind=='irq111':put32(r.m,0xe000e10c,word(r.m,0xe000e10c)|(1<<15))
            return raw,0
        r.injection=inject;r.enumerate();r.held_fault()
    passed('hidden_raw_error_partial_modes_and_changed_span_or_identity_remain_retained')

    for mask in (0x183,8):
        r=high_speed_card(Enumeration());r.stop_delays=True
        r.injection=lambda requested,raw,mask=mask:(raw,0x100) if requested==mask else (raw,0)
        r.enumerate();r.held_fault()
    passed('command_and_FIFO_ready_waits_reject_mixed_software_abort_notifications')

    for kind in ('code','count','buffer'):
        r=Enumeration();r.stop_delays=True
        def corrupt(u,pc,n,x,r=r,kind=kind):
            request=u.reg_read(REGS[0])
            if kind=='code':u.mem_write(request,b'\x16')
            elif kind=='count':put32(r.m,request+16,2)
            elif kind=='buffer':put32(r.m,request+12,0xfffffff0)
        r.m.uc.hook_add(UC_HOOK_CODE,corrupt,begin=0x80069c58,end=0x80069c58)
        r.enumerate();r.held_fault()
        assert not r.pio_number and not r.fifo_reads and not r.dma
        assert not any(c['value']&0x200000 for c in r.commands)
    passed('unsupported_PIO_opcode_count_or_wrapping_buffer_holds_before_data_command_and_FIFO_access')

    for register,value in ((PRESENT,0x01000308),(SYSTEM,0x01000000)):
        r=Enumeration();r.pause_wait=True
        def busy(mask,raw,r=r,register=register,value=value):
            if mask==0x185:put32(r.m,register,value)
            return raw,0
        r.injection=busy;r.enumerate()
        assert r.held and r.paused and not r.state()['failed'] and not r.state()['finished']
        assert r.pio_number==1 and r.m.uc.mem_read(CARD+5,1)!=b'\x02'
        r.pause_wait=False;r.injection=None
        put32(r.m,PRESENT,0x01000008);put32(r.m,SYSTEM,0x008f801f)
        assert r.resume()==0 and not r.held and r.state()['finished']
    passed('host_activity_or_reset_retains_the_PIO_frame_until_the_modeled_condition_clears')

    r=Enumeration();assert r.enumerate()==0;r.stop_delays=True
    before=list(r.commands);r.operation(4)
    assert r.held and r.retained and r.state()['failed'] and r.commands==before
    passed('second_enumeration_is_refused_before_any_command_or_remount_attempt')

    r=Enumeration();r.stop_delays=True
    put32(r.m,N['sdp_state']+7*4,1) # A prior fault may never be erased by entry.
    r.enumerate()
    assert r.held and r.retained and r.state()['failed'] and not r.commands
    assert not r.state()['active'] and not r.state()['finished']
    passed('an_already_failed_scope_cannot_return_from_the_retained_fault_path_and_be_reinitialized')

    # Known unclosed physical premise: a model can label a fresh-looking raw TC
    # as old-origin. The code has no hardware request identifier to distinguish it.
    r=Enumeration();origins=[]
    def lying_origin(mask,raw):
        if mask==0x185:origins.append('previous transaction: violated physical source exclusion')
        return raw,0
    r.injection=lying_origin;assert r.enumerate()==0 and len(origins)==2
    passed('negative_control_old_origin_TC_still_passes_if_the_physical_source_premise_is_false',
           physical_source_exclusion_proven=False)

    out=ROOT/'analysis/sd_enumeration_guard_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        raw_code_bytes=PLAN['raw_code_bytes'],globals_bytes=PLAN['globals_bytes'],
        lz4_spare_bytes=PLAN['packing']['spare_bytes'],device_access=False,
        limitations=['Cold reset, IRQ timing and W1C are explicit fixtures; event posting and scheduler endpoints are modeled.',
            'No physical source exclusion, alias/cache ownership, coupled eight-stream simulation or capture release.',
            'A late prior-origin hardware TC can still satisfy a new software latch; no hardware request identity is claimed.',
            'Only traced unit-zero, one-block status/SCR/CMD6 PIO reads are supported; no retry/remount or alternate card family.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out))))

if __name__=='__main__':main()
