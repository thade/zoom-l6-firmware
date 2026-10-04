#!/usr/bin/env python3
"""Execute the stock stop backend inside the compiled capture/manager route.

Original firmware is unmodified; queue scheduling, DSP and SD effects are fixtures.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_PC
from verify_session_manager import ManagerRig,MAN,RESET,STOPPED,BLOCKED,FINISH
from verify_recording_writer import WriterRig,C
from verify_stem_completion import calls,STATE as REC
from verify_extra_capture import STREAMS,ELF,STATE as ARENA
from verify_history_capture import payload
from verify_firmware_workflow import put32,get32
from verify_pad_protocol import ROOT,IMAGE
from verify_pad_publisher import PublisherRig
from verify_stock_pad_adapter import TEMP
from verify_record_catalogue import putstr

class RecorderRig(ManagerRig):
    def __init__(self):
        self.native_stop=False;self.events=[];self.waits=0;self.early_worker=False
        self.peer_observations=[]
        self.drain_hook_enabled=True
        super().__init__()
        self.sd=WriterRig();self.sd.m=self.m
        self.sd.files={};self.sd.cursor={};self.stock_payloads={};self.closed=[]
        def observe(uc,address,size,_):
            if not self.native_stop:return
            if address==0x8000b698:self.events.append(['stock_stop_enter'])
            elif address==0x8000ea08:
                h=uc.reg_read(UC_ARM_REG_R0)
                index=next(i for i,v in self.handles.items() if v==h)
                assert get32(self.m,C+0x4e4+index*4)==self.expected_frames
                self.events.append(['stock_finalize',h])
            elif address==0x800032b0:self.events.append(['stock_postprocess'])
            elif address==0x8000b9b2:self.events.append(['stock_stop_return'])
        for a in (0x8000b698,0x8000ea08,0x800032b0,0x8000b9b2):
            self.m.uc.hook_add(UC_HOOK_CODE,observe,begin=a,end=a)
        def drained(uc,address,size,_):
            if self.native_stop and self.drain_hook_enabled:
                uc.reg_write(UC_ARM_REG_PC,self.syms['emulator_recorder_drained_hook'])
        self.m.uc.hook_add(UC_HOOK_CODE,drained,begin=0x8000b78c,end=0x8000b78c)
    def install_stock_stubs(self):
        super().install_stock_stubs()
        if self.native_stop:self.install_recorder_stop()
    def install_recorder_stop(self):
        m=self.m
        m.hooks.pop(0x8000b698,None)
        for fn in calls(0x8000b698,0x8000b9b4):m.hooks[fn]=lambda a:0
        for fn in (0x80037dc0,0x80037d68,0x80037d98,0x80037df0,0x80002360,
                   0x80006168,0x800382a8,0x80037e98,0x80037e58,0x8000ea08,
                   0x800380d0,0x800032b0):m.hooks.pop(fn,None)
        m.hooks[0x80077686]=self.drain_schedule
        for fn in calls(0x800032b0,0x800035c8):m.hooks[fn]=lambda a:0
        m.hooks.pop(0x8000178e,None)
        m.hooks[0x80022c78]=lambda a:int(a[0] in self.handles)
        m.hooks[0x80022bd0]=lambda a:1
        m.hooks[0x80004868]=lambda a:self.events.append(['stock_process_stream',a[0]]) or 0
        m.hooks[0x800035d0]=lambda a:0
        m.hooks.update({0x800622b0:self.mux_write,0x80060620:self.mux_read,
            0x8005f168:self.mux_seek,0x8005ef40:self.mux_info,0x8005c1f8:self.mux_close})
    def mux_write(self,a):return self.sd.write(a) if a[0]<100 else self.write_file(a)
    def mux_read(self,a):return self.sd.read(a) if a[0]<100 else self.read_file(a)
    def mux_seek(self,a):return self.sd.seek(a) if a[0]<100 else self.seek_file(a)
    def mux_info(self,a):return self.sd.stat(a) if a[0]<100 else self.info_file(a)
    def mux_close(self,a):
        if a[0]<100:
            assert a[0] not in self.closed
            self.closed.append(a[0]);self.events.append(['stock_close',a[0]]);return 0
        self.events.append(['extra_close',int(bool(self.opened[a[0]][2]))])
        return self.close_file(a)
    def prepare_stock_stop(self,frames):
        # Ordinary file payloads are seeded, not recorded by this fixture. Their
        # actual headers are finalized by the original stop routine below.
        self.expected_frames=frames
        put32(self.m,C+0x50,self.capacity)
        for index,channels in STREAMS:
            # Model one final block outstanding at the shared saved endpoint.
            put32(self.m,C+0x20+index*4,(self.sequence-64)%self.capacity)
            put32(self.m,C+0x484+index*4,frames-64)
            h=self.handles[index];template=WriterRig(index,channels);template.header()
            data=struct.pack('<%df'%(frames*channels),*([h/16]*(frames*channels)))
            self.stock_payloads[h]=data;self.sd.files[h]=template.files[1]+data
            self.sd.cursor[h]=512+len(data)
            put32(self.m,C+0x1e4c+index*4,h);put32(self.m,C+0x454+index*4,frames)
            self.m.uc.mem_write(C+0x448+index,b'\x20')
        put32(self.m,C+8,0x557);put32(self.m,C+0x444,0x554)
        put32(self.m,C+0x440,0x557)
        self.m.uc.mem_write(C+0xe8,b'\0')
        self.m.uc.mem_write(REC+0x2c,b'\x01')
        self.m.uc.mem_write(REC+8,bytes([2,0,1,1,0]))
        self.native_stop=True;self.install_recorder_stop()
    def drain_schedule(self,a):
        assert not self.closed
        self.waits+=1;self.events.append(['stock_drain_wait',self.waits])
        if self.early_worker and self.waits==1:self.run_worker_while_stop_pending()
        if get32(self.m,C+0x440):
            put32(self.m,C+0x440,0);self.m.uc.mem_write(C+0xe8,b'\x01')
        else:self.m.uc.mem_write(C+0xe8,b'\0')
        return 0
    def run_worker_while_stop_pending(self):
        # Independent CPU: optional file may finish while RecPlayCtl is paused.
        # Transfer only prototype global/session RAM and its file effects back.
        peer=ManagerRig()
        for a,n in ((0x10010000,0x10000),(ARENA,0x20000)):
            peer.m.uc.mem_write(a,self.raw(a,n))
        peer.disk={p:bytearray(v) for p,v in self.disk.items()}
        peer.opened={h:list(v) for h,v in self.opened.items()};peer.next_handle=self.next_handle
        peer.counts=self.counts.copy();peer.calls=self.calls.copy();peer.session=self.session
        for _ in range(200):
            peer.tick()
            if not peer.opened:break
        assert peer.mstate()==FINISH and not peer.opened
        for _ in range(3):assert peer.tick()==11
        assert peer.result()==12 and not peer.wire and not peer.eligible()
        self.peer_observations.append(dict(file_closed=True,result_withheld=True,marker_not_sent=True))
        for a,n in ((0x10010000,0x10000),(ARENA,0x20000)):
            self.m.uc.mem_write(a,peer.raw(a,n))
        self.disk=peer.disk;self.opened=peer.opened;self.next_handle=peer.next_handle
        self.counts=peer.counts;self.calls=peer.calls
    def assert_stock_files(self):
        assert self.closed==list(range(1,8)) and self.waits==2
        for h,data in self.stock_payloads.items():
            wav=self.sd.files[h]
            assert wav[512:]==data
            assert struct.unpack_from('<I',wav,4)[0]==len(wav)-8
            assert struct.unpack_from('<I',wav,508)[0]==len(data)
        assert [e[1] for e in self.events if e[0]=='stock_process_stream']==[i for i,_ in STREAMS]
        assert get32(self.m,C+8)==0
    def take_to_boundary(self,blocks=2):
        self.audio_call();start=self.sequence
        self.request();self.dispatch_all()
        for _ in range(blocks):self.audio_call();self.tick()
        self.prepare_stock_stop(blocks*64)
        self.request(1);self.dispatch_all()
        self.drive(lambda:self.mstate() in (RESET,STOPPED,BLOCKED),with_audio=False)
        self.assert_stock_files()
        if self.mstate()==RESET:
            session,path=self.result();assert session==123
            data=self.disk[path]
            assert data[512:]==payload(start,start+blocks*64)
            assert struct.unpack_from('<I',data,508)[0]==blocks*64*8
            assert not self.opened
        return self.mstate()

def main():
    results=[]
    def passed(case,**details):results.append(dict(case=case,passed=True,**details))
    r=RecorderRig();assert r.take_to_boundary()==RESET
    assert r.events.index(['stock_close',7])<r.events.index(['extra_close',1])
    p=PublisherRig(r);p.fenced=True
    assert p.publish()=='ok' and p.history()==[r.result()[1]]
    passed('stock_queued_stop_closes_seven_ordinary_WAVs_then_extra_verification_manager_result_and_pad_publication',
           events=r.events,extra_frames=128)

    r=RecorderRig();assert r.take_to_boundary(blocks=4)==RESET
    passed('saved_stop_cursor_wrap_gives_matching_256_frame_limits_and_exact_extra_payload')

    r=RecorderRig();r.early_worker=True;assert r.take_to_boundary()==RESET
    assert r.peer_observations==[dict(file_closed=True,result_withheld=True,marker_not_sent=True)]
    passed('extra_file_can_finish_during_stock_drain_but_manager_withholds_result_until_stop_callback_and_fence_finish',
           observations=r.peer_observations)

    for operation,kind,terminal in [('audio','short',STOPPED),('final_header','error',STOPPED),
                                    ('close_write','error',BLOCKED),('read_audio','error',STOPPED)]:
        r=RecorderRig();p=PublisherRig(r);p.fenced=True
        # Establish a prior backing via the stock adapter, independently of
        # the manager visitor; the failed new take must leave it untouched.
        old='A:\\SOUND_PAD\\PAD1\\BACKING.WAV'
        p.files[old]=bytearray(p.files[p.take(900)])
        assert p.snapshot(0)[0]==0
        putstr(p.m,TEMP+0x1000,old)
        p.m.invoke(0x80008dd8,[0,TEMP+0x1000,0])
        assert p.m.invoke(p.m.symbols['od_stock_assign'],[0,TEMP+0x1000,TEMP])==0
        assert p.save()==0 and p.paths()[0]==old
        old_paths=p.paths();old_files={k:bytes(v) for k,v in p.files.items() if k not in r.disk}
        r.inject=(operation,r.counts.get(operation,0)+1,kind)
        assert r.take_to_boundary()==terminal and r.result()==12
        p.sync_boundary();before={k:bytes(v) for k,v in p.files.items()}
        assert p.publish()=='busy'
        assert p.paths()==old_paths and before=={k:bytes(v) for k,v in p.files.items()}
        assert all(bytes(p.files[k])==v for k,v in old_files.items())
        passed('extra_'+operation+'_failure_preserves_previous_pad_and_all_ordinary_WAVs',manager_state=terminal)

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['Emulator integration only: original images are unchanged; no installed hook or task',
          'Original queued stop, backend, endpoint-limit helper, predicates, WAV finalizers and postprocessing dispatcher execute',
          'Ordinary payloads and registration are seeded; final drain, deep postprocessing, filesystem and kernel scheduling are modeled',
          'One controlled two-CPU interleaving transfers prototype RAM and optional-file effects, not a complete RTOS simulation',
          'Pad publication uses the existing explicit modeled playback fence; native exclusion/reload not established by this suite',
          'No physical SD, DMA, time budget, whole-song stress, bootloader recovery or power-loss durability proof'])
    path=ROOT/'analysis/recorder_stop_integration_verification.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path))))

if __name__=='__main__':main()
