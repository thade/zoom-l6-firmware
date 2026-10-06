#!/usr/bin/env python3
"""Compiled 16-byte read tickets through stock queue wrappers and file worker.
Kernel copying/waits, task binding and cross-CPU memory sharing are fixtures.
"""
import json
import struct
from verify_reload_read import Reads, Tracked, READ, ARGS
from verify_reload_prefetch import PrefetchRig, FILE_QUEUE, READ_SEM
from verify_reload_ownership import ENV, CTX, WORKER
from verify_work_ownership import OK, BUSY, STALE, CONFLICT, FAULT
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT

TABLE=READ+0x300
TASK=TABLE+0x40
PACKET=TABLE+0x60
ORIGINAL=TABLE+0x80
SECOND=READ+0x200
MAGIC=0x52525131


class QueueReads(Reads):
    def __init__(self):
        super().__init__();put32(self.m,TABLE,READ);put32(self.m,TABLE+4,SECOND)
    def packet(self,ticket,slot=0,read=READ):
        result=self.m.invoke(self.m.symbols['rr_queue_packet'],[read,ticket,slot,PACKET])
        return result,bytes(self.m.uc.mem_read(PACKET,16))
    def decode(self,raw):
        self.m.uc.mem_write(PACKET,bytes(raw))
        status=self.m.invoke(self.m.symbols['rr_queue_decode'],[TABLE,TASK,PACKET,ORIGINAL])
        return status,bytes(self.m.uc.mem_read(ORIGINAL,16))
    def observe(self,status,actual):
        return self.m.invoke(self.m.symbols['rr_queue_observe'],[TASK,status,actual])
    def returned_read(self):return self.m.invoke(self.m.symbols['rr_queue_return'],[TASK])


