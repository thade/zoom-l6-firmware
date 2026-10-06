#!/usr/bin/env python3
"""Direct reload prefetch through the original sample file-task handshake.

Two emulator CPUs with explicit shared-state copies at semaphore waits. WAV
parsing, conversion, public file reads and RTOS scheduling remain fixtures.
"""
import hashlib
import json
import struct
from verify_pad_reload import ReloadRig, BUSY_WORD
from verify_overdub_prototype import Emulator
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop, BASE
from verify_pad_protocol import ROOT, IMAGE

FILE_QUEUE=0x7000
READ_SEM=0x7001
SCRATCH=0x80735b80
CONVERT=0x21000300


class PrefetchRig(ReloadRig):
    def __init__(self):
        super().__init__()
        self.io_cpu=Emulator();self.io_queue=[];self.trace=[];self.converted=[]
        self.read_mode='normal';self.reject_send=False;self.signals=[]
        m=self.m
        # Restore stock engine-state setters previously replaced by fixtures.
        for fn in (0x800368a8,0x800367b8,0x80036818,0x800367e8,0x800368d8,
                   0x80036800,0x80036938,0x80036950,0x800368f0,0x80036908,
                   0x80036920,0x800366f8,0x80036860,0x800368c0,0x800369a8):
            del m.hooks[fn]
        m.hooks[0x80074440]=lambda a:0
        m.invoke(0x80036688,[]) # Actual callback initialization, including read/seek.
        for pad in range(4):m.invoke(0x800367d0,[pad,CONVERT|1])
        for cpu in (m,self.io_cpu):
            put32(cpu,0x801f8f30,FILE_QUEUE);put32(cpu,0x804467fc,READ_SEM)
        m.hooks[0x800483f8]=self.send
        m.hooks[0x80076950]=self.wait
        m.hooks[CONVERT]=self.convert
        for fn in (0x8001aaa0,0x8001aab8):m.hooks[fn]=lambda a:0
        self.io_cpu.hooks.update({0x800483a8:self.receive,0x80060620:self.read_samples,
                                  0x800763d8:self.signal})

    def parse_wav(self,a):
        status=super().parse_wav(a)
        if status==0 and a[4]:
            # The fixture parser supplies sample frames, not raw byte length,
            # to the original loader/prefetch. This is not a parser audit.
            data=self.files[self.handles[a[0]][0]]
            fmt=data.find(b'fmt ');offset=data.find(b'data')+8
            channels=struct.unpack_from('<H',data,fmt+10)[0]
            bits=struct.unpack_from('<H',data,fmt+22)[0]
            self.m.uc.mem_write(a[4],struct.pack('<Q',(len(data)-offset)//(channels*bits//8)))
        return status

    def send(self,a):
        if a[0]!=FILE_QUEUE:return super().enqueue(a)
        message=bytes(self.m.uc.mem_read(a[1],16))
        kind,pad,buffer,size=struct.unpack('<4I',message)
        assert kind==0
        self.trace.append(('submit_read',pad,size))
        if not self.reject_send:self.io_queue.append(message)
        return 0xffffffff if self.reject_send else 0

    def wait(self,a):
        if a[0]!=READ_SEM:return 1
        self.trace.append(('wait',len(self.io_queue)))
        if not self.io_queue:
            # Simulate the original infinite semaphore wait as suspended, not
            # as success or a timeout. No real-time scheduler is being run.
            self.trace.append(('suspended',));return stop(self.m)
        self.io_cpu.uc.mem_write(BASE,bytes(self.m.uc.mem_read(BASE,0x9f0)))
        self.io_cpu.uc.mem_write(SCRATCH,b'\xa5'*0x46a00)
        self.signals=[];self.io_cpu.invoke(0x80036118,[])
        assert self.signals==[READ_SEM] and not self.io_queue
        self.m.uc.mem_write(BASE,bytes(self.io_cpu.uc.mem_read(BASE,0x9f0)))
        self.m.uc.mem_write(SCRATCH,bytes(self.io_cpu.uc.mem_read(SCRATCH,0x46a00)))
        self.trace.append(('wait_return',))
        return 1

    def receive(self,a):
        assert a[0]==FILE_QUEUE
        if not self.io_queue:return stop(self.io_cpu)
        raw=self.io_queue.pop(0);self.read_pad=struct.unpack('<4I',raw)[1]
        self.io_cpu.uc.mem_write(a[1],raw);return 0

    def read_samples(self,a):
        h,buffer,size,out=a[:4];path,pos=self.handles[h]
        self.trace.append(('read',self.read_pad,size))
        data=bytes(self.files[path][pos:pos+size])
        if self.read_pad==0 and self.read_mode=='error':
            put32(self.io_cpu,out,0);return 0xffffd825
        if self.read_pad==0 and self.read_mode=='short':data=data[:-64]
        self.io_cpu.uc.mem_write(buffer,data);put32(self.io_cpu,out,len(data))
        self.handles[h][1]+=len(data);self.sync(h)
        return 0

    def signal(self,a):
        self.signals.append(a[0]);self.trace.append(('signal',a[0]));return 1

    def convert(self,a):
        buffer,frames,dest,pad,channels,width=a[:6]
        assert self.trace[-1]==('wait_return',)
        data=bytes(self.m.uc.mem_read(buffer,frames*channels*width))
        self.converted.append((pad,data));self.trace.append(('convert',pad,len(data)))
        return len(data) # Conversion is a fixture; no rendered-audio claim.

    def event(self,a):
        self.trace.append(('reload_event',len(self.converted),len(self.io_queue)))
        return super().event(a)

    def errors(self):return [self.word(BASE+0x9b0+20*p) for p in range(4)]


def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,**kw))
    r=PrefetchRig();r.run()
    assert r.paths()==r.expected and len(r.converted)==4 and not r.io_queue
    assert r.trace[-1]==('reload_event',4,0) and r.word(BUSY_WORD)==1
    for pad,data in r.converted:
        raw=r.files[r.expected[pad]];assert data==bytes(raw[raw.find(b'data')+8:])
    assert r.errors()==[0]*4
    passed('four_original_direct_prefetches_join_file_worker_reads_before_reload_event',trace=r.trace)

    r.consume()
    assert len(r.converted)==8 and r.word(BUSY_WORD)==0 and not r.io_queue
    for pad,data in r.converted[4:]:
        raw=r.files[r.expected[pad]];assert data==bytes(raw[raw.find(b'data')+8:])
    assert r.errors()==[0]*4
    passed('UI_reload_performs_four_more_joined_prefetches_before_clearing_busy')

    r=PrefetchRig();r.read_mode='error';r.run();r.consume()
    assert r.errors()==[0xffffd825,0,0,0] and r.word(BUSY_WORD)==0
    assert r.paths()==r.expected and len(r.converted)==8 and not r.io_queue
    assert r.callback_returns==[0]
    assert r.converted[0][1]==b'\xa5'*8192
    passed('read_failure_is_latched_but_event_paths_and_cleared_busy_still_look_successful',
           limitation='Poison scratch is fixture evidence of continued conversion, not claimed device output')

    r=PrefetchRig();r.read_mode='short';r.run();r.consume()
    assert r.errors()==[0]*4 and r.word(BUSY_WORD)==0 and r.paths()==r.expected
    raw=r.files[r.expected[0]];expected=bytes(raw[raw.find(b'data')+8:])
    assert r.converted[0][1]==expected[:-64]+bytes(64)
    passed('successful_short_read_is_zero_filled_without_error_latch_so_length_needs_observation')

    r=PrefetchRig();r.reject_send=True;r.run()
    assert r.trace[-1]==('suspended',) and not r.converted and not r.callback_returns
    assert r.word(BUSY_WORD)==1 and not any(e[0]=='event' for e in r.events_reload)
    passed('failed_undelivered_read_send_reaches_wait_without_reload_completion')

    out=ROOT/'analysis/reload_prefetch_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(checks),results=checks,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
            'Original reload, direct prefetch, read-request producer, sample file worker and UI reload execute',
            'Two CPUs copy sampler state and scratch at explicit semaphore waits, not concurrent RTOS emulation',
            'Public file read, RIFF parsing, conversion, settings input/save and driver synchronization are fixtures',
            'Only examined direct startup/reload reads are joined; periodic refill/card/USB exclusion remains open',
            'No readiness release hook or firmware patch is installed; no device access']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(checks))))


if __name__=='__main__':main()
