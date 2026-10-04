#!/usr/bin/env python3
"""Capture boundary -> guarded publication -> planned reload -> release, offline."""
import hashlib,json,struct
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_LR
from verify_reload_manager import Managed,M,PLAN,MPORT
from verify_scheduling_boundaries import stop
from verify_reload_recovery import NOISE
from verify_reload_transport import RUNTIME,OK,BUSY,FAULT,F,WORK,UITASK,PRODUCER,DRIVER
from verify_reload_compact import UID,UQ,WQ,CURRENT,CTX,SCRATCH
from verify_guarded_publisher import transfer,LEASE
from verify_playback_shutdown import Rig as ShutdownRig,SD
from verify_playback_session import SESSION
from verify_control_coordinator import C
from verify_session_manager import ManagerRig,MAN,RESET,LIVE
from verify_pad_publisher import boundary
from verify_stock_pad_adapter import StockRig,SETTINGS,CONFIG
from verify_overdub_prototype import STATE,PORT,ELF
from verify_extra_capture import ELF as CAPTURE_ELF
from verify_pad_protocol import ROOT,IMAGE,REGS
from verify_work_ownership import LEDGER,P,STALE,CONFLICT
from verify_firmware_workflow import put32
from verify_record_catalogue import putstr,getstr,BASE as CATALOGUE,STRIDE
WF=0x2102c100;CFG=0x2102dc80;WP=0x2102dca0

