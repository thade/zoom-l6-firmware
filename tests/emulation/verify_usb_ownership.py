#!/usr/bin/env python3
"""Proposed USB parent lifetime, original outer transitions, modeled driver ports.
No physical card/USB access or installed native queue/hook is exercised.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_reload_manager import Managed,M,PLAN
from verify_reload_compact import CTX,LEDGER,WORK,UITASK,DRIVER,WQ
from verify_work_ownership import OK,BUSY,FAULT,STALE,CONFLICT,P,F,REQUEST,OUT
from verify_stock_pad_adapter import StockRig,SETTINGS
from verify_storage_readiness import callees
from verify_storage_lifetimes import VOLUME
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,REGS
from verify_overdub_prototype import ELF
US=0x2102c100;TASK=0x2102dc00;PORT=0x2102dd00;PACKET=0x2102de00

class Usb(Managed):
    verify_gate=P
    def __init__(self):
        super().__init__(reload_port='us_reload_port')
        self.external=True;self.sent=[];self.us_events=[];self.send_result=1
        self.worker_result=0;self.ready_result=OK;self.mount_result=0;self.volume_status=0
        self.present=1;self.completion_contention=False;self.after_usb=None
        sym=lambda n:self.m.symbols[n]|1
        ports=(DRIVER+0x81,sym('us_stock_enter'),DRIVER+0x91,DRIVER+0xa1,
               sym('us_stock_remount'),DRIVER+0xb1)
        self.m.uc.mem_write(PORT,struct.pack('<6I',*ports))
        self.m.hooks.update({DRIVER+0x80:lambda a:int(self.external),DRIVER+0x90:self.send_usb,
                            DRIVER+0xa0:self.checked_worker,DRIVER+0xb0:self.ready})
        assert self.us('init',LEDGER,M,PORT)==OK
        self.layout_usb=struct.unpack('<4I',self.m.uc.mem_read(self.m.symbols['us_layout'],16))
        assert self.layout_usb==(6476,32,20,24),self.layout_usb
        base_hooks=dict(self.m.hooks)
        # Run original c220, 09b18 and 62230 (zero-active volume fixture).
        # Pad/recorder bodies and catalogue changes under that release are
        # explicit excluded/quiescent effects, not evidence of native draining.
        for fn in callees(0x80009b18,0x80009b44)-{0x80062230}:
            self.m.hooks[fn]=lambda a,fn=fn:self.effect(hex(fn),a)
        self.m.hooks[0x800088d0]=lambda a:self.effect('catalogue_tail',a)
        self.m.hooks[0x800345f8]=lambda a:0x3456
        self.m.hooks[0x80061f60]=lambda a:self.effect('storage_prepare',a)
        self.m.hooks[0x80077686]=lambda a:0
        # Real card setup/getters. Lower driver and directory/catalogue effects
        # are fixtures; local_ready separately supplies CHECKED mount evidence.
        for fn in callees(0x80009a40,0x80009b18)-{0x8000ac70,0x8000ac80,0x80008d68}:
            self.m.hooks[fn]=lambda a:0
        self.m.hooks.pop(0x80062230,None)
        self.m.hooks[0x8005ec00]=lambda a:self.volume_status
        self.m.hooks[0x8005fc98]=lambda a:self.effect('mount',a) or self.mount_result
        self.m.hooks[0x80002d80]=lambda a:0
        self.m.hooks[0x8000bad0]=lambda a:0x21008000
        self.m.hooks[0x8005f0d0]=lambda a:self.effect('filesystem_reset',a)
        self.m.hooks[0x8001fca0]=lambda a:self.present
        self.m.uc.mem_write(VOLUME,bytes(0x34))
        self.m.uc.mem_write(VOLUME+4,bytes([0xa5])*0x30)
        for addr in (0x8003b7e0,0x80008d68):
            self.m.hooks.pop(addr,None)
            self.m.uc.hook_add(UC_HOOK_CODE,self.us_redirect,begin=addr,end=addr)
        def detach(uc,a,n,u):
            assert self.word(LEDGER)==P and self.owner() and self.word(LEDGER+4)==0
            self.us_events.append(('detach',))
        self.m.uc.hook_add(UC_HOOK_CODE,detach,begin=0x80062230,end=0x80062230)
        # Scope release/mount stubs to the transition controller. The subsequent
        # original reload must retain its own real unloader/loader bodies.
        for addr in (0x8003b7e0,0x80008d68):base_hooks.pop(addr,None)
        self.transition_hooks={a:f for a,f in self.m.hooks.items() if base_hooks.get(a)!=f}
        self.m.hooks=base_hooks
    def us(self,name,*args):
        old=dict(self.m.hooks)
        if name=='step':self.m.hooks.update(getattr(self,'transition_hooks',{}))
        try:return self.m.invoke(self.m.symbols['us_'+name],[US,*args])
        finally:self.m.hooks=old
    def uphase(self):return self.word(US+4)
    def owner(self):return self.word(US+12)
    def effect(self,name,a):
        assert self.word(LEDGER)==P and self.owner() and self.word(LEDGER+4)==0
        self.us_events.append((name,*a[:2]));return 0
    def us_redirect(self,uc,address,size,user):
        if address==0x80008d68:
            if self.uphase()!=7:return
            args=[US];fn='us_defer_reload';self.us_events.append(('deferred_reload',))
        else:args=[US,uc.reg_read(REGS[0]),uc.reg_read(REGS[1])];fn='us_queue'
        for reg,v in zip(REGS,args):uc.reg_write(reg,v)
        uc.reg_write(UC_ARM_REG_PC,self.m.symbols[fn]|1)
    def send_usb(self,a):
        self.effect('send',a)
        p=bytes(self.m.uc.mem_read(a[0],20))
        if self.send_result!=2:self.sent.append(p)
        return self.send_result
    def checked_worker(self,a):
        self.effect('checked_worker',a)
        p=struct.unpack('<5I',self.m.uc.mem_read(a[0],20))
        assert p[0]==self.owner() and self.word(TASK+4)==2
        self.us_events.append(('worker',p[2],p[3]))
        if self.after_usb:self.after_usb(self,p)
        if self.completion_contention:put32(self.m,LEDGER+4,1)
        return self.worker_result
    def ready(self,a):
        self.effect('checked_local_ready',a)
        return FAULT if self.mount_result else self.ready_result
    def deliver_usb(self,p=None):
        self.m.uc.mem_write(PACKET,p if p is not None else self.sent.pop(0))
        return self.m.invoke(self.m.symbols['us_receive'],[TASK,PACKET])
    def usb_work(self):return self.us('run',TASK)
    def start(self,profile=0):
        assert self.us('begin',profile)==OK
        assert self.us('step')==BUSY and self.uphase()==3
        assert bytes(self.m.uc.mem_read(VOLUME+4,0x30))==bytes(0x30)
        return self.owner()
    def host(self,profile=0):
        owner=self.start(profile);assert self.deliver_usb()==OK and self.usb_work()==OK
        assert self.us('step')==BUSY and self.uphase()==4
        return owner
    def exit_host(self):
        self.prepare(start=False)
        assert self.us('exit',self.owner(),PLAN)==OK
        assert self.us('step')==BUSY and self.uphase()==6
    def remount(self):
        assert self.deliver_usb()==OK and self.usb_work()==OK
        assert self.us('step')==BUSY and self.uphase()==10
    def finish(self):
        assert self.step()==BUSY
        self.worker();self.consume();assert self.phase()==8
        assert self.word(LEDGER)==P and self.owner()
        assert self.us('step')==OK and self.uphase()==12 and not self.owner()
    def driver(self,op,a):
        assert self.word(LEDGER)==P and self.owner()
        assert self.active in (WORK,UITASK) and self.word(self.active+4)==2
        result=getattr(StockRig,op)(self,a)
        self.observed.append((op,self.active,result))
        if self.after_io:self.after_io(self,op,result)
        return result

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    for profile in range(3):
        r=Usb();r.host(profile);r.exit_host();r.remount();r.finish()
        assert r.word(LEDGER)==0 and r.word(CTX+400)==0
        assert [x for x in r.us_events if x[0]=='worker']==[('worker',1,6+2*profile),('worker',2,0x800)]
        assert [x[0] for x in r.us_events].count('deferred_reload')==1
        assert r.verify_io.count('read')==34 and len(r.prefetch)==8
    passed('three_storage_profiles_run_original_entry_detach_remount_then_compiled_reload_and_readback_before_release')

    r=Usb();r.external=False;assert r.us('begin',0)==OK
    before=bytes(r.m.uc.mem_read(VOLUME,0x34))
    assert r.us('step')==BUSY and not r.us_events and not r.owner()
    assert bytes(r.m.uc.mem_read(VOLUME,0x34))==before
    r.external=True;put32(r.m,LEDGER+4,1)
    assert r.us('step')==BUSY and not r.us_events
    put32(r.m,LEDGER+4,0);assert r.us('step')==BUSY and r.uphase()==3
    passed('external_exclusion_and_metadata_admission_precede_first_stock_filesystem_mutation')

    r=Usb();r.m.uc.mem_write(REQUEST,struct.pack('<5I',2,1,2,3,4))
    assert r.owned('reserve',REQUEST,OUT)==OK;ordinary=r.word(OUT)
    assert r.us('begin',0)==OK and r.us('step')==BUSY and not r.us_events
    assert r.owned('cancel_prepared',ordinary)==OK and r.us('step')==BUSY and r.uphase()==3
    passed('preexisting_owned_storage_work_blocks_USB_entry_until_retired')

    r=Usb();r.start();events=list(r.us_events)
    for _ in range(3):assert r.us('step')==BUSY and r.us_events==events
    r.deliver_usb();r.usb_work();r.us('step');events=list(r.us_events)
    assert r.uphase()==4
    r.m.uc.mem_write(REQUEST,struct.pack('<5I',2,1,2,3,4))
    assert r.owned('reserve',REQUEST,OUT)==BUSY
    for _ in range(3):assert r.us('step')==BUSY and r.us_events==events and r.word(LEDGER)==P
    passed('missing_start_completion_waits_and_completed_start_retains_exclusive_owner_for_entire_host_session')

    r=Usb();r.host();r.exit_host();events=list(r.us_events)
    assert r.us('step')==BUSY and r.us_events==events and r.uphase()==6
    child=r.child(r.owner());r.deliver_usb();r.usb_work()
    assert r.us('step')==BUSY and not any(e[0]=='mount' for e in r.us_events)
    assert r.owned('complete',child)==OK;r.us('step');r.finish()
    passed('stop_completion_and_late_attributed_IO_both_join_before_first_remount_effect')

    for outcome in (2,3):
        r=Usb();r.send_result=outcome;assert r.us('begin',0)==OK
        result=r.us('step')
        if outcome==2:
            assert result==FAULT and r.owner() and r.word(LEDGER)&F and not r.sent
        else:
            assert result==BUSY and r.us('step')==BUSY
            r.deliver_usb();r.usb_work();assert r.us('step')==BUSY and r.uphase()==4
    passed('rejected_send_fails_closed_and_uncertain_send_cannot_complete_without_real_tagged_consumer')

    for op in (1,2):
        r=Usb()
        if op==1:r.start()
        else:r.host();r.exit_host()
        r.worker_result=0xffffd825;r.deliver_usb();r.usb_work()
        assert r.us('step')==FAULT and r.owner() and r.word(LEDGER)&F
        assert not any(e[0]=='mount' for e in r.us_events)
        assert r.word(US+8)==0xffffd825
    passed('checked_start_or_stop_error_retains_parent_and_prevents_remount')

    r=Usb();r.start();r.deliver_usb();r.completion_contention=True
    assert r.usb_work()==BUSY and r.word(TASK+4)==3
    count=len(r.us_events);put32(r.m,LEDGER+4,0);r.completion_contention=False
    assert r.usb_work()==OK and len(r.us_events)==count
    assert r.us('step')==BUSY and r.uphase()==4
    passed('worker_completion_contention_retries_metadata_without_repeating_driver_operation')

    r=Usb();r.start();p=r.sent.pop(0);r.deliver_usb(p);r.m.uc.mem_write(PACKET,bytes(20))
    put32(r.m,LEDGER+4,1);assert r.usb_work()==BUSY and r.word(TASK+4)==1
    assert r.deliver_usb(p)==BUSY
    put32(r.m,LEDGER+4,0);assert r.usb_work()==OK
    r.deliver_usb(p);assert r.usb_work()==STALE
    assert len([e for e in r.us_events if e[0]=='worker'])==1
    passed('copied_command_survives_queue_reuse_and_claim_contention_duplicate_does_not_run_twice')

    r=Usb();old=r.host();r.exit_host();r.remount();r.finish();r.host()
    assert r.owner()>old and r.us('error',old,0x55)==STALE
    assert r.us('exit',old,PLAN)==STALE and r.word(LEDGER)==P
    assert r.us('begin',0)==BUSY
    passed('subsequent_session_uses_fresh_owner_and_rejects_old_errors_exit_and_overlapping_begin')

    for how in ('absent','unavailable','mount_error'):
        r=Usb();r.host();r.exit_host()
        if how=='absent':r.present=0
        elif how=='unavailable':r.volume_status=1
        else:r.mount_result=0xffffd825
        r.deliver_usb();r.usb_work();assert r.us('step')==FAULT
        assert not r.q[WQ] and r.owner() and r.word(LEDGER)&F
    passed('missing_card_unavailable_volume_and_checked_mount_error_never_authorize_reload_or_release')

    r=Usb();r.host();r.exit_host();r.ready_result=BUSY;r.deliver_usb();r.usb_work()
    assert r.us('step')==BUSY and r.uphase()==8 and not r.q[WQ]
    assert r.us('step')==BUSY
    assert len([e for e in r.us_events if e[0]=='mount'])==1
    r.ready_result=OK;assert r.us('step')==BUSY and r.uphase()==10;r.finish()
    passed('pending_positive_mount_evidence_waits_without_repeating_remount_or_using_stock_success_flag')

    r=Usb();r.host();r.exit_host();r.m.uc.mem_write(PLAN,bytes(6436));r.remount();r.finish()
    passed('exit_copies_expected_plan_before_stop_and_remount_independent_of_callers_reused_buffer')

    for when in ('host','reload'):
        r=Usb();r.host()
        if when=='reload':r.exit_host();r.remount()
        r.external=False;assert r.us('step')==FAULT and r.owner() and r.word(LEDGER)&F
    passed('lost_continuous_external_exclusion_during_host_or_reload_retains_parent')

    for how in ('writer','readback'):
        r=Usb();r.host();r.exit_host();r.remount();assert r.step()==BUSY;r.worker()
        if how=='writer':r.fail=('settings_write',2,'short')
        r.service()
        if how=='readback':r.files[SETTINGS][0]^=1
        assert r.step()==FAULT and r.us('step')==FAULT and r.owner() and r.word(LEDGER)&F
    passed('original_settings_write_failure_or_corrupt_readback_blocks_outer_USB_release')

    r=Usb();r.host();r.exit_host();r.remount();r.step();r.worker();r.consume()
    child=r.child(r.owner());before=(list(r.us_events),dict(r.counts))
    assert r.us('step')==BUSY and r.uphase()==11 and r.owner()
    assert r.owned('complete',child)==OK and r.us('step')==OK
    assert before==(r.us_events,r.counts) and r.word(LEDGER)==0
    assert r.us('step')==OK
    passed('late_parent_child_blocks_final_release_and_retry_does_not_repeat_reload_or_verification')

    for field in (0,1,2,3,4):
        r=Usb();r.start();p=bytearray(r.sent[0]);values=list(struct.unpack('<5I',p))
        values[field]=values[field]+1 if field!=2 else 2
        r.deliver_usb(struct.pack('<5I',*values))
        assert r.usb_work()==(STALE if field<2 else FAULT)
        assert not any(e[0]=='worker' for e in r.us_events)
        if field<2:
            assert r.us('step')==BUSY and r.uphase()==3
            r.deliver_usb();assert r.usb_work()==OK and r.us('step')==BUSY and r.uphase()==4
        else:
            assert r.us('step')==FAULT and r.owner() and r.word(LEDGER)&F
    passed('mismatched_owner_ticket_operation_selector_or_parameter_never_runs_driver_or_completes_genuine_command')

    r=Usb();root=r.host()
    assert r.us('error',root,0x91)==OK and r.us('error',root,0x92)==OK
    assert r.word(US+8)==0x91 and r.us('step')==FAULT
    before=list(r.us_events)
    assert r.us('step')==FAULT and r.us_events==before and r.owner()==root
    passed('first_attributed_error_is_retained_and_faulted_controller_never_retries_side_effects')

    r=Usb();r.host();r.send_result=2;r.prepare(start=False)
    assert r.us('exit',r.owner(),PLAN)==OK and r.us('step')==FAULT
    assert r.owner() and not any(e[0]=='mount' for e in r.us_events)
    passed('rejected_stop_submission_does_not_remount_or_release_host_session')

    out=ROOT/'analysis/usb_ownership_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      layout=r.layout_usb,limitations=[
      'Compiled proposed owner/worker protocol, original c220/09b18/62230 and c288 remount suffix/09a40 run in emulator; original pad reload and settings verification follow',
      'USB checked worker and positive local mount evidence are required modeled ports, not newly proven native driver contracts',
      'USB queue copying, scheduling and boundary PC redirects are fixtures; native two-word mailbox has not been replaced or installed',
      'Pad/recorder release bodies, mount driver, catalogues, SD and audio are modeled; external exclusion remains a continuous required port',
      'Expected pad/settings plan is supplied by trusted fixture at exit; arbitrary host edits are not automatically reconciled',
      'Alternate c2d8 transitions and direct card/recorder entry paths remain unbound; publication must not treat this prototype as complete device exclusion',
      'No physical mixer/card access, firmware patch image, installation or power-loss recovery test']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
