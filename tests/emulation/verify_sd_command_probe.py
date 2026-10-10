#!/usr/bin/env python3
"""Passive command journal on original SD instructions; no device access.

IRQ origins, DMA advancement, W1C, kernel scheduling and controller completion
are explicit models. The delivery helper is separate from the prepared image.
"""
import contextlib,hashlib,io,json,struct,sys
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_READ
from unicorn import arm_const as A
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from verify_pad_protocol import ROOT,IMAGE,BIAS,REGS,STACK,RETURN
from verify_sd_transfer_lifetime import Sd,HOST,EVENT,BUFFER
from verify_overdub_prototype import Emulator
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_scheduling_boundaries import stop
from verify_sd_transfer_probe import patch
from verify_health_probe import query
import verify_sd_raw_probe as raw
from build_sd_command_probe import ELF,ENTRY,STATES,PROGRAM_SITES,trial
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_sd_command_probe import COMMON,SAMPLE,request,decode

with ELF.open('rb') as f:
    e=ELFFile(f);seg=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD');CODE=seg.data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    FUNCTIONS=[(s.name,s['st_value']&~1,s['st_size']) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type']=='STT_FUNC' and s['st_size']]
TRIAL,MANIFEST=trial(CODE,SYMS);STATE=SYMS['command_trace'];TASK=0x808e291c
base_overlay=raw.old_overlay
def overlay(m):
    base_overlay(m)
    for p in MANIFEST['patches']:m.uc.mem_write(p['site'],bytes.fromhex(p['new']))
for module in (raw,raw.detail):
    module.ELF=ELF;module.CODE=CODE;module.SYMS=SYMS;module.FUNCTIONS=FUNCTIONS
    module.TRIAL=TRIAL;module.MANIFEST=MANIFEST;module.STATES=STATES;module.overlay=overlay
raw.STATE=SYMS['raw_trace'];raw.detail.STATE=SYMS['completion_trace']
raw.detail.DETAIL=True;raw.detail.STATE_BYTES=380

def enable_queries(m):
    m.replies=[]
    m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
def reply(m,kind=1):
    if not hasattr(m,'replies'):enable_queries(m)
    query(m,request(kind,37));return decode(m.replies[-1])
def snapshot(m,which='last'):
    address=STATE+76+112*('current','last','last_anomaly').index(which)
    return dict(zip(SAMPLE,struct.unpack('<28I',m.uc.mem_read(address,112))))

