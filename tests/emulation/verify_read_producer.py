#!/usr/bin/env python3
"""Bound producer phases and original file worker on one controlled CPU.
Reload task RUNNING scopes, scheduling and semaphore outcomes are fixtures.
"""
import json
import struct
from verify_read_worker import Worker, BUFFER, WORKER, CURRENT, READ_SEM
from verify_reload_read_queue import SECOND, READ, FILE_QUEUE
from verify_reload_ownership import CTX, UI
from verify_work_ownership import OK, BUSY, CONFLICT, FAULT
from verify_scheduling_boundaries import BASE
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT

P_CONFIG=0x21028a00
T0=0x21029000
T1=0x21029100
P_YIELD=0x21028100
RESULT=0x21029200
IDS=(0x7100,0x7101)


class Producers(Worker):
    def __init__(self,emulator=None):
        super().__init__(emulator);self.sent=[];self.waits=[];self.p_yields=0
        self.deliver=True;self.send_ok=True;self.wait_result=1
        self.owner,self.tag=self.prepare();self.ui=self.envelope(self.owner,UI)
        assert self.rl('sent',self.owner,UI,1)==OK and self.on('claim',self.ui)==OK
        for task,tag in ((T0,self.tag),(T1,self.ui)):
            # Represents the enclosing rt_run body while suspended in a read.
            self.m.uc.mem_write(task,struct.pack('<2I',1,2)+tag)
        put32(self.m,0x80446dc8,IDS[0]);put32(self.m,0x80446da4,IDS[1])
        put32(self.m,BASE+0x9a4+20,0x5678)
        self.m.uc.mem_write(P_CONFIG,struct.pack('<14I',CTX,T0,T1,*IDS,FILE_QUEUE,READ_SEM,
            READ,SECOND,0,1,0x800483f9,0x80076951,P_YIELD|1))
        self.m.hooks[0x80076950]=self.wait_port
        self.m.hooks[P_YIELD]=self.producer_yield
        assert self.rp('bind',P_CONFIG)==OK
    def rp(self,name,*args):return self.m.invoke(self.m.symbols['rp_'+name],list(args))
    def select(self,role):put32(self.m,CURRENT,IDS[role])
    def begin_read_request(self,role):
        self.select(role)
        return self.rp('begin',role,BUFFER+role*64,16)
    def step(self,role):self.select(role);return self.rp('step')
    def signal(self,a):
        if a[0]!=FILE_QUEUE:return super().signal(a)
        raw=bytes(self.m.uc.mem_read(a[1],16));self.sent.append(raw)
        if self.deliver:self.queue.append(raw)
        return 1 if self.send_ok else 0
    def wait_port(self,a):
        assert a[:2]==[READ_SEM,1]
        self.waits.append(int.from_bytes(self.m.uc.mem_read(CURRENT,4),'little'))
        return self.wait_result
    def producer_yield(self,a):self.p_yields+=1;return 0
    def run(self):put32(self.m,CURRENT,WORKER);super().run()
    def read_public(self,a):
        self.reads+=1
        assert (a[0],a[1],a[2]) in ((0x1234,BUFFER,16),(0x5678,BUFFER+64,16))
        count=13 if self.mode=='short' else 16
        if self.mode=='error':return 0xffffd825
        self.m.uc.mem_write(a[1],b'R'*count);put32(self.m,a[3],count);return 0
    def end(self):
        self.returned_without_claim()
        assert self.rl('verify',self.owner,1)==OK
        # Worker.finish is a test convenience with different signature.
        return self.rl('finish',self.owner)
    def returned_without_claim(self):
        assert self.on('complete',self.tag)==OK and self.on('complete',self.ui)==OK


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    def join(p,role):
        assert p.begin_read_request(role)==OK
        for _ in range(5):assert p.step(role)==BUSY

    p=Producers();join(p,0)
    assert len(p.sent)==1 and p.waits==[IDS[0]] and p.reads==0
    for _ in range(4):assert p.step(0)==BUSY
    assert len(p.sent)==1 and len(p.waits)==1
    p.run();assert p.step(0)==OK and p.step(0)==OK
    assert p.rp('result',RESULT)==OK
    send,wait,ticket=struct.unpack('<3I',p.m.uc.mem_read(RESULT,12))
    assert (send,wait)==(0,1) and ticket and p.end()==OK
    passed('early_wakeup_retries_ticket_join_without_another_send_or_semaphore_wait')

    p=Producers();join(p,0);join(p,1)
    assert len(p.sent)==2 and len(p.waits)==2
    p.queue.reverse();p.run()
    assert p.step(1)==OK and p.step(0)==OK and p.reads==2 and p.end()==OK
    assert struct.unpack('<4I',p.sent[0])[1:3]!=struct.unpack('<4I',p.sent[1])[1:3]
    passed('assignment_and_Main_use_distinct_native_task_contexts_slots_and_tickets')

    p=Producers();join(p,0)
    assert p.begin_read_request(0)==BUSY and len(p.sent)==1
    put32(p.m,CURRENT,0x9999);assert p.rp('step')==CONFLICT
    put32(p.m,T0+8+4,p.owner+100);assert p.step(0)==CONFLICT
    put32(p.m,T0+8+4,p.owner)
    p.run();assert p.step(0)==OK and p.end()==OK
    assert p.rp('bind',P_CONFIG)==CONFLICT
    passed('wrong_task_changed_reload_tag_duplicate_begin_and_rebinding_cannot_replace_live_request')

    p=Producers();assert p.begin_read_request(0)==OK
    put32(p.m,CTX+4,1);assert p.step(0)==BUSY and not p.sent
    put32(p.m,CTX+4,0)
    for _ in range(5):assert p.step(0)==BUSY
    p.run();put32(p.m,READ,1);assert p.step(0)==BUSY
    put32(p.m,READ,0);assert p.step(0)==OK and len(p.sent)==len(p.waits)==1
    assert p.end()==OK
    passed('reservation_and_join_contention_keep_request_snapshot_without_duplicate_IO')

    for mode in ('short','error'):
        p=Producers();p.mode=mode;join(p,0);p.run()
        assert p.step(0)==OK and p.end()==FAULT
    p=Producers();p.wait_result=0;join(p,0);assert p.step(0)==BUSY # timeout is only a scheduling hint
    p.run();assert p.step(0)==OK and p.end()==OK
    passed('read_errors_fail_but_notification_timeout_does_not_override_matching_completion')

    p=Producers();p.send_ok=False;join(p,0);p.run()
    assert p.step(0)==OK and p.rp('result',RESULT)==OK
    assert struct.unpack('<3I',p.m.uc.mem_read(RESULT,12))[:2]==(0xffffffff,1)
    assert p.end()==OK
    p=Producers();p.send_ok=False;p.deliver=False;join(p,0)
    for _ in range(5):assert p.step(0)==BUSY
    assert len(p.sent)==len(p.waits)==1 and not p.reads
    passed('delivered_ambiguous_send_can_join_but_undelivered_request_never_times_out_to_success')

    p=Producers();assert p.begin_read_request(0)==OK
    # Change the same native pad handle before actual reservation/publication:
    # the producer's earlier snapshot must remain in the immutable request.
    put32(p.m,BASE+0x9a4,0x9999)
    for _ in range(5):assert p.step(0)==BUSY
    p.run();assert p.reads==0 and p.step(0)==BUSY and p.word()&0x40000000
    passed('changed_file_handle_is_rejected_before_reading_from_the_wrong_file')

    out=ROOT/'analysis/read_producer_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Compiled producer and file-task adapter plus original worker share one controlled emulator CPU',
        'Enclosing RtTask RUNNING scopes, task switches, queue copies, native wait outcomes and file effects are fixtures',
        'Producer is a retained phase API; synchronous callback glue that drives it to completion is not installed',
        'Handle snapshots reject substitution but do not provide full card/file lifetime ownership',
        'No device communication, physical placement, firmware patch or startup release']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
