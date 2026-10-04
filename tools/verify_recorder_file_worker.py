#!/usr/bin/env python3
"""Stock producer/file-worker/token chain inside the queued stop integration.

Uses separate emulator CPUs and explicit kernel-token/queue scheduling, not SD IO.
"""
import hashlib,json,struct
from verify_recorder_stop_integration import RecorderRig
from verify_recording_writer import WriterRig,C
from verify_extra_capture import STREAMS,ELF
from verify_uncompressed_tap import RING,STRIDE
from verify_firmware_workflow import put32,get32
from verify_session_manager import RESET,STOPPED,MAN
from verify_pad_publisher import PublisherRig
from verify_stock_pad_adapter import TEMP
from verify_record_catalogue import putstr
from verify_emulator_bridge import BR
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT,IMAGE

TOKEN=0x21036000

class FileWorkerRig(RecorderRig):
    def __init__(self,failure=None,last_index=10):
        self.clear_later=False
        super().__init__();self.failure=failure;self.last_index=last_index;self.io_events=[];self.file_error=0
        self.order=[s for s in STREAMS if s[0]!=last_index]+[s for s in STREAMS if s[0]==last_index]
    def install_stock_stubs(self):
        super().install_stock_stubs()
        if self.clear_later:self.m.hooks[0x8000b9b8]=lambda a:put32(self.m,C+0x1e48,0) or 0
    def prepare_stock_stop(self,frames):
        super().prepare_stock_stop(frames)
        # Previous blocks exist, but the final 64 samples must actually pass
        # through stock source reader -> producer -> file worker in this test.
        for index,channels in STREAMS:
            h=self.handles[index];n=64*channels*4
            del self.sd.files[h][-n:];self.sd.cursor[h]-=n
            put32(self.m,C+0x454+index*4,frames-64)
    def drain_schedule(self,a):
        assert self.waits==0 and not self.closed
        self.waits+=1
        producer=WriterRig();p=producer.m
        p.uc.mem_write(C,self.raw(C,0x4000))
        put32(p,0x804467f8,TOKEN);put32(p,C+0x1e20,0x80037359)
        for fn in (0x800376a0,0x80037638):p.hooks.pop(fn,None)
        p.hooks[0x8001aaa0]=lambda a:0;p.hooks[0x8001aab8]=lambda a:0
        put32(p,C+0x1de0,0x80037591)
        worker=WriterRig();w=worker.m
        worker.files=self.sd.files;worker.cursor=self.sd.cursor
        put32(w,0x804467f8,TOKEN)
        queue=[];available=[True];current=[None]
        def receive(args):
            if not queue:return stop(w)
            msg=queue.pop(0);op,index,ptr,n=struct.unpack('<4I',msg)
            current[0]=index
            # Shared-buffer visibility is modeled at consumption, not at send.
            w.uc.mem_write(ptr,bytes(p.uc.mem_read(ptr,n)))
            w.uc.mem_write(args[1],msg)
            self.io_events.append(['worker_receive',index,n]);return 0
        def write(args):
            index=current[0]
            worker.fail_write=self.failure if index==self.last_index else None
            self.io_events.append(['write_attempt',index,args[2]])
            return worker.write(args)
        def give(args):
            assert args[0]==TOKEN and not available[0]
            available[0]=True
            self.io_events.append(['worker_ack',current[0],get32(w,C+0x1e48)])
            return 1
        w.hooks[0x800483a8]=receive;w.hooks[0x800622b0]=write;w.hooks[0x800763d8]=give
        def send(args):
            assert not available[0] and not queue
            msg=bytes(p.uc.mem_read(args[1],16));queue.append(msg)
            _,index,_,n=struct.unpack('<4I',msg)
            self.io_events.append(['enqueue',index,n,hex(struct.unpack('<4I',msg)[2]),bytes(p.uc.mem_read(struct.unpack('<4I',msg)[2],4)).hex()]);return 0
        def wait(args):
            assert args[:2]==[TOKEN,0xffffffff]
            if not available[0]:
                assert len(queue)==1
                index=struct.unpack('<4I',queue[0])[1]
                # While the final write is delayed, execute the stock stop
                # predicate on another CPU; never fake the stream-active mask.
                poll=WriterRig();poll.m.uc.mem_write(C,bytes(p.uc.mem_read(C,0x4000)))
                for _ in range(3):
                    assert poll.m.invoke(0x80037df0,[])==0
                self.io_events.append(['delayed_write_stop_still_waiting',index])
                if index==self.last_index and self.early_worker:
                    self.run_worker_while_stop_pending()
                w.uc.mem_write(C,bytes(p.uc.mem_read(C,0x4000)))
                w.invoke(0x80037380,[])
                put32(p,C+0x1e48,get32(w,C+0x1e48))
            assert available[0]
            available[0]=False;return 1
        def producer_give(args):
            assert args[0]==TOKEN and not available[0]
            available[0]=True;self.io_events.append(['producer_rendezvous_return']);return 1
        p.hooks[0x800483f8]=send;p.hooks[0x80076950]=wait;p.hooks[0x800763d8]=producer_give
        for index,channels in self.order:
            h=self.handles[index]
            for ch in range(channels):producer.floats(RING+(index+ch)*STRIDE,[h/16]*self.capacity)
            put32(p,C+0xec,index);put32(p,C+0xf0,64)
            p.invoke(0x80038e60,[])
            if queue and index!=self.last_index:
                # Let the file task consume each earlier stream before the
                # next producer invocation; only the final write is delayed.
                w.uc.mem_write(C,bytes(p.uc.mem_read(C,0x4000)))
                w.invoke(0x80037380,[])
                put32(p,C+0x1e48,get32(w,C+0x1e48))
        assert not queue and available[0] and get32(p,C+0x440)==0
        assert p.uc.mem_read(C+0xe8,1)==b'\0'
        self.file_error=get32(p,C+0x1e48)
        self.m.uc.mem_write(C,bytes(p.uc.mem_read(C,0x4000)))
        self.io_events.append(['stock_streams_drained',self.file_error])
        return 0
    def assert_stock_files(self):
        assert self.closed==list(range(1,8)) and self.waits==1
        for h,data in self.stock_payloads.items():
            wav=self.sd.files[h]
            if self.failure and h==self.handles[self.last_index]:
                # A stock error is not assumed to produce a usable ordinary WAV.
                assert wav[512:]!=data
            else:
                assert wav[512:]==data,(h,len(wav)-512,len(data),wav[512+len(data)-256:512+len(data)-240].hex(),data[-256:-240].hex(),self.io_events)
                assert struct.unpack_from('<I',wav,4)[0]==len(wav)-8
                assert struct.unpack_from('<I',wav,508)[0]==len(data)
        assert [e[1] for e in self.io_events if e[0]=='worker_ack']==[i for i,_ in self.order]
        assert self.io_events.index(['producer_rendezvous_return'])<self.io_events.index(['stock_streams_drained',self.file_error])

