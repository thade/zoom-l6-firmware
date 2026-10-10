#!/usr/bin/env python3
"""One linked capture/Main/SD artifact, offline only.

Startup, capture and SD paths share code/placement but have bounded separate
harnesses. This is not a concurrent physical eight-stream card simulation.
Kernel scheduling, IRQ delivery, source ownership and DMA remain models.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from elftools.elf.elffile import ELFFile
from plan_capture_sd_retained import ELF,SD_SPECS,plan
from plan_capture_lz4 import packing
from plan_capture_hooks import make_patch
from capture_jump_patches import symbols
from verify_lz4_packing import startup as scatter
from verify_capture_composed import ComposedBoot
from verify_storage_lease import LeaseRig,Pending
from verify_storage_main import MainRig,LATER
from verify_storage_stop import finish_storage
from verify_session_manager import STOPPED
from verify_capture_integration import IntegrationRig,record as record_audio
from verify_sd_chunk_admission import Admission,QUIET,record,held_before_native
from verify_sd_chunk_guard import chunk
from verify_sd_transfer_probe import Probe
from verify_sd_transfer_lifetime import BUFFER,EVENT
from verify_pad_protocol import ROOT,IMAGE,REGS,RETURN
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop

PACK=packing(ELF);PLAN=plan(PACK);N=symbols(ELF)
GLOBALS=tuple(PLAN['packing']['globals'])

class CombinedBoot(ComposedBoot):
    names=N;packed=PACK;patch_plan=PLAN;global_range=GLOBALS

class CombinedRig(LeaseRig):
    sd_retained_fixture=True
    elf_path=ELF;patch_plan=PLAN;packed=PACK;candidate_globals=GLOBALS

class CombinedMain(MainRig):
    sd_retained_fixture=True
    elf_path=ELF;patch_plan=PLAN;packed=PACK;candidate_globals=GLOBALS

class CombinedPending(Pending,CombinedMain):pass

class NativeRig(Admission):
    elf_path=ELF
    names=N;patch_plan=PLAN
    def install_probe(self):
        for p in self.patch_plan['patches']:
            if p.get('adapter','').startswith('sdp_'):
                self.m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
                self.m.uc.ctl_remove_cache(p['site'],p['site']+len(bytes.fromhex(p['patch'])))
    def install_adapters(self):pass # Actual in-range B.W patches, no near veneers.
    def __init__(self,aligned=0,source=True):
        N=self.names
        super().__init__(aligned)
        if source:put32(self.m,N['sdp_source_port'],QUIET|1)
        self.irq_context=None;self.returning_irq=False;self.model_entries=[]
        self.m.uc.mem_write(0x2102bf00,b'\x00\xbf')
        def schedule(u,pc,size,data):
            if pc==0x2102bf00:
                assert self.irq_context is not None
                u.context_restore(self.irq_context);self.irq_context=None
                u.reg_write(A.UC_ARM_REG_PC,u.reg_read(A.UC_ARM_REG_PC)|1)
                self.returning_irq=True
            elif pc==0x800326c0:
                if self.returning_irq:
                    self.returning_irq=False;return
                # Host fixture supplies IRQ timing. The original IRQ and event
                # code execute; the compiled guard contains no delivery port.
                args=[u.reg_read(r) for r in REGS[:4]]
                args.append(word(self.m,u.reg_read(A.UC_ARM_REG_SP)))
                if self.deliver([args[0],args[1],args[4]]):
                    self.irq_context=u.context_save()
                    u.reg_write(REGS[0],0);u.reg_write(A.UC_ARM_REG_LR,0x2102bf01)
                    u.reg_write(A.UC_ARM_REG_PC,0x8006ea99)
            if 0x2102bd00<=pc<0x2102be00:
                self.model_entries.append(pc)
                raise AssertionError('combined guard entered removed recovery/delivery model')
        self.m.uc.hook_add(UC_HOOK_CODE,schedule)

def main():
    cases=[]
    def passed(case,**details):cases.append(dict(case=case,**details))
    assert not any(n.startswith(('sdp_stop_','sdp_recovery_')) for n in N)
    assert 'sdp_join_port' not in N and 'sdp_finish_port' not in N
    assert PLAN['packing']['spare_bytes']>0
    assert PLAN['stock_decoder_spare_bytes']<0
    with ELF.open('rb') as f:
        e=ELFFile(f)
        assert all(not s['p_filesz'] for s in e.iter_segments()
            if s['p_type']=='PT_LOAD' and s['p_vaddr']==GLOBALS[0])
    for spec in SD_SPECS:
        bad=bytearray(IMAGE);bad[spec['site']-0x80000e00]^=1
        for stock,target in ((bad,N[spec['adapter']]),(IMAGE,N[spec['adapter']]&~1)):
            try:make_patch(stock,spec,target)
            except ValueError:pass
            else:raise AssertionError('bad combined patch accepted')
    passed('combined_link_has_byte_checked_nonoverlapping_hooks_zero_globals_and_no_recovery_ports',
        raw_code_bytes=PLAN['raw_code_bytes'],globals_bytes=PLAN['globals_bytes'],
        stock_decoder_spare_bytes=PLAN['stock_decoder_spare_bytes'],
        lz4_spare_bytes=PLAN['packing']['spare_bytes'])

    result=scatter(pack=PACK)
    assert len(result['hashes'])==8 and len(result['helpers'])==10
    assert scatter(corrupt=True,pack=PACK)==dict(stopped_before_Main=True)
    passed('original_scatter_initializes_exact_combined_code_and_original_regions_and_rejects_corrupt_size')

    b=CombinedBoot();b.boot();b.guard()
    assert b.kernel_entered and b.optional_calls==1 and b.word(b.worker+8)==4
    assert b.word(b.arena()+4)==9887
    for name in ('sdp_source_port','sdp_chunk_admit_port','sdp_chunk_finish_port','sdp_cache_read_port'):
        assert b.word(N[name])==0
    assert b.word(N['ct_active'])==b.word(N['emulator_bridge_current'])==0
    delays=[]
    b.m.hooks[0x800770e8]=lambda a:b.word(b.worker+4)
    def delay(a):
        delays.append(a[0]);return stop(b.m) if len(delays)==5 else 0
    b.m.hooks[0x80074158]=delay
    b.m.invoke(N['native_worker_entry'],[b.worker]);b.guard()
    assert delays==[25]*5 and b.word(b.worker+16)==0
    passed('compiled_combined_startup_allocates_same_arena_and_worker_sleeps_with_all_SD_permissions_absent')

    # Compare the capture behavior after explicit MODEL release. This remains
    # the logical file backend, not physical card contention with SD below.
    base=record_audio(IntegrationRig(enabled=False),delay=2,blocks=23)
    r=CombinedRig();assert r.boot(release=True)==0
    r.ready();r.sequence=0
    assert record_audio(r,delay=2,blocks=23)==base
    r.extra()
    assert len(r.disk)==1 and not r.opened
    passed('same_combined_artifact_preserves_seven_ordinary_files_and_finishes_extra_TMP_after_model_release')

    r=CombinedPending();assert r.boot(release=True)==0;r.ready();r.begin_recording()
    for _ in range(5):r.audio_call();r.tick()
    r.pause='audio';r.wait_pending(audio=True)
    frame=r.frame();calls=list(r.calls)
    r.install(3);r.ui_setup([(0,9,0x32,0,0),LATER]);r.run_main()
    assert r.waiting=='join' and r.packets()==[LATER] and not r.transition_events
    assert r.frame()==frame and r.calls==calls
    r.complete();finish_storage(r);r.resume_main()
    assert r.waiting=='empty' and r.transition_events and r.lstate()==3
    passed('combined_Main_retains_USB_request_and_FIFO_while_capture_write_is_pending')

    # Actual compiled SD code with externally delivered original IRQs.
    for align in (0,4):
        for op in (2,3):
            for count,offset in ((1,0),(2,0),(2,4),(2,1),(9,1),(9,0)):
                old=Probe();assert old.request(op,count,offset)==0
                r=NativeRig(align);assert r.request(op,count,offset)==0
                assert not r.held and not r.state()['failed'] and not r.model_entries
                assert r.native_commands==old.native_commands
                assert bytes(r.m.uc.mem_read(BUFFER,0x4000))==bytes(old.m.uc.mem_read(BUFFER,0x4000))
                assert record(r)['calls']==chunk(r)['completed']+1
                assert all(not x['raw'] and not x['flags'] and not x['tokens'] for x in r.before_store)
    passed('24_native_SD_cases_preserve_data_commands_and_chunk_draining_with_actual_in_range_patches',
        source_permission='positive explicit model; not physical source proof')

    for missing in ('source','admission','completion'):
        r=NativeRig(source=False);r.stop_delay=True
        if missing!='source':put32(r.m,N['sdp_source_port'],QUIET|1)
        if missing=='admission':put32(r.m,N['sdp_chunk_admit_port'],0)
        if missing=='completion':put32(r.m,N['sdp_chunk_finish_port'],0)
        r.request(3,9,1);held_before_native(r)
        assert not r.copies and not r.dma_stores and not r.model_entries
    passed('missing_source_admission_or_completion_holds_before_any_native_buffer_or_address_effect')

    for op in (2,3):
        r=NativeRig();r.hold_call=3;r.request(op,9,1)
        assert r.held and len(r.dma_stores)==1 and chunk(r)['completed']==1
        r.hold_call=None;assert r.resume()==0 and not r.held
        for mask in (0x183,0x185):
            for kind in ('hidden_error','error','timeout'):
                r=NativeRig();r.stop_delay=True;r.fault=(mask,kind);r.request(op,9,1)
                assert r.held and r.state()['failed'] and not r.state()['finished']
                assert not r.joins and not r.model_entries
                before=(list(r.copies),list(r.native_commands),list(r.dma_stores))
                for _ in range(3):r.resume_until_blocked()
                assert before==(r.copies,r.native_commands,r.dma_stores)
                assert r.held and not r.state()['joined']
    passed('split_transfer_admission_can_resume_but_faults_retain_frames_without_recovery_or_later_buffer_reuse')

    for op in (2,3):
        for stop_mode in ('gap_status','stop_request','continue_request'):
            r=NativeRig();r.stop_delay=True
            deliver=r.deliver
            def partial(args,deliver=deliver,stop_mode=stop_mode):
                status=deliver(args)
                if args[1]==0x185:
                    if stop_mode=='gap_status':
                        put32(r.m,0x402c0030,word(r.m,0x402c0030)|4)
                    else:
                        put32(r.m,0x402c0028,word(r.m,0x402c0028)|
                              (0x10000 if stop_mode=='stop_request' else 0x20000))
                return status
            r.deliver=partial;r.request(op,9,1)
            assert r.held and chunk(r)['active'] and not chunk(r)['completed']
            assert len(r.dma_stores)==1 and len(r.copies)==int(op==3)
            before=(list(r.copies),list(r.native_commands),list(r.dma_stores))
            # Later quiet registers cannot undo observed partial-transfer state.
            put32(r.m,0x402c0028,0x22);put32(r.m,0x402c0030,0)
            for _ in range(3):r.resume_until_blocked()
            assert before==(r.copies,r.native_commands,r.dma_stores)
            assert r.held and not r.state()['finished'] and not r.joins
    passed('partial_block_gap_completion_retains_read_write_frames_before_copy_refill_or_next_address',
           completion_and_gap_conditions_injected=True)

    r=NativeRig();r.origin='late old IRQ despite lying source model'
    assert r.request(2,2)==0
    passed('negative_control_still_rejects_any_claim_that_linking_establishes_physical_source_identity',
        physical_source_exclusion_proven=False)
    out=ROOT/'analysis/capture_sd_retained_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),plan=PLAN,
        limitations=PLAN['limitations']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),lz4_spare_bytes=PLAN['packing']['spare_bytes'],report=str(out))))

if __name__=='__main__':main()
