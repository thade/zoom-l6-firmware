#!/usr/bin/env python3
"""Passive raw IRQ adapter and retained detailed wait probe, offline only."""
import contextlib,hashlib,io,json,struct,sys
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_READ
from unicorn import arm_const as A
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from verify_pad_protocol import ROOT,IMAGE,REGS,STACK
from verify_sd_transfer_lifetime import Sd,HOST,EVENT
from verify_overdub_prototype import Emulator
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_health_probe import query
import verify_sd_completion_probe as detail
from build_sd_raw_probe import ELF,ENTRY,STATES,IRQ_SITE,IRQ_BYTES,trial
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_sd_raw_probe import request,decode

with ELF.open('rb') as f:
    e=ELFFile(f);seg=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD');CODE=seg.data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    FUNCTIONS=[(s.name,s['st_value']&~1,s['st_size']) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type']=='STT_FUNC' and s['st_size']]
TRIAL,MANIFEST=trial(CODE,SYMS);STATE=SYMS['raw_trace']
old_overlay=detail.overlay
detail.DETAIL=True;detail.ELF=ELF;detail.STATES=STATES;detail.STATE_BYTES=380
detail.CODE=CODE;detail.SYMS=SYMS;detail.FUNCTIONS=FUNCTIONS
detail.TRIAL=TRIAL;detail.MANIFEST=MANIFEST;detail.STATE=SYMS['completion_trace']
def overlay(m):
    old_overlay(m)
    m.uc.mem_write(IRQ_SITE,TRIAL[IRQ_SITE-0x80000e00:IRQ_SITE-0x80000e00+IRQ_BYTES])
detail.overlay=overlay

def reply(m,kind=1):
    query(m,request(kind,37));return decode(m.replies[-1])
def irq(raw,signal=0x157f003f,unit=0,enabled=True,busy=False):
    r=Sd(Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True));m=r.m
    if enabled:overlay(m)
    put32(m,0x402c0030,raw);put32(m,0x402c0038,signal)
    for address,value in ((0x402c0024,0xfe88800e),(0x402c002c,0x008f020f),
        (0x402c0028,0x0b800022),(0x402c0048,0x80000027),(0x402c0000,0x80920000),
        (0x808e291c,0x80934000),(HOST+20,EVENT+0x100),
        (0xe000ed14,0x30000),(0xe000ef94,0x31),(0xe000ef90,0x39)):
        put32(m,address,value)
    if busy:put32(m,STATE,1)
    posts=[];writes=[];reads=[];peak=STACK
    m.hooks[0x80032828]=lambda a:posts.append(tuple(a[:2])) or 0
    def written(uc,kind,address,size,value,user):writes.append((address,size,value))
    def read(uc,kind,address,size,value,user):reads.append(address)
    m.uc.hook_add(UC_HOOK_MEM_WRITE,written,begin=0x402c0000,end=0x402c0fff)
    m.uc.hook_add(UC_HOOK_MEM_WRITE,written,begin=0xe000e000,end=0xe000efff)
    m.uc.hook_add(UC_HOOK_MEM_READ,read,begin=0x402c0000,end=0x402c0fff)
    def stack(uc,pc,n,u):
        nonlocal peak
        peak=min(peak,uc.reg_read(A.UC_ARM_REG_SP))
    m.uc.hook_add(UC_HOOK_CODE,stack)
    for i,reg in enumerate((A.UC_ARM_REG_R4,A.UC_ARM_REG_R5,A.UC_ARM_REG_R6,
        A.UC_ARM_REG_R7,A.UC_ARM_REG_R8,A.UC_ARM_REG_R9,A.UC_ARM_REG_R10,
        A.UC_ARM_REG_R11,A.UC_ARM_REG_R12)):
        m.uc.reg_write(reg,0x11001000+i*0x111)
    m.uc.reg_write(A.UC_ARM_REG_APSR,0xa80f0000)
    m.uc.reg_write(A.UC_ARM_REG_FPSCR,0x00400000)
    m.invoke(0x8006ea98,[unit])
    regs=[m.uc.reg_read(reg) for reg in (A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,
        A.UC_ARM_REG_R2,A.UC_ARM_REG_R3,A.UC_ARM_REG_R4,A.UC_ARM_REG_R5,
        A.UC_ARM_REG_R6,A.UC_ARM_REG_R7,A.UC_ARM_REG_R8,A.UC_ARM_REG_R9,
        A.UC_ARM_REG_R10,A.UC_ARM_REG_R11,A.UC_ARM_REG_R12,A.UC_ARM_REG_SP,
        A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR)]
    return r,posts,writes,reads,regs,STACK-peak

