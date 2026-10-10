#!/usr/bin/env python3
"""Passive chunk-wait probe on original SD instructions; all MMIO is modeled."""
import hashlib,json,struct,sys
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from verify_sd_transfer_lifetime import Sd,BUFFER,EVENT
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT,IMAGE,INPUT,STACK,REGS,RETURN
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_control_transport import TASK
from verify_health_probe import startup,query
from verify_scheduling_boundaries import stop
sys.path.insert(0,str(ROOT/'tools/device'))
from build_sd_completion_probe import ELF,DETAIL_ELF,ENTRY,OUT,WAIT_SITES,HOOKS,STATES,DETAIL_STATES,trial
from l6_sd_completion_probe import request,decode,FIELDS,PATHS,SUMMARY_FIELDS
from l6_health_probe import request as health_request,decode as health_decode

DETAIL='--detail' in sys.argv
assert not set(sys.argv[1:])-{'--detail'}
if DETAIL:ELF,STATES=DETAIL_ELF,DETAIL_STATES
STATE_BYTES=STATES['completion_trace']
with ELF.open('rb') as f:
    e=ELFFile(f);seg=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD');CODE=seg.data()
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    FUNCTIONS=[(s.name,s['st_value']&~1,s['st_size']) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type']=='STT_FUNC' and s['st_size']]
TRIAL,MANIFEST=trial(CODE,SYMS,DETAIL);STATE=SYMS['completion_trace']

def overlay(m):
    m.uc.mem_write(ENTRY,CODE)
    for site in (*WAIT_SITES,*HOOKS.values()):m.uc.mem_write(site,TRIAL[site-0x80000e00:site-0x80000e00+4])
def machine():
    m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True);overlay(m)
    m.replies=[];m.events=[]
    m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    m.hooks[0x80020ca0]=lambda a:m.events.append(a[:5]) or 0
    return m
def reply(m,kind=1):
    query(m,request(kind,37));return decode(m.replies[-1])
def trace(op,blocks,offset=0,enabled=True,flags=4,status=0,present=8,system=0,protocol=0x20,vendor2=0):
    r=Sd(Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True));m=r.m
    m.hooks.pop(0x8006a348)
    put32(m,0x402c0010,0x100);put32(m,0x402c0028,protocol);put32(m,0x402c00c8,vendor2)
    put32(m,TASK,0x21039000)
    m.uc.mem_write(BUFFER,bytes([0x3c])*0x4000)
    m.uc.mem_write(0x2000c4d4,bytes(range(256))*32)
    r.observed_waits=[];r.site_calls=[];r.mmio=[];r.min_sp=STACK
    # Include auxiliary native transfers entered by stock error handling; they
    # must not be mistaken for an observer counter attributed to the wrong site.
    m.uc.hook_add(UC_HOOK_CODE,lambda u,pc,n,s:r.site_calls.append(pc+4) if pc in WAIT_SITES else None,
                  begin=min(WAIT_SITES),end=max(WAIT_SITES))
    def wait(a):
        assert r.held and a[0]==EVENT and a[4]==5000
        assert m.uc.reg_read(A.UC_ARM_REG_SP)%8==0
        r.observed_waits.append(tuple(a[:5]))
        if a[1]==0x183:put32(m,a[3],2);return 0
        assert a[1]==0x185
        put32(m,0x402c0024,present);put32(m,0x402c002c,system)
        if not status:put32(m,a[3],flags)
        return status
    m.hooks[0x800328c0]=wait
    def writes(uc,kind,address,size,value,user):r.mmio.append((address,size,value))
    m.uc.hook_add(UC_HOOK_MEM_WRITE,writes,begin=0x402c0000,end=0x402c0fff)
    if enabled:
        overlay(m)
        def stack(uc,pc,n,u):r.min_sp=min(r.min_sp,uc.reg_read(A.UC_ARM_REG_SP))
        m.uc.hook_add(UC_HOOK_CODE,stack,begin=ENTRY,end=ENTRY+len(CODE)-1)
    result=r.request(op,blocks,offset)
    r.snapshot=struct.unpack('<31I',m.uc.mem_read(STATE,124)) if enabled else None
    return r,result

