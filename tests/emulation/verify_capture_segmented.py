#!/usr/bin/env python3
"""External history through compiled arena/manager/worker and native windows.

Queues, logical callback scheduling and public synchronous files are fixtures.
Native filesystem variants also run original filesystem/SD instructions with
modeled card/controller completion. This never constructs/deploys a device BIN.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_IPSR
from verify_capture_heap import HeapRig,ALLOC
from verify_capture_integration import IntegrationRig,record,C,STREAMS
from verify_capture_native_files import NativeCapture
from verify_native_storage_setup import FolderTree,FolderTreeSd
from verify_memory_layout import HEAP_STATE,HEAP_START,HEAP_END,GAP
from verify_native_worker import HANDLE,CONFIG
from verify_control_transport import QHANDLE
from verify_session_manager import LIVE,FENCE,RESET,STOPPED
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_uncompressed_tap import B,RING,STRIDE,packed
from verify_pad_protocol import ROOT,IMAGE
from verify_segmented_exchange import FLAG,CAP,META,TAILS,TAIL_BYTES,metadata

class SegmentedRig(HeapRig):
    elf_path=ROOT/'src/capture/capture-only-segmented.elf'
    initial_session=123
    candidate_globals=None
    arena_registered=False
    def __init__(self,count=1024,reserved=65536):
        super().__init__(count,reserved)
    def allocate_arena(self,count,reserved):
        m=self.m;assert word(m,HEAP_STATE)==0
        m.uc.mem_write(HEAP_START,b'\xa5'*(HEAP_END-HEAP_START))
        self.suspend_calls=self.resume_calls=0
        def suspend(a):self.suspend_calls+=1;return 0
        def resume(a):self.resume_calls+=1;return 0
        m.hooks[0x80074780]=suspend;m.hooks[0x80077540]=resume
        self.reserved=None
        if reserved:
            p=m.invoke(ALLOC,[reserved]);assert p
            self.reserved=(p,reserved);m.uc.mem_write(p,b'\x3c'*reserved)
        self.count=count;self.capacity=CAP
        self.take_session=self.initial_session
        for a in TAILS:m.uc.mem_write(a,b'\xa5'*TAIL_BYTES)
        m.uc.mem_write(META,metadata(count//8))
        self.arena=self.create_external_arena(count)
        assert self.arena
        layout=struct.unpack('<6I',self.raw(self.syms['native_arena_layout'],24))
        self.raw_allocation=word(m,self.arena+layout[1]);self.requested=word(m,self.arena+layout[2])
        self.manager=word(m,self.arena+layout[3]);self.worker=word(m,self.arena+layout[4])
        self.descriptor=self.arena+layout[5];self.d=struct.unpack('<10I',self.raw(self.descriptor,40))
        assert self.d[7:]==(FLAG|count,self.initial_session,QHANDLE)
        assert self.raw(self.d[6],72)==self.raw(META,72)
        assert all(p%32==0 for p in (*self.d[:6],self.manager,self.worker))
        if self.arena_registered:
            assert word(m,self.worker+8)==4 and word(m,self.worker)==self.manager
        else:
            assert self.raw(self.manager,self.mlayout[0])==bytes(self.mlayout[0])
            assert self.raw(self.worker,self.wlayout[0])==bytes(self.wlayout[0])
        assert all(self.raw(a,TAIL_BYTES)==b'\xa5'*TAIL_BYTES for a in TAILS)
        assert self.requested==m.invoke(self.syms['native_arena_bytes_external'],[count])
        assert self.worker+self.wlayout[0]<=self.raw_allocation+self.requested
        # Caller metadata is ephemeral; only the arena copy survives.
        m.uc.mem_write(META,b'\xcc'*72)
        put32(m,B+0x53e8,CAP);put32(m,B+0x53f8,CAP)
        put32(m,C+0x50,CAP);put32(m,C+0x1e94,CAP)
        # The older short-recording fixture capped ordinary writers at 100000
        # frames. Supply a longer synthetic end limit for this wrap experiment;
        # real ordinary registration/stop still need their device binding.
        put32(m,C+0x1de8,1000000)
        for index,_ in STREAMS:
            for offset in (0x514,0x4e4,0x4b4):put32(m,C+offset+index*4,1000000)
        def create(a):
            self.creates.append(a[:6]);assert a[2:5]==[4096,self.worker,1]
            put32(m,a[5],HANDLE);return 1
        m.hooks[0x80076c60]=create
        def access(uc,kind,a,n,value,user):
            if a+n>GAP[0] and a<GAP[1]:
                assert self.candidate_globals and self.candidate_globals[0]<=a and a+n<=self.candidate_globals[1],hex(a)
            pc=uc.reg_read(UC_ARM_REG_PC)
            code_start=self.syms.get('placement_code_start',0x10010000)
            code_end=self.syms.get('placement_load_end',0x10020000)
            if code_start<=pc<code_end and RING<=a<RING+12*STRIDE:
                assert any(base<=a and a+n<=base+count//8*528 for base in TAILS),(hex(pc),hex(a),n)
        for start,end in (GAP,(RING,RING+12*STRIDE)):
            m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,access,begin=start,end=end-1)
    def create_external_arena(self,count):
        return self.m.invoke(self.syms['native_arena_alloc_external'],[META,count,self.initial_session,QHANDLE])
    def extra(self):
        self.drive(lambda:self.mstate()==RESET,with_audio=False)
        session,path=self.result();assert path.endswith('.TMP') and session==self.take_session
        data=bytes(self.disk[path]);assert data[512:]==packed(self.expected_extra)
        assert struct.unpack_from('<I',data,508)[0]==len(self.expected_extra)*4
        assert not self.opened;self.assert_reserved();self.assert_ordinary()
        return path,data
    def check_ordinary_files(self):
        for h in range(1,8):assert bytes(self.files[h][512:])==packed(self.expected[h])
        self.assert_ordinary();self.assert_reserved()
    def event(self,kind,stamp):
        if kind==3:self.take_session=self.session
        self.m.uc.mem_write(META,struct.pack('<Q',stamp))
        return self.m.invoke(self.syms['bridge_publish'],[self.d[2],self.session,kind,META])
    def begin_recording(self,delay=0):
        self.take_session=self.session
        # Deep ordinary file registration is modeled by IntegrationRig. Native
        # per-stream draining changes this mask; registration for the next take
        # would restore all seven streams before its admission checkpoint.
        put32(self.m,C+0x440,0x557)
        return super().begin_recording(delay)

class SegmentedNativeCapture(SegmentedRig,NativeCapture):
    def __init__(self,filesystem):
        NativeCapture.__init__(self,filesystem=filesystem)
        self.allocate_arena(1024,65536)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    # Complete composition: more than three extra-history wraps, all boundaries,
    # delay at admission, and repeated 600-block worker blackouts with catch-up.
    r=SegmentedRig();assert r.boot()==0 and not r.calls
    assert r.release()==0;r.ready();r.sequence=0
    r.audio_call();r.begin_recording(delay=7)
    for i in range(3800):
        r.audio_call()
        if i%1000>=600:r.tick() # 0.8s blackout; four copies per poll while recovering
    r.stop_recording()
    # Stop doesn't freeze producer; retained selected blocks must remain exact.
    for _ in range(100):r.audio_call()
    path,data=r.extra();r.check_ordinary_files()
    assert path.endswith('OD_00000001.TMP')
    passed('compiled_manager_worker_exact_eighth_file_and_seven_stock_files_after_wraps_repeated_stalls_and_post_stop_audio',
           frames=len(r.expected_extra)//2,extra_sha256=hashlib.sha256(data).hexdigest(),
           heap_requested_bytes=r.requested,external_bytes=8*TAIL_BYTES)

    # Same allocation rearmed; previous disk data remains intact.
    saved=bytes(r.disk[path]);r.ready();r.expected_extra=[]
    r.audio_call();r.begin_recording(delay=3)
    for _ in range(25):r.audio_call();r.tick()
    r.stop_recording();path2,data2=r.extra()
    assert path2!=path and bytes(r.disk[path])==saved
    passed('rearm_reuses_segmented_arena_and_preserves_previous_verified_take')

    # Synthetic synchronous event stamps exercise sample-exact cuts through the
    # same compiled manager/worker. Native UI selection is covered separately.
    r=SegmentedRig();assert r.boot(release=True)==0;r.ready();r.sequence=0
    start=struct.unpack('<Q',r.raw(r.d[3]+32,8))[0]
    r.queued_record=True;r.audio_call()
    assert r.event(3,start+17)==0 and r.event(5,0)==0
    for _ in range(4):r.audio_call()
    assert r.event(4,start+5*64-29)==0
    r.queued_record=False;r.expected_extra=r.expected_extra[17*2:-29*2]
    for _ in range(20):r.audio_call()
    _,data=r.extra();assert len(data)==512+(5*64-17-29)*8
    passed('partial_first_and_last_blocks_are_exact_with_delayed_worker_and_continued_producer',frames=274)

    r=SegmentedRig();assert r.boot(release=True)==0;r.ready()
    start=struct.unpack('<Q',r.raw(r.d[3]+32,8))[0]
    assert r.event(3,start)==0 and r.event(5,0)==0
    for _ in range(5):r.audio_call();r.tick()
    assert r.event(4,start+16)==0
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert r.result()==12 and not r.opened
    passed('late_stop_behind_already_copied_frames_invalidates_extra_take')

    r=SegmentedRig();put32(r.m,CONFIG+8,1)
    assert r.boot(release=True)==0;r.ready()
    r.begin_recording();r.audio_call();r.stop_recording()
    r.drive(lambda:r.mstate()==FENCE,with_audio=False)
    last=TAILS[7]+127*528;put32(r.m,last,3)
    # Both cleanup paths must scan the final segment before retiring storage.
    assert r.m.invoke(r.syms['bridge_retire_quiesced'],[r.d[2],r.session])==11
    assert r.m.invoke(r.syms['bridge_detach'],[r.d[2],r.session])==11
    assert r.mstate()==FENCE
    # detach closes its gateway even while waiting. Its owner must finish that
    # same operation before asking a manager to step the closed bridge again.
    put32(r.m,last,0)
    assert r.m.invoke(r.syms['bridge_detach'],[r.d[2],r.session])==0
    r.extra();r.ready()
    passed('both_retirement_paths_refuse_a_reader_in_the_final_segment_then_rearm_after_release')

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    for filesystem in (FolderTree,FolderTreeSd):
        r=SegmentedNativeCapture(filesystem);assert r.fs.setup_card()==0
        assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        r.completed_extra();r.assert_reserved()
        passed('exact_eight_files_through_original_filesystem_'+filesystem.__name__,requests=len(r.fs.requests))

    # Overwrite an unconsumed start, then (separately) an unconsumed final block.
    for where in ('start','stop'):
        r=SegmentedRig();assert r.boot(release=True)==0;r.ready()
        r.audio_call();r.begin_recording()
        if where=='start':
            for _ in range(1030):r.audio_call()
            r.stop_recording()
        else:
            for _ in range(5):r.audio_call();r.tick()
            for _ in range(2):r.audio_call()
            r.stop_recording()
            for _ in range(1030):r.audio_call()
        r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
        assert r.result()==12 and not r.opened;r.check_ordinary_files()
        r.audio_call()
        passed('overwritten_selected_'+where+'_block_withholds_extra_result_and_keeps_ordinary_audio_running')

    # Worker/context spans and descriptor metadata are reserved in their entirety.
    r=SegmentedRig();d=r.d
    def disjoint(a,n):return r.m.invoke(r.syms['manager_storage_disjoint'],[r.manager,r.descriptor,a,n])
    for a in (*TAILS,d[6],r.manager,*d[:6]):assert disjoint(a,4)==0
    assert disjoint(TAILS[0]-32,32)==1 and disjoint(TAILS[0]+TAIL_BYTES,32)==1
    assert disjoint(0xfffffff8,32)==0
    for word_index,address in ((0,TAILS[3]),(5,TAILS[7]),(6,d[0]),(0,d[6])):
        bad=list(d);bad[word_index]=address
        r.m.uc.mem_write(META,struct.pack('<10I',*bad))
        assert r.m.invoke(r.syms['manager_boot'],[r.manager,META,0,1])==12
    passed('manager_and_worker_disjoint_checks_cover_every_tail_and_metadata')

    # Reject a duplicate reservation of native heap/control before any ALLOC.
    before=r.suspend_calls
    for a in (HEAP_START,HEAP_STATE&~7):
        spans=[(base,TAIL_BYTES) for base in TAILS];spans[0]=(a,TAIL_BYTES)
        r.m.uc.mem_write(META,metadata(spans=spans))
        assert r.m.invoke(r.syms['native_arena_alloc_external'],[META,1024,124,QHANDLE])==0
    assert r.suspend_calls==before
    passed('native_heap_and_allocator_control_cannot_be_external_history')
    r.m.uc.mem_write(META,metadata())
    for count,session,queue in ((0,1,QHANDLE),(1,1,QHANDLE),(3,1,QHANDLE),(8192,1,QHANDLE),
                               (FLAG|1024,1,QHANDLE),(1024,0,QHANDLE),(1024,1,0)):
        assert r.m.invoke(r.syms['native_arena_alloc_external'],[META,count,session,queue])==0
    r.m.uc.reg_write(UC_ARM_REG_IPSR,3)
    try:assert r.m.invoke(r.syms['native_arena_alloc_external'],[META,1024,1,QHANDLE])==0
    finally:r.m.uc.reg_write(UC_ARM_REG_IPSR,0)
    assert r.suspend_calls==before
    passed('external_arena_rejects_invalid_count_session_queue_and_handler_context_before_allocation')
    report=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        segmented_elf_sha256=hashlib.sha256(SegmentedRig.elf_path.read_bytes()).hexdigest(),
        limits=['Emulated native instruction windows with host-seeded external memory ownership.',
                'Public file/queue scheduling fixtures; native filesystem variants model SD completion.',
                'Stalls count omitted logical worker polls, not measured hardware service times.',
                'Full effects/dynamics, physical DMA/cache/FP preemption and boot/storage admission remain gates.',
                'No pad handoff, deployable BIN or device operations.'])
    (ROOT/'analysis/capture_segmented_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