class Command(Sd):
    def __init__(self,enabled=True,data_raw=2,data_present=8,advance=True,
                 entry_raw=0,entry_present=8,command_busy=False):
        super().__init__(Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True))
        m=self.m;self.enabled=enabled;self.data_raw=data_raw;self.data_present=data_present
        self.advance=advance;self.entry_raw=entry_raw;self.entry_present=entry_present
        self.command_busy=command_busy;self.pending=False;self.origins=[];self.origin='current'
        self.mmio=[];self.min_sp=STACK;self.native=[];self.wait_entries=[];self.preprogram=[]
        self.w1c=[];m.hooks.pop(0x8006a348);m.hooks.pop(0x800328c0)
        for a,v in ((TASK,0x21039000),(0x402c0010,0x100),(0x402c0028,0x20),
                    (0x402c0038,0x157f003f),(0x402c0024,entry_present)):
            put32(m,a,v)
        m.uc.mem_write(BUFFER,bytes([0xa5])*0x4000)
        m.uc.mem_write(0x2000c4d4,bytes(range(256))*32)
        m.uc.mem_map(0x10020000,0x10000)
        with (ROOT/'analysis/sd-command-delivery.elf').open('rb') as f:
            e=ELFFile(f)
            for s in e.iter_segments():
                if s['p_type']=='PT_LOAD' and s['p_filesz']:m.uc.mem_write(s['p_vaddr'],s.data())
            delivery=next(s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name=='command_delivery')
        patch(m,0x800328c0,delivery,8)
        m.hooks[0x2102be00]=self.deliver
        m.hooks[0x80032828]=lambda a:put32(m,a[0]+8,word(m,a[0]+8)|a[1]) or 0
        m.hooks[0x80076950]=lambda a:int(not a[1])
        m.hooks[0x80074580]=lambda a:put32(m,a[0],0) or 0
        m.hooks[0x80076bc8]=lambda a:1
        m.hooks[0x80073ec8]=m.hooks[0x80073f18]=lambda a:0
        if enabled:overlay(m)
        def writes(uc,k,address,n,value,user):
            self.mmio.append((address,n,value))
            if address==0x402c0030:self.w1c.append(word(m,address)&~value)
        m.uc.hook_add(UC_HOOK_MEM_WRITE,writes,begin=0x402c0000,end=0x402c0fff)
        def code(uc,pc,n,user):
            # Apply modeled W1C only AFTER the instruction's real store.
            if self.w1c:put32(m,0x402c0030,self.w1c.pop(0))
            self.min_sp=min(self.min_sp,uc.reg_read(A.UC_ARM_REG_SP))
            if pc in PROGRAM_SITES:
                put32(m,0x402c0030,self.entry_raw);put32(m,0x402c0024,self.entry_present)
                reg={0x80069fec:A.UC_ARM_REG_R11,0x8006a180:A.UC_ARM_REG_R7,
                     0x8006abf0:A.UC_ARM_REG_R4,0x8006adac:A.UC_ARM_REG_R7}[pc]
                self.preprogram.append((pc,uc.reg_read(reg),word(m,0x402c0000)))
            if pc==0x8006a348 and self.command_busy:put32(m,0x402c0024,1)
            if pc==0x8006a350:self.native.append(uc.reg_read(A.UC_ARM_REG_R4))
            if pc==0x800328c0:
                self.wait_entries.append((uc.reg_read(REGS[1]),uc.reg_read(A.UC_ARM_REG_SP)))
        m.uc.hook_add(UC_HOOK_CODE,code)
    def deliver(self,a):
        assert self.held and a[0]==EVENT
        mask=a[1];assert mask in (0x183,0x185,8,0x10),hex(mask)
        if self.pending and mask==0x185:return stop(self.m)
        value={0x183:1,0x185:self.data_raw,8:0x20,0x10:0x10}[mask]
        if mask==0x185:
            self.data_waits+=1
            if self.advance:
                size=word(self.m,0x402c0004);size=(size&0xffff)*(size>>16)
                put32(self.m,0x402c0000,word(self.m,0x402c0000)+size)
        put32(self.m,EVENT+8,0);put32(self.m,0x402c0030,value)
        put32(self.m,0x402c0024,self.data_present if mask==0x185 else 8)
        self.origins.append((mask,value,self.origin if mask==0x185 else 'current'))
        return int(bool(value))

def adapter(site,enabled,unaligned=False):
    """Execute just the displaced instructions, compare every GPR and flags."""
    r=Sd(Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True));m=r.m
    if enabled:overlay(m)
    for i,reg in enumerate(REGS):m.uc.reg_write(reg,0x12340000+i*0x111)
    m.uc.reg_write(A.UC_ARM_REG_R6,0x402c0000)
    m.uc.reg_write(A.UC_ARM_REG_R8,0x402c0020)
    m.uc.reg_write(A.UC_ARM_REG_R10,0x402c0020)
    m.uc.reg_write(A.UC_ARM_REG_SP,STACK-4 if unaligned else STACK)
    m.uc.reg_write(A.UC_ARM_REG_APSR,0xa80f0000);m.uc.reg_write(A.UC_ARM_REG_FPSCR,0x00400000)
    resume=site+PROGRAM_SITES[site][1];writes=[];read_dma=[]
    m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,s:writes.append((a,n,v)),begin=0x402c0000,end=0x402c0fff)
    # Before-store observer must see the old DS_ADDR, not the proposed one.
    put32(m,0x402c0000,0xdead0000)
    m.uc.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,s:read_dma.append(word(m,a)),begin=0x402c0000,end=0x402c0000)
    reached=[]
    def done(uc,pc,n,user):
        if pc==resume:reached.append(pc);uc.emu_stop()
    m.uc.hook_add(UC_HOOK_CODE,done)
    m.uc.emu_start(site|1,RETURN+2,count=1000000);assert reached
    regs=[m.uc.reg_read(reg) for reg in REGS]+[m.uc.reg_read(reg) for reg in
        (A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR)]
    return m,regs,writes,read_dma

