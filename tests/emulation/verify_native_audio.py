#!/usr/bin/env python3
"""Compiled audio completion hooks with full original callbacks on one CPU."""
import json
import struct
from unicorn import UC_HOOK_CODE, UC_PROT_NONE
from unicorn import arm_const as A
from verify_pad_reader_audit import AuditRig, TARGETS, SELECTOR, SECONDARY
from verify_pad_renderer_boundary import AUDIO
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, IMAGE, BIAS, RETURN
from verify_scheduling_boundaries import stop
from verify_read_worker import CURRENT
from verify_overdub_prototype import Emulator

C=0x2103a000
OUT=C+0x200
AID=0x7040
OK,BUSY,INVALID,FAULT=0,1,4,6


class NativeAudio(AuditRig):
    def __init__(self,bind=True):
        super().__init__();self.enabled=True
        # ARM MAX cannot execute M-profile MRS IPSR. Only this context probe
        # is modeled here; a separate Cortex-M7 check executes it unmodified.
        self.m.hooks[self.m.symbols['na_thread_context']&~1]=lambda a:1
        put32(self.m,0x80446d78,AID);put32(self.m,CURRENT,AID)
        for address,name in ((0x8001078a,'na_entry_hook'),(0x8001078e,'na_return_hook')):
            def redirect(uc,a,n,u,name=name):
                if self.enabled:uc.reg_write(A.UC_ARM_REG_PC,self.m.symbols[name]|1)
            self.m.uc.hook_add(UC_HOOK_CODE,redirect,begin=address,end=address)
        # Output continuation is outside the completion boundary. Replay its
        # BL/LR semantics but model its effects; all selected DSP bodies run.
        self.m.hooks[0x80010150]=lambda a:None
        if bind:assert self.m.invoke(self.m.symbols['na_bind'],[C,AID])==OK
    def oc(self,name,*args):return self.m.invoke(self.m.symbols['oc_'+name],[C,*args])
    def request(self):
        assert self.oc('close',OUT)==OK;epoch=self.word(OUT)
        assert self.oc('audio_request',epoch)==OK;return epoch
    def full(self,target=TARGETS[0],select=True):
        self.access=[];self.markers=[];self.entries=[]
        if select:put32(self.m,SELECTOR,target|1)
        self.window(0x8001077c,0x80010792)


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    row=struct.unpack_from('<6I',IMAGE,0x800a1bec-BIAS)
    assert row[0]==0x80010939 and row[5]==0x80446d78
    assert IMAGE[row[1]-BIAS:].split(b'\0',1)[0]==b'AudioProcess'
    passed('native_AudioProcess_descriptor_and_identity_word_verified')

    m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True)
    assert m.invoke(m.symbols['na_thread_context'],[])==1
    passed('Cortex_M7_executes_original_MRS_IPSR_thread_context_probe')

    for target in TARGETS:
        r=NativeAudio();epoch=r.request();r.seed(length=17)
        assert r.oc('audio_poll',epoch)==BUSY
        r.full(target)
        assert r.entries[0]==target and r.oc('audio_poll',epoch)==OK
    passed('compiled_hooks_acknowledge_all_four_full_original_callbacks_on_the_same_CPU')

    r=NativeAudio();r.seed(length=17)
    # Pause the real callback after its pad renderer but before later DSP ends.
    h=r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:stop(r.m),begin=0x2022a796,end=0x2022a796)
    r.full();saved=r.m.uc.context_save();r.m.uc.hook_del(h)
    old_stack=r.m.stack;r.m.stack=0x20030000;epoch=r.request();r.m.stack=old_stack
    h=r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:stop(r.m),begin=0x80010792,end=0x80010792)
    r.m.uc.context_restore(saved);r.m.reached_return=False
    r.m.uc.emu_start(r.m.uc.reg_read(A.UC_ARM_REG_PC)|1,RETURN+2,count=10000000)
    r.m.uc.hook_del(h)
    assert r.oc('audio_poll',epoch)==BUSY
    r.full();assert r.oc('audio_poll',epoch)==OK
    passed('request_during_original_callback_waits_for_a_new_whole_callback')

    r=NativeAudio();epoch=r.request()
    put32(r.m,SELECTOR,TARGETS[0]|1)
    r.window(0x8001077c,0x8001078c)
    assert r.oc('audio_poll',epoch)==BUSY
    r.m.invoke(r.m.symbols['na_begin'],[TARGETS[0]|1])
    assert r.oc('audio_poll',epoch)==FAULT
    passed('missing_return_retains_pending_completion_and_nested_entry_latches_fault')

    r=NativeAudio();epoch=r.request();put32(r.m,SELECTOR,0);r.full(select=False)
    assert not r.entries and r.oc('audio_poll',epoch)==BUSY
    r.full();assert r.oc('audio_poll',epoch)==OK
    passed('null_callback_never_supplies_completion_and_later_real_callback_can_acknowledge')

    for address,value in ((SELECTOR,TARGETS[3]|1),(SECONDARY,0)):
        r=NativeAudio();epoch=r.request()
        def changed(uc,a,n,u):put32(r.m,address,value)
        h=r.m.uc.hook_add(UC_HOOK_CODE,changed,begin=0x2022a796,end=0x2022a796)
        r.full();assert r.oc('audio_poll',epoch)==FAULT
    passed('changed_primary_or_secondary_selection_rejects_callback_completion')

    r=NativeAudio();epoch=r.request();r.seed(length=128,loop=1)
    r.full();assert r.oc('audio_poll',epoch)==OK and len(r.samples())==128
    r.full();assert len(r.samples())==128
    passed('negative_control_completion_alone_does_not_stop_later_looping_pad_reads')

    r=NativeAudio();r.seed(length=17);r.full()
    epoch=r.request();r.full();assert r.oc('audio_poll',epoch)==OK
    r.m.uc.mem_protect(0x21028000,0x1000,UC_PROT_NONE)
    for target in TARGETS*2:
        r.full(target);assert not r.samples() and r.oc('audio_poll',epoch)==OK
    passed('naturally_inactive_buffer_remains_unread_on_tested_paths_after_actual_completion')

    for address in (CURRENT,0x80446d78):
        r=NativeAudio();epoch=r.request();put32(r.m,address,AID+1)
        r.full();assert r.oc('audio_poll',epoch)==FAULT
    passed('wrong_task_or_changed_native_handle_faults_without_acknowledging')

    r=NativeAudio();epoch=r.request()
    r.m.hooks[r.m.symbols['na_thread_context']&~1]=lambda a:0
    r.full();assert r.oc('audio_poll',epoch)==FAULT
    r=NativeAudio();epoch=r.request();r.full()
    r.m.invoke(r.m.symbols['na_end'],[]);assert r.oc('audio_poll',epoch)==FAULT
    passed('interrupt_context_and_duplicate_return_cannot_supply_valid_completion')

    r=NativeAudio();epoch=r.request();put32(r.m,C,1)
    r.full();put32(r.m,C,0)
    assert r.oc('audio_poll',epoch)==OK
    passed('audio_observer_never_waits_for_the_control_metadata_lock')

    # Compare hook boundaries with unmodified dispatch, including all live FP
    # registers/status and the displaced continuation BL's link register.
    regs=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(13)]
    fp=[getattr(A,'UC_ARM_REG_S'+str(i)) for i in range(32)]
    allregs=regs+fp+[A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR]
    for start,end in ((0x8001078a,0x8001078c),(0x8001078e,0x80010792)):
        for alignment in (0,4):
            snapshots=[]
            for enabled in (False,True):
                r=NativeAudio();r.enabled=enabled;r.m.stack-=alignment
                for i,reg in enumerate(regs):r.m.uc.reg_write(reg,0x12340000+i*0x101)
                r.m.uc.reg_write(A.UC_ARM_REG_R0,TARGETS[0]|1)
                for i,reg in enumerate(fp):r.m.uc.reg_write(reg,0x3f000000+i*123)
                r.m.uc.reg_write(A.UC_ARM_REG_APSR,0xa80f0000)
                r.m.uc.reg_write(A.UC_ARM_REG_FPSCR,0x01400000)
                r.window(start,end)
                snapshots.append([r.m.uc.reg_read(reg) for reg in allregs])
            assert snapshots[0]==snapshots[1]
    passed('entry_and_return_hooks_preserve_integer_FP_flags_stack_and_original_BL_for_both_stack_alignments')

    r=NativeAudio(bind=False);assert r.m.invoke(r.m.symbols['na_bind'],[C,AID+1])==INVALID
    put32(r.m,C,1);assert r.m.invoke(r.m.symbols['na_bind'],[C,AID])==BUSY
    put32(r.m,C,0);assert r.m.invoke(r.m.symbols['na_bind'],[C,AID])==OK
    assert r.m.invoke(r.m.symbols['na_bind'],[C,AID])==INVALID
    passed('cold_binding_rejects_wrong_identity_busy_state_and_replacement')

    out=ROOT/'analysis/native_audio_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Compiled observer and all four original callback bodies share one ARM MAX emulator CPU',
        'ARM MAX supplies stock double-precision instruction coverage; not device chipset identification',
        'ARM MAX thread-context probe is a fixture; a separate Cortex-M7 test executes MRS IPSR unmodified',
        'Hook redirection, native task identity and input/routing memory are fixtures; output continuation effects are modeled',
        'Acknowledgment is a past completion barrier, not persistent exclusion of future pad readers',
        'Capture uses the same hook sites; observers must be composed before installation',
        'No device access, physical timing, cache/DMA proof or installed firmware patch']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
