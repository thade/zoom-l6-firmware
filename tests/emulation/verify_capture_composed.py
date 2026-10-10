#!/usr/bin/env python3
"""Packed minimal hooks + cold heap arena + segmented recording, offline only.

Native allocator/scatter/startup/selected audio and filesystem instructions run.
Tasks, interrupts, scheduling, middle DSP and controller completion are models.
Startup never releases the worker; recording tests explicitly supply admission.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from verify_capture_startup import Boot,TOP,scatter_startup
from verify_capture_hooks import HooksRig,NativeCapture,control_continuations,dsp_continuations
from verify_capture_segmented import SegmentedRig
from verify_capture_integration import IntegrationRig,record
from verify_native_storage_setup import FolderTree,FolderTreeSd
from verify_native_exfat import ExfatFoldersSd
from verify_memory_layout import HEAP_STATE,HEAP_START,HEAP_END,GAP
from verify_native_worker import HANDLE,SCHEDULER
from verify_control_transport import QHANDLE
from verify_session_manager import STOPPED
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT,IMAGE
from verify_segmented_exchange import CAP,TAILS,TAIL_BYTES,FLAG
from capture_jump_patches import symbols
from plan_capture_composed import ELF,plan
from plan_capture_packing import packing

PLAN=plan();PACK=packing(ELF);N=symbols(ELF)
GLOBALS=tuple(PLAN['packing']['globals'])

class ComposedBoot(Boot):
    names=N;packed=PACK;patch_plan=PLAN;global_range=GLOBALS
    def __init__(self,fail=None,optional='success',allocation_failure=False):
        N=self.names
        super().__init__(fail,pack=self.packed,names=N,patches=self.patch_plan['patches'])
        m=self.m
        # Queue and optional arena allocations use the original native heap.
        # Task/mutex creation remains a fixture, so this is not device headroom.
        m.hooks.pop(0x8006de78)
        m.hooks[0x80074780]=lambda a:0;m.hooks[0x80077540]=lambda a:0
        self.heap_before=None
        def before_register(uc,a,n,u):
            self.heap_before=self.word(HEAP_STATE+4)
            if allocation_failure:m.hooks[0x8006de78]=lambda a:0
        m.uc.hook_add(UC_HOOK_CODE,before_register,begin=N['startup_register']&~1,end=N['startup_register']&~1)
        original=m.hooks[0x80076c60]
        def create(a):
            if a[0]!=N['native_worker_entry']:return original(a)
            self.optional_calls+=1;self.optional_args.append(tuple(a[:6]))
            arena=self.word(N['startup_arena']);self.manager=self.word(arena+8);self.worker=self.word(arena+12)
            assert len(self.tasks)==36 and self.word(SCHEDULER)==0
            assert (a[2],a[3],a[4],a[5])==(4096,self.worker,1,self.worker+4)
            assert bytes(m.uc.mem_read(a[1],10))==b'L6Overdub\0'
            if optional!='missing_handle':put32(m,a[5],HANDLE)
            return {'success':1,'zero':0,'negative':0xffffffff,'missing_handle':1}[optional]
        m.hooks[0x80076c60]=create
    def guard(self):
        GLOBALS=self.global_range
        assert bytes(self.m.uc.mem_read(GLOBALS[0]-8,8))==b'\xa5'*8
        assert bytes(self.m.uc.mem_read(GLOBALS[1],16))==b'\xa5'*16
        assert all(GLOBALS[0]<=a and a+n<=GLOBALS[1] for a,n in self.writes)
    def arena(self):return self.word(self.names['startup_arena'])

class ComposedRig(SegmentedRig,HooksRig):
    elf_path=ELF;patch_plan=PLAN;packed=PACK
    candidate_globals=GLOBALS;initial_session=1;arena_registered=True
    def __init__(self,patched=True,enabled=True,count=1024,reserved=65536):
        HooksRig.__init__(self,patched=patched,enabled=enabled,count=32)
        self.allocate_arena(count,reserved)
    def create_external_arena(self,count):
        assert count==1024
        m=self.m
        def create(a):
            self.creates.append(a[:6]);put32(m,a[5],HANDLE);return 1
        m.hooks[0x80076c60]=create
        m.invoke(self.syms['startup_observe'],[0,0])
        assert word(m,self.syms['startup_status'])==1
        m.invoke(self.syms['startup_register'],[0,0])
        return word(m,self.syms['startup_arena'])
    def boot(self,release=False):
        # Cold fixture already registered exactly once; no second allocation.
        assert len(self.creates)==1 and word(self.m,self.syms['startup_status'])==3
        put32(self.m,SCHEDULER,1)
        status=word(self.m,self.worker+12)
        if status==0 and release:assert self.release()==0
        return status

class ComposedNative(NativeCapture,ComposedRig):
    def __init__(self,filesystem):
        NativeCapture.__init__(self,filesystem=filesystem)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    assert all(p.get('adapter','startup_capacity') in N or 'purpose' in p
               for p in PLAN['patches']+PLAN['DSP_patches'])
    assert 'native_arena_alloc' not in N and 'native_arena_alloc_external' in N
    assert not any(n.startswith(('backing_','bn_','na_','sdp_','history_','audio_fixture_')) for n in N)
    assert PLAN['packing']['spare_bytes']>=0 and GLOBALS==(0x80960080,0x809600e4)
    assert all(end-start==TAIL_BYTES for start,end in PLAN['history']['spans'])
    assert [start for start,end in PLAN['history']['spans']]==list(TAILS)
    passed('minimal_composition_has_all_patch_roots_exact_eight_spans_and_fits_stock_source',
        raw_code_bytes=len(PACK['code']),packed_code_bytes=len(PACK['packed_code']),
        spare_bytes=PLAN['packing']['spare_bytes'],globals_bytes=GLOBALS[1]-GLOBALS[0])

    hashes,helpers=scatter_startup(True,pack=PACK)
    assert len(helpers)==10 and helpers[4][3]==100
    passed('original_full_scatter_loads_composition_and_zeros_100_global_bytes',stock_regions=len(hashes))

    b=ComposedBoot();b.boot();b.guard()
    arena=b.arena();assert arena and b.kernel_entered and b.optional_calls==1
    assert b.word(N['startup_status'])==3 and b.word(b.worker+8)==4
    assert b.word(b.worker)==b.manager and b.word(b.worker+4)==HANDLE
    d=struct.unpack('<10I',b.m.uc.mem_read(arena+16,40))
    assert d[7:]==(FLAG|1024,1,b.word(0x801f8f38))
    assert b.word(arena+4)==PLAN['heap_requested_bytes']
    assert HEAP_START<=b.word(arena)<arena<b.manager<b.worker<HEAP_END
    assert struct.unpack('<2I',b.m.uc.mem_read(d[6],8))==(8,128)
    spans=struct.unpack('<16I',b.m.uc.mem_read(d[6]+8,64))
    assert tuple(spans[::2])==TAILS and tuple(spans[1::2])==(TAIL_BYTES,)*8
    assert b.word(N['ct_active'])==b.word(N['emulator_bridge_current'])==0
    assert b.word(N['bridge_gateway_readers'])==0x80000000
    requested=b.word(arena+4);peak=TOP-b.minimum_sp
    # All transient boot/config metadata can disappear before the waiting task.
    b.m.uc.mem_write(TOP-0x2000,b'\xa5'*0x2000)
    def no_manager(uc,access,a,n,v,u):raise AssertionError('waiting worker touched manager/history')
    guard=b.m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,no_manager,
        begin=b.manager,end=b.manager+2208-1)
    delays=[];b.m.hooks[0x800770e8]=lambda a:HANDLE
    b.m.hooks[0x80074158]=lambda a:delays.append(a[0]) or (stop(b.m) if len(delays)==5 else 0)
    b.m.invoke(N['native_worker_entry'],[b.worker]);b.m.uc.hook_del(guard);b.guard()
    assert delays==[25]*5 and b.word(b.worker+8)==4
    passed('encoded_stock_boot_uses_native_heap_and_permanent_metadata_then_waits_without_storage',
        requested_heap_bytes=requested,native_queue_and_arena_free_bytes=b.word(HEAP_STATE+4),
        traced_added_boot_path_stack_bytes=peak,
        caveat='Stock task stacks/TCBs are modeled; free bytes are not device headroom')

    for outcome in ('negative','zero','missing_handle'):
        b=ComposedBoot(optional=outcome);b.boot();b.guard()
        assert b.arena() and b.optional_calls==1 and b.kernel_entered
        assert b.word(b.worker+8)==3 and b.word(b.worker+12)==13
        before=b.word(HEAP_STATE+4);b.m.invoke(N['startup_register'],[0,0])
        assert b.optional_calls==1 and b.word(HEAP_STATE+4)==before
        assert b.word(N['ct_active'])==b.word(N['emulator_bridge_current'])==0
    b=ComposedBoot(allocation_failure=True);b.boot();b.guard()
    assert not b.arena() and b.kernel_entered and b.optional_calls==0
    assert b.word(N['startup_status'])==3
    b.m.invoke(N['startup_register'],[0,0]);assert not b.arena()
    passed('optional_allocation_and_task_failures_preserve_boot_remain_closed_and_never_retry')

    for fail in (('task',1),('mutex',1),('idle',1)):
        b=ComposedBoot(fail=fail);b.boot();b.guard()
        assert not b.arena() and b.optional_calls==0
        assert b.word(N['startup_status'])==(1 if fail[0]=='idle' else 2)
        assert b.kernel_entered==(fail[0]!='idle')
    passed('failed_native_initializer_or_idle_creation_never_allocates_optional_runtime')

    passed('composed_encoded_control_resumes_match_stock',comparisons=control_continuations(ComposedRig))
    passed('composed_encoded_DSP_resumes_match_stock',comparisons=dsp_continuations(ComposedRig))

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    large_exfat=lambda **kwargs:ExfatFoldersSd(spc=512,clusters=1952360,**kwargs)
    for fs,label in ((FolderTree,'FolderTree'),(FolderTreeSd,'FolderTreeSd'),
                     (large_exfat,'ExfatFoldersSd_256KiB_clusters')):
        r=ComposedNative(fs)
        assert r.fs.setup_card()==0
        if fs is large_exfat:
            r.fs.verify_folders();assert r.fs.spc==512
        assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        data=r.completed_extra();assert len(data)==13312
        passed('composed_cold_arena_and_actual_hooks_preserve_exact_eight_files_'+label,
            frames=1600,extra_sha256=hashlib.sha256(data).hexdigest())

    r=ComposedRig();assert r.boot(release=True)==0;r.ready();r.sequence=0
    r.audio_call();r.begin_recording(delay=7)
    for i in range(2400):
        r.audio_call()
        if i%800>=400:r.tick()
    r.stop_recording()
    for _ in range(40):r.audio_call()
    path,data=r.extra();r.check_ordinary_files()
    saved=bytes(r.disk[path]);r.ready();r.expected_extra=[]
    r.audio_call();r.begin_recording(delay=3)
    for _ in range(25):r.audio_call();r.tick()
    r.stop_recording();path2,data2=r.extra()
    assert path2!=path and bytes(r.disk[path])==saved
    passed('actual_hooks_recover_after_repeated_stalls_wrap_history_and_rearm_same_heap_arena',
        first_extra_bytes=len(data),second_extra_bytes=len(data2))

    r=ComposedRig();assert r.boot(release=True)==0;r.ready();r.begin_recording()
    for _ in range(1100):r.audio_call()
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert r.result()==12 and not r.opened
    r.audio_call();r.stop_recording();r.check_ordinary_files()
    passed('history_loss_fails_only_optional_take_and_keeps_seven_ordinary_files_exact')

    report=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),composed_elf_sha256=PLAN['hooks_elf_sha256'],
        packing=PLAN['packing'],limitations=PLAN['limitations']+[
            'Positive startup executes native queue/arena allocation; task and mutex allocation/scheduling remain fixtures',
            'Allocation failure is an injected allocator result after stock queue initialization',
            'Virtual exFAT has 256-KiB clusters; its geometry is not the measured on-card BPB',
            'Full scatter startup and later boot body are tested separately, not a whole interrupt-driven device boot',
            'Recording harness explicitly supplies admission; there is deliberately no startup release hook'])
    (ROOT/'analysis/capture_composed_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