class Workflow(Managed):
    verify_gate=P
    def __init__(self,capture=None,ready=True):
        super().__init__(reload_port='pw_reload_port')
        # Existing loaded pads are setup with original code, before enabling the
        # workflow. This is not the publication plan or a post-reload verdict.
        self.verify_gate=1
        _,owner=self.submit();self.worker();assert self.service()==OK
        assert self.verify(owner) and self.retire()==OK
        self.verify_gate=P
        self.capture=capture or ManagerRig()
        if capture is None:self.capture.audio_call();boundary(self.capture)
        self.m.uc.mem_map(0x10010000,0x10000);self.m.uc.mem_map(0x22000000,0x20000)
        self.sync_capture()
        self.shutdown=ShutdownRig(())
        assert self.shutdown.shutdown()==BUSY
        if ready:self.shutdown.audio();assert self.shutdown.shutdown()==OK
        transfer(self.shutdown,self)
        self.external=True;self.publish_checks=0;self.observer=None
        self.m.hooks[DRIVER+0x80]=lambda a:int(self.external)
        syms=self.capture.syms
        self.m.uc.mem_write(WP,struct.pack('<5I',*[syms[n]|1 for n in
            ('manager_bind_publication','manager_hold_publication','manager_release_publication','manager_publish_held_pads')],DRIVER+0x81))
        self.m.uc.mem_write(CFG,struct.pack('<6I',MAN,STATE,PORT,SD,M,WP))
        self.m.uc.mem_write(LEASE,struct.pack('<3I',SD,STATE,0))
        put32(self.m,PORT+28,self.m.symbols['od_emulator_publication_enter'])
        put32(self.m,PORT+32,self.m.symbols['od_emulator_publication_leave'])
        assert self.pw('init',CFG)==OK
        self.layout=struct.unpack('<3I',self.m.uc.mem_read(self.m.symbols['pw_layout'],12))
        assert self.layout==(6492,24,20),self.layout
        self.originals={p:bytes(b) for p,b in self.files.items() if p in self.capture.disk or p.startswith('A:\\RECORDER')}
    def sync_capture(self):
        c=self.capture
        self.m.uc.mem_write(0x10010000,c.raw(0x10010000,0x10000))
        self.m.uc.mem_write(MAN,c.raw(MAN,c.mlayout[0]))
        self.m.uc.ctl_remove_cache(0x10010000,0x10020000)
        for path,data in c.disk.items():self.files[path]=bytearray(data)
    def pw(self,name,*args):return self.m.invoke(self.m.symbols['pw_'+name],[WF,*args])
    def phase_w(self):return self.word(WF+4)
    def capture_call(self,name,*args):return self.m.invoke(self.capture.syms['manager_'+name],[MAN,*args])
    def redirect(self,uc,address,size,user):
        if address in (0x800604e8,0x8005c388,0x800624a8) and self.phase_w()==5:
            op={0x800604e8:'open',0x8005c388:'close',0x800624a8:'write'}[address]
            result=getattr(StockRig,op)(self,[uc.reg_read(reg) for reg in REGS])
            uc.reg_write(REGS[0],result);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR));return
        return super().redirect(uc,address,size,user)
    def yield_task(self,a):
        self.yields+=1
        # Model the scheduler yielding Main back to the publication worker;
        # never recursively call another ARM function on a paused CPU.
        if self.phase()==8 and self.phase_w()==8:return stop(self.m)
        return 0
    def driver(self,op,a):
        if self.word(LEDGER)!=P:return super().driver(op,a)
        assert self.active in (WORK,UITASK) and self.word(self.active+4)==2
        assert self.word(WF+12) and self.word(SESSION+28)==1
        result=getattr(StockRig,op)(self,a)
        self.observed.append((op,self.active,result))
        if self.after_io:self.after_io(self,op,result)
        return result
    def hit(self,op,**data):
        if self.phase_w()==5:
            assert self.word(LEASE+8) and self.word(WF+12) and self.word(LEDGER)==P
            assert self.word(MAN+12)==1
            self.publish_checks+=1
            if self.observer:self.observer(self,op)
        return super().hit(op,**data)
    def begin(self):
        assert self.pw('start')==OK
        return self.pw('step')
    def reload(self):
        assert self.step()==BUSY # Main launches the prepared immutable plan
        self.worker();self.consume()
    def complete(self):
        assert self.begin()==BUSY and self.phase_w()==8
        self.reload();assert self.phase()==8
        assert self.pw('step')==OK and self.phase_w()==12
    def assert_sources(self):
        assert all(bytes(self.files[p])==b for p,b in self.originals.items())
    def next_capture(self):
        # Transfer the release decision back into the capture fixture; execute
        # actual manager reset/handover and the next full additional capture.
        self.capture.m.uc.mem_write(MAN,bytes(self.m.uc.mem_read(MAN,self.capture.mlayout[0])))
        self.capture.drive(lambda:self.capture.mstate()==LIVE)
        boundary(self.capture)
        self.sync_capture()
        # A new shutdown cycle receives an actual emulated audio acknowledgment.
        # Transfer current control/session state into a peer only for audio work.
        transfer(self,self.shutdown)
        assert self.shutdown.shutdown()==BUSY
        self.shutdown.audio();assert self.shutdown.shutdown()==OK
        transfer(self.shutdown,self)
        for p,b in self.capture.disk.items():self.originals[p]=bytes(b)

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    r=Workflow();r.complete();r.assert_sources()
    assert r.history()==[r.capture.result()[1]] and bytes(r.files[r.paths()[0]])==bytes(r.capture.disk[r.capture.result()[1]])
    assert r.word(LEDGER)==0 and r.word(SESSION+28)==0 and r.word(C+12)==0
    assert r.word(MAN+r.capture.mlayout[0]-8)==0 and r.capture_call('step')==10
    passed('compiled_capture_result_builds_plan_publishes_reloads_verifies_releases_and_allows_next_reset')

    r=Workflow();history=[]
    for i in range(6):
        if i:r.next_capture()
        history.insert(0,r.capture.result()[1]);r.complete();r.assert_sources()
        assert r.history()==history[:4]
        for p,path in enumerate(history[:4]):assert bytes(r.files[r.paths()[p]])==bytes(r.capture.disk[path])
    passed('six_completed_takes_rotate_latest_four_extra_recordings_with_clean_sources_and_options_preserved',takes=6)

    r=Workflow();before=bytes(r.m.uc.mem_read(MAN,r.capture.mlayout[0]))
    assert r.capture_call('step')==11 and bytes(r.m.uc.mem_read(MAN,r.capture.mlayout[0]))==before
    assert r.begin()==BUSY
    assert r.capture_call('step')==11 and r.word(MAN)==RESET
    assert r.capture_call('publish_pads',STATE,PORT)==2
    assert r.capture_call('release_publication',WF+4)==12
    assert r.m.invoke(r.m.symbols['od_shutdown_finish'],[SD,r.word(WF+16),0])==BUSY
    r.reload();assert r.capture_call('step')==11
    assert r.pw('step')==OK and r.capture_call('step')==10
    passed('bound_capture_cannot_reset_or_publish_through_other_entry_and_parent_cannot_reopen_until_pipeline_releases')

    r=Workflow(ready=False);files={p:bytes(b) for p,b in r.files.items()}
    assert r.begin()==BUSY and not r.publish_checks and files=={p:bytes(b) for p,b in r.files.items()}
    r.shutdown.audio();assert r.shutdown.shutdown()==OK;transfer(r.shutdown,r)
    assert r.pw('step')==BUSY;r.reload();assert r.pw('step')==OK
    passed('missing_audio_ack_blocks_before_publication_then_same_capture_completes_after_ack')

    r=Workflow();assert r.begin()==BUSY
    intended=getstr(r.m,M+32)
    assert intended==r.paths()[0]
    # A later accidental change cannot redefine the manager's expected options.
    r.m.uc.mem_write(CONFIG+0xfc8,b'\xff')
    assert r.step()==BUSY;r.worker();assert r.service()==OK
    assert r.step()==FAULT and r.pw('step')==FAULT
    assert r.word(WF+12) and r.word(MAN+r.capture.mlayout[0]-8)==WF and r.word(LEDGER)&F
    r.assert_sources()
    passed('post_publication_option_drift_fails_independent_prepublication_plan_and_keeps_capture_and_parent_held')

    r=Workflow();r.fail=('write',1,'short')
    assert r.begin()==FAULT and not r.q[WQ] and r.word(WF+12) and r.word(LEDGER)&F
    assert r.capture_call('step')==11 and r.pw('step')==FAULT;r.assert_sources()
    passed('publication_error_never_launches_reload_or_next_take_and_is_not_automatically_retried')

    r=Workflow();assert r.begin()==BUSY and r.step()==BUSY;r.worker();assert r.service()==OK
    r.files[SETTINGS][0]^=1
    assert r.step()==FAULT and r.pw('step')==FAULT and r.word(WF+12)
    assert r.capture_call('step')==11 and r.word(SESSION+28)==1
    passed('corrupt_saved_settings_blocks_outer_release_and_capture_reset')

    for when in ('publication','reload'):
        r=Workflow()
        if when=='publication':
            def cancel(r,op):put32(r.m,MAN+8,1)
            r.observer=cancel
            assert r.begin()==FAULT
        else:
            assert r.begin()==BUSY;r.capture_call('cancel');assert r.step()==FAULT
            assert r.pw('step')==FAULT
        assert r.capture_call('step')==11 and r.word(WF+12) and r.word(LEDGER)&F
    passed('cancellation_during_publication_or_reload_cannot_bypass_retained_ownership')

    r=Workflow();assert r.begin()==BUSY;r.external=False
    assert r.step()==FAULT and r.pw('step')==FAULT and r.word(SESSION+28)==1
    passed('loss_of_explicit_ordinary_recorder_card_USB_exclusion_fails_closed')

    r=Workflow();r.complete();counts=dict(r.counts)
    assert r.pw('start')==STALE and r.pw('step')==OK and r.counts==counts
    passed('same_completed_capture_is_not_published_or_reloaded_twice')

    r=Workflow();assert r.begin()==BUSY;r.reload()
    put32(r.m,SD+12,1);assert r.pw('step')==BUSY and r.phase_w()==9
    assert r.word(WF+12) and r.capture_call('step')==11
    put32(r.m,SD+12,0);before=dict(r.counts)
    assert r.pw('step')==OK and r.counts==before
    passed('outer_child_release_contention_retries_metadata_without_republishing_or_reloading')

    r=Workflow();assert r.begin()==BUSY;r.reload()
    put32(r.m,MAN+12,1);assert r.pw('step')==BUSY and r.phase_w()==11
    assert r.word(LEDGER)==0 and r.word(MAN+r.capture.mlayout[0]-8)==WF
    put32(r.m,MAN+12,0);assert r.pw('step')==OK
    passed('capture_release_contention_retains_capture_hold_after_successful_shutdown_reopen')


    # An empty pad with an empty catalogue stays empty. If a catalogue still
    # has files, stock reload may auto-select one; reject that unintended result.
    for empty_catalogue in (True,False):
        r=Workflow()
        for p in range(1,4):
            putstr(r.m,CONFIG+0x798+p*522,'NO ASSIGN')
            r.m.uc.mem_write(CONFIG+0xfc0+p,b'\x00')
            put32(r.m,0x807348d0+p*0x22c,0)
            if empty_catalogue:
                base=CATALOGUE+p*STRIDE
                for fn in (0x8002a2e0,0x8002a428,0x8002a2c8):r.m.invoke(fn,[base])
                putstr(r.m,base+0x14,f'A:\\SOUND_PAD\\PAD{p+1}')
        assert r.begin()==BUSY and r.step()==BUSY
        r.worker();assert r.service()==OK
        status=r.step()
        if empty_catalogue:
            assert status==OK and r.pw('step')==OK
            assert r.paths()[1:]==['NO ASSIGN']*3
        else:
            assert status==FAULT and r.pw('step')==FAULT
    passed('empty_unused_pads_stay_empty_with_empty_catalogues_and_stock_unwanted_autoassignment_is_rejected')

    # A cancelled take has no new verified result to publish. A bound manager
    # must still allow explicit recovery rather than demanding an old result.
    c=ManagerRig();c.audio_call()
    assert c.m.invoke(c.syms['manager_bind_publication'],[MAN,WF])==OK
    c.cancel();c.drive(lambda:c.mstate()==9);assert c.resume()==OK
    c.drive(lambda:c.mstate()==LIVE)
    passed('bound_capture_can_resume_after_cancellation_without_misclassifying_an_old_result_as_a_new_take')

    r=Workflow();assert r.begin()==BUSY;r.reload()
    put32(r.m,M,1)
    assert r.pw('step')==BUSY and r.phase_w()==8 and r.word(WF+12)
    assert r.capture_call('step')==11 and r.word(LEDGER)==P
    put32(r.m,M,0);assert r.pw('step')==OK
    passed('cross_task_completion_query_waits_for_reload_latch_before_releasing_outer_protection')

    r=Workflow();assert r.begin()==BUSY;before=len(r.prefetch);r.seed([NOISE]*4096)
    assert r.poll()==BUSY and not r.effects
    r.worker();assert r.poll()==BUSY and len(r.prefetch)==before+8
    assert r.poll()==BUSY and r.phase()==8 and not r.effects
    assert r.word(WF+12) and r.word(LEDGER)==P
    assert r.pw('step')==OK and r.poll()==OK and r.effects and not r.q[UQ]
    passed('full_queue_mode_transition_waits_for_whole_publication_handoff_after_reload_verifies')

    r=Workflow();assert r.begin()==BUSY;r.seed([NOISE]);r.reload()
    assert r.phase()==8 and r.ui_events()==[NOISE] and r.phase_w()==8
    assert r.pw('step')==OK
    r.consume();assert not r.q[UQ]
    passed('ordinary_Main_controls_remain_queued_until_publication_worker_releases_parent_and_capture')

    out=ROOT/'analysis/publication_workflow_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      extra_capture_sha256=hashlib.sha256(CAPTURE_ELF.read_bytes()).hexdigest(),limitations=[
      'Capture and audio completion are executed in existing ARM fixtures; their state transfers at explicit boundaries into the publication/reload CPU are modeled scheduling, not a running RTOS',
      'Compiled workflow supplies intended plan and compiled shutdown/ledger/capture holds protect it; Python supplies neither the postpublication plan nor final verdict',
      'Ordinary recorder/card/USB exclusion remains an explicit external port; pad-loader asynchronous descendants, physical I/O and settings input are modeled',
      'File readback is not power-loss durability or audible playback proof',
      'No device access, SD-card writes, firmware patch creation or installation']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
