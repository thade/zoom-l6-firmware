#!/usr/bin/env python3
"""Capture arenas from the original allocator; no physical/device claims.

Allocation/free instructions are native. Scheduler exclusion, successful task
creation, audio delivery and the ordinary file backend remain fixtures.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_capture_integration import IntegrationRig,record
from verify_memory_layout import HEAP_STATE,HEAP_START,HEAP_END,INITIAL_FREE,GAP
from verify_native_worker import CONFIG,HANDLE,SCHEDULER,MAIN_HANDLE,MAIN_SLOT
from verify_control_transport import TASK,QHANDLE
from verify_session_manager import LIVE,RESET,STOPPED
from verify_firmware_workflow import put32,RESULT
from verify_record_catalogue import getstr
from verify_record_scheduler import word
from verify_pad_protocol import ROOT,IMAGE
from verify_uncompressed_tap import packed
from verify_capture_native_files import NativeCapture,UI,FS1,failed
from verify_native_storage_setup import FolderTree,FolderTreeSd

ELF=ROOT/'src/capture/capture-only-heap.elf'
ALLOC,FREE=0x8006de78,0x80073f48

class HeapRig(IntegrationRig):
    elf_path=ELF
    def __init__(self,count=128,reserved=0):
        super().__init__(count=32)
        self.allocate_arena(count,reserved)
    def allocate_arena(self,count,reserved):
        m=self.m
        # The stock heap is initially unallocated, as in its startup-zeroed
        # state. Dirty payloads verify that reserve does not clear history.
        assert word(m,HEAP_STATE)==0
        m.uc.mem_write(HEAP_START,b'\xa5'*(HEAP_END-HEAP_START))
        self.suspend_calls=self.resume_calls=0
        def suspend(a):self.suspend_calls+=1;return 0
        def resume(a):self.resume_calls+=1;return 0
        m.hooks[0x80074780]=suspend;m.hooks[0x80077540]=resume
        self.reserved=None
        if reserved:
            p=m.invoke(ALLOC,[reserved]);assert p
            self.reserved=(p,reserved);m.uc.mem_write(p,b'\x3c'*reserved)
        def no_gap(uc,access,address,size,value,user):
            assert address+size<=GAP[0] or address>=GAP[1],hex(address)
        m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,no_gap,
                      begin=GAP[0],end=GAP[1]-1)
        self.arena=m.invoke(self.syms['native_arena_alloc'],[count,123,QHANDLE])
        if not self.arena:
            self.enabled=False;return
        layout=struct.unpack('<6I',self.raw(self.syms['native_arena_layout'],24))
        self.raw_allocation=word(m,self.arena+layout[1])
        self.requested=word(m,self.arena+layout[2])
        self.manager=word(m,self.arena+layout[3]);self.worker=word(m,self.arena+layout[4])
        self.descriptor=self.arena+layout[5]
        self.d=struct.unpack('<10I',self.raw(self.descriptor,40))
        assert self.arena%32==0 and all(a%32==0 for a in (*self.d[:7],self.manager,self.worker))
        block=word(m,self.raw_allocation-4)&0x7fffffff
        assert HEAP_START<=self.raw_allocation-8<self.arena
        assert self.worker+self.wlayout[0]<=self.raw_allocation+self.requested
        assert self.raw_allocation+self.requested<=self.raw_allocation-8+block<=HEAP_END-8
        assert self.d[7:]==(count,123,QHANDLE)
        assert self.raw(self.manager,self.mlayout[0])==bytes(self.mlayout[0])
        assert self.raw(self.worker,self.wlayout[0])==bytes(self.wlayout[0])
        assert self.raw(self.d[6],count*self.xlayout[1])==b'\xa5'*(count*self.xlayout[1])
        def create(a):
            self.creates.append(a[:6])
            assert a[0]==self.syms['native_worker_entry'] and a[2:5]==[4096,self.worker,1]
            assert a[5]==self.worker+self.wlayout[1]
            put32(m,a[5],HANDLE);return 1
        m.hooks[0x80076c60]=create

    def mstate(self):return word(self.m,self.manager)
    def result(self,index=0):
        s=self.m.invoke(self.syms['manager_copy_result'],[self.manager,index,RESULT])
        return (word(self.m,RESULT),getstr(self.m,RESULT+4)) if s==0 else s
    def boot(self,release=False):
        # invoke supplies r0-r3 only; AAPCS arguments 5/6 belong on the stack.
        # Do not accidentally use the preceding WAV header's scratch pointer
        # as the initial filename serial.
        self.m.uc.mem_write(self.m.stack,struct.pack('<2I',0,1))
        result=self.m.invoke(self.syms['native_worker_register'],
                             [self.worker,self.manager,self.descriptor,CONFIG])
        put32(self.m,SCHEDULER,1)
        if result==0 and release:assert self.release()==0
        return result
    def release(self):
        previous=word(self.m,TASK);put32(self.m,TASK,MAIN_HANDLE)
        put32(self.m,MAIN_SLOT,MAIN_HANDLE)
        try:return self.m.invoke(self.syms['native_worker_release'],[self.worker])
        finally:put32(self.m,TASK,previous)
    def tick(self):
        previous=word(self.m,TASK);put32(self.m,TASK,HANDLE)
        try:status=self.m.invoke(self.syms['native_worker_poll'],[self.worker])
        finally:put32(self.m,TASK,previous)
        self.session=word(self.m,self.manager+16)
        assert word(self.m,self.worker+self.wlayout[4])<=4
        return status
    def cancel(self):self.m.invoke(self.syms['manager_cancel'],[self.manager])
    def resume(self):return self.m.invoke(self.syms['manager_resume'],[self.manager])
    def life(self,name,*args):
        argv=[self.d[4]] if name=='life_verified_path' else [self.d[4],self.d[5],*args]
        return self.m.invoke(self.syms[name],argv)
    def assert_reserved(self):
        if self.reserved:
            p,n=self.reserved;assert self.raw(p,n)==b'\x3c'*n
        assert self.suspend_calls==self.resume_calls

class HeapNativeCapture(HeapRig,NativeCapture):
    def __init__(self,filesystem):
        NativeCapture.__init__(self,filesystem=filesystem)
        self.allocate_arena(128,65536)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    for count in (32,128,256):
        r=HeapRig(count,reserved=65536);assert r.arena and r.boot()==0 and not r.calls
        assert word(r.m,r.worker+r.wlayout[2])==4
        assert r.release()==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        extra=r.completed_extra();assert len(extra)==13312;r.assert_reserved()
        passed('heap_owned_capture_'+str(count)+'_slots_exact_extra_and_seven_unchanged_stock_files',
               slots=count,history_seconds=count*64/48000,requested_bytes=r.requested,
               extra_sha256=hashlib.sha256(extra).hexdigest(),stock_reserved_bytes=65536)

    r=HeapRig();assert r.arena
    alloc_calls=r.suspend_calls
    for count,session,queue in ((0,1,QHANDLE),(1,1,QHANDLE),(3,1,QHANDLE),
            (8192,1,QHANDLE),(0xffffffff,1,QHANDLE),(128,0,QHANDLE),(128,1,0)):
        assert r.m.invoke(r.syms['native_arena_alloc'],[count,session,queue])==0
    assert r.suspend_calls==alloc_calls and not r.calls
    passed('invalid_counts_session_and_queue_rejected_before_native_allocation')

    r.m.uc.reg_write(A.UC_ARM_REG_IPSR,3)
    try:assert r.m.invoke(r.syms['native_arena_alloc'],[128,1,QHANDLE])==0
    finally:r.m.uc.reg_write(A.UC_ARM_REG_IPSR,0)
    assert r.suspend_calls==alloc_calls
    passed('handler_context_rejected_before_native_allocator')

    r=HeapRig(4096);assert not r.arena and not r.calls and not r.creates
    assert word(r.m,HEAP_STATE+4)==INITIAL_FREE
    assert word(r.m,r.syms['ct_active'])==0
    assert word(r.m,r.syms['emulator_bridge_current'])==0
    assert record(r,delay=2,blocks=23)==ordinary
    passed('old_two_megabyte_history_refused_by_native_heap_and_ordinary_recording_unchanged')

    r=HeapRig(128,reserved=450000);assert not r.arena and not r.calls and not r.creates
    assert record(r,delay=2,blocks=23)==ordinary;r.assert_reserved()
    passed('occupied_heap_refuses_optional_allocation_without_touching_stock_allocation_or_files')

    r=HeapRig(128,reserved=65536);assert r.boot(release=True)==0;r.ready()
    # A much smaller ring must fail the OPTIONAL take if its worker is starved.
    # Ordinary audio/files continue; no overwrite of a claimed history slot.
    r.begin_recording(delay=2)
    for _ in range(140):r.audio_call()
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert r.result()==12 and not r.opened
    r.audio_call();data=r.stop_recording()
    for h in range(1,8):assert data[h]==packed(r.expected[h])
    r.assert_reserved()
    passed('short_history_worker_starvation_cancels_extra_take_while_all_ordinary_files_remain_exact')

    r=HeapRig(128,reserved=65536);assert r.boot(release=True)==0;r.ready()
    # Allocate AFTER the arena, then dirty it: capture must preserve both sides.
    p=r.m.invoke(ALLOC,[32768]);assert p;r.m.uc.mem_write(p,b'\x69'*32768)
    free_after=word(r.m,HEAP_STATE+4)
    r.sequence=0;assert record(r,delay=2,blocks=23)==ordinary;r.completed_extra()
    assert r.raw(p,32768)==b'\x69'*32768
    assert word(r.m,HEAP_STATE+4)==free_after
    r.m.invoke(FREE,[p]);r.assert_reserved()
    passed('later_native_allocations_and_free_remain_usable_beside_permanent_capture_arena')

    for remaining in (1024,16432):
        r=HeapRig(128,reserved=65536)
        free_before=word(r.m,HEAP_STATE+4)
        assert r.m.invoke(ALLOC,[free_before-remaining-16])
        assert word(r.m,HEAP_STATE+4)==remaining
        r.m.hooks.pop(0x80076c60) # run the actual task creator and allocator
        assert r.boot()==13 and not r.calls and not r.creates
        assert word(r.m,r.worker+r.wlayout[2])==3
        assert word(r.m,HEAP_STATE+4)==remaining # partial stack allocation freed
        assert word(r.m,r.syms['ct_active'])==0
        assert record(r,delay=2,blocks=23)==ordinary;r.assert_reserved()
        passed('native_task_creator_heap_exhaustion_'+str(remaining)+'_bytes_keeps_optional_capture_closed')

    for filesystem in (FolderTree,FolderTreeSd):
        r=HeapNativeCapture(filesystem);assert r.arena and r.fs.setup_card()==0
        assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        extra=r.completed_extra();assert len(extra)==13312;r.assert_reserved()
        passed('heap_owned_capture_through_original_mount_folders_and_files_'+filesystem.__name__,
               extra_sha256=hashlib.sha256(extra).hexdigest(),requests=len(r.fs.requests))

    r=HeapNativeCapture(FolderTreeSd);assert r.fs.setup_card()==0
    assert r.boot(release=True)==0;r.ready();r.begin_recording(delay=2)
    r.fs.inject=(3,r.fs.physical(9,1),'data')
    for _ in range(12):
        r.audio_call();r.tick()
        if r.fs.stalled:break
    assert r.fs.stalled;r.retained((UI,FS1));frame=r.fs.frame();requests=list(r.fs.requests)
    r.resume_sd();r.retained((UI,FS1));assert r.fs.frame()==frame and r.fs.requests==requests
    r.other_task(word(r.m,TASK),r.audio_call)
    r.other_task(word(r.m,TASK),r.stop_recording)
    assert r.fs.frame()==frame and r.fs.requests==requests
    r.fs.join_allowed=True;r.resume_sd();failed(r);r.assert_reserved()
    passed('heap_arena_native_SD_error_retains_frames_and_buffers_until_explicit_modeled_join')

    report=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['Stock allocation/free instructions execute; scheduler exclusion and successful task creation are fixtures.',
            'No live free-heap/headroom, throughput, stack, cache/MPU, DMA or device measurements.',
            'Heap arenas remain allocated until reboot; cold initialization is an external prerequisite.',
            'Only runtime arenas are allocated: code/global placement, startup hook and storage authorization remain unbound.',
            'Ordinary files, audio delivery and explicit Main release are fixtures; selected extra-file cases run native FAT32/SD instructions.',
            'Native SD completion/source exclusion, sectors, DMA/cache effects and board initialization still have MODEL inputs.',
            'No firmware image constructed, installed or device accessed.'])
    (ROOT/'analysis/capture_heap_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
