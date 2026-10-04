#!/usr/bin/env python3
"""Actual compiled manager publisher borrows shutdown's retained exclusive owner.
Storage ingress reservations are explicit fixtures, not installed recorder/USB hooks.
"""
import hashlib,json,struct
from verify_pad_publisher import PublisherRig,boundary
from verify_session_manager import ManagerRig
from verify_playback_shutdown import Rig as ShutdownRig,SD,SDP
from verify_playback_session import SESSION,PORT as SESSION_PORT
from verify_control_coordinator import C
from verify_work_ownership import LEDGER,OK,BUSY,FAULT,P,F
from verify_scheduling_boundaries import BASE
from verify_pad_renderer_boundary import AUDIO
from verify_overdub_prototype import STATE,PORT,ELF
from verify_extra_capture import ELF as CAPTURE_ELF
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
LEASE=0x21003e00
REGIONS=((SESSION,32),(SESSION_PORT,28),(SD,40),(SDP,8),(C,372),(LEDGER,780),(BASE,0x1000),(AUDIO,240))

def transfer(source,dest):
    for a,n in REGIONS:dest.m.uc.mem_write(a,bytes(source.m.uc.mem_read(a,n)))

class Rig(PublisherRig):
    def __init__(self,capture,shutdown):
        super().__init__(capture);self.guard_checks=0;self.try_finish=False;self.finish_observed=False
        self.fail_release=False
        transfer(shutdown,self)
        self.m.uc.mem_write(LEASE,struct.pack('<3I',SD,STATE,0))
        put32(self.m,PORT+7*4,self.m.symbols['od_emulator_publication_enter'])
        put32(self.m,PORT+8*4,self.m.symbols['od_emulator_publication_leave'])
    def u32(self,a):return int.from_bytes(self.m.uc.mem_read(a,4),'little')
    def peer(self):
        p=ShutdownRig(());transfer(self,p);return p
    def hit(self,op,**data):
        # Only observation: original file wrappers and compiled lease run as usual.
        child=self.u32(LEASE+8);parent=self.u32(SD+32)
        assert child and parent and self.u32(LEDGER)==P and self.u32(SESSION+28)==1
        rows=[struct.unpack('<12I',self.m.uc.mem_read(LEDGER+12+i*48,48)) for i in range(16)]
        assert any(e[0]==parent and e[2]==1 and e[3]==7 for e in rows)
        assert any(e[0]==child and e[1]==parent and e[3]==4 for e in rows)
        self.guard_checks+=1
        return super().hit(op,**data)
    def checkpoint(self,a):
        if self.try_finish and not self.finish_observed:
            p=self.peer();assert p.finish()==BUSY and p.word()==P
            assert p.invoke('start',0)==BUSY and p.invoke('scan')==BUSY
            self.finish_observed=True
        result=super().checkpoint(a)
        if self.fail_release:
            # Fail before any copy; cancellation unwinds through compiled leave,
            # whose short lock cannot be obtained. The void port must report fault.
            put32(self.m,SD+12,1);return 1
        return result

