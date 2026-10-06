#!/usr/bin/env python3
"""Native file/FAT/cache -> original SD -> offline completion probe.

Unlike the earlier synthetic file router, all sector requests here come from
stock filesystem instructions. Sector bytes/DMA effects, RTOS, IRQ delivery
and completion/source permissions remain explicit models. No device binding.
"""
import hashlib,json,struct
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_native_filesystem import (NativeFiles,HANDLE,BUFFER,RESULT,
    PARTITION,FAT,DATA,DIRECTORY,MIRROR,READ,WRITE,CLOSE,IO_ERROR,SD,pattern)
from verify_capture_transitions import FS1,FS2,FS4,UI
from verify_sd_checked_recovery import RecoveryPorts
from verify_sd_transfer_probe import install
from verify_sd_transfer_lifetime import TABLE,UNIT,CARD,HOST,EVENT,EXPECTED
from verify_sd_card_recovery import STOP_FIELDS
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_pad_protocol import ROOT,IMAGE,REGS
from verify_scheduling_boundaries import stop
from sd_registers import DMA_ADDRESS,PRESENT,IRQ_STATUS,CLOCK_STABLE,DAT0_HIGH

ELF=ROOT/'analysis/capture_io_probe.elf'
UNIT_TOKEN,EVENT_TOKEN,FINISH_MODEL=0x7e20,0x7e21,0x2102ba00

