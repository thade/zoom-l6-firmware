#!/usr/bin/env python3
"""One-generation storage lease around the compiled minimal recorder, offline.

Public I/O suspension/completion is modeled; this is NOT a physical SD join.
Main runs separate-stack nonblocking preflight; no native caller patch is claimed.
"""
import hashlib,json,struct
from unicorn import arm_const as A
from verify_capture_composed import ComposedRig,ComposedBoot,ComposedNative,scatter_startup
from verify_extra_lifecycle import LifeRig
from verify_capture_integration import IntegrationRig,record
from verify_capture_native_files import NativeCapture
from verify_native_exfat import ExfatFoldersSd
from verify_session_manager import RESET,PREPARE,STOPPED,BLOCKED
from verify_native_worker import HANDLE
from verify_control_transport import TASK,QHANDLE
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,RETURN
from verify_scheduling_boundaries import stop
from capture_jump_patches import symbols
from plan_capture_lease import ELF,plan
from plan_capture_packing import packing

PLAN=plan();PACK=packing(ELF);N=symbols(ELF);GLOBALS=tuple(PLAN['packing']['globals'])
IO_ERROR=0xffffd825
class LeaseBoot(ComposedBoot):
    names=N;packed=PACK;patch_plan=PLAN;global_range=GLOBALS

class LeaseRig(ComposedRig):
    elf_path=ELF;patch_plan=PLAN;packed=PACK;candidate_globals=GLOBALS
    def kernel_send(self,a):
        # Only the gated fixture's private marker has a zero-timeout ABI.
        if a[0]==QHANDLE and a[2:4]==[0,0]:
            wire=self.raw(a[1],32)
            assert struct.unpack_from('<I',wire)[0]==self.syms['ct_drain_marker']
            self.sent.append(wire)
            if self.send_result:return 0
            self.wire.append(wire);return 1
        return super().kernel_send(a)
    def lease(self):return self.arena+word(self.m,self.syms['native_arena_layout']+24)
    def lstate(self):return word(self.m,self.lease()+4)
    def admit(self,generation=1,mount=2,directory=0):
        return self.m.invoke(self.syms['storage_lease_admit'],[self.lease(),generation,mount,directory])
    def close_gate(self):return self.m.invoke(self.syms['storage_lease_close'],[self.lease()])
    def join(self):return self.m.invoke(self.syms['storage_lease_join'],[self.lease()])
    def boot(self,release=False):
        status=super().boot(False)
        if status==0 and release:
            assert self.admit()==0 and self.release()==0
        return status
    def other(self,operation,task=0x21039000):
        m=self.m;context=m.uc.context_save();previous=word(m,TASK);stack=m.stack
        m.stack=0x20030000;put32(m,TASK,task)
        try:return operation()
        finally:m.stack=stack;put32(m,TASK,previous);m.uc.context_restore(context)
    def retire(self):
        for _ in range(300):
            if self.join()==0:return
            self.audio_call();self.tick()
            # Exercise ordinary control progress when available. Storage-only
            # closure does not require this FIFO to retire retained callbacks.
            if self.wire:self.dispatch_all()
        life=self.d[4]
        raise AssertionError(dict(message='lease did not join modeled completed resources',
            manager_state=self.mstate(),lease_state=self.lstate(),
            lifecycle_words=list(struct.unpack('<4I',self.raw(life,16))),
            pending=getattr(self,'pending',None),last_calls=self.calls[-5:]))

class LeaseNative(NativeCapture,LeaseRig):pass

