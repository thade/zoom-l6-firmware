#!/usr/bin/env python3
"""Compiled cold Main/USB witness over native instructions; offline only.

Filesystem and USB tests are separate bounded harnesses. USB requester and
worker share one memory image and switch modeled task contexts. Peripheral
setup, kernel calls and physical completion remain models; no release occurs.
"""
import hashlib,json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,RETURN
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_scheduling_boundaries import stop
from verify_native_storage_setup import FolderTree
from verify_native_exfat import ExfatFolders
from verify_overdub_prototype import Emulator
from verify_usb_startup_ack import STATE,REQUEST,ACK
from plan_capture_boot import ELF,SPECS,CALLS,plan
from plan_capture_lz4 import packing
from capture_jump_patches import symbols
from verify_capture_sd_retained import CombinedRig

PACK=packing(ELF,source_reuse=True);PLAN=plan(PACK);N=symbols(ELF)
MAIN,WORKER=0x7003,0x7004
COLD,CARD,MOUNTED,CARD_DONE,USB,REQUESTED,CONSUMED,ACKED,USB_DONE,READY,REVOKED=range(11)

class BootCapture(CombinedRig):
    elf_path=ELF;patch_plan=PLAN;packed=PACK;candidate_globals=tuple(PLAN['packing']['globals'])

def install(m):
    with ELF.open('rb') as f:
        for s in ELFFile(f).iter_segments():
            if s['p_type']=='PT_LOAD':
                m.uc.mem_write(s['p_vaddr'],s.data()+bytes(s['p_memsz']-s['p_filesz']))
    for p in PLAN['boot_patches']+[p for p in PLAN['patches'] if p.get('adapter')=='storage_main_receive']:
        m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
        m.uc.ctl_remove_cache(p['site'],p['site']+len(bytes.fromhex(p['patch'])))
    put32(m,0x801f9048,1);put32(m,0x80446da4,MAIN)
    m.hooks[0x800770e8]=lambda a:MAIN
    m.hooks[0x80006248]=lambda a:0
    return m

def phase(m):return word(m,N['storage_boot_phase'])

def mounted(cls,mode=0,**kwargs):
    r=cls(**kwargs.pop('constructor',{}));m=install(r.m)
    put32(m,0x80446da4,r.current_task())
    m.hooks[0x800770e8]=lambda a:r.current_task()
    m.hooks[0x80006248]=lambda a:mode
    invoke=m.invoke
    # Redirect only the harness entry, not the real call inside the wrapper.
    m.invoke=lambda address,args:invoke(N['storage_boot_card'] if address==0x80009a40 else address,args)
    result=r.setup_card(argument=0,**kwargs)
    return r,result,phase(m)

