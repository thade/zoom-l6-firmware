#!/usr/bin/env python3
"""Native pre-address drain and nominal host predicate; no device access.

QUIET/exclusive-span permission, MMIO/NVIC/W1C effects and kernel scheduling
remain explicit models. Near branch veneers below exist only in emulator RAM.
"""
import hashlib, json, struct, sys
from pathlib import Path
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from verify_sd_chunk_guard import Chunk, chunk, TASK
from verify_sd_transfer_probe import Probe, ELF, patch
from verify_sd_native_event import NativePorts, SEM, BIT, ISER, ISPR
from verify_sd_transfer_lifetime import BUFFER, EVENT
from verify_pad_protocol import ROOT, IMAGE, BIAS, REGS, RETURN, STACK
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_scheduling_boundaries import stop
from sd_registers import DMA_ADDRESS, PRESENT, SYSTEM, IRQ_STATUS, IRQ_SIGNAL, PROTOCOL, VENDOR2
sys.path.insert(0,str(ROOT/'tools/firmware'))
from build_added_code_probe import branch

QUIET=0x2102b800
AFIELDS='address site task prepared calls fault'.split()
SITES=((0x80069fec,'sdp_program_direct_read',4),
       (0x8006a180,'sdp_program_bounce_read',4),
       (0x8006abf0,'sdp_program_direct_write',4),
       (0x8006adac,'sdp_program_bounce_write',6))
READY=0x01000008

def record(r):
    return dict(zip(AFIELDS,struct.unpack('<6I',r.m.uc.mem_read(r.syms['sdp_admission_state'],24))))