class Pending(LeaseRig):
    def __init__(self):
        self.pause=None;self.pending=None
        super().__init__()
        self.m.hooks[0x8005ffe8]=self.open_file
        self.m.hooks[0x8005c1f8]=self.close_file
    def suspend(self,kind,args):
        if self.pause==kind:
            self.pause=None;self.pending=(kind,list(args));return True
        return False
    def open_file(self,args):
        if args[2] and self.suspend('create',args):return stop(self.m)
        return LifeRig.open_file(self,args)
    def io_write(self,args):
        if args[0] in self.files:return IntegrationRig.io_write(self,args)
        path,pos,flags=self.opened[args[0]]
        kind='initial_header' if pos==0 and not self.disk[path] else ('final_header' if pos==0 else 'audio')
        if self.suspend(kind,args):return stop(self.m)
        return LifeRig.write_file(self,args)
    def io_read(self,args):
        if args[0] in self.files:return IntegrationRig.io_read(self,args)
        path,pos,flags=self.opened[args[0]]
        if self.suspend('read_header' if pos==0 else 'read_audio',args):return stop(self.m)
        return LifeRig.read_file(self,args)
    def close_file(self,args):
        kind='close_write' if self.opened[args[0]][2] else 'close_read'
        if self.suspend(kind,args):return stop(self.m)
        return LifeRig.close_file(self,args)
    def frame(self):
        sp=self.m.uc.reg_read(A.UC_ARM_REG_SP)
        return self.raw(sp,self.m.stack-sp)
    def wait_pending(self,audio=False):
        for _ in range(100):
            if audio:self.audio_call()
            self.tick()
            if self.pending:return
        raise AssertionError('requested modeled I/O was not reached')
    def complete(self,status=0):
        # The test supplies a PHYSICALLY JOINED result. No such detector is
        # present in the lease, and an unjoined operation must remain suspended.
        kind,args=self.pending
        if not status:
            if kind=='create':status=LifeRig.open_file(self,args)
            elif kind.startswith('close'):status=LifeRig.close_file(self,args)
            elif kind.startswith('read'):status=LifeRig.read_file(self,args)
            else:status=LifeRig.write_file(self,args)
        elif kind not in ('create','close_write','close_read'):put32(self.m,args[3],0)
        self.pending=None
        m=self.m;put32(m,TASK,HANDLE);m.uc.reg_write(A.UC_ARM_REG_R0,status)
        m.reached_return=False;pc=m.uc.reg_read(A.UC_ARM_REG_PC)
        m.uc.emu_start(pc|1,RETURN+2,count=100000000)
        assert m.reached_return and not self.lstate()&4

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    assert GLOBALS==(0x80960080,0x809600e8) and PLAN['packing']['spare_bytes']>=0
    assert len(PACK['code'])==PLAN['packing']['capture']['original_bytes']
    hashes,helpers=scatter_startup(True,pack=PACK)
    assert helpers[4][3]==104 and len(hashes)==8
    b=LeaseBoot();b.boot();b.guard()
    arena=b.arena();offset=b.word(N['native_arena_layout']+24);g=arena+offset
    assert b.word(arena+4)==9887 and b.word(g)==b.manager
    assert bytes(b.m.uc.mem_read(g+4,12))==bytes(12) and b.word(b.worker+8)==4
    passed('packed_original_scatter_and_boot_bind_heap_lease_closed_without_storage',
        heap_requested_bytes=9887,globals_bytes=104,spare_bytes=PLAN['packing']['spare_bytes'])

    r=LeaseRig();assert r.boot()==0 and r.lstate()==0
    assert r.release()==0 # Identity alone cannot bypass the new manager gate.
    for _ in range(20):assert r.tick()==11
    assert not r.calls and r.mstate()==RESET and r.resume()==12
    for values in ((0,2,0),(1,0,0),(1,1,0),(1,10,0),(1,2,IO_ERROR)):
        assert r.admit(*values)==12 and r.lstate()==0 and not r.calls
    r.m.uc.reg_write(A.UC_ARM_REG_IPSR,3)
    try:
        assert r.admit()==r.close_gate()==r.join()==12
    finally:r.m.uc.reg_write(A.UC_ARM_REG_IPSR,0)
    assert r.admit()==0 and r.admit(2)==12;r.ready()
    assert r.lstate()==1 and word(r.m,r.lease()+8)==1
    passed('closed_gate_blocks_direct_worker_release_zero_mount_absent_media_errors_ISR_and_duplicate_generation')

    # Retire safely at cold or partly cleared RESET, without reading dirty Life.
    for partial in (False,True):
        r=LeaseRig();assert r.boot()==0
        if partial:
            assert r.admit()==0 and r.release()==0;r.tick()
            assert r.mstate()==RESET and word(r.m,r.manager+36)>0
        before=len(r.calls);assert r.close_gate()==0 and r.join()==0
        assert r.lstate()==3 and len(r.calls)==before
        assert r.admit(2)==12 and r.resume()==12
        for _ in range(8):assert r.tick()==(11 if partial else 12)
        assert r.mstate()==RESET and len(r.calls)==before
    passed('cold_and_partial_reset_retire_without_dirty_lifecycle_reads_or_next_TMP_creation')

    r=LeaseRig();assert r.boot(release=True)==0
    r.drive(lambda:r.mstate()==PREPARE,with_audio=False)
    assert not r.calls and r.close_gate()==0 and r.join()==11
    r.retire();assert r.mstate()==STOPPED and not r.opened and not r.calls
    passed('cancel_before_first_prepare_has_positive_resource_cleanup_and_joins')

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    large_exfat=lambda **kwargs:ExfatFoldersSd(spc=512,clusters=1952360,**kwargs)
    r=LeaseNative(filesystem=large_exfat);assert r.fs.setup_card()==0;r.fs.verify_folders()
    assert r.boot(release=True)==0;r.ready();r.sequence=0
    assert record(r,delay=2,blocks=23)==ordinary
    data=r.completed_extra();assert len(data)==13312
    before=len(r.calls);saved=r.result();assert r.mstate()==RESET
    assert r.close_gate()==0
    for _ in range(20):assert r.tick()==11
    assert len(r.calls)==before and r.join()==0 and r.result()==saved
    assert r.admit(2)==12 and r.resume()==12
    passed('one_admitted_generation_exact_exFAT_eight_files_then_closes_before_automatic_rearm',
        extra_sha256=hashlib.sha256(data).hexdigest())

    for phase in ('create','initial_header','audio','final_header','read_header','read_audio','close_write','close_read'):
        r=Pending();assert r.boot(release=True)==0
        if phase in ('create','initial_header'):
            r.pause=phase;r.wait_pending()
        else:
            r.ready();r.begin_recording()
            if phase=='audio':r.pause=phase;r.wait_pending(audio=True)
            else:
                for _ in range(24):r.audio_call();r.tick()
                r.stop_recording();r.pause=phase;r.wait_pending()
        assert r.pending and r.lstate()==5 and word(r.m,r.manager+12)==1
        frame=r.frame();before=list(r.calls)
        assert r.other(r.close_gate)==0 and r.other(r.join)==11
        assert r.lstate()==6 and r.frame()==frame and r.calls==before
        assert r.other(lambda:r.m.invoke(r.syms['native_worker_poll'],[r.worker]),HANDLE)==11
        assert r.frame()==frame and r.calls==before
        # Main preflight stays nonblocking while the native frame is retained.
        # Continued ordinary audio is exercised during the pending payload.
        if phase=='audio':r.other(r.audio_call);assert r.frame()==frame
        r.complete()
        try:r.retire()
        except AssertionError as error:raise AssertionError((phase,error)) from error
        assert r.lstate()==3 and r.result()==12 and not r.opened
        if phase=='audio':
            r.audio_call();r.stop_recording();r.check_ordinary_files()
        passed('nonblocking_close_retains_manager_and_worker_scope_until_joined_'+phase)

    r=Pending();assert r.boot(release=True)==0;r.ready();r.begin_recording()
    r.pause='audio';r.wait_pending(audio=True)
    assert r.other(r.close_gate)==0 and r.other(r.join)==11
    r.complete(IO_ERROR);r.retire()
    assert not r.opened and r.result()==12 and r.lstate()==3
    passed('positively_joined_write_failure_cleanup_retires_without_verified_take')

    r=Pending();assert r.boot(release=True)==0;r.ready();r.begin_recording()
    for _ in range(24):r.audio_call();r.tick()
    r.stop_recording();r.pause='close_write';r.wait_pending()
    assert r.other(r.close_gate)==0;r.complete(IO_ERROR)
    r.drive(lambda:r.mstate()==BLOCKED,with_audio=False)
    before=list(r.calls)
    assert r.join()==11 and r.resume()==12 and r.admit(2)==12
    for _ in range(5):r.tick();assert r.join()==11
    assert r.calls==before and r.lstate()==2
    passed('uncertain_close_blocks_storage_retirement_retry_resume_and_new_generation')

    report=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),lease_elf_sha256=PLAN['hooks_elf_sha256'],
        packing=PLAN['packing'],limitations=PLAN['limitations']+[
            'Actual mount/directory and exFAT instructions run with virtual card/controller completion',
            'Setup observations passed explicitly; lower physical join is supplied by each suspended-I/O fixture',
            'Separate-stack Main preflight is a model, not patched native transition dispatch',
            'Lease blocks outer mutation but alone cannot stop premature driver unwinding or staging reuse'])
    (ROOT/'analysis/storage_lease_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
