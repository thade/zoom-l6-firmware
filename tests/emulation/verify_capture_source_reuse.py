#!/usr/bin/env python3
"""Original startup consumes DSP input before replacing it with added code.

Separate offline layout. Later DSP-source lifetime/physical cache/source joins
remain unqualified; no hardware access, image or automatic worker release.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from verify_pad_protocol import ROOT,IMAGE,Machine
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_storage_readiness import word
from verify_lz4_packing import startup as scatter
from verify_capture_composed import ComposedBoot
from verify_capture_sd_retained import CombinedRig,NativeRig
from verify_capture_boot_cache import run as continuous
from verify_sd_enumeration_guard import Enumeration
from verify_sd_cold_start import high_speed_card
from verify_capture_integration import IntegrationRig,record as record_audio
from verify_sd_transfer_lifetime import BUFFER
from verify_sd_transfer_probe import Probe
from plan_capture_source_reuse import ELF,plan
from plan_capture_lz4 import packing
from capture_jump_patches import SCATTER,symbols,make_patch,SPECS
from capture_source_reuse_layout import CODE_INTERVAL

PACK=packing(ELF,source_reuse=True);PLAN=plan(PACK);N=symbols(ELF)
GLOBALS=tuple(PLAN['packing']['globals'])

class ReusedBoot(ComposedBoot):
    names=N;packed=PACK;patch_plan=PLAN;global_range=GLOBALS
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.m.uc.hook_add(UC_HOOK_MEM_WRITE,
            lambda u,k,a,n,v,x:self.writes.append((a,n)),begin=GLOBALS[0]-8,end=GLOBALS[1]+15)
    def guard(self):
        source=SCATTER[0]
        for a,n in ((GLOBALS[0]-8,8),(GLOBALS[1],16)):
            assert bytes(self.m.uc.mem_read(a,n))==PACK['source_blob'][a-source:a-source+n]
        assert all(GLOBALS[0]<=a and a+n<=GLOBALS[1] for a,n in self.writes)

class ReusedCapture(CombinedRig):
    elf_path=ELF;patch_plan=PLAN;packed=PACK;candidate_globals=GLOBALS

class ReusedSD(NativeRig):
    elf_path=ELF;names=N;patch_plan=PLAN

class ReusedEnumeration(Enumeration):
    elf_path=ELF;names=N;patch_plan=PLAN

def reject_loader(source,destination,count):
    m=Machine();m.uc.mem_write(SCATTER[0],PACK['source_blob'])
    failed=[];writes=[]
    address=PACK['names']['scatter_lz4_failed']&~1
    m.hooks[address]=lambda a:failed.append(True) or stop(m)
    m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,x:writes.append((a,n)),
                  begin=SCATTER[0],end=SCATTER[0]+SCATTER[2]-1)
    m.invoke(PACK['names']['scatter_lz4'],[source,destination,count])
    assert failed and not writes

def main():
    checks=[]
    def passed(case,**extra):checks.append(dict(case=case,**extra))
    reuse=PLAN['reuse'];j=PACK['jumps']
    assert SCATTER[0]<=reuse['live_loader'][0]<reuse['live_loader'][1]<=reuse['code'][0]
    assert reuse['code'][1]<=reuse['globals'][0]<reuse['globals'][1]<=reuse['unread_code_input'][0]
    assert reuse['consumed_DSP_input'][0]==reuse['code'][0]
    assert reuse['consumed_DSP_input'][1]==reuse['unread_code_input'][0]
    assert reuse['unread_code_input'][1]<=SCATTER[0]+SCATTER[2]
    assert PLAN['packing']['spare_bytes']>0 and not reuse['additional_code_or_global_gap_bytes']
    # Existing planners still reject the lower target unless this experiment
    # explicitly selects its separate interval.
    target=N[SPECS[0]['adapter']]
    try:make_patch(IMAGE,SPECS[0],target)
    except ValueError:pass
    else:raise AssertionError('default planner accepted reused-source target')
    assert make_patch(IMAGE,SPECS[0],target,code_interval=CODE_INTERVAL)
    passed('explicit_reuse_geometry_excludes_live_loader_unread_code_input_and_all_proposed_RAM_gaps',reuse=reuse)

    loaded=scatter(pack=PACK)
    assert len(loaded['hashes'])==8 and len(loaded['helpers'])==10
    passed('original_reset_and_full_scatter_expand_DSP_then_code_then_zero_globals_with_exact_original_destinations',**loaded)
    assert scatter(corrupt=True,pack=PACK)==dict(stopped_before_Main=True)
    passed('bad_code_header_halts_after_DSP_expansion_before_Main_or_partial_added_code_use')

    # Validate the loader's runtime destination restrictions independently of
    # the host planner: helper/code-input/global addresses are never targets.
    for destination,count in ((SCATTER[0],64),(CODE_INTERVAL[0]-4,64),
          (GLOBALS[0],64),(CODE_INTERVAL[0],GLOBALS[0]-CODE_INTERVAL[0]+1),
          (0x20220000,SCATTER[2]-1),(0xfffffff0,64)):
        reject_loader(PACK['code_source'],destination,count)
    reject_loader(CODE_INTERVAL[0],CODE_INTERVAL[0],len(PACK['code']))
    passed('compiled_loader_rejects_live_helper_unread_input_wrong_destinations_and_lengths_before_reused_area_writes')

    for ccr in (0,0x30000):
        result=continuous(ccr,boot_factory=ReusedBoot,pack=PACK,names=N,globals_range=GLOBALS)
        assert result['worker_waiting'] and not result['capture_released']
        passed('continuous_reused_source_startup_cache_MPU_and_native_registration',**result)
    result=continuous(0x30000,corrupt=True,boot_factory=ReusedBoot,pack=PACK,names=N,globals_range=GLOBALS)
    passed('continuous_corrupt_reused_source_stops_before_cache_and_added_code',**result)

    base=record_audio(IntegrationRig(enabled=False),delay=2,blocks=23)
    r=ReusedCapture();assert r.boot(release=True)==0;r.ready();r.sequence=0
    assert record_audio(r,delay=2,blocks=23)==base;r.extra()
    assert len(r.disk)==1 and not r.opened
    passed('relocated_code_and_globals_preserve_seven_ordinary_files_and_exact_extra_TMP_after_explicit_model_release')

    for op in (2,3):
        for count,offset in ((2,0),(2,4),(9,1)):
            baseline=Probe();assert baseline.request(op,count,offset)==0
            r=ReusedSD();assert r.request(op,count,offset)==0
            assert not r.held and not r.state()['failed'] and not r.model_entries
            assert r.native_commands==baseline.native_commands
            assert bytes(r.m.uc.mem_read(BUFFER,0x4000))==bytes(baseline.m.uc.mem_read(BUFFER,0x4000))
        r=ReusedSD(source=False);r.stop_delay=True;r.request(op,9,1)
        assert r.held and not r.copies and not r.dma_stores
    passed('relocated_native_direct_and_bounce_SD_guards_preserve_data_and_still_require_source_permission')

    r=high_speed_card(ReusedEnumeration());assert r.enumerate()==0 and r.pio_number==6
    r=high_speed_card(ReusedEnumeration());r.stop_delays=True
    r.injection=lambda mask,raw:(0,0x104) if mask==0x185 else (raw,0)
    r.enumerate();r.held_fault()
    passed('relocated_startup_guard_completes_traced_negotiation_and_retains_mixed_error_notification')

    out=ROOT/'analysis/capture_source_reuse_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,plan=PLAN,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),device_access=False,
        limitations=PLAN['limitations']+[
            'Startup, capture and SD checks are bounded separate harnesses; not concurrent whole-board execution.',
            'Card, DMA/cache effects, source permission, scheduler and kernel task creation remain models.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),spare_bytes=PLAN['packing']['spare_bytes'],report=str(out))))

if __name__=='__main__':main()
