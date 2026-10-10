#!/usr/bin/env python3
"""Original producer/writer staging under explicitly controlled schedules.

Two CPU contexts share pointed-to payload bytes at consumption, never a send-time
copy. Kernel scheduling/tokens and disk IO are modeled. No device or image edits.
"""
import hashlib,json,struct
from verify_recording_writer import WriterRig,C
from verify_uncompressed_tap import RING,STRIDE,packed
from verify_firmware_workflow import put32,get32
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT,IMAGE

TOKEN=0x21035000
BUFFER0=0x807c6d28
BUFFER_STRIDE=0x80400

class StagingRig:
    def __init__(self,final=False,immediate=False,failure=None):
        self.producer=WriterRig();self.worker=WriterRig()
        p=self.producer;m=p.m;w=self.worker;wm=w.m
        p.files={1:bytearray(),2:bytearray()};p.cursor={1:0,2:0}
        w.files=p.files;w.cursor=p.cursor;w.fail_write=failure
        m.hooks.pop(0x800374f0,None)
        put32(m,0x804467f8,TOKEN);put32(wm,0x804467f8,TOKEN)
        self.available=True;self.queue=[];self.sent=[];self.consumed=[];self.events=[]
        self.final=final;self.immediate=immediate
        self.overwrites=[]
        m.hooks[0x80076950]=self.take;m.hooks[0x800483f8]=self.send
        wm.hooks[0x800483a8]=self.receive;wm.hooks[0x800763d8]=self.give
        from unicorn import UC_HOOK_MEM_WRITE
        def track(uc,access,address,size,value,user):
            for _,_,ptr,n in self.sent[len(self.consumed):]:
                if address<ptr+n and ptr<address+size:
                    self.overwrites.append(dict(address=hex(address),bytes=size))
        m.uc.hook_add(UC_HOOK_MEM_WRITE,track,begin=BUFFER0,end=BUFFER0+2*BUFFER_STRIDE-1)

    def receive(self,a):
        if not self.queue:return stop(self.worker.m)
        msg=self.queue.pop(0);_,index,ptr,n=struct.unpack('<4I',msg)
        payload=bytes(self.producer.m.uc.mem_read(ptr,n))
        self.worker.m.uc.mem_write(ptr,payload);self.worker.m.uc.mem_write(a[1],msg)
        self.consumed.append((index,payload));self.events.append(['receive',index,hex(ptr),n])
        return 0
    def give(self,a):
        assert a[0]==TOKEN and not self.available
        self.available=True;self.events.append(['ack',get32(self.worker.m,C+0x1e48)])
        return 1
    def consume(self):
        assert len(self.queue)==1 and not self.available
        self.worker.m.uc.mem_write(C,bytes(self.producer.m.uc.mem_read(C,0x4000)))
        self.worker.m.invoke(0x80037380,[])
        put32(self.producer.m,C+0x1e48,get32(self.worker.m,C+0x1e48))
        assert self.available and not self.queue
    def take(self,a):
        assert a[:2]==[TOKEN,0xffffffff]
        self.events.append(['take_entry',self.available])
        if not self.available:self.consume()
        assert self.available;self.available=False;return 1
    def send(self,a):
        assert not self.available and not self.queue
        msg=bytes(self.producer.m.uc.mem_read(a[1],16))
        request=struct.unpack('<4I',msg);assert request[0]==0
        self.queue.append(msg);self.sent.append(request)
        self.events.append(['send',request[1],hex(request[2]),request[3]])
        if self.immediate:self.consume()
        return 0
    def run(self):
        p=self.producer;m=p.m;expected={}
        for stream,handle in ((2,1),(10,2)):
            p.index=stream;p.channels=2;p.frames=64;p.position=0
            put32(m,C+0x1e4c+stream*4,handle)
            put32(m,C+0x444,1<<stream);m.uc.mem_write(C+0x448+stream,b'\x20')
            for offset in (0x514,0x4e4,0x4b4):put32(m,C+offset+stream*4,100000)
            if self.final:put32(m,C+0x4e4+stream*4,64)
            values=[handle/8,handle/8+1/16]
            for lane,v in enumerate(values):p.floats(RING+(stream+lane)*STRIDE,[v]*128)
            expected[handle]=packed(values*64)
            p.produce()
        if self.queue:self.consume()
        assert not self.queue and self.available
        return expected

def main():
    results=[]
    def passed(case,r,**details):
        results.append(dict(case=case,passed=True,requests=[list(q[:2])+[hex(q[2]),q[3]] for q in r.sent],
                            events=r.events,pending_payload_writes=len(r.overwrites),**details))
    r=StagingRig();want=r.run()
    assert all(r.worker.files[h]==v for h,v in want.items()) and not r.overwrites
    assert [q[2] for q in r.sent]==[BUFFER0,BUFFER0+BUFFER_STRIDE]
    passed('delayed_nonfinal_requests_use_distinct_buffers_and_preserve_two_stereo_payloads',r)
    r=StagingRig(final=True,immediate=True);want=r.run()
    assert all(r.worker.files[h]==v for h,v in want.items()) and not r.overwrites
    assert [q[2] for q in r.sent]==[BUFFER0,BUFFER0]
    passed('immediate_final_stream_service_preserves_payload_before_same_buffer_reuse',r)
    r=StagingRig(final=True);want=r.run()
    assert r.worker.files[1]!=want[1] and r.worker.files[1]==want[2]
    assert r.worker.files[2]==want[2] and r.overwrites
    assert [q[2] for q in r.sent]==[BUFFER0,BUFFER0]
    assert r.events.index(['take_entry',False])>r.events.index(['send',2,hex(BUFFER0),512])
    passed('negative_control_final_stream_changes_overwrite_pending_payload_before_next_token_wait',r,
           reproduced_device_defect=False,explanation='Controlled schedule demonstrates missing lifetime proof; no claim this schedule occurs on hardware.')
    for failure,error in (((0,128),0xffffd826),((0xffffd825,0),0xffffd825)):
        r=StagingRig(failure=failure);r.run()
        assert [e for e in r.events if e[0]=='ack'] and all(e[1]==error for e in r.events if e[0]=='ack')
        passed('delayed_worker_acknowledges_native_failed_attempt_'+hex(error),r,
               acknowledgement_is_io_success=False)
    report=dict(passed_groups=len(results),results=results,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        production_changes=False,device_access=False,
        limitations=['Original producer/worker bodies on two CPU contexts; queue, token, request metadata and disk calls modeled.',
          'Files receive bytes from live shared staging at consumption. The recorded source is two synthetic 64-frame stereo streams.',
          'No complete RTOS priorities/scheduling, SD buffer lifetime, physical completion or actual extra service is exercised.',
          'The negative control excludes treating arbitrary delay at the stock writer as a proven safe integration contract.'])
    out=ROOT/'analysis/native_writer_staging_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out))))

if __name__=='__main__':main()