def main():
    results=[]
    for blocks in (2,4):
        r=FileWorkerRig();r.early_worker=True;assert r.take_to_boundary(blocks)==RESET
        assert r.file_error==0 and len(r.peer_observations)==1
        results.append(dict(case=f'original_final_writes_and_completion_token_{blocks*64}_frames',passed=True,events=r.io_events))
    # The old prototype still exposes a result if the new observation hook is
    # disabled: keep the original failure as a reproducible negative control.
    r=FileWorkerRig((0,128));r.drain_hook_enabled=False
    assert r.take_to_boundary()==RESET and r.result()!=12 and r.file_error==0xffffd826
    results.append(dict(case="disabled_observation_reproduces_premature_eligibility_after_failed_stock_write",passed=True))
    for failure,error in [((0,128),0xffffd826),((0xffffd825,0),0xffffd825)]:
        r=FileWorkerRig(failure);r.early_worker=True
        p=PublisherRig(r);p.fenced=True
        old='A:\\SOUND_PAD\\PAD1\\BACKING.WAV'
        p.files[old]=bytearray(p.files[p.take(900)])
        assert p.snapshot(0)[0]==0
        putstr(p.m,TEMP+0x1000,old);p.m.invoke(0x80008dd8,[0,TEMP+0x1000,0])
        assert p.m.invoke(p.m.symbols['od_stock_assign'],[0,TEMP+0x1000,TEMP])==0
        assert p.save()==0
        saved_paths=p.paths();saved={k:bytes(v) for k,v in p.files.items() if k not in r.disk}
        terminal=r.take_to_boundary()
        assert r.file_error==error
        assert terminal==STOPPED and r.result()==12,(terminal,r.result(),hex(r.file_error))
        assert get32(r.m,MAN+4)==33
        p.sync_boundary();assert p.publish()=='busy' and p.paths()==saved_paths
        assert all(bytes(p.files[k])==v for k,v in saved.items())
        results.append(dict(case='failed_last_stock_write_blocks_extra_result_'+hex(error),passed=True,events=r.io_events))
    for index in (0,2):
        r=FileWorkerRig((0,128),index);r.early_worker=True
        assert r.take_to_boundary()==STOPPED and r.result()==12 and get32(r.m,MAN+4)==33
        results.append(dict(case=f'failed_final_channel_stem_{index}_blocks_extra_result',passed=True))
    r=FileWorkerRig((0xffffd825,0));r.clear_later=True;r.early_worker=True
    assert r.take_to_boundary()==STOPPED and r.file_error==0xffffd825
    assert get32(r.m,C+0x1e48)==0 and get32(r.m,MAN+4)==33 and r.result()==12
    results.append(dict(case='error_retained_before_later_cleanup_clears_stock_latch',passed=True))
    r=FileWorkerRig();before=r.raw(BR,r.blayout[0]);put32(r.m,C+0x1e48,0xffffd825)
    r.m.invoke(r.syms['ct_record_drained'],[])
    assert r.raw(BR,r.blayout[0])==before and get32(r.m,C+0x1e48)==0xffffd825
    results.append(dict(case='unowned_observation_does_not_fault_capture_or_clear_stock_error',passed=True))
    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['Separate original producer and file-worker CPUs, with explicit shared-memory/queue/token schedule',
          'Final 64 samples per stream traverse original reader, producer and worker; earlier payload and admission are seeded',
          'SD IO, kernel scheduling, deep postprocessing and native hook placement are not executed',
          'No physical timing, DMA/cache, durability or firmware installation claims'])
    path=ROOT/'analysis/recorder_file_worker_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path))))

if __name__=='__main__':main()
