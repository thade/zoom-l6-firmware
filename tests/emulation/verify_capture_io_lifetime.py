#!/usr/bin/env python3
"""Capture-only files + original SD driver with separate offline join fixtures.

Sector translation, logical bytes, MMIO, scheduling and physical joins remain
models. The production capture ELF is loaded unchanged; no device binding.
"""
import hashlib,json,struct
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_capture_transitions import CaptureFiles,FS1,UI
from verify_extra_lifecycle import LifeRig
from verify_native_worker import WORKER,HANDLE as WORKER_TASK
from verify_session_manager import MAN,STOPPED,BLOCKED
from verify_control_transport import TASK
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,REGS
from verify_record_scheduler import word
from verify_scheduling_boundaries import stop
from verify_sd_transfer_lifetime import TABLE,UNIT,CARD,HOST,EVENT,EXPECTED
from verify_sd_transfer_probe import install,patch
from verify_sd_card_recovery import STOP_FIELDS
from verify_sd_checked_recovery import RecoveryPorts,SAFE,PERMIT
from sd_registers import PRESENT,IRQ_STATUS,CLOCK_STABLE,DAT0_HIGH,ACTIVITY

ELF=ROOT/'analysis/capture_io_probe.elf'
UNIT_TOKEN,EVENT_TOKEN=0x7e20,0x7e21
FINISH_MODEL=0x2102ba00