def main(report_path=None,retained_report_paths=None):
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,passed=True,**kw))
    with contextlib.redirect_stdout(io.StringIO()):
        retained=raw.main(*(retained_report_paths or (
            ROOT/'analysis/sd_command_retained_raw_verification.json',
            ROOT/'analysis/sd_command_retained_detail_verification.json')))
    assert retained['passed'] and retained['groups']==23
    passed('all_twenty_three_retained_raw_detail_and_health_groups_pass_on_exact_command_image',retained_groups=23)
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for name,a,n in FUNCTIONS:
        assert not any(i.mnemonic.startswith('v') for i in md.disasm(CODE[a-ENTRY:a-ENTRY+n],a)),name
    for name,n in STATES.items():assert CODE[SYMS[name]-ENTRY:SYMS[name]-ENTRY+n]==bytes(n)
    assert b'\x01\xbe\x02\x21' not in CODE # emulator delivery pointer absent
    passed('integer_only_loaded_zero_state_and_emulator_delivery_absent_from_device_image')
    for site in PROGRAM_SITES:
        for unaligned in (False,True):
            old=adapter(site,False,unaligned);new=adapter(site,True,unaligned)
            assert old[1:3]==new[1:3],hex(site)
            p=struct.unpack('<8I',new[0].uc.mem_read(STATE+44,32))
            assert p[0]==1 and p[1]==site and p[2]==new[2][-1][2]
    passed('all_four_prestore_adapters_preserve_displaced_GPR_APSR_FPSCR_and_MMIO_with_both_stack_alignments',logical_cases=8)
    sites=0;peak=0
    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(2,4),(2,1),(9,1),(9,0)):
            old=Command(False);old_result=old.request(op,blocks,offset)
            r=Command();result=r.request(op,blocks,offset);s=snapshot(r.m)
            assert result==old_result==0 and not r.held and r.mmio==old.mmio
            assert bytes(r.m.uc.mem_read(BUFFER,0x4000))==bytes(old.m.uc.mem_read(BUFFER,0x4000))
            assert r.native==old.native and [x[0] for x in r.wait_entries]==[x[0] for x in old.wait_entries]
            assert all(sp%8==0 for _,sp in r.wait_entries)
            assert s['program_address']==s['address'] and s['bytes']>0
            assert s['wait_dma']==s['address']+s['bytes'] and s['task']==s['program_task']==0x21039000
            assert s['event']==EVENT and s['command_status']==s['wait_status']==0 and s['wait_flags']==4
            assert s['irq_raw']==3 and s['tc_count']==1 and s['irq_count']==2 and not s['reasons']
            assert word(r.m,STATE+36)==0 and r.data_waits==word(r.m,STATE+24)==word(r.m,STATE+20)
            sites|=word(r.m,STATE+12);peak=max(peak,STACK-r.min_sp)
    assert sites==15
    passed('original_command_IRQ_event_predicate_and_four_data_paths_preserve_payload_MMIO_result_and_unit_lifetime',
           logical_cases=12,modeled_native_caller_max_stack_bytes=peak)
    for value,reason in ((0x100002,8),(0x20000,32),(0,32)):
        old=Command(False,data_raw=value);old_result=old.request(2,2)
        r=Command(data_raw=value);result=r.request(2,2);s=snapshot(r.m)
        assert result==old_result and not r.held and r.mmio==old.mmio and s['reasons']&reason
        if not value:assert s['wait_status'] and s['wait_flags']==0 and not s['tc_count']
        if value==0x100002:assert result==0 and s['wait_flags']==4 and s['irq_raw']&0x100000
    passed('masked_TC_error_mixed_flags_and_timeout_preserve_native_result_with_undefined_timeout_flags_unread')
    r=Command(data_present=0xfe88800e,entry_raw=2,entry_present=0x30f)
    # Native command rejects active admission; record that outcome faithfully.
    old=Command(False,data_present=0xfe88800e,entry_raw=2,entry_present=0x30f)
    assert r.request(2,2)==old.request(2,2) and r.mmio==old.mmio
    s=snapshot(r.m);assert s['program_raw']==2 and s['program_present']==0x30f
    assert s['reasons']&6==6 and s['command_status'] and s['wait_site']==0 and not r.data_waits
    passed('native_busy_admission_records_prestore_activity_and_command_failure_without_an_extra_data_wait')
    r=Command(data_present=0xfe88800e);assert r.request(3,2)==0
    s=snapshot(r.m);assert s['reasons']==256 and s['wait_present']==0xfe88800e
    passed('trailing_DAT0_busy_is_reported_as_activity_without_changing_success_or_declaring_a_fault')
    r=Command();r.origin='late prior physical transfer';assert r.request(2,2)==0
    d=reply(r.m);assert d['tc_count']==1 and not d['reasons'] and r.origins[1][2]==r.origin
    assert not d['physical_completion_proven'] and not d['transfer_owner_identified']
    passed('negative_control_late_prior_origin_TC_can_still_match_software_sequence_and_never_proves_physical_join')
    r=Command();r.pending=True;r.request(2,2);m=r.m
    assert r.held and word(m,STATE+36)==1 and not word(m,STATE)&1
    ctx=m.uc.context_save();sp=m.uc.reg_read(A.UC_ARM_REG_SP);frame=bytes(m.uc.mem_read(sp,STACK-sp))
    saved=bytes(m.uc.mem_read(STATE,412));m.stack=STACK-0x1000
    try:assert reply(m,3)['active']==1 and reply(m,3)['observer_consistent']
    finally:del m.stack;m.uc.context_restore(ctx)
    assert frame==bytes(m.uc.mem_read(sp,STACK-sp)) and saved==bytes(m.uc.mem_read(STATE,412)) and r.held
    passed('no_command_epoch_lock_across_native_wait_and_separate_stack_query_preserves_pending_native_frame')
    # Observer contention must never delay or suppress the underlying operation.
    old=Command(False);expected=old.request(2,2)
    r=Command();put32(r.m,STATE,1);assert r.request(2,2)==expected and r.mmio==old.mmio
    assert word(r.m,STATE)==1 and word(r.m,STATE+4)>0 and not word(r.m,STATE+20)
    passed('busy_command_observer_counts_omissions_without_waiting_changing_MMIO_or_suppressing_IO')
    # Direct scoped observer calls test mismatches without inventing native races.
    r=Command();m=r.m;put32(m,STATE+36,1);put32(m,STATE+76,99)
    put32(m,STATE+76+8,0x21039000);put32(m,STATE+76+12,EVENT)
    put32(m,HOST+20,EVENT+0x100);put32(m,0x402c0030,2)
    m.invoke(0x8006ea98,[1]);assert snapshot(m,'current')['reasons']&64
    m.invoke(SYMS['command_wait_end'],[98,0,4]);assert word(m,STATE+36)==1 and not snapshot(m)['sequence']
    put32(m,STATE+4,1);put32(m,TASK,0x21039004)
    m.hooks[0x800328c0]=lambda a:put32(m,a[3],4) or 0
    m.invoke(SYMS['completion_wait'],[EVENT+16,0x185,1,0x21008000,5000]);s=snapshot(m)
    assert s['reasons']&64 and s['reasons']&2048 and s['reasons']&16 and not word(m,STATE+36)
    passed('wrong_unit_event_task_old_ticket_and_observer_gap_are_visible_without_publishing_an_old_ticket')
    # Stub only the stock delegate to isolate the journal's packet reads. Put an
    # unknown opcode at the very last mapped byte: any extended read must fault.
    r=Command();m=r.m;m.hooks[SYMS['command_stock']&~1]=lambda a:11
    m.uc.mem_write(0x2103ffff,b'\x03')
    assert m.invoke(SYMS['command_probe'],[0x2103ffff,0])==11
    assert word(m,STATE+16)==1 and not word(m,STATE+20)
    req=0x21008000;m.uc.mem_write(req,struct.pack('<6I',23,7,0,0,2,1))
    put32(m,0x402c0000,BUFFER)
    m.invoke(SYMS['command_program_sample'],[BUFFER,0x80069fec])
    assert m.invoke(SYMS['command_probe'],[req,0])==11
    s=snapshot(m);assert s['bytes']==1024 and s['command_status']==11 and s['reasons']==128
    # Reusing a consumed preprogram marker must be marked incomplete.
    assert m.invoke(SYMS['command_probe'],[req,0])==11 and snapshot(m)['reasons']&1
    m.uc.mem_write(req+16,struct.pack('<2I',0x10002,0))
    m.invoke(SYMS['command_program_sample'],[BUFFER,0x80069fec])
    assert m.invoke(SYMS['command_probe'],[req,0])==11 and snapshot(m)['reasons']&512
    # Overlap is observed without replacing or completing the existing scope.
    put32(m,STATE+36,1);put32(m,STATE+76,123)
    before=word(m,STATE+20);m.invoke(SYMS['command_probe'],[req,0])
    assert word(m,STATE+20)==before and snapshot(m,'current')['sequence']==123
    assert snapshot(m,'current')['reasons']&1024 and word(m,STATE+36)==1
    passed('unknown_one_byte_packet_bounds_consumed_program_bad_shape_and_overlap_with_stock_delegate_modeled')
    r=Command();m=r.m;enable_queries(m)
    for kind in (1,2,3):
        d=reply(m,kind);assert d['observer_consistent'] and not d['data_commands']
        assert len(m.replies[-1])==(73 if kind==3 else 213)
        assert not d['physical_completion_proven'] and not d['transfer_owner_identified']
    assert r.request(2,2)==0;before=bytes(m.uc.mem_read(STATE,412));reads=[];writes=[]
    h=m.uc.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,s:reads.append(a),begin=0x402c0000,end=0x402c0fff)
    h2=m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,s:writes.append((a,n)))
    for kind in (1,2,3):reply(m,kind)
    m.uc.hook_del(h);m.uc.hook_del(h2)
    assert before==bytes(m.uc.mem_read(STATE,412)) and not reads
    assert all(STACK-768<=a and a+n<=STACK for a,n in writes)
    packet=m.replies[-1]
    for index,value in ((5,0),(6,128),(7,127),(11,16),(-1,0)):
        bad=bytearray(packet);bad[index]=value
        try:decode(bytes(bad))
        except ValueError:pass
        else:raise AssertionError('malformed command reply accepted')
    for bad in (packet[:-1],packet[:-1]+b'\0\xf7'):
        try:decode(bad)
        except ValueError:pass
        else:raise AssertionError('malformed length accepted')
    for kind,token in ((0,0),(4,0),(1,-1),(1,128)):
        try:request(kind,token)
        except ValueError:pass
        else:raise AssertionError('invalid request accepted')
    put32(m,STATE,1);assert not reply(m)['observer_consistent']
    put32(m,STATE,0);epoch_reads=0
    def changed(uc,k,a,n,v,s):
        nonlocal epoch_reads
        epoch_reads+=1
        if epoch_reads==2:put32(m,STATE,2)
    h=m.uc.hook_add(UC_HOOK_MEM_READ,changed,begin=STATE,end=STATE)
    assert not reply(m)['observer_consistent'];m.uc.hook_del(h)
    passed('fixed_read_only_queries_lengths_malformed_rejection_and_odd_or_changed_epoch_consistency')
    report=dict(passed=True,groups=len(cases)-1+retained['groups'],command_groups=len(cases)-1,
        retained_groups=retained['groups'],results=cases,trial_sha256=hashlib.sha256(TRIAL).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=MANIFEST['limitations']+[
         'Original native instructions execute with synthetic RAM, W1C and modeled IRQ delivery on the same emulated CPU stack',
         'IRQ origin is fixture metadata unavailable to the diagnostic: a clean sample does not prove physical freshness',
         'No hardware cache behavior, bus safety, real interrupt arbitration, elapsed timing or actual stack headroom is measured'])
    out=report_path or ROOT/'analysis/sd_command_probe_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=report['groups'],report=str(out))))
    return report
if __name__=='__main__':main()
