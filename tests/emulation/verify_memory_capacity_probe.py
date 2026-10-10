#!/usr/bin/env python3
"""Fixed register query, exact image and retained native diagnostic checks.

Register contents are fixtures. This does not measure physical RAM or confirm
the fitted CPU, bus behavior or safe RAM ownership on the mixer.
"""
import contextlib,hashlib,io,json,struct,sys
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_CODE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,INPUT,STACK,BIAS
from verify_overdub_prototype import Emulator
from verify_firmware_workflow import put32
from verify_health_probe import query
import verify_sd_command_probe as command
from build_memory_capacity_probe import ELF,ENTRY,OUT,STATES,trial
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_memory_capacity_probe import FIELDS,request,decode

with ELF.open('rb') as f:
    e=ELFFile(f);seg=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD');CODE=seg.data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    FUNCTIONS=[(s.name,s['st_value']&~1,s['st_size']) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type']=='STT_FUNC' and s['st_size']]
TRIAL,MANIFEST=trial(CODE,SYMS)

ADDRESSES=(0x402f0000,0x402f0004,0x402f0010,0x402f0014,0x402f0018,0x402f001c,
           0x402f0040,0x402f0044,0x402f0048,0x402f004c,0x400ac040,0x400ac044,
           0xe000ef94,0xe000ef90,0xe000ed00,0x400d8260)
CONTENTS=(0x10000004,0,0x8000001b,0,0,0,0xf31,0x00652922,0x50210a09,0x50210a09,
          7,0xaaaa555f,0x49,0x41,0x411fc271,0x006c0000)

def machine(values=CONTENTS):
    m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True)
    m.uc.mem_write(0x80001000,TRIAL[0x200:0xb5ce4])
    for address,n in ((0x402f0000,0x1000),(0x400ac000,0x1000),
                      (0x400d8000,0x1000),(0xe000e000,0x2000)):m.uc.mem_map(address,n)
    for a,v in zip(ADDRESSES,values):put32(m,a,v)
    m.replies=[];m.reads=[];m.writes=[];m.min_sp=STACK
    m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    def read(uc,k,a,n,v,s):m.reads.append(a)
    for lo,hi in ((0x402f0000,0x402f0fff),(0x400ac000,0x400acfff),
                  (0x400d8000,0x400d8fff),(0xe000e000,0xe000ffff)):
        m.uc.hook_add(UC_HOOK_MEM_READ,read,begin=lo,end=hi)
    m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,s:m.writes.append((a,n)))
    def stack(uc,pc,n,u):m.min_sp=min(m.min_sp,uc.reg_read(A.UC_ARM_REG_SP))
    m.uc.hook_add(UC_HOOK_CODE,stack)
    return m

def direct(m,data,state=2):
    m.uc.mem_write(INPUT,struct.pack('<I',len(data))+data+bytes(16))
    m.uc.mem_write(0x80629b60,bytes([state]))
    return m.invoke(SYMS['memory_capacity_dispatch'],[INPUT])

