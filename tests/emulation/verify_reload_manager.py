#!/usr/bin/env python3
"""Automatic planned reload completion; compiled ARM plus bytearray SD fixture."""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_reload_recovery import Recovery,NOISE
from verify_reload_compact import UID,UQ,WQ,CURRENT,CTX,LEDGER,PRODUCER,UITASK,DRIVER,SCRATCH
from verify_reload_transport import RUNTIME,OK,BUSY,FAULT,F
from verify_stock_pad_adapter import StockRig,SETTINGS,CONFIG
from verify_work_ownership import REQUEST,OUT,CONFLICT
from verify_firmware_workflow import put32
from verify_record_catalogue import putstr
from verify_pad_protocol import ROOT,IMAGE,REGS
from verify_overdub_prototype import ELF
M=0x21028000;PLAN=0x2102a000;MPORT=0x2102c000

class Managed(Recovery):
    verify_gate=1
    def __init__(self,reload_port=None):
        super().__init__();self.fenced=True;self.verify_io=[];self.check_fail=None;self.check_calls={}
        self.m.hooks[DRIVER+0x70]=lambda a:int(self.fenced)
        put32(self.m,MPORT,DRIVER+0x71)
        assert self.rm('init',RUNTIME,PRODUCER,self.m.symbols[reload_port] if reload_port else MPORT)==OK
        assert self.rc('bind_manager',M)==OK
        self.layout=struct.unpack('<3I',self.m.uc.mem_read(self.m.symbols['rm_layout'],12))
        assert self.layout==(6468,6436,4),self.layout
        # Verification uses the same actual PUBLIC filesystem wrappers as the
        # saver, checked synchronously under its sealed owner. Only lower-level
        # driver effects are modeled; it does not reuse RT_RUNNING attribution.
        self.m.hooks[0x80060818]=lambda a:self.check_driver('read',a) if self.phase()==4 else StockRig.read(self,a)
    def phase(self):return self.word(M+4)
    def rm(self,name,*args):return self.m.invoke(self.m.symbols['rm_'+name],[M,*args])
    def redirect(self,uc,address,size,user):
        if address in (0x800604e8,0x8005c388,0x800624a8) and self.phase()==4:
            assert address!=0x800624a8,'verification must never write'
            op='open' if address==0x800604e8 else 'close'
            result=self.check_driver(op,[uc.reg_read(reg) for reg in REGS])
            uc.reg_write(REGS[0],result)
            from unicorn.arm_const import UC_ARM_REG_LR
            uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR));return
        super().redirect(uc,address,size,user)
    def check_driver(self,op,a):
        assert self.word(LEDGER)==self.verify_gate and self.word(CTX+400)==M
        assert self.word(CTX+4)==0 and self.word(LEDGER+4)==0
        owner=self.word(M+16)
        entries=[struct.unpack('<12I',self.m.uc.mem_read(LEDGER+12+i*48,48)) for i in range(16)]
        assert any(e[0]==owner and e[2]==0 and e[3]==8 for e in entries)
        self.verify_io.append(op);self.check_calls[op]=self.check_calls.get(op,0)+1
        fail=self.check_fail==(op,self.check_calls[op],'error')
        short=self.check_fail==(op,self.check_calls[op],'short')
        if fail and op!='close':
            if op=='read':put32(self.m,a[3],0)
            return 0xffffd825
        result=getattr(StockRig,op)(self,a)
        if short:put32(self.m,a[3],a[2]-1)
        return 0xffffd825 if fail else result
    def prepare(self,start=True):
        pads=bytearray(548*4)
        payload=bytearray(self.m.uc.mem_read(CONFIG+0x798,0xc34))+bytearray(self.m.uc.mem_read(0x80445524+0xc34,0x400))
        for p,path in enumerate(self.expected):
            enc=(path+'\0').encode('utf-16le');pads[p*548:p*548+len(enc)]=enc
            struct.pack_into('<6I',pads,p*548+524,p%3,49+p,60+p,0,0,0)
            payload[0x828+p]=1
        plan=bytes(pads)+bytes(self.m.uc.mem_read(0x800a202e,0x60))+bytes(payload)
        assert len(plan)==6436
        self.m.uc.mem_write(PLAN,plan)
        return self.rm('start',PLAN,0) if start else None
    def launch(self):
        assert self.prepare()==OK
        assert self.step()==BUSY and self.phase()==3
        return self.word(M+16)
    def step(self):
        put32(self.m,CURRENT,UID);self.active=UITASK
        try:return self.rm('step')
        finally:self.active=None
    def finished_bodies(self):
        self.worker();assert self.service()==OK
    def owned(self,name,*args):return self.m.invoke(self.m.symbols['od_own_'+name],[LEDGER,*args])
    def child(self,owner):
        self.m.uc.mem_write(REQUEST,struct.pack('<5I',2,5,6,7,8))
        assert self.owned('child',owner,REQUEST,OUT)==OK
        ticket=self.word(OUT)
        for op,args in (('offer',(ticket,)),('submitted',(ticket,1)),('claim',(ticket,REQUEST)),('producer_done',(ticket,0))):
            assert self.owned(op,*args)==OK
        return ticket

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    r=Managed();o=r.launch();r.worker();r.consume()
    assert r.phase()==8 and r.word(PRODUCER+4)==0 and r.word(LEDGER)==0 and r.word(CTX+400)==0
    assert r.verify_io.count('read')==34 and r.counts['settings_write']==2 and len(r.prefetch)==8
    passed('original_Main_receive_automatically_checks_runtime_and_disk_then_retires_producer_without_Python_verdict')

    r=Managed();assert r.prepare()==OK
    assert r.poll()==BUSY and r.phase()==3 and not r.effects
    r.worker();assert r.poll()==BUSY and len(r.prefetch)==8
    assert r.poll()==OK and r.phase()==8 and r.effects
    saved=list(r.effects);assert r.poll()==OK and r.effects==saved
    passed('mode5_can_start_prepared_manager_drain_reload_verify_and_resume_setup_once')

    r=Managed();r.launch();r.seed([NOISE]*4096);r.worker()
    assert r.poll()==BUSY and len(r.prefetch)==8 and not r.effects
    assert r.poll()==OK and r.phase()==8 and not r.q[UQ]
    passed('full_UI_queue_completes_verification_and_mode_transition_without_manual_release')

    r=Managed();r.launch();r.finished_bodies();r.m.uc.mem_write(PLAN,bytes(6436))
    assert r.step()==OK and r.phase()==8
    passed('copied_intended_result_is_independent_of_callers_reused_plan_buffer')

    for which in ('configured','runtime','mode','level','adjacent','loaded'):
        r=Managed();r.launch();r.finished_bodies()
        if which=='configured':putstr(r.m,CONFIG+0x798,'A:\\WRONG.WAV')
        elif which=='runtime':putstr(r.m,0x807348d0+0x20,'A:\\WRONG.WAV')
        elif which=='loaded':put32(r.m,0x807348d0,0)
        else:r.m.uc.mem_write(CONFIG+{'mode':0xfc4,'level':0xfc8,'adjacent':0x329}[which],b'\xff')
        assert r.step()==FAULT and r.word(M+8)==0xffff1001 and not r.verify_io
        assert r.word(PRODUCER+4)!=0 and r.word(LEDGER)&F and r.word(CTX+400)==M
    passed('wrong_path_runtime_path_options_or_loaded_state_rejected_before_any_settings_read')

    for offset in (0,0x60,0x60+0x82c,0x60+0xc34):
        r=Managed();r.launch();r.finished_bodies();r.files[SETTINGS][offset]^=1
        assert r.step()==FAULT and r.word(M+8)==0xffff1002 and r.verify_io[-1]=='close'
        n=len(r.verify_io);assert r.step()==FAULT and len(r.verify_io)==n
    passed('corrupt_header_path_options_or_preserved_tail_faults_without_repair_or_retry_writes')

    for delta in (-1,1):
        r=Managed();r.launch();r.finished_bodies()
        if delta<0:r.files[SETTINGS].pop()
        else:r.files[SETTINGS].append(0)
        assert r.step()==FAULT and r.verify_io==['open','close']
    passed('truncated_and_oversize_settings_files_fail_exact_size_check_and_close')

    for failure in (('open',1,'error'),('read',1,'error'),('read',17,'error'),('read',34,'short'),('close',1,'error')):
        r=Managed();r.launch();r.finished_bodies();r.check_fail=failure
        assert r.step()==FAULT and r.word(PRODUCER+4)!=0 and r.word(LEDGER)&F
        assert r.verify_io.count('close')==(0 if failure[0]=='open' else 1)
        assert len(r.handles)==4
    passed('verification_open_read_short_read_and_close_errors_retain_owner_and_close_successful_opens_once')

    r=Managed();r.launch();r.finished_bodies();del r.files[SETTINGS]
    assert r.step()==FAULT and r.verify_io==['open'] and r.counts['settings_write']==2
    passed('missing_settings_is_failure_not_create_or_repair')

    r=Managed();r.launch();r.finished_bodies()
    for p,path in enumerate(r.expected):
        at=0x60+p*522+len((path+'\0').encode('utf-16le'));r.files[SETTINGS][at]^=0x5a
    assert r.step()==OK
    passed('unused_UTF16_path_padding_does_not_cause_false_corruption_failure')

    r=Managed();o=r.launch();child=r.child(o);r.finished_bodies()
    assert r.step()==BUSY and not r.verify_io and r.word(PRODUCER+4)==o
    assert r.owned('complete',child)==OK and r.step()==OK
    passed('late_attributed_descendant_blocks_all_final_IO_and_retirement_until_joined')

    r=Managed();r.launch();r.worker();r.fail=('settings_write',2,'short');assert r.service()==OK
    assert r.step()==FAULT and not r.verify_io and r.word(PRODUCER+4)
    passed('original_writer_error_cannot_be_erased_by_good_runtime_state_or_final_verification')

    for state in ('before','after'):
        r=Managed();o=r.launch()
        if state=='after':r.finished_bodies()
        r.fenced=False;assert r.step()==FAULT and r.word(PRODUCER+4)==o
    passed('lost_external_exclusion_faults_before_verifying_or_retiring')

    r=Managed();o=r.launch();assert r.submit(PRODUCER+0x20)==(BUSY,0)
    r.producer=PRODUCER;r.finished_bodies();assert r.step()==OK
    assert r.rl('cleanup_begin')==OK and r.rl('cleanup_end')==OK
    passed('manager_lease_blocks_competing_reload_and_releases_after_success')

    for lockaddr in (CTX+4,LEDGER+4):
        r=Managed();r.launch();r.finished_bodies();put32(r.m,lockaddr,1)
        assert r.step()==BUSY and not r.verify_io
        put32(r.m,lockaddr,0);assert r.step()==OK
    passed('metadata_contention_before_seal_defers_verification_without_repeating_bodies')

    # Inject contention as the checked close returns. Evidence remains stored
    # under the sealed root; successful I/O must not repeat when metadata retries.
    for lockaddr,expected_phase in ((CTX+4,5),(PRODUCER,6)):
        r=Managed();o=r.launch();r.finished_bodies();orig=r.check_driver
        def delayed(op,a):
            result=orig(op,a)
            if op=='close':put32(r.m,lockaddr,1)
            return result
        r.check_driver=delayed
        assert r.step()==BUSY and r.phase()==expected_phase
        calls=list(r.verify_io)
        r.m.uc.mem_write(REQUEST,struct.pack('<5I',2,1,2,3,4))
        assert r.owned('child',o,REQUEST,OUT)==CONFLICT
        put32(r.m,lockaddr,0);r.check_driver=orig
        assert r.step()==OK and r.verify_io==calls
    passed('sealed_root_rejects_new_children_and_metadata_retries_do_not_repeat_settings_IO')

    r=Managed();r.launch();r.finished_bodies();orig=r.check_driver
    def loss(op,a):
        result=orig(op,a)
        if op=='close':r.fenced=False
        return result
    r.check_driver=loss
    assert r.step()==FAULT and r.word(PRODUCER+4)!=0
    passed('exclusion_loss_during_readback_is_detected_before_accepting_evidence')

    r=Managed();r.launch();old=r.q[WQ][0];r.worker();r.consume();first=r.word(M+16)
    assert r.phase()==8
    assert r.prepare()==OK and r.step()==BUSY and r.word(M+16)>first
    r.q[WQ].appendleft(old);r.qsync(WQ);r.worker();r.consume()
    assert r.phase()==8 and len(r.prefetch)==16 and r.word(LEDGER)==0
    passed('completed_manager_can_run_next_pass_and_reject_old_worker_ticket')

    r=Managed();assert r.prepare()==OK
    assert r.rm('start',PLAN,0)==BUSY
    r=Managed();r.fenced=False;assert r.prepare()==CONFLICT and not r.q[WQ]
    # Deliberately inconsistent plan, before any admission or state mutation.
    r=Managed();r.prepare(start=False)
    r.m.uc.mem_write(PLAN+548*4+0x60,b'\xff')
    assert r.rm('start',PLAN,0)==CONFLICT and not r.q[WQ]
    passed('unfenced_inconsistent_or_overlapping_plans_do_not_launch_reload')

    out=ROOT/'analysis/reload_manager_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      layout=r.layout,limitations=[
      'Compiled manager, original reload bodies and public filesystem wrappers execute on one emulated ARM CPU; RTOS queues, SD drivers, settings-input reader and audio engine remain fixtures',
      'Expected complete plan is supplied by fixture before reload; automatic wiring from capture SessionManager and publication owner is not implemented',
      'Continuous external pad/playback/recorder/card/USB exclusion is an explicit required port, modeled here; manager lease only serializes reload and queue cleanup',
      'Readback proves modeled filesystem bytes and runtime state, not physical SD durability, power-loss recovery or audible playback',
      'Native task placement, scheduler hooks, public-wrapper errors during original bodies and all asynchronous descendants still require audit',
      'No mixer access, SD writes, firmware patch image or installation']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
