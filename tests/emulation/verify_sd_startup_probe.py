#!/usr/bin/env python3
"""Exact passive startup diagnostic, original SD paths and retained diagnostics.

Card responses, IRQ arrivals, W1C, reset self-clear and scheduling are modeled.
This cannot establish physical completion, source exclusion or hardware timing.
"""
import contextlib,hashlib,io,json,struct,sys,tempfile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,BIAS,REGS,STACK,INPUT,RETURN
from verify_sd_cold_start import Cold,PIO_READ_WAIT,high_speed_card
from verify_overdub_prototype import Emulator
from verify_sd_transfer_lifetime import EVENT,HOST,CARD,UNIT
from verify_sd_transfer_probe import patch
from verify_health_probe import query,startup
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_scheduling_boundaries import stop
from sd_registers import SD,IRQ_STATUS,PRESENT,SYSTEM,RESET_ALL,INITIAL_CLOCKS
DETAIL='--detail' in sys.argv
if DETAIL:
    from build_sd_startup_detail import ELF,ENTRY,OUT,STATES,RESET_SITE,WAIT_SITES,trial
else:
    from build_sd_startup_probe import ELF,ENTRY,OUT,STATES,RESET_SITE,WAIT_SITES,trial
SLOTS=8 if DETAIL else 4
KINDS=11 if DETAIL else 6
STATE_BYTES=724 if DETAIL else 364
PREFIX='sd_startup_detail' if DETAIL else 'sd_startup'
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_sd_startup_probe import request,decode,summarize,SUMMARY,RESET,PIO

with ELF.open('rb') as f:
    e=ELFFile(f);seg=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD');CODE=seg.data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    FUNCTIONS=[(s.name,s['st_value']&~1,s['st_size']) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type']=='STT_FUNC' and s['st_size']]
TRIAL,MANIFEST=trial(CODE,SYMS);STATE=SYMS['startup_trace']

class Diagnostic(Cold):
    def __init__(self,enabled=True,mclass=False):
        # The generic ARM engine handles the native double-precision clock
        # setup. Its missing IPSR read is explicitly modeled as Thread mode.
        # Separate Cortex-M7 cases execute real IPSR checks and adapter ABI.
        emulator=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True) if mclass else None
        super().__init__(emulator);m=self.m
        if enabled:
            m.uc.mem_write(ENTRY,CODE)
            for p in MANIFEST['patches']:m.uc.mem_write(p['site'],bytes.fromhex(p['new']))
        self.enabled=enabled;self.current_site=0;self.mmio=[];self.min_sp=STACK
        self.w1c=[];self.origins=[];self.instructions=0
        md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
        ipsr={i.address:(getattr(A,'UC_ARM_REG_'+i.op_str.split(',')[0].upper()),i.size)
            for _,a,n in FUNCTIONS for i in md.disasm(CODE[a-ENTRY:a-ENTRY+n],a)
            if i.mnemonic=='mrs' and i.op_str.endswith(', ipsr')}
        put32(m,0x808e291c,0x21039000)
        m.uc.mem_map(0x10020000,0x10000)
        with (ROOT/'analysis/sd-command-delivery.elf').open('rb') as f:
            e=ELFFile(f)
            for s in e.iter_segments():
                if s['p_type']=='PT_LOAD' and s['p_filesz']:m.uc.mem_write(s['p_vaddr'],s.data())
            delivery=next(s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name=='command_delivery')
        patch(m,0x800328c0,delivery,8)
        m.hooks[0x2102be00]=self.deliver
        m.hooks[0x80032828]=lambda a:put32(m,a[0]+8,word(m,a[0]+8)|a[1]) or 0
        m.hooks[0x80076bc8]=lambda a:1
        def write(u,k,a,n,v,s):
            self.mmio.append((a,n,v))
            if a==IRQ_STATUS:self.w1c.append(word(m,a)&~v)
        m.uc.hook_add(UC_HOOK_MEM_WRITE,write,begin=SD,end=SD+0xfff)
        def code(u,p,n,s):
            if self.w1c:put32(m,IRQ_STATUS,self.w1c.pop(0))
            if p in WAIT_SITES:self.current_site=p
            self.min_sp=min(self.min_sp,u.reg_read(A.UC_ARM_REG_SP));self.instructions+=1
            if not mclass and p in ipsr:
                reg,size=ipsr[p];u.reg_write(reg,0);u.reg_write(A.UC_ARM_REG_PC,(p+size)|1)
        m.uc.hook_add(UC_HOOK_CODE,code)
        m.replies=[]
        m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0

    def at_wait(self,u,p,n,x):
        # The separate delivery helper below supplies the actual native IRQ
        # and event path. Do not preseed Cold's success flags at this entry.
        pass

    def deliver(self,a):
        assert self.held and a[0]==EVENT
        # The failed-negotiation cleanup also waits for TC alone (mask4).
        mask=a[1];raw={0x183:1,0x185:2,4:2,8:0x20,0x10:0x10}[mask]
        flags=2 if mask==0x183 else 4 if mask==0x185 else mask
        software=mask==0x185 and self.bad_final is not None
        if software:raw=0;flags=self.bad_final
        self.waits.append(dict(site=hex(self.current_site),mask=mask,flags=flags,held=self.held))
        put32(self.m,EVENT+8,flags if software else 0);put32(self.m,IRQ_STATUS,raw)
        self.origins.append(raw)
        if self.current_site==self.hold_site:stop(self.m)
        return int(bool(raw))

    def reply(self,kind=1):
        query(self.m,request(kind,kind));return decode(self.m.replies[-1])

    def rows(self):return [self.reply(k) for k in range(1,KINDS+1)]

