#!/usr/bin/env python3
"""Actual startup jump bytes and compiled registration on the original stack.

Stock boot/scheduler control flow and scatter helpers execute. Board setup,
task creation, heap backing and scheduling are fixtures. No storage release.
"""
import hashlib,json,struct,sys
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_PROT_NONE
from unicorn import arm_const as A
from verify_startup_order import StartupRig,SCHEDULER
from verify_pad_protocol import ROOT,IMAGE,RETURN
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_capture_packing import startup as scatter_startup,edit_memory,expand_payloads
sys.path.insert(0,str(ROOT/'tools/firmware'))
from plan_capture_startup import ELF,SPECS,plan,make_patch
from capture_jump_patches import BIAS,symbols
from plan_capture_packing import packing,DECOMPRESS,ZERO,SCATTER

P=packing(ELF);N=symbols(ELF)
PATCHES=[make_patch(IMAGE,s,N[s['adapter']]) for s in SPECS]
MAN=0x80961de0;WORKER=0x80962680;TOP=0x2021fff0
REGS=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(13)]
FP=[getattr(A,'UC_ARM_REG_S'+str(i)) for i in range(32)]
STATUS=[A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR]

class Boot(StartupRig):
    def __init__(self,fail=None,optional='success',patched=True,pack=P,names=N,patches=PATCHES):
        P,N=pack,names
        code_start=P['jumps']['candidate_code_start']
        super().__init__(fail,real_scheduler=True)
        m=self.m;m.uc.mem_map(0x20210000,0x10000);m.stack=TOP
        # Make the unrelated historical overlay inaccessible. Load the capture
        # code from packed source with the original decoder, not ELF PT_LOAD.
        m.uc.mem_protect(0x10000000,0x10000,UC_PROT_NONE)
        m.uc.mem_write(0x80960078,b'\xa5'*(0x26c8-0x78))
        m.uc.mem_write(code_start,b'\xa5'*len(P['code']))
        edit_memory(m.uc,P)
        j=P['jumps']
        expand_payloads(m,P)
        assert bytes(m.uc.mem_read(code_start,len(P['code'])))==P['code']
        if patched:
            for p in patches:m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
        self.optional_calls=0;self.optional_args=[];self.observed_init=None
        self.minimum_sp=TOP;self.c_stack=[];self.writes=[]
        original=m.hooks[0x80076c60]
        def create(a):
            if a[0]!=N['native_worker_entry']:return original(a)
            self.optional_calls+=1;self.optional_args.append(tuple(a[:6]))
            assert len(self.tasks)==36 and self.word(SCHEDULER)==0
            assert self.word(0x801f9060)!=0
            assert bytes(m.uc.mem_read(a[1],10))==b'L6Overdub\0'
            assert (a[2],a[3],a[4],a[5])==(4096,WORKER,1,WORKER+4)
            assert m.uc.reg_read(A.UC_ARM_REG_SP)%8==0
            if optional!='missing_handle':put32(m,a[5],0x7f00)
            return {'success':1,'missing_handle':1,'zero':0,'negative':0xffffffff}[optional]
        m.hooks[0x80076c60]=create
        def observe(uc,a,n,u):self.observed_init=uc.reg_read(A.UC_ARM_REG_R0)
        m.uc.hook_add(UC_HOOK_CODE,observe,begin=0x80067a84,end=0x80067a84)
        # Trace SP only around the added adapters and compiled code. Original
        # task/driver execution has separate bounds; no physical stack claim.
        def trace(uc,a,n,u):
            self.minimum_sp=min(self.minimum_sp,uc.reg_read(A.UC_ARM_REG_SP))
            if a in (N['startup_observe']&~1,N['startup_register']&~1):
                self.c_stack.append(uc.reg_read(A.UC_ARM_REG_SP))
        m.uc.hook_add(UC_HOOK_CODE,trace,begin=code_start,end=code_start+len(P['code'])-1)
        def writes(uc,access,address,size,value,u):self.writes.append((address,size))
        m.uc.hook_add(UC_HOOK_MEM_WRITE,writes,begin=0x80960078,end=0x80bb93ff)
        # Any accidental public-file work is a hard failure, not a modeled
        # synchronous success. No storage provider is established at startup.
        def forbidden(a):raise AssertionError('startup touched a public file API')
        for fn in (0x8005ffe8,0x80060620,0x800622b0,0x8005c1f8,0x8005ef40):m.hooks[fn]=forbidden

    def guard(self):
        assert bytes(self.m.uc.mem_read(0x80960078,8))==b'\xa5'*8
        assert bytes(self.m.uc.mem_read(0x809626c0,8))==b'\xa5'*8
        for a,n in self.writes:
            assert (0x80960080<=a and a+n<=0x809600e0) or (MAN<=a and a+n<=WORKER+64),(hex(a),n)