class USBRun:
    def __init__(self,success=True,stale=False):
        m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True)
        m.uc.mem_map(0x81000000,0x1000000)
        m.invoke(0x80001994,[0x800a6980,0x801f5400,0x3780])
        self.m=m=install(m);self.task=MAIN;self.stale=stale
        self.main_context=None;self.gives=[];self.setups=[];self.pids=[]
        self.consume=False;self.worker_waits=0
        for a,n in ((0x401b0000,0x10000),(0x401f8000,0x1000),(0xe000e000,0x1000)):
            m.uc.mem_map(a,n)
        put32(m,STATE,REQUEST);put32(m,STATE+12,ACK);put32(m,STATE+24,0x7002)
        put32(m,N['storage_boot_phase'],CARD_DONE) # mount is independently executed above
        m.hooks[0x800770e8]=lambda a:self.task
        m.hooks[0x800345f8]=lambda a:0x1234
        for fn in (0x80077686,0x80073ec8,0x80073f18,0x80006aa8,
                   0x8003b580,0x80025f78,0x8001bcd8,0x8001bc98,0x80026bf0,
                   0x8001bc20,0x80026b90,0x8003b558,0x8003b5d0):
            m.hooks[fn]=lambda a:0
        m.hooks[0x800684b8]=lambda a:self.setups.append('SD_setup') or 0
        m.hooks[0x80068318]=lambda a:self.setups.append('SD_teardown') or 0
        m.hooks[0x80068508]=lambda a:self.setups.append('SD_notify') or 0
        def start(a):
            self.pids.append(struct.unpack('<H',m.uc.mem_read(a[0]+4,2))[0]);return int(success)
        def give(a):
            self.gives.append((a[0],phase(m)));return 1
        def take(a):
            if self.task==MAIN:
                assert a[:2]==[ACK,0xffffffff]
                if self.stale:return 1
                self.main_context=m.uc.context_save();return stop(m)
            assert a[:2]==[REQUEST,10]
            if not self.worker_waits:
                self.worker_waits+=1;return 1
            return stop(m)
        m.hooks.update({0x8003b5a8:start,0x800763d8:give,0x80076950:take})
    def request(self,profile=0):
        self.task=MAIN
        # Execute the actual encoded Main BL; stop on its normal continuation.
        h=self.m.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:stop(self.m),begin=0x8002c348,end=0x8002c348)
        try:self.m.invoke(0x8002c344,[0,profile])
        finally:self.m.uc.hook_del(h)
    def worker(self):
        self.task=WORKER;self.m.stack=0x20018000
        try:self.m.invoke(0x80045cf0,[])
        finally:self.m.stack=0x20010000
    def resume_main(self):
        m=self.m;self.task=MAIN;m.uc.context_restore(self.main_context)
        # Model the native ACK wait returning after the actual worker give.
        m.uc.reg_write(A.UC_ARM_REG_R0,1)
        m.uc.reg_write(A.UC_ARM_REG_PC,m.uc.reg_read(A.UC_ARM_REG_LR))
        h=m.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:stop(m),begin=0x8002c348,end=0x8002c348)
        try:
            m.reached_return=False;m.uc.emu_start(m.uc.reg_read(A.UC_ARM_REG_PC)|1,RETURN+2,count=100000)
            assert m.reached_return
        finally:m.uc.hook_del(h)
    def receive(self,packet=(1,4,26,0,0),site=0x8002c440):
        self.task=MAIN;m=self.m
        m.hooks[0x80020690]=lambda a:m.uc.mem_write(a[0],struct.pack('<5I',*packet)) or 0
        h=m.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:stop(m),begin=site+4,end=site+4)
        try:m.invoke(site,[0x20030000])
        finally:m.uc.hook_del(h)
    def complete(self,profile=0):
        self.request(profile);assert phase(self.m)==REQUESTED
        self.worker();assert phase(self.m)==ACKED
        self.resume_main();assert phase(self.m)==USB_DONE
        self.receive();assert phase(self.m)==READY

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    assert PLAN['packing']['spare_bytes']>0
    assert PLAN['boot_state_bytes']==12
    # No FP instructions in any observer function/callee in the new module.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    with ELF.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        for s in e.get_section_by_name('.symtab').iter_symbols():
            if (s.name.startswith('storage_boot_') or s.name in ('advance','main_thread')) and s['st_info']['type']=='STT_FUNC':
                a=s['st_value']&~1;n=s['st_size']
                if not n:continue # Assembly adapters are verified by replay below.
                seg=next(p for p in segments if p['p_vaddr']<=a<a+n<=p['p_vaddr']+p['p_filesz'])
                code=seg.data()[a-seg['p_vaddr']:a-seg['p_vaddr']+n]
                assert not any(i.mnemonic.startswith(('v','f')) for i in md.disasm(code,a)),s.name
    passed('Six new byte-checked patches fit consumed-source layout and integer-only observers need no FP save',
           raw_code_bytes=PLAN['raw_code_bytes'],globals_bytes=PLAN['globals_bytes'],spare_bytes=PLAN['packing']['spare_bytes'])

    registers=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(13)]+[A.UC_ARM_REG_LR,A.UC_ARM_REG_SP,A.UC_ARM_REG_APSR]
    for spec in SPECS:
        for alignment in (0,4):
            snapshots=[]
            for patched in (False,True):
                m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True);install(m)
                if not patched:m.uc.mem_write(spec['site'],bytes.fromhex(spec['original']))
                m.stack=0x20010000+alignment
                for i,r in enumerate(registers[:13]):m.uc.reg_write(r,0x100+i)
                m.uc.reg_write(A.UC_ARM_REG_R6,STATE);m.uc.reg_write(A.UC_ARM_REG_R8,STATE)
                m.uc.reg_write(A.UC_ARM_REG_R7,0);m.uc.reg_write(A.UC_ARM_REG_R10,0)
                m.uc.reg_write(A.UC_ARM_REG_APSR,0xa8000000)
                put32(m,STATE+4,0x20);put32(m,STATE+8,0x1234)
                m.hooks[0x80006140]=lambda a:0
                def end(u,a,n,x):
                    snapshots.append(([u.reg_read(r) for r in registers],bytes(u.mem_read(STATE,28))))
                    stop(m)
                m.uc.hook_add(UC_HOOK_CODE,end,begin=spec['resume'],end=spec['resume'])
                m.invoke(spec['site'],[])
            assert snapshots[0]==snapshots[1],(spec,alignment,snapshots)
    passed('All four inline observers replay original registers, flags, stack and mailbox effects at both stack alignments')

    for cls in (FolderTree,ExfatFolders):
        r,result,p=mounted(cls);assert result==0 and p==CARD_DONE;r.verify_folders()
        for kw in (dict(present=False),dict(constructor={'readonly':True}),dict(mode=2),dict(mode=3)):
            r,result,p=mounted(cls,**kw);assert p==REVOKED
    passed('Compiled card wrapper uses actual FAT32/exFAT success branch; missing card, folder failure and special boots stay revoked')

    rows=[]
    for profile in range(3):
        for success in (False,True):
            r=USBRun(success);r.complete(profile)
            assert r.gives==[(REQUEST,REQUESTED),(ACK,ACKED)] and not r.setups
            assert r.m.invoke(N['storage_boot_ready'],[])==1
            rows.append(dict(profile=profile,USB_setup_success=success,pids=r.pids))
    passed('Same-memory native requester and worker match all three audio-only profiles before first Main receive',rows=rows)

    for profile in range(3):
        r=USBRun(stale=True);r.request(profile);assert phase(r.m)==REVOKED
        r.worker();r.receive();assert phase(r.m)==REVOKED
        assert r.m.invoke(N['storage_boot_ready'],[])==0
    passed('Stale ACK cannot qualify and later real worker completion cannot revive the boot')

    for address,value in ((STATE+4,0x40),(STATE+8,0x5678)):
        r=USBRun();r.request();put32(r.m,address,value);r.worker()
        assert phase(r.m)==REVOKED;r.resume_main();r.receive();assert phase(r.m)==REVOKED
    r=USBRun();put32(r.m,STATE+4,0x40);r.worker();assert phase(r.m)==REVOKED
    r=USBRun();r.complete();r.request();assert phase(r.m)==REVOKED
    passed('Changed command/argument, prior SD worker history and second USB request cannot reuse a witness')

    for site in (0x8002c258,0x8002c39c,0x8002c3d4,0x8002c408):
        r=USBRun();r.request();r.worker();r.resume_main();r.receive(site=site)
        assert phase(r.m)==REVOKED
    for packet in ((0,8,0x32,0,0),(1,0,2,0,0),(2,0,0xa2,0,0),(2,0xffffffff,0xa3,0,0)):
        r=USBRun();r.complete();r.receive(packet);assert phase(r.m)==REVOKED
        r.receive();assert phase(r.m)==REVOKED
    r=USBRun();r.complete();r.receive();assert phase(r.m)==READY
    passed('Only ordinary Main reception qualifies; all existing transition classes revoke before their handlers')

    r=BootCapture();assert r.boot()==0
    # Other physical prerequisites are supplied by this existing explicit
    # admission harness; the new logical requirement is necessary, not enough.
    for p in (COLD,CARD,CARD_DONE,REQUESTED,CONSUMED,ACKED,USB_DONE,REVOKED):
        put32(r.m,N['storage_boot_phase'],p)
        assert r.admit()==12 and r.lstate()==0
    put32(r.m,N['storage_boot_phase'],READY)
    assert r.admit()==0 and r.lstate()==1
    assert word(r.m,r.worker+8)==4
    passed('Linked lease admission requires complete boot witness even with explicit modeled physical prerequisites; worker remains waiting')

    # Capture remains dormant and every physical storage port remains null.
    r=USBRun();r.complete()
    assert word(r.m,N['startup_arena'])==0
    for n in ('sdp_source_port','sdp_chunk_admit_port','sdp_chunk_finish_port','sdp_cache_read_port'):
        assert word(r.m,N[n])==0
    passed('Logical readiness has no side effect on worker allocation, lease admission, physical ports or file I/O')
    report=dict(passed_groups=len(cases),cases=cases,plan=PLAN,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=PLAN['limitations']+['Filesystem and USB are separate bounded harnesses; USB task switching and kernel/peripheral setup are modeled.'])
    out=ROOT/'analysis/storage_boot_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
