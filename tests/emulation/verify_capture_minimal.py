#!/usr/bin/env python3
"""Separate minimal linked build: real hooks/native files, all offline."""
import hashlib,json
from verify_capture_hooks import (HooksRig,NativeCapture,failed,Boot,control_continuations,dsp_continuations,
    queue_arguments,native_queue_fifo,queue_fixture_rejects_bad_arguments)
from verify_capture_integration import IntegrationRig,record
from verify_native_storage_setup import FolderTree,FolderTreeSd
from verify_capture_native_files import UI,FS1
from verify_control_transport import TASK
from verify_record_scheduler import word
from verify_pad_protocol import ROOT,IMAGE
from verify_session_manager import STOPPED
from capture_jump_patches import symbols
from plan_capture_hooks import plan
from plan_capture_packing import packing

ELF=ROOT/'src/capture/capture-only-minimal.elf'
PLAN=plan(ELF);PACK=packing(ELF)
class MinimalRig(HooksRig):
    elf_path=ELF
    patch_plan=PLAN
    packed=PACK
class MinimalCapture(NativeCapture,MinimalRig):
    pass

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    names=symbols(ELF);full=symbols(ROOT/'src/capture/capture-only-hooks.elf')
    omitted=('ct_init','ct_scope','ct_request_op','native_worker_bind_audio','bridge_bind',
        'bridge_publish','bridge_route_scope','bridge_retire_quiesced','manager_init',
        'manager_hold_publication','rr_released')
    assert all(n in full and n not in names for n in omitted)
    assert all(p['adapter'] in names for p in PLAN['patches']+PLAN['DSP_patches'])
    assert PLAN['packing']['spare_bytes']>2500
    assert PLAN['packing']['globals']==[0x80960080,0x809600e0]
    assert not any(n.startswith(('backing_','bn_','na_','sdp_','history_','audio_fixture_')) for n in names)
    passed('minimal_link_removes_unreachable_research_APIs_keeps_all_patch_roots_and_has_more_than_2500_packed_bytes_spare',
           code_bytes=len(PACK['code']),packed_code_bytes=len(PACK['packed_code']),
           spare_bytes=PLAN['packing']['spare_bytes'],omitted_examples=list(omitted))

    passed('minimal_control_adapters_reach_exact_plan_resumes',comparisons=control_continuations(MinimalRig))
    passed('minimal_DSP_adapters_match_stock_at_exact_plan_resumes',comparisons=dsp_continuations(MinimalRig))
    passed('minimal_common_sender_preserves_all_four_kernel_arguments',comparisons=queue_arguments(MinimalRig))
    passed('minimal_original_kernel_queue_preserves_FIFO_without_assertion',comparisons=native_queue_fifo(MinimalRig))
    passed('minimal_queue_fixture_rejects_unsupported_arguments',rejected=queue_fixture_rejects_bad_arguments(MinimalRig))

    b=Boot(pack=PACK,names=names,patches=PLAN['patches']);b.boot();b.guard()
    assert b.optional_calls==1 and b.kernel_entered and b.word(0x80962688)==4
    passed('original_boot_with_minimal_hooks_registers_sleeping_worker_without_storage_or_extra_file')

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    for fs in (FolderTree,FolderTreeSd):
        r=MinimalCapture(filesystem=fs)
        assert r.fs.setup_card()==0 and r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        extra=r.completed_extra();assert len(extra)==13312
        assert not any(n.startswith('emulator_') for n in r.entries)
        passed('minimal_link_actual_hooks_and_native_folder_mount_capture_'+fs.__name__,frames=1600,
               extra_bytes=len(extra),extra_sha256=hashlib.sha256(extra).hexdigest())

    r=MinimalCapture(filesystem=FolderTree);assert r.fs.setup_card()==0
    assert r.boot(release=True)==0;r.ready();r.begin_recording();r.audio_call();r.tick()
    r.cancel();r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert not r.life('life_verified_path') and not r.opened and r.locks.tokens=={UI}
    before=len(r.expected[7]);r.audio_call()
    assert len(r.expected[7])>before and r.locks.tokens=={UI}
    passed('minimal_link_cancellation_closes_optional_file_and_allows_ordinary_audio_to_continue')

    r=MinimalCapture(filesystem=FolderTreeSd);assert r.fs.setup_card()==0
    assert r.boot(release=True)==0;r.ready();r.begin_recording(delay=2)
    sector=r.fs.physical(9,1);r.fs.inject=(3,sector,'data')
    for _ in range(12):
        r.audio_call();r.tick()
        if r.fs.stalled:break
    assert r.fs.stalled;r.retained((UI,FS1));frame=r.fs.frame();requests=list(r.fs.requests)
    r.resume_sd();r.retained((UI,FS1));assert r.fs.frame()==frame and r.fs.requests==requests
    r.other_task(word(r.m,TASK),r.audio_call)
    r.other_task(word(r.m,TASK),r.stop_recording)
    assert r.fs.frame()==frame and r.fs.requests==requests
    r.fs.join_allowed=True;r.resume_sd();failed(r)
    assert not r.fs.owner()
    passed('minimal_link_retains_failed_native_SD_stack_and_buffers_while_ordinary_audio_STOP_continue')

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        minimal_elf_sha256=PLAN['hooks_elf_sha256'],packing=PLAN['packing'],
        limitations=PLAN['limitations']+['Minimal link changes retained entry points only; explicit emulator observation roots remain.',
            'No production storage/SD completion binding, startup release, physical placement or device timing evidence.'])
    (ROOT/'analysis/capture_minimal_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    (ROOT/'analysis/capture_minimal_plan.json').write_text(json.dumps(PLAN,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