class CaptureSd(CaptureFiles,RecoveryPorts):
    def __init__(self,checked=False,finish_guard=True):
        super().__init__();m=self.m
        self.core_symbols=set(self.syms)
        m.uc.mem_map(0x10020000,0x10000)
        with ELF.open('rb') as f:
            elf=ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type']=='PT_LOAD' and seg['p_filesz']:
                    m.uc.mem_write(seg['p_vaddr'],seg.data())
            extra={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        assert not any(n.startswith(('sdp_','dependency_')) for n in self.core_symbols)
        self.syms.update(extra)
        assert m.invoke(0x80001994,[0x800a6980,0x801f5400,0x3780])==0
        assert list(struct.unpack('<11I',m.uc.mem_read(TABLE,44)))==EXPECTED
        for base in (0x402c0000,0x400fc000):m.uc.mem_map(base,0x1000)
        m.uc.mem_write(UNIT+4,b'\x01');put32(m,UNIT+8,UNIT_TOKEN)
        m.uc.mem_write(CARD+4,b'\0\x02');m.uc.mem_write(0x802142b4,b'\x01')
        put32(m,HOST+4,EVENT);put32(m,EVENT,EVENT_TOKEN);put32(m,0x402c0010,0x100)
        self.unit_held=False;self.current_io=None;self.current_name=None
        self.injection=None;self.injected=False;self.stage_count=0
        self.sd_ops=[];self.native_waits=[];self.logical=[];self.joins=[];self.finishes=[]
        self.join_allowed=False;self.finish_allowed=True;self.finish_reply=0;self.stalled=False
        self.finish_busy=False;self.unsafe_unlock=False
        self.configure(abort=checked)
        if not checked:put32(m,self.syms['sdp_join_port'],0x2102bd01)
        install(m,self.syms)
        if finish_guard:put32(m,self.syms['sdp_finish_port'],FINISH_MODEL|1)
        m.hooks[FINISH_MODEL]=self.finish_model;m.hooks[0x2102bd00]=self.join
        m.hooks[0x80074580]=lambda a:put32(m,a[0],0) or 0
        m.hooks[0x80073ec8]=m.hooks[0x80073f18]=lambda a:0
        # Keep the SD and file tokens on the same CPU fixture.
        previous_take=m.hooks[0x80076950];previous_give=m.hooks[0x800763d8]
        def take(a):
            if a[0]==UNIT_TOKEN:
                assert not self.unit_held and FS1 in self.locks.tokens
                self.unit_held=True;return 1
            return previous_take(a)
        def give(a):
            if a[0]==UNIT_TOKEN:
                assert self.unit_held
                if self.finish_busy:self.unsafe_unlock=True
                self.unit_held=False;return 1
            return previous_give(a)
        self.sd_take=take;self.sd_give=give
        m.hooks[0x80076950]=take;m.hooks[0x800763d8]=give
        m.hooks[0x2102bf00]=self.read_bytes;m.hooks[0x2102bf04]=self.write_bytes
        for native,name in ((0x80060818,'dependency_read'),(0x800624a8,'dependency_write')):
            m.hooks.pop(native,None);patch(m,native,self.syms[name],8)
            def entry(uc,pc,size,user,native=native):
                args=tuple(uc.reg_read(r) for r in REGS)
                self.current_io=(2 if native==0x80060818 else 3,args)
                path,pos,flags=self.opened[args[0]]
                self.current_name=('read_header' if pos==0 else 'read_audio') if not flags else (
                    'initial_header' if pos==0 and not self.disk[path] else 'final_header' if pos==0 else 'audio')
                self.native.append(('read' if not flags else 'write',args))
            m.uc.hook_add(UC_HOOK_CODE,entry,begin=native,end=native)
        # Extra reads now execute the public native wrapper too. Ordinary reads
        # retain the prior integration model, on the same CPU but separate handles.
        m.hooks.pop(0x80060620,None)
        def ordinary_read(uc,pc,size,user):
            args=[uc.reg_read(r) for r in REGS]
            if args[0] in self.files:
                uc.reg_write(REGS[0],self.io_read(args));uc.reg_write(A.UC_ARM_REG_PC,uc.reg_read(A.UC_ARM_REG_LR))
        m.uc.hook_add(UC_HOOK_CODE,ordinary_read,begin=0x80060620,end=0x80060620)
        # The dispatcher acquires the unit later; observe its input before lock.
        def request_entry(uc,pc,size,user):
            assert FS1 in self.locks.tokens and self.current_io
            self.sd_ops.append((self.current_name,bytes(uc.mem_read(uc.reg_read(REGS[0]),20))))
            self.stage_count=0
        m.uc.hook_add(UC_HOOK_CODE,request_entry,begin=0x80068378,end=0x80068378)

    def request(self,ui=0):
        try:return super().request(ui)
        finally:
            self.m.hooks[0x80076950]=self.sd_take
            self.m.hooks[0x800763d8]=self.sd_give
    def owner(self):return self.unit_held and FS1 in self.locks.tokens
    def stop_state(self):
        return dict(zip(STOP_FIELDS,struct.unpack('<10I',self.raw(self.syms['sdp_stop_state'],40))))
    def model(self,a):
        result=RecoveryPorts.model(self,a)
        if self.holds:self.stalled=True
        if a[0]==SAFE and result==1:self.joined=True
        return result
    def delay(self,a):
        result=RecoveryPorts.delay(self,a)
        if self.holds:self.stalled=True
        return result
    def data_deliver(self,a):
        assert self.owner() and self.probe()['active']
        assert a[0]==EVENT and a[1] in (0x183,0x185) and a[2]==5000
        self.stage_count+=1
        stage={1:'command',2:'data',3:'status'}[self.stage_count]
        self.native_waits.append((self.current_name,stage))
        raw=1 if a[1]==0x183 else 2
        faulty=not self.injected and self.injection and self.injection[:2]==(self.current_name,stage)
        if faulty:
            self.injected=True;self.joined=False
            raw={'hidden_error':raw|0x100000,'error':0x20000,'timeout':0}[self.injection[2]]
        put32(self.m,EVENT+8,0);put32(self.m,IRQ_STATUS,raw)
        put32(self.m,PRESENT,CLOCK_STABLE|(0x206 if faulty or self.finish_busy else DAT0_HIGH))
        return int(bool(raw))
    def join(self,a):
        assert self.owner() and self.probe()['failed'] and not self.probe()['finished']
        assert a[:3]==[0,self.probe()['buffer'],self.probe()['bytes']]
        self.joins.append((tuple(a[:4]),self.m.uc.reg_read(A.UC_ARM_REG_SP)))
        if not self.join_allowed:self.stalled=True;return stop(self.m)
        # Explicit MODEL physical/controller/cache/card/source validity.
        put32(self.m,PRESENT,CLOCK_STABLE|DAT0_HIGH);put32(self.m,IRQ_STATUS,0)
        self.joined=True;return 1
    def finish_model(self,a):
        assert self.owner() and self.probe()['active'] and not self.probe()['finished']
        assert a[:4]==[0,EVENT,self.probe()['buffer'],512]
        assert a[5]==self.probe()['failed']
        self.finishes.append((self.current_name,tuple(a[:6])))
        if not self.finish_allowed or self.finish_busy:
            self.stalled=True;stop(self.m);return self.finish_reply
        assert self.joined # failures cannot bypass their retained error recovery
        return 1
    def write_bytes(self,a):
        assert not self.unit_held and self.joined and FS1 in self.locks.tokens
        self.logical.append(('write',self.current_name,a[2]));return LifeRig.write_file(self,a)
    def read_bytes(self,a):
        assert not self.unit_held and self.joined and FS1 in self.locks.tokens
        self.logical.append(('read',self.current_name,a[2]));return LifeRig.read_file(self,a)
    def resume_io(self):
        previous=word(self.m,TASK);put32(self.m,TASK,WORKER_TASK);self.stalled=False
        try:return RecoveryPorts.resume(self)
        finally:put32(self.m,TASK,previous)
    def retained(self):
        assert self.stalled and self.owner() and self.probe()['active'] and not self.probe()['finished']
        assert self.opened and word(self.m,WORKER+20)==1 and word(self.m,MAN+12)==1
        assert self.mstate() not in (STOPPED,BLOCKED)
    def fault_write(self,stage='data',kind='hidden_error'):
        self.injection=('audio',stage,kind)
        for _ in range(12):
            self.audio_call();self.tick()
            if self.stalled:return
        raise AssertionError('Expected a retained payload transfer')
    def stop_after_fault(self):
        self.drive(lambda:self.mstate() in (STOPPED,BLOCKED),with_audio=False)
        assert self.mstate()==STOPPED and not self.opened and self.result()==12
        assert not self.unit_held and self.locks.tokens=={UI} and not self.unsafe_close

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=CaptureSd();r.running()
    for _ in range(10):r.audio_call();r.tick()
    r.stop_recording();r.completed_extra()
    assert r.sd_ops and {p[0] for _,p in r.sd_ops}=={2,3}
    assert len(r.finishes)==len(r.sd_ops) and not r.unit_held and r.locks.tokens=={UI}
    assert not r.holds and not r.joins and not r.unsafe_close
    passed('unchanged_capture_only_ELF_and_separate_SD_fixture_finish_exact_extra_file_with_native_read_write_joins',
           sectors=len(r.sd_ops))

    for stage in ('command','data','status'):
        for kind in ('hidden_error','error','timeout'):
            r=CaptureSd();r.running();r.fault_write(stage,kind);r.retained()
            assert r.probe()['failed'] and not r.probe()['joined']
            assert r.current_name=='audio' and not any(op[0]=='close' for op in r.native)
            frame=r.frame();before=list(r.native);r.request_cancel()
            assert r.worker_busy()==11 and r.frame()==frame and r.native==before
            r.join_allowed=True;r.resume_io();r.stop_after_fault()
    passed('command_data_and_status_errors_timeouts_and_hidden_error_bits_retain_file_and_SD_frames_before_cleanup',
           combinations=9)

    r=CaptureSd();r.injection=('initial_header','data','timeout');assert r.boot(release=True)==0
    for _ in range(32):
        r.tick()
        if r.stalled:break
    r.retained();assert not r.logical and not r.joined
    r.request_cancel();r.join_allowed=True;r.resume_io();r.stop_after_fault()
    passed('initial_header_error_cannot_close_new_file_or_unwind_header_frame_before_join')

    r=CaptureSd();r.running()
    for _ in range(3):r.audio_call();r.tick()
    r.injection=('final_header','data','hidden_error');r.stop_recording()
    for _ in range(32):
        r.tick()
        if r.stalled:break
    r.retained();assert r.current_name=='final_header'
    r.join_allowed=True;r.resume_io();r.stop_after_fault()
    passed('final_header_transfer_failure_retains_finalize_frame_and_never_yields_verified_result')

    r=CaptureSd();r.running()
    for _ in range(3):r.audio_call();r.tick()
    r.injection=('read_audio','data','timeout');r.stop_recording()
    for _ in range(32):
        r.tick()
        if r.stalled:break
    r.retained();assert r.current_name=='read_audio'
    r.join_allowed=True;r.resume_io();r.stop_after_fault()
    passed('readback_timeout_retains_destination_buffer_and_native_read_frame_before_close')

    r=CaptureSd();r.running();r.finish_allowed=False
    for _ in range(12):
        r.audio_call();r.tick()
        if r.stalled:break
    r.retained();assert not r.probe()['failed']
    frame=r.frame();before=list(r.logical);r.request_cancel()
    assert r.worker_busy()==11 and r.frame()==frame and r.logical==before
    r.finish_allowed=True;r.resume_io();r.stop_after_fault()
    passed('nominal_success_waits_before_original_dispatcher_unlock_until_explicit_MODEL_completion_permission')

    for reply in (2,-1):
        r=CaptureSd();r.running();r.finish_allowed=False;r.finish_reply=reply
        for _ in range(12):
            r.audio_call();r.tick()
            if r.stalled:break
        r.retained();frame=r.frame();r.request_cancel()
        assert r.worker_busy()==11 and r.frame()==frame
        r.finish_allowed=True;r.resume_io();r.stop_after_fault()
    passed('only_exact_JOINED_one_allows_completion_checkpoint_to_return')

    r=CaptureSd();r.running();r.join_allowed=True;r.finish_allowed=False;r.fault_write()
    r.retained();assert r.probe()['failed'] and r.probe()['joined']==1
    assert r.finishes[-1][1][4]!=0 and r.finishes[-1][1][5]==1
    assert not any(op[0]=='close' for op in r.native)
    r.finish_allowed=True;r.resume_io();r.stop_after_fault()
    passed('error_join_does_not_bypass_final_completion_permission_and_preserves_native_status')

    r=CaptureSd();r.running();r.finish_busy=True
    for _ in range(12):
        r.audio_call();r.tick()
        if r.stalled:break
    r.retained();assert not r.probe()['failed'] and word(r.m,PRESENT)&ACTIVITY
    r.finish_busy=False;put32(r.m,PRESENT,CLOCK_STABLE|DAT0_HIGH)
    r.request_cancel();r.resume_io();r.stop_after_fault()
    passed('completion_event_with_busy_controller_keeps_unit_file_and_synthetic_sector_owned')

    r=CaptureSd(finish_guard=False);r.running();r.finish_busy=True
    # Counterexample: earlier error-only guard still gives the unit on success.
    for _ in range(12):
        r.audio_call();r.tick()
        if r.unsafe_unlock:break
    assert r.unsafe_unlock and not r.finishes
    passed('negative_control_error_only_probe_can_release_unit_after_nominal_success_with_activity',
           negative_control=True)

    r=CaptureSd(checked=True);r.running();r.decisions[SAFE]=0;r.fault_write();r.retained()
    assert r.rec()['resets']==1 and not r.probe()['joined']
    frame=r.frame();r.request_cancel();assert r.frame()==frame and r.worker_busy()==11
    r.decisions[SAFE]=1;r.resume_io();r.stop_after_fault()
    assert r.rec()['resets']==1
    passed('checked_abort_reset_recovery_keeps_capture_file_and_SD_ownership_until_MODEL_card_cache_validity')

    for reason in ('permission','abort'):
        r=CaptureSd(checked=True);r.running()
        if reason=='permission':r.decisions[PERMIT]=0
        else:
            from verify_sd_card_recovery import STOP_ROW
            put32(r.m,STOP_ROW+4,word(r.m,STOP_ROW+4)&~0xc00000)
        r.fault_write();r.retained()
        assert not r.rec()['resets'] and not r.probe()['joined']
        assert not any(op[0]=='close' for op in r.native)
    passed('ungranted_reset_permission_or_nonabort_stock_stop_cannot_release_capture_transfer')

    r=CaptureSd();r.running();r.fault_write();r.retained()
    frame=r.frame();sectors=len(r.sd_ops);logical=list(r.logical)
    for _ in range(3):assert r.worker_busy()==11
    assert r.frame()==frame and len(r.sd_ops)==sectors and r.logical==logical
    passed('retained_fault_has_no_payload_retry_sector_resubmission_or_reentrant_cleanup')

    report=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        fixture_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=[
            'Capture-only ELF is unchanged; SD fixture has separate emulator-only placement.',
            'Native public read/write, SD dispatcher/command/event/IRQ and compiled capture code execute.',
            'Sector translation, logical bytes, kernel tokens, MMIO, scheduling and joins remain models.',
            'Checked recovery uses a counterfactual abort table and explicit reset/card/cache/source permissions.',
            'Success completion checkpoint is an explicit MODEL port, not a hardware idle detector.',
            'Actual open/close/FAT/cache metadata and complete native task/IRQ interleavings are unverified.',
            'No production I/O hook, transition guard, storage release or firmware image was installed.'])
    (ROOT/'analysis/capture_io_lifetime_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),cases=[c['case'] for c in cases]),indent=2))

if __name__=='__main__':main()
