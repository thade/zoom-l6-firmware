#!/usr/bin/env python3
"""Execute original task allocation/list/frame setup with the compiled worker.

One native baseline task seeds the cold RTOS lists. Suspend/resume scheduling
endpoints are modeled; there is no running scheduler, interrupt/preemption or
device claim. Native allocator, free, task creation, list and frame code execute.
"""
import hashlib,json,struct
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_memory_layout import HEAP_STATE,HEAP_START,HEAP_END
from verify_segmented_exchange import TAILS,TAIL_BYTES
from build_boot_probe import ELF
from capture_jump_patches import symbols

N=symbols(ELF);ALLOC=0x8006de78;CREATE=0x80076c60
ARENA_COST,STACK_COST,TCB_COST=9896,16400,160

class NativeRegistration:
    def __init__(self,remaining=None):
        self.m=m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True)
        m.uc.mem_map(0xe000e000,0x1000)
        with ELF.open('rb') as f:
            for s in ELFFile(f).iter_segments():
                if s['p_type']=='PT_LOAD':
                    m.uc.mem_write(s['p_vaddr'],s.data()+bytes(s['p_memsz']-s['p_filesz']))
        for fn in (0x80074780,0x80077540):m.hooks[fn]=lambda a:0
        # Actual first task creation initializes the native ready/delayed lists.
        # Entry and argument are sentinels; this baseline task never executes.
        m.uc.mem_write(0x20020000,b'Baseline\0')
        m.uc.mem_write(0x20010000,struct.pack('<2I',0,0x20020040))
        assert m.invoke(CREATE,[0x10010001,0x20020000,128,0x20030000])==1
        self.baseline_task=word(m,0x20020040)
        if remaining is not None:
            free=word(m,HEAP_STATE+4)
            assert m.invoke(ALLOC,[free-remaining-9])
            assert word(m,HEAP_STATE+4)==remaining
        self.before=word(m,HEAP_STATE+4);self.requests=[];self.frames=[]
        m.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:self.requests.append(u.reg_read(A.UC_ARM_REG_R0)),begin=ALLOC,end=ALLOC)
        m.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:self.frames.append(tuple(u.reg_read(r) for r in
            (A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2))),begin=0x8006e080,end=0x8006e080)
        def forbidden(*args):raise AssertionError('cold registration touched history/file IO')
        for a in TAILS:m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,forbidden,begin=a,end=a+TAIL_BYTES-1)
        for a in (0x8005ffe8,0x80060620,0x800622b0,0x8005c1f8,0x8005ef40):m.hooks[a]=forbidden
        put32(m,0x801f8f38,0x1234);put32(m,N['startup_status'],1)
    def run(self):
        self.m.invoke(N['startup_register'],[0,0]);m=self.m
        self.arena=word(m,N['startup_arena']);self.worker=word(m,self.arena+12) if self.arena else 0
        self.task=word(m,self.worker+4) if self.worker else 0
        return self.before-word(m,HEAP_STATE+4)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=NativeRegistration();cost=r.run();m=r.m
    assert r.requests==[9887,16384,148] and cost==ARENA_COST+STACK_COST+TCB_COST==26456
    assert HEAP_START<=r.arena<r.worker<r.task<HEAP_END
    base,top,saved=word(m,r.task+0x30),word(m,r.task+0x64),word(m,r.task)
    assert base%8==0 and top==(base+16384-4)&~7
    assert base<=saved<=top and r.frames==[(top,N['native_worker_entry'],r.worker)]
    assert word(m,r.task+0x2c)==1 and bytes(m.uc.mem_read(r.task+0x34,10))==b'L6Overdub\0'
    assert bytes(m.uc.mem_read(base,saved-base))==b'\xa5'*(saved-base)
    assert word(m,0x808e291c)==r.task # Native cold scheduling selects higher priority.
    assert word(m,r.worker+8)==4 and word(m,r.worker+12)==0
    passed('Compiled startup uses original heap/task creation and initial frame/list construction with exact26456-byte additional heap cost',
        arena_allocation_bytes=ARENA_COST,stack_allocation_bytes=STACK_COST,task_allocation_bytes=TCB_COST,
        raw_task_object_bytes=148,stack_payload_bytes=16384,initial_saved_frame_extent_bytes=base+16384-saved,
        limitation='Untouched initial stack pattern is not runtime stack headroom; no task context switch or preemption occurs')

    for remaining,requests in ((10000,[9887,16384]),(ARENA_COST+STACK_COST+80,[9887,16384,148])):
        r=NativeRegistration(remaining);assert r.run()==ARENA_COST
        assert r.requests==requests and r.arena and not r.task
        assert word(r.m,r.worker+8)==3 and word(r.m,r.worker+12)==13
        assert word(r.m,0x808e291c)==r.baseline_task and not r.frames
        before=word(r.m,HEAP_STATE+4);r.m.invoke(N['startup_register'],[0,0])
        assert r.requests==requests and word(r.m,HEAP_STATE+4)==before
        passed('Native '+('stack' if len(requests)==2 else 'task-object')+' allocation failure keeps arena closed with no retry or leaked stack',
               remaining_before=remaining,retained_bytes=ARENA_COST,requests=requests)
    r=NativeRegistration(8000);assert r.run()==0 and not r.arena and r.requests==[9887]
    assert word(r.m,0x808e291c)==r.baseline_task
    passed('Arena exhaustion skips native task creation and preserves the existing cold task')
    out=ROOT/'analysis/native_worker_allocation_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),cases=cases,
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),device_access=False,
        limitations=['One real native baseline task seeds lists; this is not every original task during complete board startup.',
            'Scheduler suspend/resume and arrivals are modeled; no physical allocation margin, runtime stack high-water, interrupt or performance claim.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),extra_heap_bytes=26456,report=str(out))))
if __name__=='__main__':main()
