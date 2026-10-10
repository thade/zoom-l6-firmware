#!/usr/bin/env python3
"""Exact isolated loader image, identity query and retained diagnostics.

No device access. Original scatter and query instructions execute; hardware,
kernel scheduling and IRQ timing retain the existing explicit models.
"""
import contextlib,hashlib,io,json,struct,sys
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from build_loader_probe import ELF,OUT,ENTRY,STATES,trial
from build_health_probe import DSP_SOURCE,DSP_DEST,DSP_BYTES,SCATTER,END
from build_deployment_probe import validate
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT,RETURN,STACK
from verify_firmware_workflow import put32
import verify_health_probe as health
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_loader_probe import request,decode

with ELF.open('rb') as f:
    e=ELFFile(f);CODE=next(s.data() for s in e.iter_segments() if s['p_type']=='PT_LOAD')
    SYMS={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
    FUNCTIONS=[(s.name,s['st_value']&~1,s['st_size']) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type']=='STT_FUNC' and s['st_size']]
TRIAL,MANIFEST=trial(CODE,SYMS)
HELPER=MANIFEST['loader_record'][3]

def machine():
    m=health.machine(False);m.uc.mem_write(0x80001000,TRIAL[0x200:0xb5ce4])
    m.record_reads=[];m.writes=[]
    m.uc.hook_add(UC_HOOK_MEM_READ,lambda u,k,a,n,v,x:m.record_reads.append((a,n)),begin=SCATTER,end=SCATTER+15)
    m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,x:m.writes.append((a,n)))
    return m

def direct(m,packet,state=2):
    m.uc.mem_write(INPUT,struct.pack('<I',len(packet))+packet+bytes(16))
    m.uc.mem_write(0x80629b60,bytes([state]));m.writes.clear()
    return m.invoke(SYMS['loader_dispatch'],[INPUT])

def startup(image):return health.startup(image,extra_helpers=(HELPER,))

def main():
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,**kw))
    assert (OUT/'trial_loader/L6.BIN').read_bytes()==TRIAL
    validate(TRIAL)
    assert TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    assert MANIFEST['state_bytes']==1780 and MANIFEST['new_persistent_state_bytes']==0
    assert MANIFEST['native_capacity_frames']==223104
    old,old_calls=startup(IMAGE);new,new_calls=startup(TRIAL)
    assert new==old and len(new)==8 and len(new_calls)==8
    assert old_calls[:4]==new_calls[:4] and old_calls[5:]==new_calls[5:]
    assert new_calls[4]==(HELPER,*MANIFEST['loader_record'][:3])
    passed('exact_whitelisted_image_restores_all_eight_original_regions_through_actual_scatter_and_LZ4')

    # Stop malformed inputs at the compiled fail entry, before Main/DSP use.
    for corrupt in ('length','token'):
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        for a,n in ((0x80000000,0x2000000),(0x20000000,0x40000),(0x20210000,0x20000),(0,0x1000)):
            u.mem_map(a,n)
        u.mem_write(0x80001000,TRIAL[0x200:0xb5ce4])
        src=MANIFEST['loader_record'][0]
        if corrupt=='length':u.mem_write(src,b'\xff'*4)
        else:u.mem_write(src,struct.pack('<I',1)+b'\xf0')
        entered=[]
        def stop_at(u,a,n,x):entered.append(a);u.emu_stop()
        for a in (MANIFEST['loader_failed_entry'],0x80067a60):u.hook_add(UC_HOOK_CODE,stop_at,begin=a,end=a)
        u.emu_start(0x80001401,0x80067a62,count=100000000)
        assert entered==[MANIFEST['loader_failed_entry']]
    passed('malformed_compressed_size_and_truncated_token_stop_before_Main_in_exact_new_image')

    for token in (0,37,127):
        m=machine();before=bytes(m.uc.mem_read(ENTRY,len(CODE)))
        assert direct(m,request(token))==1
        result=decode(m.replies[-1]);assert result['token']==token
        assert [result[k] for k in ('source','destination','bytes','helper')]==MANIFEST['loader_record']
        assert m.record_reads==[(SCATTER+i*4,4) for i in range(4)]
        assert bytes(m.uc.mem_read(ENTRY,len(CODE)))==before
        assert all(STACK-256<=a and a+n<=STACK for a,n in m.writes)
    passed('new_query_reports_fixed_scatter_record_with_four_RAM_reads_and_only_bounded_stack_writes')

    packet=request(19);bad=[packet[:-1],packet+b'\0']
    for i,v in ((0,0),(1,0),(2,1),(3,1),(4,0),(5,0),(5,4),(6,128),(7,0)):
        b=bytearray(packet);b[i]=v;bad.append(bytes(b))
    for p in bad:
        m=machine();assert direct(m,p)==0 and not m.record_reads and not m.replies
    for state in (0,1,3):
        m=machine();assert direct(m,packet,state)==0 and not m.record_reads and not m.replies
    m=machine();m.uc.reg_write(A.UC_ARM_REG_IPSR,16)
    assert direct(m,packet)==0 and not m.record_reads and not m.replies
    m=machine();direct(m,packet);reply=m.replies[-1]
    for changed in (reply[:-1],reply+b'\0'):
        try:decode(changed)
        except ValueError:pass
        else:raise AssertionError('bad reply length accepted')
    for i,v in ((6,128),(7,2),(11,16),(-1,0)):
        b=bytearray(reply);b[i]=v
        try:decode(bytes(b))
        except ValueError:pass
        else:raise AssertionError('bad encoded reply accepted')
    for token in (-1,128):
        try:request(token)
        except ValueError:pass
        else:raise AssertionError('bad token accepted')
    passed('request_context_and_host_decoder_reject_malformed_data_without_identity_reads')

    m=machine();m.hooks.pop(0x80031648);given=[];ring=0x8062ad84
    put32(m,0x8062cd84,8191);put32(m,0x8062cd8c,8192)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    health.query(m,request(19))
    actual=bytes(m.uc.mem_read(ring+8191,1))+bytes(m.uc.mem_read(ring,32))
    assert actual==reply and given==[0x7111,0x7112]
    passed('original_parser_and_sender_copy_complete_identity_reply_across_transmit_ring_wrap')

    # Reuse all 66 checks with this exact code/image, while counting the new
    # scatter helper in the existing full-startup observer. No device fixtures.
    sys.argv.append('--detail')
    import verify_sd_startup_probe as retained
    import verify_sd_completion_probe as completion
    # The optimizer folds startup_dispatch into the new outer dispatcher.
    # Direct-query cases enter that real compiled dispatcher; no query body
    # or context check is substituted by the host.
    retained_symbols=dict(SYMS,startup_dispatch=SYMS['loader_dispatch'])
    for k,v in dict(ELF=ELF,OUT=OUT,CODE=CODE,SYMS=retained_symbols,FUNCTIONS=FUNCTIONS,
                   TRIAL=TRIAL,MANIFEST=MANIFEST,STATES=STATES,
                   STATE=SYMS['startup_trace'],PREFIX='loader_retained',startup=startup).items():
        setattr(retained,k,v)
    completion.startup=startup
    with contextlib.redirect_stdout(io.StringIO()):retained.main()
    retained_report=json.loads((ROOT/'analysis/loader_retained_probe_verification.json').read_text())
    assert retained_report['passed'] and retained_report['groups']==66
    passed('all_66_expanded_startup_RAM_capacity_command_raw_detail_and_health_checks_pass_on_exact_loader_image')
    report=dict(passed=True,groups=len(cases)-1+66,loader_groups=len(cases)-1,retained_groups=66,
        results=cases,trial_sha256=hashlib.sha256(TRIAL).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=MANIFEST['limitations'])
    out=ROOT/'analysis/loader_probe_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=report['groups'],report=str(out))))

if __name__=='__main__':main()