def adapters(r):
    for i,(site,name,span) in enumerate(SITES):
        # Test-only nearby veneer: the separate ELF is outside B.W range.
        near=0x80f00000+i*16
        patch(r.m,near,r.syms[name],8)
        r.m.uc.mem_write(site,branch(site,near)+b'\x00\xbf'*((span-4)//2))
        r.m.uc.ctl_remove_cache(site,site+span)

class Admission(NativePorts,Chunk):
    def install_adapters(self):adapters(self)
    def __init__(self,aligned=0):
        Chunk.__init__(self)
        self.native_setup()
        self.m.stack=STACK+aligned
        self.data_present=READY
        self.quiet_calls=[];self.hold_call=None;self.quiet_reply=0
        self.after_quiet=None;self.stop_delay=False;self.delay_count=0
        self.pending_status=None;self.status_w1c=True;self.before_store=[]
        self.adapter_snapshots={};self.adapter_pairs=[]
        put32(self.m,PRESENT,READY);put32(self.m,PROTOCOL,0x22)
        put32(self.m,VENDOR2,0);put32(self.m,SYSTEM,0)
        put32(self.m,self.syms['sdp_chunk_admit_port'],self.syms['sdp_native_admit']|1)
        put32(self.m,self.syms['sdp_chunk_finish_port'],self.syms['sdp_native_chunk_join']|1)
        self.m.hooks[QUIET]=self.quiet
        self.m.hooks[0x80032250]=self.delay
        self.install_adapters()
        def written(uc,access,address,size,value,user):
            if address==IRQ_STATUS and self.status_w1c:
                self.pending_status=word(self.m,IRQ_STATUS)&~value
            if address==DMA_ADDRESS:
                self.before_store.append(dict(address=value,raw=word(self.m,IRQ_STATUS),
                    flags=word(self.m,EVENT+8),tokens=word(self.m,SEM+0x38),
                    admission=record(self),present=word(self.m,PRESENT)))
        self.m.uc.hook_add(UC_HOOK_MEM_WRITE,written,begin=DMA_ADDRESS,end=IRQ_SIGNAL)
        def code(uc,pc,size,user):
            if self.pending_status is not None:
                put32(self.m,IRQ_STATUS,self.pending_status);self.pending_status=None
            for site,name,span in SITES:
                if pc==site:
                    self.adapter_snapshots[site]=self.registers()
                if pc==site+span:
                    before=self.adapter_snapshots.pop(site)
                    self.adapter_pairs.append((site,before,self.registers()))
        self.m.uc.hook_add(UC_HOOK_CODE,code)

    def registers(self):
        general=tuple(getattr(A,f'UC_ARM_REG_R{i}') for i in range(13))
        return [self.m.uc.reg_read(x) for x in (*general,A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR)]
    def quiet(self,args):
        assert self.held and self.state()['active'] and not self.state()['finished']
        assert args[:2]==[0,EVENT] and self.m.uc.reg_read(A.UC_ARM_REG_IPSR)==0
        self.quiet_calls.append(dict(args=args[:4],record=record(self),copies=list(self.copies),
            stores=list(self.dma_stores),raw=word(self.m,IRQ_STATUS)))
        if self.after_quiet:self.after_quiet(self)
        if self.hold_call==record(self)['calls']+1:
            stop(self.m);return self.quiet_reply
        return 1 # MODEL source lease held through this chunk's host join.
    def delay(self,args):
        assert args[0]==1 and self.held
        self.delay_count+=1
        if self.stop_delay:return stop(self.m)
        return 0
    def resume_until_blocked(self):
        self.m.reached_return=False
        self.m.uc.emu_start(self.m.uc.reg_read(A.UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
        assert self.m.reached_return
        return self.m.uc.reg_read(REGS[0])

def held_before_native(r):
    assert r.held and r.state()['active'] and not r.state()['finished']
    assert not r.native_commands and not r.dma_stores

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    assert hashlib.sha256(IMAGE).hexdigest()=='64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'

    exercised=set()
    for align in (0,4):
        for op in (2,3):
            for n,off in ((1,0),(2,0),(2,4),(2,1),(9,1),(9,0)):
                old=Probe();assert old.request(op,n,off)==0
                r=Admission(align);assert r.request(op,n,off)==0 and not r.held
                assert bytes(r.m.uc.mem_read(BUFFER,0x4000))==bytes(old.m.uc.mem_read(BUFFER,0x4000))
                assert r.native_commands==old.native_commands
                assert [x['mask'] for x in r.waits]==[x['mask'] for x in old.waits]
                assert record(r)['calls']==chunk(r)['completed']+1 and not record(r)['prepared']
                for site,before,after in r.adapter_pairs:
                    exercised.add(site)
                    # Replay changes R1+flags in bounce read, flags in bounce write.
                    ignored={1,15} if site==0x8006a180 else {15} if site==0x8006adac else set()
                    assert all(a==b for i,(a,b) in enumerate(zip(before,after)) if i not in ignored)
                assert all(not x['raw'] and not x['flags'] and not x['tokens'] and
                    x['admission']['prepared'] for x in r.before_store)
                assert not record(r)['fault'] and not r.joins
    assert exercised=={x[0] for x in SITES}
    passed('24_native_direct_bounce_read_write_cases_preserve_payload_commands_waits_and_inline_registers',stack_alignments=[0,4])

    for op in (2,3):
        for reply in (0,2,0xffffffce):
            r=Admission();r.hold_call=1;r.quiet_reply=reply
            r.request(op,9,1);held_before_native(r)
            assert not r.copies and not record(r)['calls']
            r.hold_call=None;assert r.resume()==0 and not r.held
    passed('entry_holds_before_first_native_bounce_fill_cache_or_address_effect_until_exact_source_lease_one')

    for op in (2,3):
        r=Admission();r.hold_call=2
        r.request(op,9,1);held_before_native(r)
        assert len(r.copies)==int(op==3) and record(r)['calls']==1
        r.hold_call=3;r.resume_until_blocked()
        assert r.held and len(r.dma_stores)==1 and chunk(r)['completed']==1
        assert len(r.copies)==(1 if op==2 else 2) and record(r)['calls']==2
        r.hold_call=None;assert r.resume()==0 and not r.held and len(r.dma_stores)==2
    passed('each_split_chunk_holds_before_DS_ADDR_with_prior_chunk_already_joined')

    r=Admission();put32(r.m,IRQ_STATUS,3);put32(r.m,EVENT+8,0x104);put32(r.m,SEM+0x38,1)
    assert r.request(3,9,1)==0
    assert r.quiet_calls[0]['raw']==3
    assert all(x['raw']==x['flags']==x['tokens']==0 for x in r.before_store)
    assert r.native_entries and 0x80076958 in r.executed
    assert word(r.m,ISER)&BIT and not word(r.m,ISPR)&BIT
    passed('real_event_flag_binary_token_and_IRQ_pending_drain_follow_W1C_before_every_address')

    for field,value in ((PRESENT,READY|0x206),(SYSTEM,0x04000000),(PRESENT,8),(PRESENT,0x01000000)):
        r=Admission();put32(r.m,field,value);r.stop_delay=True
        r.request(3,2,1);held_before_native(r)
        assert not r.copies and not r.quiet_calls and not record(r)['fault']
        put32(r.m,PRESENT,READY);put32(r.m,SYSTEM,0);r.stop_delay=False
        assert r.resume()==0 and not r.held
    passed('prior_host_card_reset_and_clock_conditions_hold_entry_without_clearing_or_overwriting_buffers')

    for field,value in ((PROTOCOL,0x220),(PROTOCOL,0),(PROTOCOL,0x10022),
                        (PROTOCOL,0x20022),(IRQ_STATUS,4),(VENDOR2,0x1000),
                        (ISER,BIT|(1<<15)),(ISPR,1<<15),(IRQ_STATUS,0x100000)):
        r=Admission();put32(r.m,field,value);r.stop_delay=True
        r.request(2,2);held_before_native(r)
        assert record(r)['fault'] and not r.quiet_calls
        assert not r.before_store
    passed('unsupported_DMA_modes_second_IRQ_sources_and_existing_raw_errors_fail_closed_before_native_effects')

    for kind in ('task','event','mode','block_gap','activity','reset','error','second_irq'):
        r=Admission();r.stop_delay=True
        def change(r,kind=kind):
            address,value={'task':(TASK,0x2103b100),'event':(0x808e28e0,EVENT+0x100),
                'mode':(PROTOCOL,0x220),'block_gap':(PROTOCOL,0x10022),
                'activity':(PRESENT,READY|0x200),
                'reset':(SYSTEM,0x04000000),'error':(IRQ_STATUS,0x100000),
                'second_irq':(ISER,BIT|(1<<15))}[kind]
            put32(r.m,address,value)
        r.after_quiet=change;r.request(2,2);held_before_native(r)
        assert record(r)['fault'] and not r.before_store
    passed('positive_source_provider_cannot_override_changed_identity_mode_activity_reset_error_or_second_source')

    for kind in ('w1c','pending','tokens'):
        r=Admission();r.stop_delay=True
        if kind=='w1c':r.status_w1c=False;put32(r.m,IRQ_STATUS,2)
        elif kind=='pending':r.reassert_pending=True
        else:
            put32(r.m,SEM+0x38,2) # violates the recovered binary schema
        r.request(2,2);held_before_native(r)
        assert record(r)['fault'] and not r.before_store
    passed('failed_status_pending_IRQ_or_binary_schema_drain_never_reaches_DS_ADDR')

    r=Admission();r.pending=True
    # Restore one address instruction: selecting the port cannot silently admit
    # an unpatched path. The command refuses the missing prepared marker.
    site,_,span=SITES[0]
    r.m.uc.mem_write(site,IMAGE[site-BIAS:site-BIAS+span]);r.m.uc.ctl_remove_cache(site,site+span)
    r.request(2,2)
    assert r.held and r.state()['failed'] and r.joins and not r.native_commands
    assert len(r.dma_stores)==1 and not chunk(r)['completed']
    passed('missing_inline_hook_is_rejected_at_command_entry',
        limitation='The unpatched DS_ADDR already ran: this is installation detection, not protection of that missing hook')

    # Directly execute the candidate host join. Source admission/ownership is
    # deliberately seeded, so these are predicate tests, not a source proof.
    def joined_case(change=None):
        r=Admission();r.held=True
        r.seed(active=1,unit=0,event=EVENT,buffer=BUFFER,bytes=1024)
        r.m.uc.mem_write(r.syms['sdp_admission_state'],struct.pack('<6I',BUFFER,0x80069fec,0x2103b000,0,2,0))
        r.m.uc.mem_write(r.syms['sdp_chunk_state'],struct.pack('<8I',1,23,BUFFER,1024,2,0x2103b000,0,0))
        if change:change(r)
        return r,r.m.invoke(r.syms['sdp_native_chunk_join'],[0,EVENT,BUFFER,1024])
    assert joined_case()[1]==1
    assert joined_case(lambda r:put32(r.m,PRESENT,6))[1]==1
    for change in (lambda r:put32(r.m,PRESENT,0x100),lambda r:put32(r.m,SYSTEM,0x04000000),
        lambda r:put32(r.m,IRQ_STATUS,0x100000),lambda r:put32(r.m,TASK,0x2103b100),
        lambda r:put32(r.m,PROTOCOL,0x220),lambda r:put32(r.m,ISER,BIT|(1<<15)),
        lambda r:put32(r.m,r.syms['sdp_chunk_state']+16,0),
        lambda r:put32(r.m,r.syms['sdp_chunk_admit_port'],0),
        lambda r:put32(r.m,r.syms['sdp_admission_state'],BUFFER+512)):
        assert joined_case(change)[1]==0
    passed('compiled_nominal_host_join_requires_admitted_exact_span_fresh_TC_identity_and_quiet_host_DMA',
        trailing_card_busy_is_separate=True,source_lease_is_MODEL=True)

    for change in (lambda r:put32(r.m,PROTOCOL,0x10022),
                   lambda r:put32(r.m,PROTOCOL,0x20022),
                   lambda r:put32(r.m,r.syms['sdp_chunk_state']+16,6),
                   lambda r:put32(r.m,IRQ_STATUS,4)):
        assert joined_case(change)[1]==0
    passed('TC_cannot_join_a_full_span_with_stop_continue_or_observed_block_gap_even_when_host_is_idle',
           partial_transfer_is_a_model=True)

    r=Admission();r.origin='late prior-origin TC violating MODEL source exclusion'
    assert r.request(2,2)==0
    passed('negative_false_source_lease_can_still_make_late_prior_TC_look_current',physical_source_exclusion_proven=False)

    r=Admission();put32(r.m,r.syms['sdp_chunk_finish_port'],0);r.stop_delay=True
    r.request(3,9,1);held_before_native(r)
    assert not r.copies and record(r)['fault']==11
    passed('admission_without_a_chunk_completion_checkpoint_stays_closed_before_native_effects')

    from verify_capture_io_lifetime import CaptureSd
    class CaptureAdmission(NativePorts,CaptureSd):
        def __init__(self):
            CaptureSd.__init__(self)
            self.native_setup();adapters(self)
            put32(self.m,TASK,0x2103b000)
            put32(self.m,self.syms['sdp_chunk_admit_port'],self.syms['sdp_native_admit']|1)
            put32(self.m,self.syms['sdp_chunk_finish_port'],self.syms['sdp_native_chunk_join']|1)
            self.source_names=[];self.hold_name=None
            self.m.hooks[QUIET]=self.source
        def source(self,args):
            assert self.owner() and self.probe()['active'] and args[:2]==[0,EVENT]
            self.source_names.append((self.current_name,args[3]))
            if self.hold_name==self.current_name:
                self.stalled=True;return stop(self.m)
            return 1 # Explicit MODEL exclusion/ownership, not a joined callback.
    r=CaptureAdmission();r.running()
    for _ in range(10):r.audio_call();r.tick()
    r.stop_recording();r.completed_extra()
    required={'initial_header','audio','final_header','read_header','read_audio'}
    assert required<={name for name,site in r.source_names if site==0}
    assert required<={name for name,site in r.source_names if site!=0}
    assert not r.unit_held and not r.unsafe_close
    passed('unchanged_capture_core_uses_native_admission_and_host_checks_for_metadata_payload_and_readback',
        logical_file_and_sector_routing_are_models=True)

    for name in ('initial_header','audio','final_header','read_audio'):
        r=CaptureAdmission()
        if name=='initial_header':r.hold_name=name;assert r.boot(release=True)==0
        else:
            r.running()
            for _ in range(3):r.audio_call();r.tick()
            r.hold_name=name
            if name!='audio':r.stop_recording()
        for _ in range(32):
            if name=='audio':r.audio_call()
            r.tick()
            if r.stalled:break
        r.retained();before=list(r.native);frame=r.frame()
        assert record(r)['calls']==0 and not chunk(r)['active']
        r.request_cancel()
        assert r.worker_busy()==11 and r.frame()==frame and r.native==before
        r.hold_name=None;r.resume_io();r.stop_after_fault()
        assert not r.unsafe_close
    passed('pending_source_admission_retains_capture_file_frames_and_cancellation_before_first_buffer_effects',logical_cases=4)

    from verify_native_filesystem_sd import NativeFileSd
    from verify_native_filesystem import WRITE,FAT,PARTITION,MIRROR,DIRECTORY,pattern
    class MetadataAdmission(NativePorts,NativeFileSd):
        def __init__(self):
            NativeFileSd.__init__(self);self.native_setup();adapters(self)
            put32(self.m,TASK,0x2103b000)
            put32(self.m,self.syms['sdp_chunk_admit_port'],self.syms['sdp_native_admit']|1)
            put32(self.m,self.syms['sdp_chunk_finish_port'],self.syms['sdp_native_chunk_join']|1)
            self.source_sectors=[];self.m.hooks[QUIET]=self.source
        def source(self,args):
            assert self.owner() and self.probe()['active'] and args[:2]==[0,EVENT]
            self.source_sectors.append((self.current['op'],self.current['sector'],args[3]))
            return 1 # MODEL source/exclusive-span lease, not sector translation.
    r=MetadataAdmission();r.empty();first=pattern(700,131);second=pattern(5000,25)
    assert r.io(WRITE,len(first),first)==(0,len(first))
    assert r.io(WRITE,len(second),second)==(0,len(second)) and r.close()==0
    r.chain=(2,3);assert r.logical()[:5700]==first+second
    assert r.sectors[PARTITION+FAT]==r.sectors[PARTITION+FAT+MIRROR]
    assert struct.unpack_from('<I',r.sectors[PARTITION+DIRECTORY],60)[0]==5700
    metadata={PARTITION+FAT,PARTITION+FAT+MIRROR,PARTITION+DIRECTORY}
    assert metadata<={sector for op,sector,site in r.source_sectors if op==3 and site==0}
    assert metadata<={sector for op,sector,site in r.source_sectors if op==3 and site!=0}
    passed('original_FAT_mirror_directory_and_file_sectors_use_the_same_native_admission_guard',
        stock_filesystem_sector_translation=True,physical_DMA_and_source_lease_are_models=True)

    with ELF.open('rb') as f:
        e=ELFFile(f);functions=[s for s in e.get_section_by_name('.symtab').iter_symbols()
            if s['st_info']['type']=='STT_FUNC' and s['st_shndx']!='SHN_UNDEF' and
            (s.name.startswith('sdp_native_') or s.name in ('sdp_before_address','sdp_admission_begin','admit'))]
        md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
        for s in functions:
            section=e.get_section(s['st_shndx']);offset=(s['st_value']&~1)-section['sh_addr']
            ops=list(md.disasm(section.data()[offset:offset+s['st_size']],s['st_value']&~1))
            assert ops and not any(x.mnemonic.startswith('v') for x in ops),s.name
    passed('compiled_inline_admission_helpers_are_integer_only',functions=[s.name for s in functions])
    report=dict(passed=True,groups=len(checks),results=checks,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),fixture_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        capture_io_fixture_sha256=hashlib.sha256((ROOT/'analysis/capture_io_probe.elf').read_bytes()).hexdigest(),
        test_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        device_access=False,limitations=['Physical source lease, exact buffer/cache ownership and MMIO/NVIC effects remain models.',
            'Native status writes and original event/IRQ/flag/binary-token instructions execute; no physical arbitration or DMA simulation.',
            'Cold entry and all four per-chunk pre-address sites are opt-in test-only; no capture image or device operation.',
            'Nominal host predicate is a candidate under trusted admission, not checked failure recovery or card persistence.',
            'Outer card/USB transition exclusion and actual-chip bus semantics remain deployment gates.'])
    (ROOT/'analysis/sd_chunk_admission_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(checks))))

if __name__=='__main__':main()