class Queued(Tracked):
    def __init__(self):
        super().__init__();self.p=QueueReads();self.wire=[];self.after_signal_checks=0
        self.p.m.hooks[0x800763d8]=self.kernel_send
        self.p.m.hooks[0x80076710]=self.kernel_receive
    def kernel_send(self,a):
        assert a[:1]==[FILE_QUEUE] and a[2:4]==[0xffffffff,0]
        raw=bytes(self.p.m.uc.mem_read(a[1],16));self.wire.append(raw)
        if self.reject_send:return 0
        self.io_queue.append(raw);return 1
    def kernel_receive(self,a):
        assert a[0]==FILE_QUEUE and a[2]==0xffffffff
        if not self.io_queue:return 0
        self.p.m.uc.mem_write(a[1],self.io_queue.pop(0));return 1
    def send(self,a):
        if a[0]!=FILE_QUEUE:return PrefetchRig.send(self,a)
        _,pad,buffer,size=struct.unpack('<4I',self.m.uc.mem_read(a[1],16))
        assert self.p.begin_read(self.current,(pad,buffer,size))==OK
        ticket=self.p.ticket();assert self.p.rr('ready',ticket)==OK
        status,raw=self.p.packet(ticket);assert status==OK
        self.read_tickets.append((ticket,struct.unpack('<4I',self.current)[3]))
        self.trace.append(('tagged_submit',pad,size))
        return self.p.m.invoke(0x800483f8,[FILE_QUEUE,PACKET])
    def receive(self,a):
        assert a[0]==FILE_QUEUE
        # This next receive is reached only after the original signal call
        # returned; all current-request buffer access has finished.
        if int.from_bytes(self.p.m.uc.mem_read(TASK+4,4),'little'):
            assert self.signals==[READ_SEM]
            assert self.p.returned_read()==OK
            self.after_signal_checks+=1
        result=self.p.m.invoke(0x800483a8,[FILE_QUEUE,PACKET])
        if result:return stop(self.io_cpu)
        raw=bytes(self.p.m.uc.mem_read(PACKET,16))
        status,original=self.p.decode(raw);assert status==OK
        self.read_pad=struct.unpack('<4I',original)[1]
        self.io_cpu.uc.mem_write(a[1],original);return 0
    def read_samples(self,a):
        result=PrefetchRig.read_samples(self,a)
        actual=int.from_bytes(self.io_cpu.uc.mem_read(a[3],4),'little')
        assert self.p.observe(result,actual)==OK
        # Having the result is not permission to retire while the original
        # worker still may zero-fill and signal using this request.
        assert self.p.rr('finish',self.p.ticket())==BUSY
        return result
    def signal(self,a):
        assert self.p.rr('finish',self.p.ticket())==BUSY
        return super().signal(a)


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    r=Queued();r.run();r.consume();assert r.finish()==OK
    assert len(r.wire)==8 and r.after_signal_checks==8
    assert all(len(raw)==16 and struct.unpack('<4I',raw)[0]==MAGIC for raw in r.wire)
    assert [struct.unpack('<4I',raw)[2] for raw in r.wire]==[t for t,role in r.read_tickets]
    passed('eight_compiled_tickets_cross_stock_send_receive_wrappers_and_original_file_worker')

    for mode in ('error','short'):
        r=Queued();r.read_mode=mode;r.run();r.consume()
        assert r.paths()==r.expected and r.finish()==FAULT and r.after_signal_checks==8
    passed('tagged_public_read_results_preserve_error_and_short_read_rejection')

    r=Queued();r.reject_send=True;r.run()
    assert not r.converted and not r.callback_returns and r.p.finish(r.owner)==BUSY
    assert r.p.rr('finish',r.p.ticket())==BUSY
    passed('undelivered_tagged_request_remains_owned_without_synthetic_reply')

    p=QueueReads();owner,tag=p.prepare();assert p.begin_read(tag)==OK;t=p.ticket()
    assert p.rr('ready',t)==OK;status,raw=p.packet(t);assert status==OK
    assert p.decode(raw)==(OK,struct.pack('<4I',0,0,0x80735b80,8192))
    assert p.decode(raw)[0]==BUSY and p.returned_read()==BUSY
    assert p.observe(0,8192)==OK and p.rr('finish',t)==BUSY
    assert p.observe(0,8192)==CONFLICT
    assert p.returned_read()==OK and p.returned_read()==STALE
    assert p.decode(raw)[0]==STALE and p.rr('finish',t)==OK
    assert p.begin_read(tag)==OK;new=p.ticket();assert new>t
    assert p.rr('ready',new)==OK and p.packet(new)[0]==OK
    assert p.decode(raw)[0]==STALE and p.rr('finish',new)==BUSY
    passed('duplicate_packets_results_and_stale_tickets_cannot_finish_a_reused_slot')

    p=QueueReads();owner,tag=p.prepare();assert p.begin_read(tag)==OK;t=p.ticket()
    assert p.rr('ready',t)==OK;_,first=p.packet(t)
    p.m.uc.mem_write(ENV,tag);p.m.uc.mem_write(ARGS,struct.pack('<3I',2,0x80735c80,256))
    assert p.m.invoke(p.m.symbols['rr_begin'],[CTX,SECOND,ENV,ARGS])==OK
    second_ticket=int.from_bytes(p.m.uc.mem_read(SECOND+8,4),'little')
    assert p.m.invoke(p.m.symbols['rr_ready'],[CTX,SECOND,second_ticket])==OK
    _,second=p.packet(second_ticket,1,SECOND)
    for packet,read,ticket,count in ((second,SECOND,second_ticket,256),(first,READ,t,8192)):
        assert p.decode(packet)[0]==OK and p.observe(0,count)==OK
        assert p.returned_read()==OK
        assert p.m.invoke(p.m.symbols['rr_finish'],[CTX,read,ticket])==OK
    p.returned(owner,tag);assert p.rl('verify',owner,1)==OK and p.finish(owner)==OK
    passed('reversed_delivery_of_two_slots_uses_packet_identity_not_FIFO_matching')

    p=QueueReads();owner,tag=p.prepare();assert p.begin_read(tag)==OK;t=p.ticket()
    assert p.rr('ready',t)==OK;_,raw=p.packet(t)
    words=list(struct.unpack('<4I',raw))
    for field,value in ((0,0xdead),(1,8),(2,0),(3,1)):
        bad=words.copy();bad[field]=value
        assert p.decode(struct.pack('<4I',*bad))[0]==CONFLICT
    put32(p.m,READ,1);assert p.decode(raw)[0]==BUSY
    put32(p.m,READ,0);assert p.decode(raw)[0]==OK and p.observe(0,8192)==OK
    put32(p.m,READ,1);assert p.returned_read()==BUSY
    put32(p.m,READ,0);assert p.returned_read()==OK and p.rr('finish',t)==OK
    passed('malformed_packets_rejected_and_contended_decode_return_retain_read_identity')

    p=QueueReads()
    for kind in (0,1):
        raw=struct.pack('<4I',kind,3,0x1234,512)
        assert p.decode(raw)==(6,raw) and p.observe(0,512)==STALE
    passed('ordinary_stock_read_and_seek_packets_forward_without_fabricated_reload_evidence')
    out=ROOT/'analysis/reload_read_queue_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Kernel queue copy and scheduling are fixtures; original 16-byte wrappers execute',
        'Compiler performs encoding, slot/ticket matching and result attribution; no Python FIFO identity sidecar',
        'Producer envelope binding, file-task identity, call-site interception and cross-CPU sharing remain harness supplied',
        'Native receive loop must retain a dequeued packet on BUSY and retry return before another receive',
        'No hook installation, startup release, device access or physical RAM placement']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
