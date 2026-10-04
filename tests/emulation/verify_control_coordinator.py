#!/usr/bin/env python3
"""Compiled control coordinator + original whole handlers and copy/audio paths.

Submission occurs at a proposed upstream boundary supplied by the harness; this
is not an installed UI/RTOS adapter and does not establish a pad renderer fence.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_control_admission import ControlRig,EFFECT
from verify_pad_reader_audit import AuditRig,SELECTOR
from verify_overdub_prototype import ELF
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,RETURN
C=0x21039000;ARGS=0x21039800;OUT=ARGS+16
OK,BUSY,FULL,STALE,INVALID,EXHAUSTED=range(6)
class Rig(ControlRig):
    def __init__(self):
        super().__init__();self.size,self.jobsize,self.offset=struct.unpack('<3I',self.raw(self.m.symbols['oc_layout'],12))
        self.order=[]
        for kind,fn in enumerate((0x8000e748,0x8000e7b0,0x80006ca8,0x80006fc8,0x8001d968),1):
            self.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u,kind=kind:self.order.append(kind),begin=fn,end=fn)
        # Deep mode-workflow subsystems remain fixtures; setters run stock.
        for fn in (0x8002fba8,0x8002fa18,0x80007ff8,0x800060b8,0x80006098,0x80002388,0x8001e4d8,0x800494c0):
            self.m.hooks[fn]=lambda a:0
    def call(self,name,*args):return self.m.invoke(self.m.symbols['oc_'+name],[C,*args])
    def submit(self,kind=1,args=(0,37)):
        self.m.uc.mem_write(ARGS,struct.pack('<2I',*args));put32(self.m,OUT,0xaabbccdd)
        result=self.call('submit',kind,ARGS,OUT)
        return result,self.word(OUT)
    def run(self):return self.call('run_one',self.m.symbols['oc_stock_dispatch'])
    def close(self):
        result=self.call('close',OUT);return result,self.word(OUT)
    def jobs(self):return [struct.unpack('<5I',self.raw(C+self.offset+i*self.jobsize,self.jobsize)) for i in range(16)]
    def phase(self,ticket):return next(j[1] for j in self.jobs() if j[0]==ticket)
    def peer(self):
        p=Rig();p.m.uc.mem_write(C,self.raw(C,self.size));return p
    def import_peer(self,p):self.m.uc.mem_write(C,p.raw(C,p.size))

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=Rig();tickets=[]
    for kind,args in ((1,(0,42)),(3,(0,0)),(2,(0,63)),(5,(0,0)),(4,(0,0))):
        status,t=r.submit(kind,args);assert status==OK;tickets.append(t)
        assert r.call('take_done',t)==BUSY
    assert not r.order and not r.events
    for ticket in tickets:
        assert r.run()==OK and r.phase(ticket)==3
        assert r.call('take_done',ticket)==OK and r.call('take_done',ticket)==STALE
    assert r.order==[1,3,2,5,4] and r.run()==BUSY
    assert ('update',0,2,42) in r.events and ('update',0,3,63) in r.events
    passed('accepted_is_not_done_and_worker_executes_original_whole_handlers_in_submission_order')

    r=Rig();_,first=r.submit(1,(0,81));assert r.close()==(OK,1)
    _,second=r.submit(3,(0,0));assert r.call('drained',1)==OK
    for _ in range(3):assert r.run()==BUSY
    assert not r.order and not r.events and r.phase(first)==r.phase(second)==1
    assert r.call('reopen',1)==OK
    assert r.run()==OK and r.run()==OK and r.order==[1,3]
    passed('closure_parks_both_preexisting_unstarted_and_new_commands_without_claiming_they_completed')

    r=Rig();_,first=r.submit(1,(0,91));r.held=True
    r.run();assert r.suspended and r.phase(first)==2 and r.word(C+16)==first
    # Independent manager CPU closes admission while worker is in original wait.
    p=r.peer();assert p.close()==(OK,1);_,second=p.submit(2,(0,22))
    assert p.call('drained',1)==BUSY and p.call('reopen',1)==BUSY
    assert p.run()==BUSY and p.call('take_done',first)==BUSY
    r.import_peer(p);r.held=False;r.resume()
    assert r.phase(first)==3 and r.call('drained',1)==OK and r.phase(second)==1
    assert r.call('take_done',first)==OK and r.run()==BUSY
    assert r.call('reopen',1)==OK and r.run()==OK
    assert r.order==[1,2] and ('update',0,2,91) in r.events
    passed('close_during_original_effect_lock_wait_joins_admitted_handler_and_keeps_later_handler_parked')

    r=Rig();put32(r.m,EFFECT+0x14,r.m.symbols['oc_fixture_effect_copy'])
    payload=bytes(range(16));r.m.uc.mem_write(0x21037000,payload)
    _,ticket=r.submit(1,(0,25));stopped=[]
    def poll(uc,a,n,u):
        if not stopped:
            stopped.append(True);r.m.reached_return=True;uc.emu_stop()
    h=r.m.uc.hook_add(UC_HOOK_CODE,poll,begin=0x8005b776,end=0x8005b776)
    r.run();assert stopped and r.phase(ticket)==2 and r.word(0x8044530c)==4
    assert r.word(C)==0 # No coordinator lock held through blocking stock code.
    p=r.peer();assert p.close()==(OK,1);assert p.call('drained',1)==BUSY
    _,later=p.submit(5,(0,0));r.import_peer(p)
    audio=AuditRig()
    for addr,n in ((0x80445308,8),(0x80445164,16)):audio.m.uc.mem_write(addr,r.raw(addr,n))
    audio.full();assert audio.raw(0x21038000,16)==payload and audio.word(0x8044530c)==0
    for addr,n in ((0x80445308,8),(0x21038000,16)):r.m.uc.mem_write(addr,audio.raw(addr,n))
    r.m.uc.hook_del(h);r.m.reached_return=False
    r.m.uc.emu_start(r.m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
    assert r.m.reached_return and r.phase(ticket)==3 and r.phase(later)==1
    assert r.call('drained',1)==OK and r.raw(0x21038000,16)==payload
    passed('admitted_real_imported_copy_completes_through_full_stock_audio_before_control_drain_can_succeed',
           fixture='Compiled synthetic effect callback invokes original copy import; real effects algorithm not replaced on a device')

    r=Rig();_,ticket=r.submit(3,(0,0));r.close();before=r.word(SELECTOR)
    assert r.run()==BUSY and r.word(SELECTOR)==before and not r.order
    r.call('reopen',1);assert r.run()==OK and r.word(SELECTOR)==0x800133e9
    passed('deferred_mode_command_does_not_enter_its_workflow_or_change_selector_until_reopened')

    r=Rig();_,ticket=r.submit(1,(0,71));r.m.uc.mem_write(ARGS,bytes(8));assert r.run()==OK
    assert ('update',0,2,71) in r.events
    passed('accepted_scalar_payload_is_copied_and_survives_reuse_of_submission_buffer')

    r=Rig();ids=[r.submit(5,(0,0))[1] for _ in range(16)]
    assert r.submit(5,(0,0))==(FULL,0xaabbccdd)
    for _ in range(16):assert r.run()==OK
    assert r.submit(5,(0,0))==(FULL,0xaabbccdd) # DONE owns a slot until consumed.
    assert r.call('take_done',ids[3])==OK
    status,t=r.submit(5,(0,0));assert status==OK and t>max(ids)
    assert r.call('take_done',ids[3])==STALE and r.run()==OK
    passed('bounded_queue_never_drops_jobs_or_overwrites_unconsumed_completion_and_reuses_slots_with_fresh_tickets')

    r=Rig();assert r.call('drained',0)==STALE and r.call('reopen',1)==STALE
    assert r.close()==(OK,1);assert r.close()[0]==BUSY
    assert r.call('drained',2)==STALE and r.call('reopen',2)==STALE
    assert r.call('reopen',1)==OK and r.call('reopen',1)==STALE
    assert r.close()==(OK,2) and r.call('reopen',1)==STALE
    passed('non_reused_closure_epochs_reject_stale_duplicate_or_missing_reopen')

    r=Rig();put32(r.m,C+4,0xffffffff)
    assert r.submit()==(EXHAUSTED,0xaabbccdd)
    r=Rig();put32(r.m,C+8,0xffffffff);assert r.close()[0]==EXHAUSTED and r.word(C+12)==0
    passed('ticket_and_epoch_exhaustion_never_wrap')

    r=Rig();before=r.raw(C,r.size)
    for kind,args in ((0,(0,0)),(6,(0,0)),(3,(1,0)),(5,(0,1))):assert r.submit(kind,args)[0]==INVALID
    assert r.raw(C,r.size)==before
    _,ticket=r.submit();put32(r.m,C,1);before=r.raw(C,r.size)
    assert r.submit()[0]==BUSY and r.run()==BUSY and r.close()[0]==BUSY
    assert r.call('drained',1)==BUSY and r.call('reopen',1)==BUSY and r.call('take_done',ticket)==BUSY
    assert r.raw(C,r.size)==before and not r.order
    passed('invalid_payloads_and_metadata_lock_contention_have_no_original_control_side_effects')

    r=Rig();_,ticket=r.submit();r.held=True;r.run();p=r.peer()
    assert p.run()==BUSY and not p.order
    r.import_peer(p);r.held=False;r.resume();assert r.phase(ticket)==3 and r.order==[1]
    passed('second_worker_cannot_execute_or_duplicate_inflight_work')

    out=ROOT/'analysis/control_coordinator_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,coordinator_bytes=r.size,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Proposed upstream submission boundary provided by harness; no original UI/RTOS event deferral adapter installed',
        'Five whole handlers with scalar payloads only; unknown mode/import callers remain outside coverage',
        'Effects-lock scheduling, plug-in body or synthetic copy fixture, and deep mode subsystem calls are modeled',
        'Drain proves admitted control completion only; no audio epoch, stream/card/recorder fence or pad-publication integration',
        'No hardware write, physical timing, queue wakeup, task priority or memory-placement proof']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