def adapter(enabled,alignment):
    r=Diagnostic(enabled,mclass=True);m=r.m
    for i,reg in enumerate(REGS):m.uc.reg_write(reg,0x12340000+i*0x111)
    m.uc.reg_write(A.UC_ARM_REG_R4,SD+0x24)
    m.uc.reg_write(A.UC_ARM_REG_SP,STACK-alignment)
    m.uc.reg_write(A.UC_ARM_REG_APSR,0xa80f0000);m.uc.reg_write(A.UC_ARM_REG_FPSCR,0x00400000)
    put32(m,SYSTEM,0x0102000f);put32(m,PRESENT,0x01000008)
    seen=[]
    m.uc.hook_add(UC_HOOK_CODE,lambda u,p,n,x:seen.append(p) or u.emu_stop(),begin=RESET_SITE+6,end=RESET_SITE+6)
    m.uc.emu_start(RESET_SITE|1,RETURN+2,count=1000000);assert seen==[RESET_SITE+6]
    values=[m.uc.reg_read(reg) for reg in REGS]+[m.uc.reg_read(reg) for reg in
        (A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR)]
    return r,values

def main():
    checks=[]
    def passed(case,**details):checks.append(dict(case=case,**details))
    path=OUT/('trial_sd_startup_detail/L6.BIN' if DETAIL else 'trial_sd_startup/L6.BIN')
    if path.exists():assert path.read_bytes()==TRIAL
    assert len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert not any(n.startswith(('extra_','sdp_','native_worker','storage_lease')) for n in SYMS)
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for name,a,n in FUNCTIONS:
        assert not any(i.mnemonic.startswith('v') for i in md.disasm(CODE[a-ENTRY:a-ENTRY+n],a)),name
    for name,n in STATES.items():assert CODE[SYMS[name]-ENTRY:SYMS[name]-ENTRY+n]==bytes(n)
    assert startup(TRIAL)[0]==startup(IMAGE)[0]
    passed('Exact byte-checked patch set, all original scatter outputs, zero loaded state and integer-only observers; no capture or model endpoints')

    for alignment in (0,4):
        old,ov=adapter(False,alignment);new,nv=adapter(True,alignment)
        assert ov==nv and old.mmio==new.mmio==[]
        assert new.reply(2)['system']==0x0102000f
    passed('Reset inline adapter preserves all general registers, flags and FPSCR at both native stack alignments without MMIO writes')

    old=Diagnostic(False);new=Diagnostic();assert old.enumerate()==new.enumerate()==0
    assert old.commands==new.commands and old.waits==new.waits and old.mmio==new.mmio
    assert old.fifo_reads==new.fifo_reads and not new.dma and not new.held
    rows=new.rows();summary=summarize(rows)
    assert summary['first_enumeration_observed'] and summary['startup_observer_errors']==0
    assert rows[0]['pio_waits']==2 and rows[0]['commands']==13 and rows[0]['waits']==17
    assert rows[1]['resets']==1 and not rows[1]['system']&RESET_ALL
    for r,blocks in zip(rows[2:4],(0x10040,0x10008)):
        assert r['site']==PIO_READ_WAIT+4 and r['flags']==4 and r['raw']&2
        assert r['blocks']==blocks and not r['mix']&1
    assert not any(r['sequence'] for r in rows[4:2+SLOTS])
    passed('Continuous original first enumeration preserves commands, event waits, FIFO payload and every MMIO write while reporting both PIO completions',
           modeled_stack_bytes=STACK-new.min_sp,original_modeled_stack_bytes=STACK-old.min_sp)

    for flags in (1,0x80,0x100,0x104):
        old=Diagnostic(False);new=Diagnostic();old.bad_final=new.bad_final=flags
        assert old.enumerate()==new.enumerate()==0 and old.mmio==new.mmio
        rows=new.rows();assert rows[0]['errors']>=2
        assert all(r['flags']==flags and not r['raw']&2 for r in rows[2:4])
    passed('Synthetic false-success startup flags are reported without repairing or changing the original return, readiness state or MMIO behavior')

    r=Diagnostic();r.reset_clear=False;assert r.cold()==0
    assert r.reply(2)['system']&RESET_ALL
    saved=r.reply(2);put32(r.m,SYSTEM,0);r.m.invoke(SYMS['startup_reset_sample'],[])
    later=r.reply(2);assert later['resets']==2 and all(later[k]==saved[k] for k in RESET[1:])
    passed('Reset observation keeps a still-set reset visible and preserves the first sample across later reset visits')

    r=Diagnostic();r.hold_site=PIO_READ_WAIT;r.enumerate()
    assert r.held
    # Querying directly would reset SP; preserve the suspended native frame.
    saved_sp=r.m.uc.reg_read(A.UC_ARM_REG_SP)
    assert word(r.m,STATE+48)==1 and not word(r.m,STATE+52)
    frame=bytes(r.m.uc.mem_read(saved_sp,STACK-saved_sp))
    assert frame
    r.hold_site=None;assert r.resume()==0 and not r.held
    assert r.reply()['done']==1
    passed('Pending startup completion retains the original frame and unit token; observation never replaces or shortens the wait')

    r=Diagnostic();assert r.enumerate()==0
    original=r.rows();before=bytes(r.m.uc.mem_read(STATE+108,256))
    assert r.operation(4)!=0
    later=r.rows();assert later[0]['attempts']==2 and later[0]['omitted']==1
    assert bytes(r.m.uc.mem_read(STATE+108,256))==before
    assert all(later[0][k]==original[0][k] for k in SUMMARY if k not in ('attempts','omitted'))
    assert not summarize(later)['first_enumeration_observed']
    passed('A later enumeration attempt cannot replace the first completed records or masquerade as one uninterrupted cold start')

    r=Diagnostic();put32(r.m,STATE,1)
    assert r.enumerate()==0 and not r.held and r.reply()['skipped']>0
    assert not r.reply()['observer_consistent']
    passed('Busy observer claims skip rather than wait or change native enumeration')

    r=Diagnostic();assert r.enumerate()==0;before=bytes(r.m.uc.mem_read(STATE,STATE_BYTES))
    r.mmio.clear();r.rows();assert not r.mmio and bytes(r.m.uc.mem_read(STATE,STATE_BYTES))==before
    packet=request(1,1);bad=[packet[:-1],packet+b'\0']
    for i,v in ((0,0),(1,0),(2,1),(3,1),(4,0),(5,0),(5,KINDS+1),(6,128),(7,0)):
        b=bytearray(packet);b[i]=v;bad.append(bytes(b))
    count=len(r.m.replies)
    for p in bad:
        r.m.uc.mem_write(INPUT,struct.pack('<I',len(p))+p+bytes(16))
        assert r.m.invoke(SYMS['startup_dispatch'],[INPUT])==0
    assert len(r.m.replies)==count
    query(r.m,request(1,1));valid=r.m.replies[-1]
    for i,v in ((5,KINDS+1),(6,128),(7,3),(11,16),(-1,0)):
        b=bytearray(valid);b[i]=v
        try:decode(bytes(b))
        except ValueError:pass
        else:raise AssertionError('Malformed host reply accepted')
    assert not summarize(rows[:2])['first_enumeration_observed']
    passed('Queries preserve frozen state and MMIO; firmware and host reject malformed packets and incomplete snapshots')

    r=Diagnostic(mclass=True);m=r.m
    reads=[]
    m.uc.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,s:reads.append(a),begin=SD,end=SD+0xfff)
    m.uc.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,s:reads.append(a),begin=0xe000e000,end=0xe000efff)
    for state,ipsr,accepted in ((0,0,False),(1,0,False),(2,16,False),(2,0,True)):
        m.uc.mem_write(0x80629b60,bytes([state]));m.uc.reg_write(A.UC_ARM_REG_IPSR,ipsr)
        p=request(1,1);m.uc.mem_write(INPUT,struct.pack('<I',len(p))+p+bytes(16))
        count=len(m.replies);before=bytes(m.uc.mem_read(STATE,STATE_BYTES))
        assert bool(m.invoke(SYMS['startup_dispatch'],[INPUT]))==accepted
        assert len(m.replies)==count+int(accepted)
        assert bytes(m.uc.mem_read(STATE,STATE_BYTES))==before and not reads and not r.mmio
    passed('Cortex-M7 executes the new query context checks; disconnected and Handler-mode requests are rejected and every query avoids controller/core MMIO')

    old=high_speed_card(Diagnostic(False));new=high_speed_card(Diagnostic())
    assert old.enumerate()==new.enumerate()==0
    assert old.commands==new.commands and old.waits==new.waits and old.mmio==new.mmio
    rows=new.rows();s=rows[0]
    assert s['commands']==31 and s['waits']==43 and s['pio_waits']==6 and not s['errors'] and not s['skipped']
    assert s['omitted']==max(0,6-SLOTS)
    assert summarize(rows)['first_enumeration_observed']==DETAIL
    if DETAIL:
        assert [(r['code'],r['argument']) for r in rows[2:8]]==[(17,0),(41,0),(5,1),(5,1),(5,0x80000001),(5,1)]
        assert not any(r['sequence'] for r in rows[8:10])
        assert not rows[10]['system']&RESET_ALL
        assert rows[10]['unit_token']==rows[1]['unit_token']
    passed('Original high-speed negotiation preserves native behavior; bounded journal completeness matches capacity and nested CMD55 keeps the enclosing request identity',
        retained_pio_samples=min(SLOTS,6),omitted=max(0,6-SLOTS))

    old=high_speed_card(Diagnostic(False));new=high_speed_card(Diagnostic())
    busy=bytearray(old.switch);busy[17]=1;busy[29]=2
    old.switch=new.switch=bytes(busy)
    assert old.enumerate()==new.enumerate()!=0
    assert old.commands==new.commands and old.waits==new.waits and old.mmio==new.mmio
    rows=new.rows();s=rows[0]
    assert s['pio_waits']>SLOTS and s['omitted']==s['pio_waits']-SLOTS and not s['skipped']
    assert [r['sequence'] for r in rows[2:2+SLOTS]]==list(range(1,SLOTS+1))
    assert not summarize(rows)['first_enumeration_observed']
    if DETAIL:
        assert rows[10]['unit_token']==rows[1]['unit_token'] and not rows[10]['system']&RESET_ALL
    passed('Unmodified busy-switch polling exceeds the journal; omissions prevent a complete-trace claim and adjacent first-command state remains intact')

    if DETAIL:
        for cleared in (False,True):
            old=Diagnostic(False);new=Diagnostic()
            for r in (old,new):
                r.reset_clear=False
                assert r.cold()==0 and r.operation(0)==0
                # An explicit hardware model event between setup and the first
                # command; never a helper writing the real device's registers.
                mask=INITIAL_CLOCKS|(RESET_ALL if cleared else 0)
                put32(r.m,SYSTEM,word(r.m,SYSTEM)&~mask)
                assert r.operation(4)==0
            assert old.commands==new.commands and old.mmio==new.mmio
            rows=new.rows()
            assert rows[1]['system']&RESET_ALL
            assert bool(rows[10]['system']&RESET_ALL)==(not cleared)
            assert not summarize(rows)['physical_completion_proven']
        passed('Early reset and first-command snapshots distinguish deferred reset clear from still-set reset without changing native decisions or claiming physical completion')

    # Retained original diagnostics execute against the exact new image; their
    # private reports use a separate prefix and do not replace prior evidence.
    import verify_ram_activity_probe as retained
    for module in (retained,retained.memory):
        for k,v in dict(ELF=ELF,CODE=CODE,SYMS=SYMS,FUNCTIONS=FUNCTIONS,TRIAL=TRIAL,MANIFEST=MANIFEST,STATES=STATES).items():
            setattr(module,k,v)
    with tempfile.TemporaryDirectory(dir=ROOT/'analysis') as tmp:
        candidate=ROOT/tmp/'L6.BIN';candidate.write_bytes(TRIAL)
        with contextlib.redirect_stdout(io.StringIO()):
            result=retained.main(ROOT/f'analysis/{PREFIX}_retained_ram_verification.json',
                prepared_image=candidate,retained_prefix=PREFIX+'_retained')
    assert result['passed'] and result['groups']==53
    passed('All 53 existing passive diagnostic groups pass on the exact startup image',retained_groups=53)
    report=dict(passed=True,groups=len(checks)-1+53,startup_groups=len(checks)-1,
        retained_groups=53,results=checks,trial_sha256=hashlib.sha256(TRIAL).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=MANIFEST['limitations']+[
            'Continuous cold setup uses generic ARM emulation for native double-precision clock code; its IPSR query reads are modeled as Thread mode',
            'Separate Cortex-M7 cases execute the actual new query IPSR checks, reset adapter and retained diagnostic checks',
            'Measured software stack excludes physical exception nesting and does not establish hardware headroom'])
    out=ROOT/f'analysis/{PREFIX}_probe_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=report['groups'],report=str(out))))

if __name__=='__main__':main()