def main(report_path=None,retained_report_paths=None,prepared_image=None):
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,passed=True,**kw))
    prepared=(prepared_image or OUT/'trial_memory_capacity/L6.BIN').read_bytes()
    assert prepared==TRIAL and len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert MANIFEST['native_capacity_frames']==223104 and MANIFEST['memory_query_persistent_state_bytes']==0
    assert not any(n.startswith(('extra_','sdp_','native_worker','storage_lease')) for n in SYMS)
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for name,a,n in FUNCTIONS:
        assert not any(i.mnemonic.startswith('v') for i in md.disasm(CODE[a-ENTRY:a-ENTRY+n],a)),name
    for name,n in STATES.items():assert CODE[SYMS[name]-ENTRY:SYMS[name]-ENTRY+n]==bytes(n)
    passed('exact_whitelisted_image_integer_only_no_capture_allocation_or_new_persistent_state')

    m=machine();before=[bytes(m.uc.mem_read(SYMS[n],size)) for n,size in STATES.items()]
    query(m,request(1,37));r=decode(m.replies[-1])
    assert r['token']==37 and r['observer_consistent'] and m.reads==list(ADDRESSES)*2
    assert tuple(r[n] for n in FIELDS[2:])==CONTENTS
    assert r['semc_enabled'] and r['sdram_refresh_enabled'] and r['bus_width_bits']==16
    assert r['column_bits']==9 and r['bank_count']==4
    assert r['sdram_windows'][0]['configured_bytes']==32*1024*1024
    assert r['dtcmcr_configured_bytes']==256*1024 and r['itcmcr_configured_bytes']==128*1024
    assert r['gpr17_selected'] and not r['physical_capacity_confirmed'] and not r['unused_memory_proven']
    assert before==[bytes(m.uc.mem_read(SYMS[n],size)) for n,size in STATES.items()]
    assert all(STACK-512<=a and a+n<=STACK for a,n in m.writes)
    assert STACK-m.min_sp<=512
    passed('encoded_parser_detour_returns_exact_fixed_double_snapshot_with_stack_only_writes',
           modeled_query_stack_bytes=STACK-m.min_sp,register_reads=len(m.reads))

    for code,n in ((12,16*1024*1024),(13,32*1024*1024),(14,64*1024*1024)):
        values=list(CONTENTS);values[2]=0x80000001+(code<<1)
        m=machine(values);assert direct(m,request(1,127))==1
        r=decode(m.replies[-1]);assert r['sdram_windows'][0]['configured_bytes']==n
        assert not r['physical_capacity_confirmed'] and not r['unused_memory_proven']
    # The compared official headers give PS a one-bit mask. Reserved bit 1
    # must not turn a documented 8/16-bit selection into an unknown width.
    for port_size,width in ((0,8),(1,16),(2,8),(3,16)):
        values=list(CONTENTS);values[6]=(values[6]&~3)|port_size
        m=machine(values);direct(m,request(1,0));r=decode(m.replies[-1])
        assert r['bus_width_bits']==width
        assert not r['physical_capacity_confirmed'] and not r['unused_memory_proven']
    values=list(CONTENTS);values[0]=2;values[2]=0;values[9]=0;values[10]=0
    m=machine(values);direct(m,request(1,0));r=decode(m.replies[-1])
    assert not r['semc_enabled'] and not r['sdram_refresh_enabled'] and not r['gpr17_selected']
    assert not r['sdram_windows'][0]['enabled'] and r['sdram_windows'][0]['configured_bytes']==0
    passed('different_or_disabled_configurations_never_become_physical_or_unused_memory_claims')

    m=machine();hits=0
    def changed(uc,k,a,n,v,s):
        nonlocal hits
        hits+=1
        if hits==2:put32(m,a,0x8000001d)
    m.uc.hook_add(UC_HOOK_MEM_READ,changed,begin=0x402f0010,end=0x402f0010)
    direct(m,request(1,1));r=decode(m.replies[-1])
    assert not r['observer_consistent'] and r['br0']==CONTENTS[2] and len(m.reads)==32
    passed('changed_controller_configuration_marks_snapshot_inconsistent_without_retry_or_writes')

    m=machine()
    data=request(1,37)
    bad_packets=[data[:-1],data+b'\0']
    for index,value in ((0,0),(1,0),(2,1),(3,1),(4,0x6d),(5,0),(5,2),(6,128),(7,0)):
        bad=bytearray(data);bad[index]=value;bad_packets.append(bytes(bad))
    # The compiler folds the diagnostic delegate chain into this entry. A zero
    # result makes the existing parser detour continue the original prologue.
    for bad in bad_packets:assert direct(m,bad)==0
    assert direct(m,data,state=1)==0
    assert not m.reads and not m.replies
    passed('all_nonmatching_packets_and_unconnected_editor_return_to_stock_parser_without_register_access')

    m=machine();m.uc.reg_write(A.UC_ARM_REG_IPSR,16)
    assert direct(m,request(1,2))==0 and not m.reads and not m.replies
    passed('handler_context_refuses_register_query_without_access_or_reply')

    m=machine();direct(m,request(1,4));packet=m.replies[-1]
    for index,value in ((5,2),(6,128),(7,2),(11,16),(12,2),(-1,0)):
        bad=bytearray(packet);bad[index]=value
        try:decode(bytes(bad))
        except ValueError:pass
        else:raise AssertionError('Malformed RAM reply accepted')
    for bad in (packet[:-1],packet[:-1]+b'\0\xf7'):
        try:decode(bad)
        except ValueError:pass
        else:raise AssertionError('Wrong RAM reply length accepted')
    for kind,token in ((0,0),(2,0),(1,-1),(1,128)):
        try:request(kind,token)
        except ValueError:pass
        else:raise AssertionError('Host-selected invalid RAM query accepted')
    assert decode(bytes((0xf0,0x52,0,0,0x70,1,0,0xf7))) is None
    passed('host_schema_rejects_malformed_words_lengths_tokens_and_nonfixed_requests')

    # Reuse all existing native SD, IRQ, query and DSP checks against this exact
    # new image, writing separate reports so prior evidence stays intact.
    for module in (command,command.raw,command.raw.detail):
        module.ELF=ELF;module.CODE=CODE;module.SYMS=SYMS;module.FUNCTIONS=FUNCTIONS
        module.TRIAL=TRIAL;module.MANIFEST=MANIFEST;module.STATES=STATES
    command.STATE=SYMS['command_trace'];command.raw.STATE=SYMS['raw_trace']
    command.raw.detail.STATE=SYMS['completion_trace']
    with contextlib.redirect_stdout(io.StringIO()):
        paths=retained_report_paths or (ROOT/'analysis/memory_capacity_retained_command_verification.json',
            ROOT/'analysis/memory_capacity_retained_raw_verification.json',
            ROOT/'analysis/memory_capacity_retained_detail_verification.json')
        retained=command.main(paths[0],paths[1:])
    assert retained['passed'] and retained['groups']==35
    passed('all_thirty_five_native_command_raw_detail_and_health_groups_pass_on_exact_new_image',retained_groups=35)
    report=dict(passed=True,groups=len(cases)-1+retained['groups'],memory_groups=len(cases)-1,
        retained_groups=retained['groups'],results=cases,trial_sha256=hashlib.sha256(TRIAL).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=MANIFEST['limitations'])
    out=report_path or ROOT/'analysis/memory_capacity_probe_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=report['groups'],report=str(out))))
    return report
if __name__=='__main__':main()
