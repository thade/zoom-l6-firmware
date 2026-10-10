#!/usr/bin/env python3
"""Original SD initialization and small-data paths, using a virtual card.

Card responses/FIFO, reset effects and kernel scheduling are models. Original
driver tables, command/data instructions and event predicates execute. No
physical source lease, capture release, firmware patch or device access.
"""
import hashlib,json,struct
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_sd_transfer_lifetime import Sd,UNIT,CARD,HOST,EVENT,SEM,REQ,BUFFER
from verify_pad_protocol import ROOT,IMAGE,REGS,RETURN
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_scheduling_boundaries import stop
from sd_registers import (SD,PRESENT,SYSTEM,PROTOCOL,MIX,COMMAND,BLOCKS,
                          DMA_ADDRESS,RESET_ALL,INITIAL_CLOCKS)

CONFIG=0x2100a000
CALLBACK=0x802350e4
PIO_READ_WAIT=0x80069d64
PIO_WRITE_WAIT=0x8006a904

class Cold(Sd):
    def __init__(self,emulator=None):
        super().__init__(emulator);m=self.m
        self.trace=[];self.commands=[];self.waits=[];self.fifo=[];self.fifo_reads=[]
        self.fifo_writes=[];self.dma=[];self.tick=0;self.reset_clear=True
        self.event_result=EVENT;self.token_result=SEM
        self.hold_site=None;self.bad_final=None;self.bad_command=None
        self.responses={3:0x12340000,8:0x1aa,41:0xc0ff8000}
        self.scr=bytes.fromhex('0001000000000000')
        self.switch=bytes(64)
        self.csd=bytes.fromhex('400000325b5900007fff0000000000')
        self.ready_after=0;self.ready_polls=0
        self.command_number=None;self.command_value=0
        self.m.uc.mem_write(UNIT,bytes(12));self.m.uc.mem_write(CARD,bytes(32))
        put32(m,HOST+4,0);put32(m,CALLBACK,0x12345679)
        put32(m,CONFIG,198000000);put32(m,CONFIG+4,0)
        put32(m,PRESENT,0x01000008);put32(m,PROTOCOL,0x20)
        m.hooks.pop(0x8006a348);m.hooks.pop(0x800328c0)
        m.hooks[0x800321f8]=lambda a:self.created('unit_token',self.token_result)
        m.hooks[0x800321c0]=lambda a:self.created('controller_semaphore',0x7003)
        m.hooks[0x800321b8]=lambda a:self.created('controller_event',self.event_result)
        m.hooks[0x80032218]=lambda a:self.trace.append(('delete',a[0])) or 0
        # Divider arithmetic and scheduler endpoints are explicit fixtures.
        m.hooks[0x80069510]=lambda a:put32(m,a[0],1) or put32(m,a[1],1) or 0
        m.hooks[0x80032250]=self.delay
        m.hooks[0x80032818]=self.clock
        m.hooks[0x80076950]=lambda a:1
        m.hooks[0x80074580]=lambda a:put32(m,a[0],0) or 0
        m.hooks[0x80073ec8]=m.hooks[0x80073f18]=lambda a:0
        m.uc.hook_add(UC_HOOK_CODE,self.at_wait,begin=0x800328c0,end=0x800328c0)
        m.uc.hook_add(UC_HOOK_MEM_READ,self.read_fifo,begin=SD+0x20,end=SD+0x23)
        m.uc.hook_add(UC_HOOK_MEM_WRITE,self.write_register,begin=SD,end=SD+0x48)
        m.uc.hook_add(UC_HOOK_CODE,self.reset_effect,begin=0x80069b9c,end=0x80069b9c)
        for p in (0x80069b20,0x800694f8,0x80068548,0x8006ae78,0x800699b8):
            m.uc.hook_add(UC_HOOK_CODE,
                lambda u,p,n,x:self.trace.append(('entry',hex(p),u.reg_read(REGS[0]),u.reg_read(REGS[1]))),
                begin=p,end=p)

    def created(self,name,value):
        self.trace.append((name,value))
        if name=='controller_event' and value:
            self.m.uc.mem_write(value,bytes(12));put32(self.m,value,0x7002)
        return value

    def delay(self,a):
        self.tick+=a[0]
        if self.tick>100000:raise AssertionError('Unexpected unbounded modeled delay')
        return 0

    def clock(self,a):put32(self.m,a[0],self.tick);return 0

    def reset_effect(self,u,p,n,x):
        if self.reset_clear:
            # Only self-clear is modeled; not a controller reset implementation.
            put32(self.m,SYSTEM,word(self.m,SYSTEM)&~RESET_ALL)

    def read_fifo(self,u,k,p,n,x,_):
        assert n==4 and self.fifo,('FIFO underflow',self.command_number,self.commands)
        value=self.fifo.pop(0);put32(self.m,SD+0x20,value);self.fifo_reads.append(value)

    def write_register(self,u,k,p,n,v,_):
        if p==DMA_ADDRESS:self.dma.append((u.reg_read(A.UC_ARM_REG_PC),v))
        if p==SD+0x20:self.fifo_writes.append(v)
        if p!=COMMAND:return
        self.command_number=v>>24&0x3f;self.command_value=v
        self.commands.append(dict(number=self.command_number,value=v,
            argument=word(self.m,SD+8),blocks=word(self.m,BLOCKS),mix=word(self.m,MIX)))
        response=self.responses.get(self.command_number,0)
        if self.command_number==41:
            self.ready_polls+=1
            if self.ready_polls<=self.ready_after:response&=~0x80000000
        put32(self.m,SD+0x10,response)
        if self.command_number in (2,9):
            # Original command response unpacker converts 136-bit registers to
            # these 15 bytes. CSD is one explicit synthetic high-capacity card.
            data=self.csd if self.command_number==9 else bytes(15)
            put32(self.m,SD+0x1c,int.from_bytes(data[:3],'big'))
            for off,index in ((0x18,3),(0x14,7),(0x10,11)):
                put32(self.m,SD+off,int.from_bytes(data[index:index+4],'big'))
        if v&0x200000:
            size=(word(self.m,BLOCKS)&0xffff)*(word(self.m,BLOCKS)>>16)
            # These are synthetic card responses; the original parser decides
            # width/speed and may issue more reads. No negotiation is stubbed.
            data=self.scr if self.command_number==51 else self.switch if self.command_number==6 else bytes(64)
            assert size<=len(data),(self.command_number,size)
            self.fifo=list(struct.unpack('<'+'I'*((size+3)//4),data[:size]+bytes((-size)%4)))

    def at_wait(self,u,p,n,x):
        a=[u.reg_read(r) for r in REGS[:4]]
        site=u.reg_read(A.UC_ARM_REG_LR)-5
        assert a[0]==EVENT and a[2]==1,(a,hex(site))
        flags=2 if a[1]==0x183 else 4 if a[1]==0x185 else a[1]
        if site in (PIO_READ_WAIT,PIO_WRITE_WAIT) and self.bad_final is not None:flags=self.bad_final
        if a[1]==0x183 and self.bad_command is not None:flags=self.bad_command
        self.waits.append(dict(site=hex(site),mask=a[1],flags=flags,held=self.held))
        # Native 328c0 executes its ANY-bit test and clears the accepted bits.
        # Posted flags and a successful semaphore take are the environment.
        put32(self.m,EVENT+8,flags)
        if self.hold_site==site:stop(self.m)

    def cold(self):return self.m.invoke(0x800684b8,[CONFIG])

    def operation(self,op):
        request=bytearray(20);request[0]=op;request[1]=1
        self.m.uc.mem_write(REQ,bytes(request))
        return self.m.invoke(0x80068378,[REQ])

    def enumerate(self):
        assert self.cold()==0
        assert self.operation(0)==0
        # Native initialization issued initial clocks. Completion is modeled
        # before enumeration, separately from the earlier reset-bit self-clear.
        put32(self.m,SYSTEM,word(self.m,SYSTEM)&~INITIAL_CLOCKS)
        return self.operation(4)

    def resume(self):
        self.m.reached_return=False
        self.m.uc.emu_start(self.m.uc.reg_read(A.UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
        assert self.m.reached_return
        return self.m.uc.reg_read(REGS[0])

    def install_block_guard(self):
        from verify_sd_transfer_probe import ELF,install
        self.m.uc.mem_map(0x10010000,0x20000)
        with ELF.open('rb') as f:
            elf=ELFFile(f)
            for segment in elf.iter_segments():
                if segment['p_type']=='PT_LOAD' and segment['p_filesz']:
                    self.m.uc.mem_write(segment['p_vaddr'],segment.data())
            symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        install(self.m,symbols)
        # Ports may be selected, but the current block wrapper has no active
        # scope during operation 4. An unexpected model call must fail this test.
        def forbidden(a):raise AssertionError('Unexpected block-guard source/join call during enumeration')
        self.m.hooks[0x2102b800]=self.m.hooks[0x2102bd00]=self.m.hooks[0x2102bd04]=forbidden
        put32(self.m,symbols['sdp_chunk_finish_port'],0x2102b801)
        put32(self.m,symbols['sdp_chunk_admit_port'],0x2102b801)
        return symbols

def high_speed_card(r,ready_after=6):
    """Synthetic SDXC-like capabilities, not a dump of the user's card.

    Original parsing sees SCR spec3/four-bit support and successful switch
    status. The six busy ACMD41 polls reproduce the observed aggregate counts,
    but these counts do not uniquely identify the physical response sequence.
    """
    r.scr=bytes.fromhex('0205800000000000');r.ready_after=ready_after
    csd=bytearray(r.csd);csd[7:10]=bytes.fromhex('0fffff');r.csd=bytes(csd)
    switch=bytearray(64);switch[0]=1;switch[16]=1;r.switch=bytes(switch)
    r.responses[6]=0x20 # Native ACMD6 validation requires APP_CMD in R1.
    return r

def main():
    checks=[]
    def passed(case,**details):checks.append(dict(case=case,**details))
    assert hashlib.sha256(IMAGE).hexdigest()=='64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'

    r=Cold();assert r.cold()==0
    assert [t[1:] for t in r.trace if t[0]=='entry']==[
        (hex(p),0,198000000) for p in (0x80069b20,0x800694f8,0x80068548,0x8006ae78)]
    assert word(r.m,UNIT+8)==SEM and not word(r.m,CALLBACK)
    assert not word(r.m,HOST+4) and not r.commands
    assert word(r.m,0x808e07d4)==0
    passed('Cold constructor executes all four original driver-table initializers with the pointed-to clock configuration before event creation')

    r=Cold();put32(r.m,UNIT+8,SEM)
    assert r.cold()==1 and not r.trace and word(r.m,CALLBACK)==0x12345679
    r=Cold();assert r.m.invoke(0x800684b8,[0])==2 and not r.trace
    r=Cold();r.token_result=0
    assert r.cold()==0 and not word(r.m,UNIT+8)
    r=Cold();r.reset_clear=False
    assert r.cold()==0 and word(r.m,SYSTEM)&RESET_ALL
    passed('An existing token bypasses reset; constructor success alone does not prove token allocation or reset completion')

    r=Cold();r.m.hooks[0x80069b20]=lambda a:1
    assert r.cold()==1 and word(r.m,UNIT+8)==SEM
    assert word(r.m,CALLBACK)==0x12345679
    before=list(r.trace);assert r.cold()==1 and r.trace==before
    r=Cold();r.event_result=0
    assert r.cold()==0 and r.operation(0)==0xffffd8ef
    assert not word(r.m,HOST+4) and not word(r.m,HOST+8) and not r.held
    assert r.m.uc.mem_read(UNIT+4,1)==b'\x01'
    assert ('delete',0x7003) in r.trace
    before=list(r.trace);assert r.operation(0)==0xffffd7c3 and r.trace==before
    passed('Failed cold driver or event setup retains partially initialized native state; repeating setup is not a fresh cold witness')

    r=Cold();assert r.enumerate()==0 and not r.held
    assert [c['number'] for c in r.commands]==[0,8,55,41,2,3,9,7,55,13,55,51,16]
    data=[c for c in r.commands if c['value']&0x200000]
    assert [(c['number'],c['blocks']) for c in data]==[(13,0x10040),(51,0x10008)]
    assert all(c['mix']&0x11==0x10 for c in data) and not r.dma
    assert len(r.fifo_reads)==18 and not r.fifo
    assert all(w['held'] for w in r.waits)
    assert [w['site'] for w in r.waits if w['mask']==0x185]==[hex(PIO_READ_WAIT)]*2
    assert r.m.uc.mem_read(CARD+5,1)==b'\x02' and word(r.m,CARD+0x10)==0x2000000
    nominal=dict(commands=r.commands,waits=r.waits,card=bytes(r.m.uc.mem_read(CARD,32)).hex())
    passed('Continuous original cold setup and enumeration reach card-ready via 64-byte status and 8-byte SCR FIFO reads under the native unit token',
        command_count=len(r.commands),fifo_bytes=len(r.fifo_reads)*4,
        data_wait_site=hex(PIO_READ_WAIT),dma_address_writes=0)

    r=high_speed_card(Cold());assert r.enumerate()==0 and not r.held
    data=[c for c in r.commands if c['value']&0x200000]
    assert [(c['number'],c['argument'],c['blocks']) for c in data]==[
        (13,0,0x10040),(51,0,0x10008),(6,1,0x10040),(6,1,0x10040),
        (6,0x80000001,0x10040),(6,1,0x10040)]
    assert len(r.commands)==31 and len(r.waits)==43 and r.ready_polls==7
    assert len(r.fifo_reads)==82 and not r.fifo and not r.dma
    assert word(r.m,PROTOCOL)&6==2 and word(r.m,CARD+4)==0x015a0220
    assert all(w['held'] for w in r.waits)
    passed('Original four-bit/high-speed SDXC negotiation performs six PIO reads and matches the hardware trace aggregate counts with synthetic responses',
        command_count=31,wait_count=43,pio_reads=6,fifo_bytes=328,
        physical_response_sequence_proven=False)

    for flags in (1,0x80,0x100,0x104):
        r=high_speed_card(Cold());r.bad_final=flags
        assert r.enumerate()==0 and word(r.m,CARD+4)==0x015a0220
        assert len([w for w in r.waits if w['mask']==0x185])==6
    r=high_speed_card(Cold());r.responses[6]=0
    assert r.enumerate()!=0 and not r.m.uc.mem_read(CARD+5,1)[0]&2
    passed('High-speed negotiation retains the final-wait false-success counterexample, while a missing ACMD6 response bit is rejected by original parsing')

    r=Cold();r.hold_site=PIO_READ_WAIT;r.enumerate()
    assert r.held and not r.m.uc.mem_read(CARD+5,1)[0]&2
    assert len(r.fifo_reads)==16 and r.commands[-1]['number']==13
    assert r.m.uc.reg_read(A.UC_ARM_REG_PC)==0x800328c0
    r.hold_site=None;assert r.resume()==0 and not r.held and len(r.fifo_reads)==18
    passed('An unfinished startup FIFO completion keeps original enumeration, dispatcher frame and unit token live')

    for flags in (1,0x80,0x100,0x104):
        r=Cold();r.bad_final=flags
        assert r.enumerate()==0 and not r.held and r.m.uc.mem_read(CARD+5,1)==b'\x02'
        assert all(w['flags']==flags for w in r.waits if w['mask']==0x185)
    passed('Counterexample: original startup final ANY waits accept error or software notification bits and still mark the virtual card ready',
        injected_flags=[1,128,256,260],physical_fault_reproduced=False)

    for flags in (1,0x80,0x100):
        r=Cold();r.bad_command=flags
        assert r.enumerate()!=0 and not r.held and not r.fifo_reads
        assert not r.m.uc.mem_read(CARD+5,1)[0]&2
    r=Cold();r.responses[8]=0x1ab
    assert r.enumerate()!=0 and not r.held and not r.fifo_reads
    assert not r.m.uc.mem_read(CARD+5,1)[0]&2
    passed('Command error/notification flags and a mismatched interface echo reject enumeration before startup data reads')

    for flags in (4,0x100):
        r=Cold();symbols=r.install_block_guard();r.bad_final=flags
        assert r.enumerate()==0 and not r.held
        assert bytes(r.m.uc.mem_read(symbols['sdp_state'],56))==bytes(56)
        assert not word(r.m,symbols['sdp_admission_state']+16)
    passed('Existing compiled block guard is inactive through enumeration, including the false-ready counterexample; selecting its ports does not cover startup')

    out=ROOT/'analysis/sd_cold_start_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
        nominal=nominal,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),device_access=False,
        limitations=['Synthetic default-speed/one-bit and high-speed/four-bit cards; other negotiation branches remain open.',
            'Matching hardware aggregate counts is an explanatory model, not proof of the exact physical card responses or omitted reads.',
            'Card responses/FIFO, reset-bit and initial-clock self-clear, clock division and RTOS scheduling are modeled.',
            'Original command, FIFO data, event predicates, dispatcher locking and initialization branches execute; not a full board boot.',
            'Injected flags are controlled counterexamples, not faults reproduced on the mixer; no physical IRQ/DMA/cache/source proof.',
            'No new runtime guard, capture release, firmware update image, device access or installation.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out))))

if __name__=='__main__':main()