def run_raw(r,start,end):
    m=r.m;h=m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:stop(m),begin=end,end=end)
    m.reached_return=False
    try:
        m.uc.emu_start(start|1,RETURN+2,count=1000000)
        assert m.reached_return
        return [m.uc.reg_read(x) for x in REGS+FP+STATUS]
    finally:m.uc.hook_del(h)

def seed(r,flags,misalign):
    u=r.m.uc
    # Warm the modeled FPU with one hook pass before status sentinels. CPACR,
    # physical lazy stacking and early-board FPU enablement are not proved.
    put32(r.m,N['startup_status'],2)
    u.reg_write(A.UC_ARM_REG_SP,TOP)
    run_raw(r,N['startup_idle_hook'],0x800745ec)
    for i,x in enumerate(REGS):u.reg_write(x,0x12340000+i*0x101)
    for i,x in enumerate(FP):u.reg_write(x,0x3f000000+i*123)
    u.reg_write(A.UC_ARM_REG_SP,TOP+misalign)
    u.reg_write(A.UC_ARM_REG_LR,0x20001001)
    u.reg_write(A.UC_ARM_REG_APSR,(flags<<28)|0x080f0000)
    u.reg_write(A.UC_ARM_REG_FPSCR,0x01400000)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    p=plan();assert p['packing']['spare_bytes']>=0
    for s in SPECS:
        corrupt=bytearray(IMAGE);corrupt[s['site']-BIAS]^=1
        for stock,target in ((corrupt,N[s['adapter']]),(IMAGE,N[s['adapter']]&~1),(IMAGE,0x10010001)):
            try:make_patch(stock,s,target)
            except ValueError:pass
            else:raise AssertionError('invalid startup patch accepted')
    assert p['packing']['globals']==[0x80960080,0x809600e0]
    passed('byte_gated_complete_startup_instructions_and_packed_source_budget',spare_bytes=p['packing']['spare_bytes'])

    hashes,helpers=scatter_startup(True,pack=P)
    assert len(helpers)==10 and helpers[4][3]==96
    passed('complete_original_scatter_entry_loads_startup_ELF_and_zeros_its_globals',original_regions=len(hashes))

    # Compare all registers/flags/FPU state at the original continuation.
    # For BL the expected LR is its return address, not the incoming sentinel.
    for spec in SPECS:
        site,end=spec['site'],spec['continuation']
        comparisons=0
        for flags in range(16):
            for alignment in (0,4):
                states=[]
                for patched in (False,True):
                    r=Boot(patched=patched);seed(r,flags,alignment)
                    if site==0x80067a84:put32(r.m,N['startup_status'],0)
                    states.append(run_raw(r,site,end));r.guard()
                assert states[0]==states[1],(hex(site),flags,alignment)
                comparisons+=1
        passed('startup_jump_matches_stock_at_'+hex(site),comparisons=comparisons)

    r=Boot();r.boot();r.guard()
    assert r.kernel_entered and not r.idle_failed and r.word(SCHEDULER)==1
    assert r.observed_init==0 and r.word(N['startup_status'])==3
    assert r.optional_calls==1 and r.word(WORKER+8)==4
    assert r.word(WORKER)==MAN and r.word(WORKER+4)==0x7f00
    assert bytes(r.m.uc.mem_read(WORKER+24,20))==struct.pack('<5I',4096,1,4,1,25)
    assert bytes(r.m.uc.mem_read(MAN+44,40))==struct.pack('<10I',0x809600e0,0x809607a0,
        0x809607c0,0x809608c0,0x80960960,0x80960da0,0x80962720,4096,1,r.word(0x801f8f38))
    assert r.word(N['bridge_gateway_readers'])==0x80000000
    assert r.word(N['ct_active'])==0 and r.word(N['emulator_bridge_current'])==0
    assert all(a%8==0 for a in r.c_stack) and len(r.c_stack)==2
    peak=TOP-r.minimum_sp
    # Descriptor/configuration reside on the boot stack and are copied. Erase
    # it before the worker starts to detect retention of these local inputs.
    r.m.uc.mem_write(TOP-0x2000,b'\xa5'*0x2000)
    delays=[];r.m.hooks[0x800770e8]=lambda a:0x7f00
    def delay(a):
        delays.append(a[0])
        return stop(r.m) if len(delays)==5 else 0
    r.m.hooks[0x80074158]=delay
    # Uninitialized capture arenas/history must not be touched while waiting.
    r.m.uc.mem_protect(0x80960000+0x1000,0x1000,UC_PROT_NONE)
    # Manager spans the protected page: W_WAITING short-circuits before access.
    r.m.invoke(N['native_worker_entry'],[WORKER]);r.guard()
    assert delays==[25]*5 and r.word(WORKER+8)==4 and r.word(WORKER+16)==0
    passed('actual_jumps_register_on_boot_stack_then_worker_sleeps_without_storage',
           original_tasks_and_idle=36,optional_calls=1,traced_added_path_stack_bytes=peak,idle_ticks=25)

    for fail in (('task',1),('mutex',1),('queue',1),('queue',7)):
        r=Boot(fail);r.boot();r.guard()
        assert r.observed_init==0xffffffff and r.word(N['startup_status'])==2
        assert r.kernel_entered and r.word(SCHEDULER)==1 and r.optional_calls==0
        assert bytes(r.m.uc.mem_read(MAN,2208+64))==b'\xa5'*(2208+64)
        assert r.m.invoke(0x80048248,[])==0
        r.m.invoke(N['startup_observe'],[0,0]);r.m.invoke(N['startup_register'],[0,0])
        assert r.word(N['startup_status'])==2 and r.optional_calls==0
    passed('first_initializer_failures_are_sticky_and_preserve_stock_kernel_path')

    for idle in ('negative','zero'):
        r=Boot(('idle',1) if idle=='negative' else None)
        if idle=='zero':
            original=r.m.hooks[0x80076c60]
            r.m.hooks[0x80076c60]=lambda a:0 if a[2]==90 and a[4]==0 else original(a)
        r.boot();r.guard()
        assert r.optional_calls==0 and not r.kernel_entered and r.word(N['startup_status'])==1
        assert r.idle_failed==(idle=='negative')
    passed('idle_failure_and_non_success_never_enter_optional_registration')

    for outcome in ('negative','zero','missing_handle'):
        r=Boot(optional=outcome);r.boot();r.guard()
        assert r.kernel_entered and r.word(SCHEDULER)==1 and r.optional_calls==1
        assert r.word(WORKER+8)==3 and r.word(WORKER+12)==13
        assert r.word(N['ct_active'])==0 and r.word(N['emulator_bridge_current'])==0
        r.m.invoke(N['startup_register'],[0,0]);assert r.optional_calls==1
    passed('optional_creation_failures_stay_closed_without_retries_or_stock_startup_changes')

    out=ROOT/'analysis/capture_startup_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),startup_elf_sha256=p['startup_elf_sha256'],
        limitations=p['limitations']+[
            'Original decoder/zero helpers load capture; stock early board initialization and interrupts are fixtures',
            'Original startup/scheduler instructions execute; task creation, allocator backing and kernel entry are modeled',
            'SP trace covers added code only with task creator intercepted; no boot or worker stack capacity proof',
            'Complete scatter entry and later startup bodies tested separately; no full device boot or live interrupts']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