def main(report_path=None):
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    assert len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert all(CODE[SYMS[n]-ENTRY:SYMS[n]-ENTRY+size]==bytes(size) for n,size in STATES.items())
    assert not any(n.startswith(('storage_lease','native_worker','extra_','sdp_','ring_')) for n in SYMS)
    passed('exact_image_allowlist_and_loaded_zero_state_with_capture_worker_and_recovery_absent')

    old,helpers=startup(IMAGE);new,new_helpers=startup(TRIAL)
    assert old==new and helpers[:4]==new_helpers[:4] and helpers[5:]==new_helpers[5:]
    passed('original_full_scatter_and_entire_DSP_output_preserved')
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for name,address,size in FUNCTIONS:
        assert not any(i.mnemonic.startswith('v') for i in md.disasm(CODE[address-ENTRY:address-ENTRY+size],address)),name
    passed('all_compiled_observer_functions_use_integer_registers_only')

    sites=0;peak=0
    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(2,4),(2,1),(9,1),(9,0)):
            old,result=trace(op,blocks,offset,False);r,new=trace(op,blocks,offset)
            assert result==new==0 and not r.held and r.mmio==old.mmio
            assert bytes(r.m.uc.mem_read(BUFFER,0x4000))==bytes(old.m.uc.mem_read(BUFFER,0x4000))
            assert [(x[0],x[1],x[2],x[4]) for x in r.observed_waits]==[(x[0],x[1],x[2],x[4]) for x in old.observed_waits]
            epoch,waits,skips,seen,anomalies=r.snapshot[:5]
            assert epoch==waits*2 and waits==sum(x[1]==0x185 for x in r.observed_waits) and waits and not skips and not anomalies
            sites|=seen;peak=max(peak,STACK-r.min_sp)
    assert sites==15
    passed('all_four_real_chunk_call_sites_preserve_wait_ABI_MMIO_payloads_results_and_unit_release',
           logical_cases=12,traced_SD_caller_and_observer_stack_bytes=peak)

    for kwargs in (dict(flags=1),dict(flags=0x84),dict(status=0xffffffce),dict(present=0x30f),
                   dict(system=0x04000000),dict(protocol=0x220),dict(protocol=0),dict(vendor2=0x1000)):
        old,status=trace(2,2,enabled=False,**kwargs);r,new=trace(2,2,**kwargs)
        assert status==new and r.mmio==old.mmio and not r.held and r.snapshot[4]==1
        assert r.snapshot[5:18]==r.snapshot[18:31]
    passed('mixed_timeout_active_reset_DMA_and_endian_anomalies_recorded_without_changing_stock_return_or_recovery')

    m=machine();d=reply(m);assert d['waits']==0 and d['observer_consistent'] and not d['physical_completion_proven']
    for bad in (0,8):
        try:request(bad,0)
        except ValueError:pass
        else:raise AssertionError('invalid kind accepted')
    packet=m.replies[-1]
    for changed in (packet[:-1],packet[:-1]+b'\0\xf7'):
        try:decode(changed)
        except ValueError:pass
        else:raise AssertionError('invalid length accepted')
    for index,value in ((5,8),(6,128),(11,16),(7,128),(-1,0)):
        changed=bytearray(packet);changed[index]=value
        try:decode(bytes(changed))
        except ValueError:pass
        else:raise AssertionError('invalid reply accepted')
    put32(m,STATE,1);assert not reply(m)['observer_consistent']
    passed('fixed_host_query_schema_rejects_malformed_replies_and_marks_busy_snapshots_incomplete')

    r,result=trace(2,2);m=r.m;m.replies=[]
    m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    before=bytes(m.uc.mem_read(STATE,STATE_BYTES));writes=[]
    h=m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,s:writes.append((a,n)))
    latest=reply(m);first=reply(m,2)
    if DETAIL:
        detail=reply(m,3)
        assert detail['per_site']['direct_read']['waits']==1
        assert all(not reply(m,k)['sample_present'] for k in range(4,8))
    m.uc.hook_del(h)
    assert latest['sites']==1 and latest['status']==0 and latest['flags']==4 and latest['anomalies']==0
    assert first['site']==0 and before==bytes(m.uc.mem_read(STATE,STATE_BYTES))
    assert all(STACK-512<=a and a+n<=STACK for a,n in writes)
    query(m,health_request(1,42));assert health_decode(m.replies[-1])['token']==42
    passed('read_only_latest_and_first_queries_keep_probe_state_unchanged_and_preserve_legacy_health')

    r,status=trace(2,2,present=0x30f);m=r.m
    first=r.snapshot[5:18]
    # External model now clears activity before another independently requested
    # transfer; the passive diagnostic does not perform recovery or resubmit it.
    put32(m,0x402c0024,8)
    m.hooks[0x800328c0]=lambda a:put32(m,0x402c0024,8) or put32(m,a[3],2 if a[1]==0x183 else 4) or 0
    assert r.request(2,2)==0 and word(m,STATE+16)==1
    assert tuple(struct.unpack('<13I',m.uc.mem_read(STATE+20,52)))==first
    assert word(m,STATE+72+7*4)==8
    passed('first_anomaly_is_retained_after_later_good_transfer_without_reset_or_retry_added')

    r,status=trace(2,2);m=r.m
    ordinary_wait=m.hooks[0x800328c0]
    m.hooks[0x800328c0]=lambda a:stop(m) if a[1]==0x185 else ordinary_wait(a)
    r.request(2,2);assert word(m,STATE)&1 and r.held
    context=m.uc.context_save();sp=m.uc.reg_read(A.UC_ARM_REG_SP)
    frame=bytes(m.uc.mem_read(sp,STACK-sp));before=bytes(m.uc.mem_read(STATE,STATE_BYTES))
    m.stack=STACK-0x1000;m.replies=[]
    m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    try:
        assert not reply(m)['observer_consistent']
        if DETAIL:assert not reply(m,3)['observer_consistent']
    finally:del m.stack;m.uc.context_restore(context)
    assert before==bytes(m.uc.mem_read(STATE,STATE_BYTES)) and frame==bytes(m.uc.mem_read(sp,STACK-sp)) and r.held
    passed('separate_stack_query_during_pending_wait_is_nonblocking_and_leaves_native_frame_and_unit_owned')

    r,status=trace(2,2);m=r.m;put32(m,STATE,1)
    assert r.request(2,2)==status and word(m,STATE+8)==1 and word(m,STATE)==1
    passed('busy_observer_never_blocks_or_suppresses_native_IO_and_counts_omissions')
    if DETAIL:
        # Run each original direct/bounce read/write entry. Each retained page
        # must describe its own site, even after an independently modeled good
        # transfer at another site; the diagnostic never makes it good itself.
        r,status=trace(2,2,present=6);m=r.m;m.replies=[]
        m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
        states=((2,0,6),(2,1,0x200),(3,0,0x100),(3,1,4))
        for i,(op,offset,present) in enumerate(states):
            if i:
                put32(m,0x402c0024,8)
                m.hooks[0x800328c0]=lambda a,present=present:put32(m,0x402c0024,present) or put32(m,a[3],2 if a[1]==0x183 else 4) or 0
                r.request(op,2,offset)
        summary=reply(m,3)
        assert summary['sites']==15 and summary['waits']==summary['anomalies']==4 and not summary['skipped']
        for i,(_,_,present) in enumerate(states):
            site=summary['per_site'][PATHS[i]];sample=reply(m,4+i)
            assert site['waits']==site['anomalies']==1 and site['reason_union']==present<<8
            assert sample['sample_present'] and sample['activity_bits']==present and sample['flags']==4
        put32(m,0x402c0024,8)
        m.hooks[0x800328c0]=lambda a:put32(m,0x402c0024,8) or put32(m,a[3],2 if a[1]==0x183 else 1) or 0
        assert r.request(2,2)==0
        summary=reply(m,3)
        assert summary['per_site']['direct_read']['anomalies']==2
        assert summary['per_site']['direct_read']['reason_union']==0x606
        assert reply(m,4)['flags']==1 and reply(m,2)['flags']==4
        retained=[reply(m,k) for k in range(4,8)]
        put32(m,0x402c0024,8)
        m.hooks[0x800328c0]=lambda a:put32(m,0x402c0024,8) or put32(m,a[3],2 if a[1]==0x183 else 4) or 0
        assert r.request(2,2)==0
        new=reply(m,3);assert new['waits']==6 and new['anomalies']==5
        for i in range(4):
            assert new['per_site'][PATHS[i]]['reason_union']==summary['per_site'][PATHS[i]]['reason_union']
            assert {k:reply(m,4+i)[k] for k in FIELDS[6:-2]}=={k:retained[i][k] for k in FIELDS[6:-2]}
        assert not reply(m)['activity_bits']
        passed('per_site_counts_reason_unions_and_latest_anomalies_survive_later_quiet_waits_on_other_paths')

        for kwargs,expected in ((dict(status=0xffffffce),1),(dict(flags=1),6),
             (dict(flags=0x84),4),(dict(system=0x04000000),8),
             (dict(protocol=0x220),16),(dict(vendor2=0x1000),16)):
            for op,offset,index in ((2,0,0),(2,1,1),(3,0,2),(3,1,3)):
                r,result=trace(op,2,offset,**kwargs);m=r.m;m.replies=[]
                m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
                d=reply(m,3)
                assert d['per_site'][PATHS[index]]['reason_union']==expected
                assert d['per_site'][PATHS[index]]['anomalies']==1
                for j,n in enumerate(PATHS):
                    expected_count=r.site_calls.count(WAIT_SITES[j]+4)
                    assert d['per_site'][n]['waits']==expected_count
                    assert d['per_site'][n]['anomalies']==expected_count
                    wanted=expected if expected_count else 0
                    if expected_count and j!=index:
                        # Stock write-error diagnostics issue a bounce read in
                        # mode 0x10 with DMA disabled. Preserve that real path
                        # and classify it separately from the requested write.
                        extra=reply(m,4+j)
                        assert op==3 and j==1 and extra['mix']==0x10
                        wanted|=16
                    assert d['per_site'][n]['reason_union']==wanted
        passed('wait_error_completion_flags_reset_and_unexpected_modes_are_classified_at_each_actual_native_path',logical_cases=24)

        m=machine();d=reply(m,3);packet=m.replies[-1]
        assert d['schema']==2 and len(packet)==8+5*len(SUMMARY_FIELDS)
        for index,value in ((7,1),(11,16),(7+5*14,64)):
            bad=bytearray(packet);bad[index]=value
            try:decode(bytes(bad))
            except ValueError:pass
            else:raise AssertionError('malformed detail summary accepted')
        r,result=trace(2,2,present=6);m=r.m;m.replies=[]
        m.hooks[0x80031648]=lambda a:m.replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
        reply(m,4);bad=bytearray(m.replies[-1]);bad[5]=5
        try:decode(bytes(bad))
        except ValueError:pass
        else:raise AssertionError('cross-site anomaly page accepted')
        passed('detail_host_rejects_wrong_schema_unknown_reasons_and_cross_site_samples')
    report=dict(passed=True,groups=len(cases),results=cases,trial_sha256=hashlib.sha256(TRIAL).hexdigest(),
                limitations=MANIFEST['limitations']+['MMIO, flags, DMA effects, kernel locking and controller completion are models'])
    out=report_path or ROOT/('analysis/sd_completion_detail_verification.json' if DETAIL else 'analysis/sd_completion_probe_verification.json')
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
    return report
if __name__=='__main__':main()