def fresh(ready=True,root=False):
    c=ManagerRig();c.audio_call();boundary(c)
    s=ShutdownRig(())
    if root:assert s.reserve(kind=4)[0]==OK
    assert s.shutdown()==BUSY
    if ready:
        s.audio();assert s.shutdown()==(BUSY if root else OK)
    return c,s,Rig(c,s)

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    c,s,r=fresh();r.try_finish=True;ordinary=r.take(900);original=bytes(r.files[ordinary])
    ticket=r.u32(SD+32)
    assert r.publish()=='ok' and r.guard_checks and r.finish_observed
    assert r.history()==[c.result()[1]] and r.u32(LEASE+8)==0 and r.u32(LEDGER)==P
    assert r.u32(SD+32)==ticket and bytes(r.files[ordinary])==original
    assert bytes(r.files[r.paths()[0]])==bytes(c.disk[c.result()[1]])
    p=r.peer();assert p.finish(ticket)==OK and p.word()==0 and p.field(7)==0
    passed('completed_extra_capture_publishes_under_same_exclusive_ticket_with_owned_child_and_preserved_master')

    c,s,r=fresh(ready=False);before={p:bytes(b) for p,b in r.files.items()}
    assert r.publish()=='busy' and not r.guard_checks and r.u32(LEASE+8)==0
    assert before=={p:bytes(b) for p,b in r.files.items()}
    s.audio();assert s.shutdown()==OK;transfer(s,r)
    assert r.publish()=='ok'
    passed('missing_audio_completion_blocks_before_file_or_catalogue_side_effects_then_retry_uses_real_ack')

    c,s,r=fresh(root=True);before={p:bytes(b) for p,b in r.files.items()}
    assert r.publish()=='busy' and not r.guard_checks and before=={p:bytes(b) for p,b in r.files.items()}
    assert s.sf(4)==5 and s.field(7)==1
    ticket=next(e[0] for e in s.entries() if e[1]==0)
    assert s.call('cancel_prepared',ticket)==OK # explicit fixture: operation definitely not sent
    assert s.shutdown()==OK;transfer(s,r);assert r.publish()=='ok'
    passed('attributed_card_or_recorder_reservation_blocks_handoff_until_positive_retirement_evidence',
           limitation='Root reserved by fixture; cancel_prepared models definite nonpublication, not ambiguous stock failure')

    c,s,r=fresh(root=True);root=next(e[0] for e in s.entries() if e[1]==0)
    assert s.call('offer',root)==OK and s.call('submitted',root,3)==OK
    assert s.call('producer_done',root,1)==OK
    transfer(s,r);assert r.publish()=='busy' and not r.guard_checks
    assert s.shutdown()==BUSY and s.word()==1
    passed('uncertain_storage_operation_remains_blocking_despite_producer_return_and_playback_quiet')

    c,s,r=fresh();r.fail=('close',1,'error')
    assert r.publish()=='fault' and r.u32(LEASE+8) and r.u32(LEDGER)&F
    assert r.peer().finish()==FAULT
    events=len(r.events);assert r.publish()=='fault' and len(r.events)==events
    passed('uncertain_close_keeps_publication_child_and_parent_owned_and_blocks_reopen')

    c,s,r=fresh();r.fail=('write',1,'short')
    assert r.publish()=='io' and r.u32(LEASE+8)==0 and r.u32(LEDGER)==P
    assert r.paths()==['NO ASSIGN']*4 and r.history()==[]
    r.fail=None;assert r.publish()=='ok'
    passed('recoverable_copy_failure_retires_child_but_keeps_parent_held_for_explicit_retry')

    c,s,r=fresh();r.fail_release=True
    assert r.publish()=='fault' and r.u32(LEASE+8) and r.u32(LEDGER)&F
    put32(r.m,SD+12,0);assert r.peer().finish()==FAULT
    passed('void_leave_port_ownership_failure_is_propagated_as_fault_instead_of_false_cancel_or_success')

    c,s,r=fresh();assert r.publish()=='ok';before={p:bytes(b) for p,b in r.files.items()};checks=r.guard_checks
    assert r.publish()=='skipped' and r.u32(LEASE+8)==0 and r.u32(LEDGER)==P
    assert checks==r.guard_checks and before=={p:bytes(b) for p,b in r.files.items()}
    passed('duplicate_manager_snapshot_borrows_and_releases_child_without_IO_or_dropping_parent')

    out=ROOT/'analysis/guarded_publisher_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      extra_capture_sha256=hashlib.sha256(CAPTURE_ELF.read_bytes()).hexdigest(),limitations=[
      'Compiled manager, publisher, shutdown and ledger connected through explicit emulator memory transfer',
      'Real USB/card and ordinary-recorder lifetime roots remain unbound; their reservations here are explicit fixtures',
      'Stock pad assignment path executes but audio file-loader/prefetch operations remain existing models',
      'The child spans the synchronous publisher call; real asynchronous file/prefetch descendants still need inherited attribution',
      'No firmware installation, hardware changes, SD durability or complete device-safe exclusion claim']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
