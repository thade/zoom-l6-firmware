#!/usr/bin/env python3
"""Capture-only composition beside all seven stock files, entirely offline.

Uses the normal capture-only ELF, original DSP/stream/control instruction
windows, compiled worker/manager and modeled synchronous files/queues. The
harness schedules windows within a logical callback; it does not run full DSP,
boot, RTOS, SD/DMA or install a patch.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_PROT_NONE,UC_PROT_ALL
from unicorn import arm_const as A
from verify_extra_lifecycle import LifeRig,LIFE
from verify_extra_capture import STATE,STREAMS
from verify_recording_writer import WriterRig,C
from verify_uncompressed_tap import B,MIX,packed
from verify_block_exchange import P,SLOTS
from verify_emulator_bridge import BR,HOOKS
from verify_request_router import ROUTER
from verify_session_manager import ManagerRig,MAN,LIVE,ACTIVATE,STOPPED,BLOCKED,RESET
from verify_session_handover import DESC
from verify_native_worker import WorkerRig,WORKER,CONFIG,HANDLE,SCHEDULER
from verify_control_transport import T,TASK,PRODUCER,WORKER as CONTROL_TASK,QHANDLE,assert_fifo_send
from verify_auto_requests import ENTRIES
from verify_record_scheduler import word,request_setup
from verify_record_events import TARGET
from verify_firmware_workflow import put32
from verify_record_catalogue import BASE
from verify_pad_protocol import ROOT,IMAGE
from verify_scheduling_boundaries import stop

FILE_QUEUE=0x21032010
FILE_TASK=0x21033200
DEEP_STUBS=(0x80008a60,0x8001e4d8,0x80007c20,0x80008a70,0x8000b320,0x8000b330,
    0x8000b698,0x8000acf0,0x8000b9b8,0x80008a80,0x80008880,0x80008890,0x800068c8,
    0x8000bab8,0x8000bbe8,0x80020360,0x80006968,0x80006740,0x8000ac00)

class IntegrationRig(LifeRig):
    elf_path=ROOT/'src/capture/capture-only.elf'
    mstate=ManagerRig.mstate
    result=ManagerRig.result
    drive=ManagerRig.drive
    cancel=ManagerRig.cancel
    resume=ManagerRig.resume
    release=WorkerRig.release
    tick=WorkerRig.tick
    loops=WorkerRig.loops

    def __init__(self,enabled=True,count=32,create_failure=False):
        super().__init__();m=self.m
        # Shared machine construction maps the historical overdub ELF. Make it
        # inaccessible: this composition may execute only the capture-only code.
        m.uc.mem_protect(0x10000000,0x10000,UC_PROT_NONE)
        excluded=('audio_fixture_','history_','na_','backing_','bn_')
        if not getattr(self,'sd_retained_fixture',False):excluded+=('sdp_',)
        assert not any(n.startswith(excluded) for n in self.syms)
        self.enabled=enabled;self.session=123;self.sequence=0;self.capacity=256
        self.audio_cursor=0;self.audio_active=False;self.queued_record=False;self.recording=False
        self.pending_stock=[];self.expected={h:[] for h in range(1,8)};self.expected_extra=[]
        self.wire=[];self.sent=[];self.send_result=0;self.entries=[];self.creates=[]
        self.pad_before=self.raw(BASE,0xb10)
        self.mlayout=struct.unpack('<7I',self.raw(self.syms['manager_layout'],28))
        self.wlayout=struct.unpack('<5I',self.raw(self.syms['native_worker_layout'],20))
        self.xlayout=struct.unpack('<7I',self.raw(self.syms['exchange_layout'],28))
        m.uc.mem_map(SLOTS,(count*self.xlayout[1]+4095)&~4095)
        arenas=(T,ROUTER,BR,P,LIFE,STATE)
        layouts=('ct_layout','rr_layout','bridge_layout','exchange_layout','life_layout','extra_layout')
        for addr,name in zip(arenas,layouts):m.uc.mem_write(addr,b'\xa5'*word(m,self.syms[name]))
        m.uc.mem_write(SLOTS,b'\xa5'*(count*self.xlayout[1]))
        m.uc.mem_write(MAN,bytes(self.mlayout[0]));m.uc.mem_write(WORKER,bytes(self.wlayout[0]))
        m.uc.mem_write(DESC,struct.pack('<10I',*arenas,SLOTS,count,self.session,QHANDLE))
        m.uc.mem_write(CONFIG,struct.pack('<5I',4096,1,4,1,25)) # experimental budgets
        m.uc.mem_map(0xe000e000,0x1000)
        for addr,value in ((TASK,PRODUCER),(SCHEDULER,0),(0x801f8f38,QHANDLE),
                (0x801f8f2c,FILE_QUEUE),(0x80446dc0,CONTROL_TASK),(0x80446894,0x21033300),
                (B+0x53e8,self.capacity),(B+0x53c8,0x2022a791)):
            put32(m,addr,value)
        put32(m,C+0x440,0x557);m.uc.mem_write(TARGET,b'\xff')
        self.files={h:bytearray() for h in range(1,8)};self.cursor={h:0 for h in range(1,8)}
        # Public synchronous I/O is modeled. Stock and extra files share one CPU,
        # but use distinct handles and independent format/lifecycle state.
        m.hooks.update({0x800622b0:self.io_write,0x80060620:self.io_read,
            0x8005f168:self.io_seek,0x8005ef40:self.io_info,
            0x800763d8:self.kernel_send,0x800483a8:self.receive,
            0x80076950:lambda a:1,0x80010150:lambda a:0,
            0x800376a0:lambda a:WriterRig.request(self,a)})
        for fn in DEEP_STUBS:m.hooks[fn]=lambda a:0
        del m.hooks[0x800483f8] # compiled sender must own both queue paths
        # Deep file registration is modeled; original start/stop setters and
        # queue dispatch execute. This checkpoint is NOT a device admission hook.
        self.redirect(0x8000b650,'ct_emulator_admit',always=True)
        for addr,name in ENTRIES.items():self.redirect(addr,name)
        self.redirect(0x800483f8,'ct_queue_send')
        for addr,name in HOOKS.items():
            self.redirect(addr,'emulator_audio_outer_hook' if name=='emulator_outer_hook' else name)
        self.redirect(0x8001078e,'emulator_audio_return_hook')
        # Root public-request branches use the same explicit status fixtures as
        # existing transport tests. They must not alter audio history state.
        for fn in (0x80007ad0,0x80006958):m.hooks[fn]=lambda a:0
        m.hooks[0x8000ad10]=lambda a:1
        def create(a):
            self.creates.append(a[:6])
            assert a[0]==self.syms['native_worker_entry'] and a[2:5]==[4096,WORKER,1]
            if create_failure:return 0xffffffff
            put32(m,a[5],HANDLE);return 1
        m.hooks[0x80076c60]=create
        # Ordinary file setup/header generation is explicit, not a full record
        # initialization. All reader/producer/queued-write/finalizer bodies run.
        for index,ch in STREAMS:
            h=self.handles[index]
            m.invoke(0x8000fb68,[0,48000,ch,32]);put32(m,0x21031000,512)
            m.uc.mem_write(m.stack,struct.pack('<3I',0,0x21031000,512))
            assert m.invoke(0x8000fc68,[h,0,0,0x801f8ee0])==0

    def redirect(self,address,name,always=False):
        def hook(uc,a,size,u):
            if self.enabled or always:
                self.entries.append(name);uc.reg_write(A.UC_ARM_REG_PC,self.syms[name])
        self.m.uc.hook_add(UC_HOOK_CODE,hook,begin=address,end=address)

    def assert_ordinary(self):assert self.raw(BASE,0xb10)==self.pad_before
    def io_write(self,a):
        assert not self.audio_active,'File I/O inside audio callback'
        return LifeRig.write_file(self,a) if a[0] in self.opened else WriterRig.write(self,a)
    def io_read(self,a):
        assert not self.audio_active
        return LifeRig.read_file(self,a) if a[0] in self.opened else WriterRig.read(self,a)
    def io_seek(self,a):
        return LifeRig.seek_file(self,a) if a[0] in self.opened else WriterRig.seek(self,a)
    def io_info(self,a):
        return LifeRig.info_file(self,a) if a[0] in self.opened else WriterRig.stat(self,a)
    def kernel_send(self,a):
        if a[0] in (QHANDLE,FILE_QUEUE):assert_fifo_send(a)
        if a[0]==QHANDLE:
            self.sent.append(self.raw(a[1],32))
            if self.send_result:return 0
            self.wire.append(self.sent[-1])
        elif a[0]==FILE_QUEUE:WriterRig.send(self,a)
        return 1
    def receive(self,a):
        queue=self.wire if a[0]==QHANDLE else self.queue
        assert a[0] in (QHANDLE,FILE_QUEUE)
        if not queue:return stop(self.m)
        self.m.uc.mem_write(a[1],queue.pop(0));return 0
    def dispatch_all(self):
        previous=word(self.m,TASK);put32(self.m,TASK,CONTROL_TASK)
        try:self.m.invoke(0x80034bc8,[])
        finally:put32(self.m,TASK,previous)

    def boot(self,release=False):
        self.m.uc.mem_write(self.m.stack,struct.pack('<2I',0,1))
        result=self.m.invoke(self.syms['native_worker_register'],[WORKER,MAN,DESC,CONFIG])
        put32(self.m,SCHEDULER,1)
        if result==0 and release:assert self.release()==0
        return result
    def ready(self):self.drive(lambda:self.mstate()==LIVE)
    def request(self,ui=0):
        request_setup(self.m,ui);self.m.hooks[0x800763d8]=self.kernel_send
        if not ui:self.queued_record=True
        self.m.invoke(0x80034f40,[0xffffffff])
    def begin_recording(self,delay=0):
        self.request()
        for _ in range(delay):self.audio_call()
        self.dispatch_all();self.recording=True;self.flush_stock()

    def audio_call(self):
        before=list(self.calls);self.audio_active=True;position=self.audio_cursor
        try:
            self.m.uc.reg_write(A.UC_ARM_REG_R0,0x2022a791)
            self.window(0x8001078a,0x8001078c) # before original BLX; DSP windows below
            inputs=[[(self.sequence+i+c-32)/2048 for i in range(64)] for c in range(10)]
            pad_l=[(self.sequence+i)/4096 for i in range(64)]
            pad_r=[-(self.sequence+i+16)/4096 for i in range(64)]
            self.pad(0,[v*2**31 for v in pad_l],[v*2**31 for v in pad_r])
            for c in range(10):self.floats(B+0x10+c*256,[v*2**31 for v in inputs[c]])
            self.floats(B+0x5e34,[1]+[0]*9+[0,1]+[0]*8)
            clean=self.raw(B+0x10,2560);self.mix()
            left=[a+b for a,b in zip(inputs[0],pad_l)];right=[a+b for a,b in zip(inputs[1],pad_r)]
            assert self.raw(MIX)==packed([v*2**31 for v in left+right])
            self.gain(.5);self.stock_staging()
            for c in range(10):self.floats(B+0xc10+c*256,[v*2**31 for v in inputs[c]])
            self.window(0x20227622,0x20227626)
            self.m.uc.reg_write(A.UC_ARM_REG_R11,B)
            self.window(0x20229b82,0x2022a77a)
            assert self.raw(B+0x10,2560)==clean
            self.window(0x8001078e,0x80010792) # matching original post-BLX continuation
            self.audio_cursor=word(self.m,B+0x53e4);self.sequence+=64
            assert self.audio_cursor==(position+64)%self.capacity and self.calls==before
            if self.queued_record:
                self.pending_stock.append(position)
                self.expected_extra.extend(v for pair in zip(left,right) for v in pair)
                for index,ch in STREAMS:
                    values=([v*.5 for v in left],[v*.5 for v in right]) if index==10 else inputs[index:index+ch]
                    self.expected[self.handles[index]].extend(v for pair in zip(*values) for v in pair)
        finally:self.audio_active=False
        if self.recording:self.flush_stock()

    def flush_stock(self):
        previous=word(self.m,TASK);put32(self.m,TASK,FILE_TASK)
        try:
            for position in self.pending_stock:
                self.position=position
                for index,ch in STREAMS:
                    self.index=index;self.channels=ch;self.produce();self.drain()
            self.pending_stock=[]
        finally:put32(self.m,TASK,previous)

    def stop_recording(self):
        self.request(1);self.dispatch_all();self.queued_record=self.recording=False
        frames=len(self.expected[7])//2
        # Exact ordinary endpoints and terminal sector flush are supplied at the
        # deep backend boundary. Original producer/finalizer perform the work.
        self.frames=0;self.position=self.audio_cursor
        for index,ch in STREAMS:
            put32(self.m,C+0x4e4+4*index,frames)
            self.index=index;self.channels=ch;self.produce();self.drain()
        self.frames=64
        return {h:self.finish_file(h) for h in range(1,8)}

    def completed_extra(self):
        self.drive(lambda:self.mstate()==RESET,with_audio=False)
        session,path=self.result();assert path.endswith('.TMP') and session==123
        data=bytes(self.disk[path]);assert data[512:]==packed(self.expected_extra)
        assert struct.unpack_from('<I',data,508)[0]==len(self.expected_extra)*4
        assert not self.opened and word(self.m,self.syms['bridge_audio_calls'])==0
        self.assert_ordinary();return data

def record(r,delay=0,blocks=22):
    r.audio_call();r.begin_recording(delay)
    for _ in range(blocks):
        r.audio_call()
        if r.enabled and r.mstate()==LIVE:r.tick()
    data=r.stop_recording()
    for h in range(1,8):assert data[h]==packed(r.expected[h])
    r.assert_ordinary();return {h:bytes(r.files[h]) for h in range(1,8)}

def main():
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,**kw))
    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2)
    r=IntegrationRig();assert r.boot()==0
    # Closed registration does no work and ignores dirty/inaccessible arenas.
    r.m.uc.mem_protect(STATE,MAN-STATE,UC_PROT_NONE);r.m.uc.mem_protect(SLOTS,0x5000,UC_PROT_NONE)
    before=list(r.calls);assert r.loops(3)==[25]*3;r.audio_call()
    assert r.calls==before
    r.m.uc.mem_protect(STATE,MAN-STATE,UC_PROT_ALL);r.m.uc.mem_protect(SLOTS,0x5000,UC_PROT_ALL)
    assert r.release()==0;r.ready()
    # Normalize input sequence to baseline; the released/adopting callback is
    # idle and intentionally not part of either recording's selected range.
    r.sequence=0
    result=record(r,delay=2);extra=r.completed_extra()
    assert result==ordinary
    assert extra[512:]!=result[7][512:]
    passed('normal_capture_only_ELF_cold_hold_then_one_exact_extra_file_and_seven_byte_identical_stock_files',
        frames=24*64,setup_delay_blocks=2,extra_bytes=len(extra),stock_files=7,
        stock_sha256={str(h):hashlib.sha256(data).hexdigest() for h,data in result.items()})

    r=IntegrationRig(create_failure=True);assert r.boot()==13 and not r.calls
    assert record(r,delay=2)==ordinary and r.result()==12 and not r.disk
    passed('optional_task_creation_failure_keeps_ordinary_recording_byte_identical')

    r=IntegrationRig();assert r.boot(release=True)==0;r.inject=('create',1,'error')
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False);r.sequence=0
    assert record(r,delay=2)==ordinary and r.result()==12 and not r.opened
    passed('optional_file_preparation_failure_leaves_stems_and_master_unchanged')

    for operation,kind,terminal in (('audio','short',STOPPED),('read_audio','short',STOPPED),
                                    ('close_write','error',BLOCKED)):
        r=IntegrationRig();assert r.boot(release=True)==0;r.ready();r.sequence=0
        r.inject=(operation,1,kind)
        assert record(r,delay=2)==ordinary
        r.drive(lambda:r.mstate()==terminal,with_audio=False)
        assert r.result()==12
        calls=list(r.calls);before=r.raw(STATE,MAN-STATE)
        for _ in range(3):r.tick()
        assert r.calls==calls and r.raw(STATE,MAN-STATE)==before
        if terminal==BLOCKED:assert r.resume()==12
    passed('write_readback_and_uncertain_close_failures_withhold_extra_result_without_reusing_memory_or_altering_stock_files')

    # Without worker progress, required history is overwritten. Optional failure
    # still does not inhibit the seven ordinary writers or subsequent callbacks.
    baseline=IntegrationRig(enabled=False);long_ordinary=record(baseline,blocks=40)
    r=IntegrationRig(count=2);assert r.boot(release=True)==0;r.ready();r.sequence=0
    r.audio_call();r.begin_recording()
    for _ in range(40):r.audio_call()
    r.stop_recording()
    assert {h:bytes(r.files[h]) for h in range(1,8)}==long_ordinary
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert r.result()==12
    r.audio_call();r.assert_ordinary()
    passed('lost_required_history_cancels_extra_only_while_ordinary_recording_and_audio_continue')

    report=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),capture_only_sha256=hashlib.sha256(r.elf_path.read_bytes()).hexdigest(),
        limits=['Normal capture-only ELF; broad overlay and synthetic DSP callback symbols absent',
            'Logical callback spans original dispatch/tap/gain/staging/ring/return windows; full DSP/dynamics/effects omitted',
            'ADC/input staging, deep ordinary file registration/endpoints, Main storage authorization and successful task creation are fixtures',
            'One CPU with selected task identities, in-memory synchronous public files and modeled queue delivery',
            'No real-time scheduling, cache/MPU enforcement, IRQ, SD/DMA joining or power-loss durability',
            'Emulator addresses only; no startup patch, physical RAM ownership or deployable firmware',
            'Extra remains verified TMP; no seal, pad assignment, settings persistence or device access'])
    out=ROOT/'analysis/capture_integration_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
