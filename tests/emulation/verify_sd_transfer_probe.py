#!/usr/bin/env python3
"""Compiled scoped SD probe + original driver/IRQ/event code. No device I/O.

Only the recovery JOINED callback, IRQ delivery, MMIO and kernel endpoints are
models. The probe is deliberately linked only into the handoff-test profile.
"""
import hashlib,json,struct
import unicorn.arm_const as arm
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from elftools.elf.elffile import ELFFile
from verify_overdub_prototype import Emulator
from verify_sd_transfer_lifetime import Sd,BUFFER,EVENT
from verify_pad_protocol import ROOT,IMAGE,BIAS,REGS,RETURN
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_scheduling_boundaries import stop

ELF=ROOT/'src/capture/handoff-test.elf';BOUNCE=0x2000c4d4
FIELDS='active unit event buffer bytes raw errors failed reasons waits commands join_calls joined finished'.split()

def patch(m,address,target,span):
    # Correct PC/literal alignment even at the halfword-aligned IRQ site.
    literal=(address+7)&~3;pc=(address+4)&~3
    code=struct.pack('<HH',0xf8df,0xf000+literal-pc)
    code+=bytes.fromhex('00bf')*((literal-address-4)//2)
    code+=struct.pack('<I',target|1)
    code+=bytes.fromhex('00bf')*((span-len(code))//2)
    assert len(code)==span
    m.uc.mem_write(address,code);m.uc.ctl_remove_cache(address,address+span)

def install(m,syms):
    for address,name,span in ((0x80068db0,'sdp_read',10),(0x80068e40,'sdp_write',10),
          (0x8006a348,'sdp_command',8),(0x800328c0,'sdp_wait',8),
          (0x8006eab6,'sdp_irq_hook',12)):
        patch(m,address,syms[name],span)

class Probe(Sd):
    elf_path=ELF
    def install_probe(self):install(self.m,self.syms)
    def __init__(self,enabled=True):
        super().__init__(Emulator(cpu_model=arm.UC_CPU_ARM_CORTEX_M7,mclass=True))
        m=self.m;m.uc.mem_map(0x10010000,0x20000)
        with self.elf_path.open('rb') as f:
            elf=ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type']=='PT_LOAD' and seg['p_filesz']:
                    m.uc.mem_write(seg['p_vaddr'],seg.data())
                if seg['p_type']=='PT_LOAD' and seg['p_memsz']>seg['p_filesz']:
                    m.uc.mem_write(seg['p_vaddr']+seg['p_filesz'],bytes(seg['p_memsz']-seg['p_filesz']))
            self.syms={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        self.waits=[];self.joins=[];self.native_commands=[];self.copies=[]
        self.fault=None;self.fault_once=True;self.pending=False;self.join_reply=0;self.kernel_waits=[]
        self.success_active=False;self.origin='current transfer';self.irq_origins=[]
        self.command_busy=False
        m.hooks.pop(0x8006a348);m.hooks.pop(0x800328c0)
        put32(m,0x402c0010,0x100)
        m.uc.mem_write(BOUNCE,bytes(range(256))*16)
        m.uc.mem_write(BUFFER,bytes([0xa5])*0x4000)
        m.hooks[0x80032828]=self.post
        m.hooks[0x80076950]=self.take
        m.hooks[0x80074580]=lambda a:put32(m,a[0],0) or 0
        m.hooks[0x80076bc8]=lambda a:1 # modeled expired deadline if no event
        m.hooks[0x80073ec8]=m.hooks[0x80073f18]=lambda a:0
        m.hooks[0x2102bd00]=self.join;m.hooks[0x2102bd04]=self.deliver
        def wait_entry(uc,pc,size,user):
            assert self.held
            self.waits.append(dict(pc=uc.reg_read(arm.UC_ARM_REG_LR)&~1,
                mask=uc.reg_read(REGS[1]),sp=uc.reg_read(arm.UC_ARM_REG_SP),
                out=uc.reg_read(REGS[3]),dma=word(m,0x402c0000)))
        m.uc.hook_add(UC_HOOK_CODE,wait_entry,begin=0x800328c0,end=0x800328c0)
        def command_entry(uc,pc,size,user):
            assert self.held
            if self.command_busy:put32(m,0x402c0024,1)
        m.uc.hook_add(UC_HOOK_CODE,command_entry,begin=0x8006a348,end=0x8006a348)
        def command_body(uc,pc,size,user):
            assert self.held
            self.native_commands.append(uc.reg_read(arm.UC_ARM_REG_R4))
        m.uc.hook_add(UC_HOOK_CODE,command_body,begin=0x8006a350,end=0x8006a350)
        def copy_entry(uc,pc,size,user):
            self.copies.append(tuple(uc.reg_read(r) for r in REGS[:3]))
        m.uc.hook_add(UC_HOOK_CODE,copy_entry,begin=0x80001754,end=0x80001754)
        if enabled:
            self.install_probe()
    def state(self):
        values=struct.unpack('<14I',self.m.uc.mem_read(self.syms['sdp_state'],56))
        return dict(zip(FIELDS,values))
    def seed(self,**values):
        for key,value in values.items():put32(self.m,self.syms['sdp_state']+FIELDS.index(key)*4,value)
    def post(self,a):
        assert a[0]==EVENT
        put32(self.m,EVENT+8,word(self.m,EVENT+8)|a[1]);return 0
    def take(self,a):
        assert a[0]==0x7002
        self.kernel_waits.append(a[1])
        return 1 if not a[1] else 0
    def deliver(self,a):
        assert self.held and self.state()['active'] and a[0]==EVENT and a[2]==5000
        mask=a[1];assert mask in (0x183,0x185,8,0x10)
        raw={0x183:1,0x185:2,8:0x20,0x10:0x10}[mask]
        faulty=self.fault and self.fault[0]==mask and self.fault_once
        if faulty:
            self.fault_once=False
            raw={'hidden_error':raw|0x100000,'error':0x20000,'timeout':0}[self.fault[1]]
        put32(self.m,EVENT+8,0);put32(self.m,0x402c0030,raw)
        put32(self.m,0x402c0024,0x207 if faulty else 0x204 if self.success_active else 0)
        self.irq_origins.append((raw,self.origin if mask==0x185 else 'current transfer'))
        return int(bool(raw))
    def join(self,a):
        s=self.state();assert self.held and s['active'] and not s['finished']
        assert a[:3]==[s['unit'],s['buffer'],s['bytes']]
        self.joins.append(dict(state=s,sp=self.m.uc.reg_read(arm.UC_ARM_REG_SP),
            dma=word(self.m,0x402c0000),copies=list(self.copies)))
        if self.pending:
            stop(self.m);return self.join_reply
        # The physical meaning of JOINED is supplied by this fixture, NOT by
        # stock cleanup/reset, clock stability or the probe's software state.
        put32(self.m,0x402c0024,0);put32(self.m,0x402c002c,0)
        return 1
    def resume(self):
        m=self.m;self.pending=False;m.reached_return=False
        m.uc.emu_start(m.uc.reg_read(arm.UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
        assert m.reached_return
        return m.uc.reg_read(REGS[0])

def handoff_cases(passed):
    from verify_handoff_dependencies import Dependencies,FS1,SCRATCH
    class HandoffProbe(Dependencies):
        def __init__(self):
            super().__init__()
            self.inject=False;self.join_pending=False;self.probe_joins=[];self.deliveries=[]
            install(self.m,self.syms)
            self.m.hooks[0x2102bd00]=self.join
            self.m.hooks[0x2102bd04]=self.deliver
        def deliver(self,a):
            assert self.unit_held and FS1 in self.tokens and self.current_io
            initial=0x80735b80<=self.current_io[1]<0x8077c580
            faulty=self.inject and initial and a[1]==0x185
            raw=1 if a[1]==0x183 else 2
            if faulty:raw|=0x100000;self.inject=False
            self.deliveries.append((raw,self.current_io))
            put32(self.m,EVENT+8,0);put32(self.m,0x402c0030,raw)
            put32(self.m,0x402c0024,0x207 if faulty else 0)
            return 1
        def join(self,a):
            assert self.unit_held and self.tokens=={FS1,SCRATCH} and self.locked
            state=struct.unpack('<14I',self.m.uc.mem_read(self.syms['sdp_state'],56))
            assert state[0]==1 and state[6]==0x100000 and state[13]==0
            self.probe_joins.append(dict(state=dict(zip(FIELDS,state)),
                tokens=sorted(self.tokens),sp=self.m.uc.reg_read(arm.UC_ARM_REG_SP)))
            if self.join_pending:return stop(self.m)
            put32(self.m,0x402c0024,0);put32(self.m,0x402c002c,0);return 1
        def resume(self):
            self.join_pending=False;m=self.m;m.reached_return=False
            m.uc.emu_start(m.uc.reg_read(arm.UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
            assert m.reached_return
            return m.uc.reg_read(REGS[0])
    r=HandoffProbe();assert r.step()==0
    assert r.deliveries and {io[0] for raw,io in r.deliveries}=={2,3}
    assert not r.probe_joins and not r.tokens and not r.unit_held and not r.locked
    assert not r.ui_attempts and not r.queue_calls
    passed('same_CPU_checked_handoff_and_compiled_probe_preserve_native_SD_completion_without_Main_service',
           limitation='Filesystem sector translation and logical file bytes remain the existing synthetic router')

    r=HandoffProbe();r.inject=True;r.join_pending=True;r.step()
    assert len(r.probe_joins)==1 and r.unit_held and r.tokens=={FS1,SCRATCH} and r.locked
    assert not any(t[0]=='leave' for t in r.trace) and not r.ui_attempts
    assert r.resume()==7 and not r.unit_held and not r.tokens and not r.locked
    assert len(r.probe_joins)==2 and r.probe_joins[-1]['state']['join_calls']==2
    assert not r.ui_attempts
    passed('checked_handoff_cannot_begin_rollback_or_release_while_native_SD_model_join_is_pending',
           limitation='Safe rollback after resume assumes the fixture JOINED contract; no physical recovery guarantee')

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    prefixes={0x800328c0:'ddf800c0cdf800c0',
              0x80068db0:'2de9f04188b048f64462',0x80068e40:'2de9f04f89b048f64462',
              0x8006a348:'2de9f04f8bb00478',0x8006eab6:'cc0503ea0203cef8003003d5'}
    # Assert actual bytes rather than trusting trampoline instruction spelling.
    # IRQ span includes its conditional branch as well as the W1C write.
    for address,expected in prefixes.items():
        raw=bytes.fromhex(expected)
        assert IMAGE[address-BIAS:address-BIAS+len(raw)]==raw,(hex(address),IMAGE[address-BIAS:address-BIAS+len(raw)].hex())
    passed('trampolines_pin_original_entry_bytes_and_halfword_aligned_IRQ_literal')

    cases=[]
    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(2,4),(2,1),(9,1)):
            r=Probe();assert r.request(op,blocks,offset)==0 and not r.held
            s=r.state();assert not s['active'] and s['finished'] and not s['failed'] and not r.joins
            assert s['buffer']==BUFFER+offset and s['bytes']==blocks*512
            assert s['waits']==len(r.waits) and s['commands']>=2
            assert {w['mask'] for w in r.waits}=={0x183,0x185}
            cases.append(dict(op=op,blocks=blocks,offset=offset,dma=sorted({hex(w['dma']) for w in r.waits})))
    passed('compiled_probe_preserves_registered_read_write_command_data_and_status_paths_under_one_SD_lock',cases=cases)

    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(9,1)):
            r=Probe();r.fault=(0x185,'hidden_error');r.pending=True
            r.request(op,blocks,offset)
            assert r.held and r.state()['active'] and not r.state()['finished'] and r.state()['errors']==0x100000
            assert r.state()['joined']==0 and len(r.joins)==1 and r.waits[-1]['mask']==0x185
            assert r.joins[0]['dma']==(BUFFER if blocks==2 else BOUNCE)
            assert r.joins[0]['sp']<r.waits[-1]['sp']
            if op==2:assert not r.copies and bytes(r.m.uc.mem_read(BUFFER,512))==bytes([0xa5])*512
            assert r.resume()==0xffffd8ef and not r.held
            s=r.state();assert s['finished'] and not s['active'] and s['failed'] and s['joined']==1
            assert s['join_calls']==2
            assert len(r.native_commands)==1 # Follow-up status/diagnostic never submitted.
    passed('hidden_data_error_retains_direct_or_bounce_buffer_and_native_stack_until_explicit_modeled_join',
           limitation='JOINED is a fixture callback; no hardware cancellation is performed')

    for mask in (0x183,0x185):
        for kind in ('error','timeout'):
            r=Probe();r.fault=(mask,kind);r.pending=True;r.request(op=2,blocks=2)
            assert r.held and r.state()['active'] and r.state()['failed'] and not r.state()['finished']
            assert (r.state()['reasons']&(4 if kind=='timeout' else 1))
            assert r.resume()==0xffffd8ef and r.state()['joined']==1 and not r.held
    passed('command_and_data_error_or_native_event_timeout_cannot_unwind_before_modeled_join')

    for reply in (0,2,0xffffffce):
        r=Probe();r.fault=(0x185,'timeout');r.pending=True;r.join_reply=reply
        r.request(op=2,blocks=1)
        assert r.held and r.state()['active'] and not r.state()['joined'] and not r.state()['finished']
        assert not r.copies and word(r.m,0x402c0000)==BOUNCE
        assert r.resume()==0xffffd8ef and r.state()['joined']==1 and not r.held
    passed('pending_unrecognized_or_failed_recovery_retains_bounce_and_stack_until_explicit_JOINED')

    r=Probe();r.command_busy=True;r.pending=True;r.request(op=2,blocks=2)
    assert r.held and r.state()['active'] and r.state()['reasons']&8
    assert not r.waits and r.state()['join_calls']==1
    r.command_busy=False
    assert r.resume()==0xffffd8ef and r.state()['finished'] and not r.held
    passed('command_inhibit_exit_before_any_event_wait_joins_while_parent_transfer_buffers_remain_live')

    for op in (2,3):
        r=Probe()
        old=r.deliver;command_waits=0
        def final_error(a):
            nonlocal command_waits
            if a[1]==0x183:
                command_waits+=1
                if command_waits==2:r.fault=(0x183,'hidden_error')
            return old(a)
        r.m.hooks[0x2102bd04]=final_error
        assert r.request(op,blocks=2)==0xffffd8ef
        assert r.state()['errors']==0x100000 and r.state()['failed'] and r.state()['joined']==1 and not r.held
    passed('scope_includes_final_status_so_original_read_cannot_ignore_its_retained_error')

    for raw,event in ((0x100002,4),(0x100102,4),(3,2),(0x100,0)):
        for enabled in (False,True):
            r=Probe(enabled);r.seed(active=1,unit=0)
            put32(r.m,0x402c0030,raw);put32(r.m,0x402c0038,0x157f003f)
            for i in range(32):r.m.uc.reg_write(getattr(arm,f'UC_ARM_REG_S{i}'),0x12340000+i)
            r.m.uc.reg_write(arm.UC_ARM_REG_APSR,0xa8000000)
            r.m.invoke(0x8006ea98,[0])
            regs=[getattr(arm,f'UC_ARM_REG_R{i}') for i in range(13)]
            regs += [arm.UC_ARM_REG_SP,arm.UC_ARM_REG_APSR,arm.UC_ARM_REG_FPSCR]
            regs += [getattr(arm,f'UC_ARM_REG_S{i}') for i in range(32)]
            result=[r.m.uc.reg_read(reg) for reg in regs]
            if not enabled:baseline=result
            else:assert result==baseline and r.state()['errors']==raw&0x157f0000
            assert word(r.m,EVENT+8)==event
    passed('compiled_preack_IRQ_hook_preserves_original_register_flags_float_state_and_event_mapping')

    r=Probe();r.seed(active=1,unit=0,raw=3,errors=0)
    r.m.invoke(r.syms['sdp_irq_sample'],[1,0x100000]);assert r.state()['raw']==3 and not r.state()['errors']
    r.seed(active=0);r.m.invoke(r.syms['sdp_irq_sample'],[0,0x100000]);assert not r.state()['errors']
    put32(r.m,EVENT+8,4);out=BUFFER+0x3000
    assert r.m.invoke(r.syms['sdp_wait'],[EVENT,0x185,1,out,5000])==0 and word(r.m,out)==4
    assert not r.joins and not r.state()['waits']
    passed('out_of_scope_or_other_unit_IRQ_is_ignored_and_unscoped_wait_uses_original_predicate')

    # Deliberately negative: metadata and a software unit lock do not identify
    # whether a late same-unit IRQ belongs to the newly submitted operation.
    r=Probe();r.origin='previous transfer (injected negative control)'
    assert r.request(op=2,blocks=2)==0 and not r.state()['failed'] and not r.joins
    assert r.irq_origins[-2][0]==2
    passed('negative_control_late_same_unit_completion_has_no_hardware_request_identity',
           limitation='Freshness requires prior physical join, stale-status drain and serialized arm/IRQ admission; probe alone cannot establish it')

    r=Probe();r.success_active=True
    assert r.request(op=2,blocks=2)==0 and word(r.m,0x402c0024)==0x204 and not r.held
    passed('negative_control_mapped_completion_still_does_not_prove_physical_idle',
           limitation='Raw completion observation plus event success cannot substitute for physical controller/bus-master proof')

    handoff_cases(passed)

    out=ROOT/'analysis/sd_transfer_probe_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=[
          'Compiled test-only probe and original SD/IRQ/event instructions execute on one CPU with synthetic MMIO and kernel endpoints',
          'Explicit JOINED, IRQ delivery/freshness, prior idle and data movement are models; no physical cancellation, cache or persistence proof',
          'No production hook, gate binding, firmware deployment image or device access',
          'Only registered read/write paths and examined waits/exits are covered; other callers, card-ready exhaustion and auxiliary diagnostic success remain unverified']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))

if __name__=='__main__':main()