def main(report_path=None,retained_report_path=None):
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,passed=True,**kw))
    # Reuse the complete detail verifier against this exact new ELF/image and
    # encoded IRQ detour. Keep the original evidence reports untouched.
    with contextlib.redirect_stdout(io.StringIO()):
        retained=detail.main(retained_report_path or ROOT/'analysis/sd_raw_retained_completion_verification.json')
    assert retained['passed'] and retained['groups']==13
    passed('all_thirteen_retained_detail_groups_pass_against_exact_raw_image',retained_groups=13)
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for name,address,n in FUNCTIONS:
        assert not any(i.mnemonic.startswith('v') for i in md.disasm(CODE[address-ENTRY:address-ENTRY+n],address)),name
    assert not any(n.startswith(('extra_','sdp_','native_worker','storage_lease','ring_')) for n in SYMS)
    assert len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    passed('whole_image_allowlist_capture_absence_zero_state_and_integer_only_IRQ_adapter')

    peak=0;raw_cases=(2,0x100002,3,0x20,0x200000,0)
    for unit in (0,1):
        for raw in raw_cases:
            old=irq(raw,unit=unit,enabled=False);new=irq(raw,unit=unit)
            assert old[1:3]==new[1:3] and old[4]==new[4]
            assert new[3][:1]==old[3][:1] # native INT_STATUS read still comes first
            r=new[0];m=r.m
            words=struct.unpack('<8I',m.uc.mem_read(STATE,32))
            assert words==(2,0,1,int(bool(raw&2)),int(bool(raw&0x157f0000)),
                int(bool(raw&2 and raw&0x157f0000)),int(bool(raw&2)),1<<unit)
            if raw&2:
                sample=struct.unpack('<13I',m.uc.mem_read(STATE+32+52,52))
                assert sample[:10]==(unit,raw,0x157f003f,0xfe88800e,0x008f020f,
                    0x0b800022,0x80000027,0x80920000,0x80934000,EVENT+unit*0x100)
                assert sample[10:]==(0x30000,0x31,0x39)
            peak=max(peak,new[5])
    passed('original_IRQ_posts_MMIO_writes_GPR_flags_and_FPSCR_preserved_for_both_native_units',
           logical_cases=12,traced_IRQ_stack_bytes=peak,physical_IRQ_delivery_modeled=True)
    old=irq(0x100002,signal=2,enabled=False);r,posts,writes,reads,regs,sp=irq(0x100002,signal=2)
    assert posts==old[1]==[(EVENT,4)]
    assert word(r.m,STATE+16)==word(r.m,STATE+20)==word(r.m,STATE+24)==1
    passed('full_TC_plus_masked_error_is_retained_before_native_success_only_event_mapping')
    before=irq(2,enabled=False);r,posts,writes,reads,regs,sp=irq(2,busy=True)
    assert posts==before[1] and writes==before[2] and regs==before[4]
    assert word(r.m,STATE)==1 and word(r.m,STATE+4)==1 and word(r.m,STATE+8)==0
    passed('busy_raw_observer_counts_omission_without_waiting_or_suppressing_native_IRQ')

    m=detail.machine();d=reply(m)
    assert d['observer_consistent'] and not d['sample_present'] and d['irqs']==0
    assert not d['physical_completion_proven'] and not d['transfer_owner_identified']
    for kind in range(1,5):assert reply(m,kind)['observer_consistent']
    passed('fixed_raw_pages_decode_zero_startup_state_without_completion_or_owner_claim')
    r=irq(2)[0];m=r.m;m.replies=[]
    m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    saved=bytes(m.uc.mem_read(STATE,188));reads=[];writes=[]
    read_hook=m.uc.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,s:reads.append(a),begin=0x402c0000,end=0x402c0fff)
    core_hook=m.uc.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,s:reads.append(a),begin=0xe000e000,end=0xe000efff)
    write_hook=m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,s:writes.append((a,n)))
    for kind in range(1,5):reply(m,kind)
    m.uc.hook_del(read_hook);m.uc.hook_del(core_hook);m.uc.hook_del(write_hook)
    assert bytes(m.uc.mem_read(STATE,188))==saved and not reads
    assert all(STACK-512<=a and a+n<=STACK for a,n in writes)
    assert reply(m)['ccr_dcache_enabled'] and reply(m)['dtcm_enabled'] and reply(m)['itcm_enabled']
    assert reply(m,4)['units']==1 and not reply(m,3)['sample_present']
    passed('raw_queries_read_stored_state_only_with_no_controller_or_core_register_access')
    first=reply(m,2)
    # New raw error snapshot on the same image, preserving first TC forever.
    put32(m,0x402c0030,0x200000);put32(m,0x402c0038,0x157f003f)
    m.invoke(0x8006ea98,[0]);assert reply(m,3)['raw']==0x200000
    assert reply(m,2)['raw']==first['raw'] and reply(m)['raw']==first['raw']
    assert reply(m,4)['errors']==1 and reply(m,4)['tc']==1
    passed('first_TC_and_latest_TC_survive_later_raw_error_and_error_page_is_independent')
    packet=m.replies[-1]
    for malformed in (packet[:-1],packet[:-1]+b'\0\xf7'):
        try:decode(malformed)
        except ValueError:pass
        else:raise AssertionError('malformed raw length accepted')
    for index,value in ((5,0),(6,128),(7,127),(11,16),(-1,0)):
        bad=bytearray(packet);bad[index]=value
        try:decode(bytes(bad))
        except ValueError:pass
        else:raise AssertionError('malformed raw reply accepted')
    for kind,token in ((0,0),(5,0),(1,128),(1,-1)):
        try:request(kind,token)
        except ValueError:pass
        else:raise AssertionError('bad raw request accepted')
    passed('host_rejects_bad_kind_token_schema_length_uint32_and_delimiter')
    put32(m,STATE,1);assert not reply(m)['observer_consistent']
    put32(m,STATE,0);epoch_reads=0
    def changed(uc,access,address,n,value,user):
        nonlocal epoch_reads
        epoch_reads+=1
        if epoch_reads==2:put32(m,STATE,2)
    h=m.uc.hook_add(UC_HOOK_MEM_READ,changed,begin=STATE,end=STATE)
    assert not reply(m)['observer_consistent'];m.uc.hook_del(h)
    passed('odd_or_changed_epoch_marks_raw_snapshot_incomplete_without_an_IRQ_lock')
    # There is no per-chunk armed context: this is deliberately a raw IRQ
    # measurement, not a replacement for fresh admission/error joining.
    out=report_path or ROOT/'analysis/sd_raw_probe_verification.json'
    report=dict(passed=True,groups=len(cases)+retained['groups'],raw_groups=len(cases),
        retained_groups=retained['groups'],results=cases,
        trial_sha256=hashlib.sha256(TRIAL).hexdigest(),limitations=MANIFEST['limitations']+[
         'Original native IRQ bodies execute with synthetic registers and event-post endpoints',
         'No physical cache, TCM mapping, bus accesses, interrupt arbitration or elapsed timing is tested'])
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=report['groups'],report=str(out))))
    return report
if __name__=='__main__':main()
