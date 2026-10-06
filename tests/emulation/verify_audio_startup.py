#!/usr/bin/env python3
"""Closed capture boot -> shared-hook activation -> native worker release.

Compiled components on one CPU; explicit Main release is a readiness fixture,
not a recovered production storage-admission or firmware-installation hook.
"""
import json
import struct
from unicorn import UC_HOOK_CODE, UC_PROT_NONE, UC_PROT_ALL
from unicorn import arm_const as A
from verify_native_worker import WorkerRig, WORKER, CONFIG, SCHEDULER, MAIN_SLOT, MAIN_HANDLE
from verify_manager_boot import MAN, DESC, STATE, SLOTS
from verify_control_transport import TASK
from verify_native_audio import C, AID
from verify_pad_reader_audit import SECONDARY
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, RETURN
from verify_scheduling_boundaries import stop

PORT=0x21038000


class Rig(WorkerRig):
    outer_hook=None
    audio_boundary_hooks=('na_entry_hook','na_return_hook')
    def word(self,address):return struct.unpack('<I',self.raw(address,4))[0]
    def __init__(self):
        super().__init__()
        self.original_audio=self.audio_call;self.audio_call=self.audio
        put32(self.m,0x80446d78,AID);put32(self.m,SECONDARY,0x2022a789)
        self.m.uc.mem_write(PORT,struct.pack('<5I',*[self.m.symbols[s] for s in
            ('na_prepare','na_arm','na_ready')],C,AID))
    def audio(self,*args,**kwargs):
        old=self.word(TASK);put32(self.m,TASK,AID)
        try:return self.original_audio(*args,**kwargs)
        finally:put32(self.m,TASK,old)
    def boot(self,bind=True):
        self.m.uc.mem_write(self.m.stack,struct.pack('<2I',0,1))
        s=self.m.invoke(self.syms['native_worker_register'],[WORKER,MAN,DESC,CONFIG])
        if s:return s
        return self.bind_audio() if bind else 0
    def bind_audio(self):return self.m.invoke(self.syms['native_worker_bind_audio'],[WORKER,PORT])
    def audio_ready(self):return self.m.invoke(self.m.symbols['na_ready'],[])
    def start(self):
        assert self.boot()==0;put32(self.m,SCHEDULER,1)
        assert self.release()==11
        self.audio_call();assert self.release()==0


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    r=Rig()
    # Both before manager boot and after dormant binding, capture arenas are
    # deliberately dirty and inaccessible while ordinary callbacks continue.
    for booted in (False,True):
        if booted:assert r.boot()==0
        r.m.uc.mem_protect(STATE,0x20000,UC_PROT_NONE)
        r.m.uc.mem_protect(SLOTS,0x20000,UC_PROT_NONE)
        for callback in (0x2022a791,0,0x80010961):r.audio_call(callback=callback)
        r.m.uc.mem_protect(STATE,0x20000,UC_PROT_ALL)
        r.m.uc.mem_protect(SLOTS,0x20000,UC_PROT_ALL)
        assert not r.calls and r.word(C+348)==0 and r.word(C+352)==0
    put32(r.m,SCHEDULER,1);assert r.release()==11
    before=r.raw(MAN,r.mlayout[0]);assert r.loops(3)==[25]*3
    assert r.raw(MAN,r.mlayout[0])==before and not r.calls
    r.audio_call();assert r.audio_ready()==0 and r.release()==0
    r.ready();first=r.take(2);second=r.take(3)
    assert bytes(r.disk[first[1]])==first[2] and r.result()==second[:2]
    passed('early_callbacks_skip_dirty_storage_then_first_whole_callback_releases_worker_for_two_exact_takes')

    r=Rig();assert r.boot()==0;put32(r.m,SCHEDULER,1)
    put32(r.m,TASK,AID);r.m.uc.reg_write(A.UC_ARM_REG_R0,0x2022a791)
    r.window(0x8001078a,0x8001078c)
    saved=r.m.uc.context_save();stack=r.m.stack;r.m.stack=0x20030000
    assert r.release()==11
    r.m.stack=stack;r.m.uc.context_restore(saved)
    h=r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:stop(r.m),begin=0x80010792,end=0x80010792)
    r.m.uc.emu_start(0x8001078d,RETURN+2,count=10000000);r.m.uc.hook_del(h)
    assert r.audio_ready()==1 and r.word(C+348)==0 and r.word(C+352)==0
    assert r.release()==11
    r.audio_call();assert r.release()==0
    passed('arming_during_preexisting_dormant_callback_ignores_its_return_and_waits_for_new_entry')

    r=Rig();assert r.boot()==0;put32(r.m,SCHEDULER,1);assert r.release()==11
    r.audio_call(callback=0);assert r.audio_ready()==1 and r.release()==11
    r.audio_call();assert r.release()==0 and r.release()==12
    passed('null_callback_and_duplicate_release_cannot_bypass_first_complete_invocation')

    r=Rig();assert r.boot()==0;put32(r.m,SCHEDULER,1);assert r.release()==11
    put32(r.m,TASK,AID);r.m.uc.reg_write(A.UC_ARM_REG_R0,0x2022a791)
    r.window(0x8001078a,0x8001078c)
    r.m.stack=0x20030000
    assert r.audio_ready()==1 and r.release()==11 and not r.calls
    assert r.word(r.syms['bridge_audio_calls'])==1
    passed('missing_first_return_keeps_worker_waiting_without_file_preparation')

    for reason in ('identity','gateway','dirty_control'):
        r=Rig();assert r.boot(bind=False)==0
        if reason=='identity':put32(r.m,PORT+16,AID+1)
        elif reason=='gateway':put32(r.m,r.syms['bridge_gateway_readers'],0x80000001)
        else:put32(r.m,C,1)
        assert r.bind_audio()==13 and r.word(WORKER+r.wlayout[2])==3
        put32(r.m,SCHEDULER,1);assert r.release()==12
        assert r.loops(2)==[25,25] and not r.calls
        r.audio_call();assert not r.calls
    passed('failed_shared_prepare_permanently_disables_worker_and_never_prepares_files')

    r=Rig();r.m.hooks[0x80076c60]=lambda a:0xffffffff
    assert r.boot()==13 and r.bind_audio()==12
    r.audio_call();assert not r.calls and r.word(C+352)==0
    passed('task_creation_failure_never_binds_or_activates_audio')

    r=Rig();assert r.boot()==0
    assert r.release()==12
    put32(r.m,SCHEDULER,1);put32(r.m,MAIN_SLOT,MAIN_HANDLE)
    assert r.m.invoke(r.syms['native_worker_release'],[WORKER])==12
    r.audio_call();assert r.audio_ready()==1
    assert r.release()==11
    put32(r.m,0x80446d78,AID+1);r.audio_call()
    assert r.audio_ready()==6 and r.release()==12 and not r.calls
    passed('scheduler_Main_identity_and_AudioProcess_identity_checks_prevent_invalid_activation')

    for address in (MAN,WORKER,STATE,SLOTS,0xfffffff0):
        r=Rig();assert r.boot(bind=False)==0;put32(r.m,PORT+12,address)
        assert r.bind_audio()==12 and not r.calls and r.word(C+352)==0
    r=Rig();assert r.boot()==0;assert r.bind_audio()==12
    put32(r.m,SCHEDULER,1);assert r.bind_audio()==12
    passed('binding_rejects_overlapping_wrapping_storage_replacement_and_running_scheduler')

    r=Rig();r.start();r.inject=('create',1,'error')
    r.drive(lambda:r.mstate()==9,with_audio=False)
    assert not r.opened and r.word(r.syms['ct_active'])==0
    assert r.word(r.syms['emulator_bridge_current'])==0
    r.audio_call();assert r.audio_ready()==0
    passed('file_preparation_failure_keeps_capture_unpublished_while_original_audio_continues')

    r=Rig();assert r.boot()==0;put32(r.m,SCHEDULER,1)
    assert r.release()==11
    r.audio_call()
    # Main never retries: the authorized worker observes completion itself.
    r.ready();first=r.take(2)
    assert bytes(r.disk[first[1]])==first[2]
    passed('one_Main_authorization_suffices_while_worker_polls_first_audio_completion')

    out=ROOT/'analysis/audio_startup_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'One CPU executes compiled manager, worker, capture, native observer and original dispatch with synthetic DSP',
        'Main release remains explicit fixture authorization, not proof of stock initialization or storage ownership',
        'No native startup hook, allocator reserve, physical placement, scheduling, IRQ, DMA or timing proof',
        'Legacy worker registration without an audio binding remains for isolated tests; production composition must bind before release',
        'No device access or deployable firmware image']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