class NativeFileSd(NativeFiles,RecoveryPorts):
    def __init__(self,finish_guard=True):
        NativeFiles.__init__(self)
        self.configure_sd(finish_guard)
    def configure_sd(self,finish_guard=True):
        m=self.m
        m.uc.mem_map(0x10020000,0x10000)
        with ELF.open('rb') as f:
            elf=ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type']=='PT_LOAD' and seg['p_filesz']:
                    m.uc.mem_write(seg['p_vaddr'],seg.data())
            self.syms={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        assert m.invoke(0x80001994,[0x800a6980,0x801f5400,0x3780])==0
        assert list(struct.unpack('<11I',m.uc.mem_read(TABLE,44)))==EXPECTED
        for base in (0x402c0000,0x400fc000,0xe000e000):
            if not any(lo<=base and base+0xfff<=hi for lo,hi,prot in m.uc.mem_regions()):m.uc.mem_map(base,0x1000)
        m.uc.mem_write(UNIT+4,b'\x01');put32(m,UNIT+8,UNIT_TOKEN)
        m.uc.mem_write(CARD+4,b'\0\x02');m.uc.mem_write(0x802142b4,b'\x01')
        put32(m,HOST+4,EVENT);put32(m,EVENT,EVENT_TOKEN);put32(m,0x402c0010,0x100)
        # Controlled SDHC addressing state: native split/bounce code tests bit
        # 30 here to advance command arguments by sectors instead of bytes.
        put32(m,HOST+12,0x40000000)
        self.unit_held=False;self.current=None;self.command_code=None;self.command_sector=None;self.stalled=False
        self.dma_effects=[]
        self.inject=None;self.injected=False;self.joins=[];self.finishes=[]
        self.join_allowed=False;self.finish_pending=None;self.busy_sector=None
        self.configure(abort=False) # Source exclusion remains a MODEL contract.
        put32(m,self.syms['sdp_join_port'],0x2102bd01)
        if finish_guard:put32(m,self.syms['sdp_finish_port'],FINISH_MODEL|1)
        install(m,self.syms)
        m.hooks[0x2102bd00]=self.join;m.hooks[FINISH_MODEL]=self.finish
        m.hooks[0x80074580]=lambda a:put32(m,a[0],0) or 0
        m.hooks[0x80073ec8]=m.hooks[0x80073f18]=lambda a:0
        previous_take=m.hooks[0x80076950];previous_give=m.hooks[0x800763d8]
        def take(a):
            if a[0]==UNIT_TOKEN:
                assert not self.unit_held and FS1 in self.locks.tokens
                self.unit_held=True;return 1
            return previous_take(a)
        def give(a):
            if a[0]==UNIT_TOKEN:
                assert self.unit_held;self.unit_held=False;return 1
            return previous_give(a)
        m.hooks[0x80076950]=take;m.hooks[0x800763d8]=give
        m.hooks.pop(SD) # Actual dispatcher, not the block callback model.
        def request(uc,pc,size,user):
            packet=self.raw(uc.reg_read(REGS[0]),20);op,unit=packet[:2]
            assert unit==1 and FS1 in self.locks.tokens
            self.assert_context()
            param,buf,count,sector=struct.unpack_from('<4I',packet,4)
            assert param==0
            self.current=dict(op=op,sector=sector,buffer=buf,count=count,
                tokens=sorted(self.locks.tokens),handle_state=self.raw(self.active_handle,1)[0])
            if op==6:
                assert packet[8] in (1,4,5,6)
                self.current.update(sector=None,buffer=None,count=None,subcommand=packet[8])
            else:assert op in (2,3)
            self.requests.append(self.current);self.command_code=None
        m.uc.hook_add(UC_HOOK_CODE,request,begin=SD,end=SD)
        def command(uc,pc,size,user):
            self.command_code=self.raw(uc.reg_read(REGS[0]),1)[0]
        m.uc.hook_add(UC_HOOK_CODE,command,begin=0x8006a348,end=0x8006a348)
        def argument(uc,pc,size,user):
            # The native command clears ARG after command completion. Observe
            # its issued value before that cleanup, without replacing the store.
            self.command_sector=uc.reg_read(A.UC_ARM_REG_R3)
        m.uc.hook_add(UC_HOOK_CODE,argument,begin=0x8006a528,end=0x8006a528)

    def owner(self):return self.unit_held and FS1 in self.locks.tokens
    def stop_state(self):
        return dict(zip(STOP_FIELDS,struct.unpack('<10I',self.raw(self.syms['sdp_stop_state'],40))))
    def data_deliver(self,a):
        assert self.owner() and self.probe()['active'] and a[0]==EVENT and a[2]==5000
        assert a[1] in (0x183,0x185)
        stage='data' if a[1]==0x185 else 'status' if self.command_code==15 else 'command'
        faulty=not self.injected and self.inject and self.inject==(self.current['op'],self.current['sector'],stage)
        raw=1 if a[1]==0x183 else 2
        if faulty:self.injected=True;raw|=0x100000
        if stage=='data' and not faulty:
            # Explicit DMA MODEL at data delivery. Native registers determine
            # the DMA buffer/count/sector; stock bounce copies also execute.
            # No file-byte translation or synthetic file router is supplied.
            q=self.current
            dma=word(self.m,DMA_ADDRESS);count=word(self.m,0x402c0004)>>16
            sector=self.command_sector
            assert count and q['sector']<=sector and sector+count<=q['sector']+q['count']
            self.dma_effects.append((q['op'],dma,count,sector))
            if q['op']==2:
                self.m.uc.mem_write(dma,b''.join(self.sectors.get(sector+i,bytes(512)) for i in range(count)))
            else:
                for i in range(count):self.sectors[sector+i]=self.raw(dma+i*512,512)
        put32(self.m,EVENT+8,0);put32(self.m,IRQ_STATUS,raw)
        busy=faulty or self.current['sector']==self.busy_sector
        put32(self.m,PRESENT,CLOCK_STABLE|(0x206 if busy else DAT0_HIGH))
        return 1
    def join(self,a):
        assert self.owner() and self.probe()['failed'] and not self.probe()['finished']
        assert a[:3]==[0,self.current['buffer'],self.current['count']*512]
        self.joins.append(dict(request=dict(self.current),sp=self.m.uc.reg_read(A.UC_ARM_REG_SP)))
        if not self.join_allowed:self.stalled=True;return stop(self.m)
        put32(self.m,PRESENT,CLOCK_STABLE|DAT0_HIGH);put32(self.m,IRQ_STATUS,0)
        return 1 # Explicit MODEL completion, never inferred from status or reset.
    def finish(self,a):
        assert self.owner() and self.probe()['active'] and not self.probe()['finished']
        assert a[:4]==[0,EVENT,self.current['buffer'],self.current['count']*512]
        assert a[5]==self.probe()['failed']
        self.finishes.append(dict(request=dict(self.current),args=tuple(a[:6])))
        if self.current['sector']==self.finish_pending:
            self.stalled=True;return stop(self.m)
        return 1
    def frame(self):
        sp=self.m.uc.reg_read(A.UC_ARM_REG_SP)
        return self.raw(sp,getattr(self.m,'stack',0x20010000)-sp)
    def retained(self,tokens):
        assert self.stalled and self.owner() and self.locks.tokens==set(tokens)
        assert self.probe()['active'] and not self.probe()['finished']
        assert word(self.m,0x801f8df0)==self.current_task()
    def resume_io(self):
        self.stalled=False;result=RecoveryPorts.resume(self)
        assert not self.owner() and self.locks.tokens=={UI} and word(self.m,0x801f8df0)==0
        return result

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=NativeFileSd();r.empty();first=pattern(700,131);second=pattern(5000,25)
    assert r.io(WRITE,len(first),first)==(0,len(first))
    assert r.io(WRITE,len(second),second)==(0,len(second)) and r.close()==0
    r.chain=(2,3);assert r.logical()[:5700]==first+second
    assert r.sectors[PARTITION+FAT]==r.sectors[PARTITION+FAT+MIRROR]
    assert struct.unpack_from('<I',r.sectors[PARTITION+DIRECTORY],60)[0]==5700
    assert len(r.finishes)==len(r.requests)-1 and not r.joins
    # Controlled reopen: handle identity is modeled; original reads execute.
    r.m.uc.mem_write(HANDLE,b'\x40\0');r.position(0)
    assert r.io(READ,5700)==(0,5700) and r.raw(BUFFER,5700)==first+second
    assert sum(count for op,dma,count,sector in r.dma_effects)==sum(q['count'] for q in r.requests if q['op'] in (2,3))
    assert {op for op,dma,count,sector in r.dma_effects if dma==0x2000c4d4}=={2,3}
    assert any(BUFFER<=dma<BUFFER+5700 for op,dma,count,sector in r.dma_effects)
    passed('native_allocation_append_close_and_readback_use_actual_SD_dispatch_and_driver',
           requests=len(r.requests),physical_join='MODEL only')

    for op,sector,stage in ((2,PARTITION+FAT,'data'),(2,PARTITION+DATA,'data'),
                            (3,PARTITION+DATA,'command'),(3,PARTITION+DATA,'data'),
                            (3,PARTITION+DATA,'status')):
        r=NativeFileSd();r.inject=(op,sector,stage)
        r.m.uc.mem_write(BUFFER,pattern(1024));put32(r.m,RESULT,0xdeadbeef)
        r.m.invoke(READ if op==2 and sector==PARTITION+DATA else WRITE,[HANDLE,BUFFER,1024,RESULT])
        r.retained((UI,FS1));assert word(r.m,RESULT)==0 and word(r.m,HANDLE+0x22c)==0
        frame=r.frame();requests=list(r.requests)
        assert RecoveryPorts.resume(r)==0 # Repeated MODEL wait cannot unwind.
        r.retained((UI,FS1))
        assert r.frame()==frame and r.requests==requests
        r.join_allowed=True;assert r.resume_io()==IO_ERROR
        assert r.injected and len(r.joins)==3 and word(r.m,RESULT)==0
        assert r.requests==requests # No resubmission while unwinding the error.
    passed('native_FAT_read_payload_read_and_write_failures_keep_file_SD_and_exception_frames_until_MODEL_join',combinations=5)

    for sector in (PARTITION+FAT,PARTITION+FAT+MIRROR,PARTITION+DATA+1,PARTITION+DIRECTORY):
        r=NativeFileSd();r.empty();assert r.io(WRITE,700,pattern(700))==(0,700)
        r.inject=(3,sector,'data');r.m.invoke(CLOSE,[HANDLE])
        r.retained((UI,FS1,FS2,FS4));assert r.raw(HANDLE,1)==b'\xff'
        # The original close has already changed cache bookkeeping; retaining
        # the native call, unit and file tokens still prevents its unwinding.
        assert r.raw(r.current['buffer']+0x204,1)==b'\0'
        r.join_allowed=True;assert r.resume_io()==IO_ERROR
        assert not any(q['op']==6 for q in r.requests)
    passed('FAT_primary_mirror_cached_payload_and_directory_close_errors_retain_all_three_file_tokens_before_unwind',transfers=4)

    r=NativeFileSd();r.finish_pending=PARTITION+DATA;r.busy_sector=PARTITION+DATA
    r.m.uc.mem_write(BUFFER,pattern(1024));r.m.invoke(WRITE,[HANDLE,BUFFER,1024,RESULT])
    r.retained((UI,FS1));assert not r.probe()['failed'] and word(r.m,RESULT)==0
    r.finish_pending=None;r.busy_sector=None;put32(r.m,PRESENT,CLOCK_STABLE|DAT0_HIGH)
    assert r.resume_io()==0 and word(r.m,RESULT)==1024
    passed('nominal_success_retains_original_direct_payload_frame_until_MODEL_final_completion')

    r=NativeFileSd(finish_guard=False);r.busy_sector=PARTITION+DATA
    assert r.io(WRITE,1024,pattern(1024))==(0,1024) and not r.owner()
    assert word(r.m,PRESENT)&0x206==0x206 and not r.finishes
    passed('negative_control_error_only_guard_releases_real_file_and_SD_tokens_while_controller_MODEL_stays_active')

    report=dict(firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),passed_groups=len(cases),results=cases,
        limitations=['Actual file/FAT/cache requests replace the synthetic dependency router; controlled geometry, handle/reopen and cache list.',
            'DMA sector effects, IRQ timing, RTOS, source exclusion and physical completion are MODEL inputs.',
            'No compiled capture manager composition, full mount/open/bitmap/FSInfo path, device binding or installable image.'])
    (ROOT/'analysis/native_filesystem_sd_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
