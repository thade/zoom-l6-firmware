#!/usr/bin/env python3
"""Compiled native file-task boundary adapter; original worker runs on same CPU.
Call-site redirection, kernel queue copying and public read effects are fixtures.
"""
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_CPU_ARM_CORTEX_M7, UC_ARM_REG_PC, UC_ARM_REG_LR
from verify_overdub_prototype import Emulator
from verify_reload_read_queue import QueueReads, READ, TABLE, SECOND, FILE_QUEUE
from verify_reload_ownership import CTX
from verify_work_ownership import LEDGER, OK, BUSY, CONFLICT, FAULT
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop, BASE
from verify_pad_protocol import ROOT

CONFIG=0x21027800
YIELD=0x21028000
BUFFER=0x21010000
WORKER=0x7003
CURRENT=0x808e291c
READ_SEM=0x7001


class Worker(QueueReads):
    def __init__(self,emulator=None):
        super().__init__()
        self.m=emulator if emulator is not None else Emulator(cpu_model=UC_CPU_ARM_CORTEX_M7,mclass=True)
        put32(self.m,CTX,LEDGER);put32(self.m,TABLE,READ);put32(self.m,TABLE+4,SECOND)
        self.queue=[];self.receives=0;self.reads=0;self.signals=[];self.yields=0
        self.mode='normal';self.after_read=None;self.after_signal=None
        self.m.uc.mem_write(CONFIG,struct.pack('<14I',CTX,READ,SECOND,*([0]*6),
            WORKER,FILE_QUEUE,0x800483a9,0x80060621,YIELD|1))
        put32(self.m,0x80446dc4,WORKER);put32(self.m,0x801f8f30,FILE_QUEUE)
        put32(self.m,CURRENT,WORKER);put32(self.m,0x804467fc,READ_SEM)
        put32(self.m,0x80446800,READ_SEM+1);put32(self.m,BASE+0x9a4,0x1234)
        self.m.hooks.update({0x80076710:self.receive,0x800763d8:self.signal,
                             0x80060620:self.read_public,YIELD:self.yield_task,
                             0x8005f168:lambda a:0})
        for address,name in ((0x80036152,'next'),(0x80036184,'read')):
            def redirect(uc,addr,n,u,name=name):
                uc.reg_write(UC_ARM_REG_LR,(addr+4)|1)
                uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rw_'+name]|1)
            self.m.uc.hook_add(UC_HOOK_CODE,redirect,begin=address,end=address)
        assert self.rw('bind',CONFIG)==OK
    def rw(self,fn,*args):return self.m.invoke(self.m.symbols['rw_'+fn],list(args))
    def receive(self,a):
        assert a[0]==FILE_QUEUE and a[2]==0xffffffff
        self.receives+=1
        if not self.queue:return 0
        self.m.uc.mem_write(a[1],self.queue.pop(0));return 1
    def signal(self,a):
        self.signals.append(a[0])
        if self.after_signal:self.after_signal(self)
        return 1
    def read_public(self,a):
        self.reads+=1;assert a[:3]==[0x1234,BUFFER,16]
        n=13 if self.mode=='short' else 16
        if self.mode=='error':
            # Do not write the count: the compiled adapter must initialize it.
            result=0xffffd825
        else:
            self.m.uc.mem_write(a[1],b'R'*n);put32(self.m,a[3],n);result=0
        if self.after_read:self.after_read(self)
        return result
    def yield_task(self,a):self.yields+=1;return stop(self.m)
    def admit(self):
        self.owner,self.tag=self.prepare()
        assert self.begin_read(self.tag,(0,BUFFER,16))==OK
        ticket=self.ticket();assert self.rr('ready',ticket)==OK
        status,raw=self.packet(ticket);assert status==OK
        self.queue.append(raw);self.m.uc.mem_write(BUFFER,b'?'*16)
        return ticket,raw
    def run(self):self.m.invoke(0x80036118,[])
    def finish(self,ticket):
        assert self.rr('finish',ticket)==OK
        self.returned(self.owner,self.tag)
        assert self.rl('verify',self.owner,1)==OK
        return super().finish(self.owner)


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    w=Worker();ticket,_=w.admit();w.run()
    assert w.reads==1 and w.signals==[READ_SEM] and w.receives==2 and w.yields==1
    assert bytes(w.m.uc.mem_read(BUFFER,16))==b'R'*16 and w.finish(ticket)==OK
    passed('same_CPU_stock_file_worker_uses_bound_compiled_receive_read_and_return_tracking')

    w=Worker();ticket,_=w.admit();put32(w.m,READ,1);w.run()
    assert w.receives==1 and not w.queue and not w.reads
    put32(w.m,READ,0);w.run()
    assert w.reads==1 and w.receives==2 and w.finish(ticket)==OK
    passed('dequeued_packet_is_retained_across_busy_decode_without_second_receive')

    for mode,expected in (('normal',OK),('short',FAULT),('error',FAULT)):
        w=Worker();w.mode=mode;ticket,_=w.admit()
        w.after_read=lambda w:put32(w.m,READ,1)
        w.run();assert w.reads==1 and w.receives==1 and w.signals==[READ_SEM]
        put32(w.m,READ,0);w.after_read=None;w.run()
        assert w.reads==1 and w.signals==[READ_SEM] and w.receives==2
        assert w.finish(ticket)==expected
        if mode=='short':assert bytes(w.m.uc.mem_read(BUFFER,16))==b'R'*13+bytes(3)
    passed('result_status_and_count_survive_busy_observation_without_repeating_read_or_signal')

    w=Worker();ticket,_=w.admit();observations=[];returns=[]
    def observe(uc,a,n,u):observations.append(1)
    def hold(uc,a,n,u):
        returns.append(1)
        if len(returns)==1:put32(w.m,READ,1)
    # Compiler may inline the queue wrapper; the retained observer is the
    # operation whose second execution would reject/overwrite evidence.
    w.m.uc.hook_add(UC_HOOK_CODE,observe,begin=w.m.symbols['rr_observe']&~1,end=w.m.symbols['rr_observe']&~1)
    hook=w.m.uc.hook_add(UC_HOOK_CODE,hold,begin=w.m.symbols['rr_queue_return']&~1,end=w.m.symbols['rr_queue_return']&~1)
    w.run();assert w.reads==1 and len(observations)==1 and w.receives==1
    put32(w.m,READ,0);w.m.uc.hook_del(hook);w.run()
    assert w.reads==1 and len(observations)==1 and w.finish(ticket)==OK
    passed('busy_return_retries_only_completion_after_result_was_committed')

    w=Worker();ticket,_=w.admit();put32(w.m,CURRENT,WORKER+1)
    assert w.rw('next',FILE_QUEUE,BUFFER)==0xffffffff
    assert w.rw('read',0x1234,BUFFER,16,BUFFER+32)==0xffff0004
    assert w.receives==0 and w.reads==0 and len(w.queue)==1
    put32(w.m,CURRENT,WORKER)
    for address,value in ((0x80446dc4,WORKER+1),(0x801f8f30,FILE_QUEUE+1)):
        old=int.from_bytes(w.m.uc.mem_read(address,4),'little');put32(w.m,address,value)
        assert w.rw('next',FILE_QUEUE,BUFFER)==0xffffffff and w.receives==0
        put32(w.m,address,old)
    w.run();assert w.finish(ticket)==OK
    assert w.rw('bind',CONFIG)==CONFLICT
    passed('wrong_task_cannot_receive_or_read_and_permanent_binding_cannot_be_replaced')

    w=Worker();ticket,raw=w.admit();w.run();assert w.rr('finish',ticket)==OK
    assert w.begin_read(w.tag,(0,BUFFER,16))==OK;new=w.ticket();assert new>ticket
    assert w.rr('ready',new)==OK;_,fresh=w.packet(new)
    w.queue.extend([raw,fresh]);w.run()
    assert w.reads==1 and len(w.queue)==1
    w.run();assert w.reads==2 and w.finish(new)==OK
    passed('late_packet_is_discarded_without_reading_or_claiming_the_new_request')

    w=Worker();w.queue.append(struct.pack('<4I',0,0,BUFFER,16));w.run()
    assert w.reads==1 and w.signals==[READ_SEM] and w.word()==0
    w.queue.append(struct.pack('<4I',1,0,123,2));w.run()
    assert w.reads==1 and w.signals==[READ_SEM,READ_SEM+1] and w.word()==0
    passed('ordinary_read_and_seek_follow_original_worker_without_reload_attribution')

    w=Worker();ticket,_=w.admit();put32(w.m,BASE+0x9a4,0);w.run()
    assert not w.reads and w.signals==[READ_SEM] and w.receives==1
    assert w.rr('finish',ticket)==BUSY and w.word()&0x40000000
    passed('stock_missing_handle_signal_cannot_invent_a_successful_read_result')

    w=Worker();w.queue.append(struct.pack('<4I',0xdead,0,0,0));w.run()
    assert w.receives==1 and not w.reads and w.word()&0x40000000
    w.queue.append(struct.pack('<4I',0,0,BUFFER,16));w.run()
    assert w.receives==1 and len(w.queue)==1
    passed('malformed_packet_latches_fault_and_does_not_continue_unverified_file_work')

    out=ROOT/'analysis/read_worker_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Original worker and compiled boundary adapter share one CPU; RTOS copying and reads remain fixtures',
        'Original current-task getter and IPSR thread check execute; no real task scheduling or interrupt test',
        'Call-site PC/LR redirection is emulator supplied, not an installed firmware patch',
        'Yield pauses at a retained state; fixture reenters the worker loop on the next scheduled pass',
        'Producer attribution, matching-wait retry, handle lifetime and startup release still require native binding',
        'No device access or physical memory placement']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
