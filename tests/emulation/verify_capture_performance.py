#!/usr/bin/env python3
"""Actual FP instructions, exact scaling and native payload alignment offline.

Instruction counts are not cycle timings. MMIO, DMA completion and scheduling
remain fixtures; this does not establish device throughput or FPU context.
"""
import hashlib,json,random,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_extra_capture import ExtraRig,STATE,MIX,ROOT
from verify_capture_heap import HeapNativeCapture
from verify_native_exfat import ExfatFoldersSd
from verify_sd_controller_setup import transfer_trace
from verify_firmware_workflow import put32
from verify_overdub_prototype import Emulator

PROFILES=('capture','capture-only','capture-only-heap','capture-only-placement',
          'capture-only-startup','capture-only-hooks','capture-only-minimal','handoff','handoff-test')

def scaled(bits):
    """Independent integer oracle for binary32 * 2**-31, nearest/ties-even."""
    sign=bits&0x80000000;exponent=(bits>>23)&255;fraction=bits&0x7fffff
    if exponent==255:return bits|(0x400000 if fraction else 0)
    if exponent>31:return sign|((exponent-31)<<23)|fraction
    if not exponent:return sign
    mantissa=0x800000|fraction;shift=32-exponent
    value=mantissa>>shift;remainder=mantissa&((1<<shift)-1);half=1<<(shift-1)
    return sign|(value+int(remainder>half or (remainder==half and value&1)))

def instructions(path,name):
    with path.open('rb') as f:
        elf=ELFFile(f);symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
        s=symbols[name];address=s['st_value']&~1
        section=elf.get_section(s['st_shndx']);offset=address-section['sh_addr']
        code=section.data()[offset:offset+s['st_size']]
        return list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(code,address)),set(symbols)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    for profile in PROFILES:
        decoded,names=instructions(ROOT/f'src/capture/{profile}.elf','extra_capture_frames')
        assert sum(i.mnemonic=='vmul.f32' for i in decoded)==2,profile
        assert not {'__aeabi_fmul','__mulsf3'}&names,profile
        assert sum(i.mnemonic=='vmrs' for i in decoded)==1
        assert sum(i.mnemonic=='vmsr' for i in decoded)==2
        positions={name:[j for j,i in enumerate(decoded) if i.mnemonic==name]
                   for name in ('vmrs','vmsr','vmul.f32')}
        assert positions['vmrs'][0]<positions['vmsr'][0]<positions['vmul.f32'][0]
        assert positions['vmul.f32'][-1]<positions['vmsr'][-1]
    passed('every_selected_build_emits_hardware_scaling_with_an_explicit_FPSCR_scope',profiles=len(PROFILES))

    r=ExtraRig();assert r.layout[:2]==(4160,32)
    patterns=[sign|exponent<<23|fraction for sign in (0,0x80000000)
        for exponent in range(256) for fraction in (0,1,0x3fffff,0x400000,0x400001,0x7fffff)]
    rng=random.Random(0x16);patterns += [rng.getrandbits(32) for _ in range(4096)]
    # Each rounding mode, both flush/default-NaN modes and preexisting flags.
    # The oracle includes signed zero, signaling/quiet NaNs and halfway cases.
    modes=[rounding<<22|controls for rounding in range(4) for controls in (0,0x0700009f)]
    preserved=[getattr(A,'UC_ARM_REG_S'+str(i)) for i in range(16,32)]
    for i,reg in enumerate(preserved):r.m.uc.reg_write(reg,0x3f000000+i*97)
    sentinels=[r.m.uc.reg_read(reg) for reg in preserved]
    for mode in modes:
        for first in range(0,len(patterns),128):
            chunk=patterns[first:first+128];count=(len(chunk)+1)//2
            chunk += [0]*(count*2-len(chunk))
            r.call('extra_init',8)
            r.m.uc.mem_write(MIX,struct.pack('<%dI'%count,*chunk[::2]))
            r.m.uc.mem_write(MIX+256,struct.pack('<%dI'%count,*chunk[1::2]))
            r.m.uc.reg_write(A.UC_ARM_REG_FPSCR,mode)
            assert r.call('extra_capture_frames',MIX,MIX+256,count)==0
            actual=struct.unpack('<%dI'%len(chunk),r.raw(STATE+r.layout[1],len(chunk)*4))
            assert actual==tuple(map(scaled,chunk)),(hex(mode),first)
            assert r.m.uc.reg_read(A.UC_ARM_REG_FPSCR)==mode
            assert [r.m.uc.reg_read(reg) for reg in preserved]==sentinels
    passed('bit_exact_binary32_scaling_and_preserved_caller_FP_state',patterns=len(patterns),modes=len(modes))

    counts={}
    for bits in (0,1,0x4e800000):
        r.call('extra_init',8);r.m.uc.mem_write(MIX,struct.pack('<128I',*([bits]*128)))
        total=[0]
        def count(uc,address,size,user):total[0]+=1
        hook=r.m.uc.hook_add(UC_HOOK_CODE,count)
        assert r.capture()==0;r.m.uc.hook_del(hook)
        counts[hex(bits)]=total[0];assert total[0]<1000,total
    passed('64_frame_scaling_executes_fewer_than_1000_emulated_instructions',counts=counts,
           limitation='Instruction counts only; no measured cycles, deadlines or utilization')

    # Run the stock software context-switch body. Its hardware exception frame
    # (s0-s15/FPSCR) is deliberately left untouched, not synthesized as proof.
    for outgoing_fp in (False,True):
        for incoming_fp in (False,True):
            m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True)
            m.uc.mem_map(0xe000e000,0x1000);put32(m,0xe000ed88,0xf00000)
            m.uc.reg_write(A.UC_ARM_REG_FPEXC,0x40000000)
            old_top=0x20035000;new_saved=0x20032000
            task_a,task_b=0x20025000,0x20025100
            old_regs=[0x12340000+i for i in range(8)]
            new_regs=[0x56780000+i for i in range(8)]
            old_fp=[0x3f400000+i for i in range(16)]
            new_fp=[0xbf400000+i for i in range(16)]
            put32(m,0x808e291c,task_a);put32(m,task_b,new_saved)
            old_lr=0xffffffed if outgoing_fp else 0xfffffffd
            new_lr=0xffffffed if incoming_fp else 0xfffffffd
            saved=new_regs+[new_lr]+(new_fp if incoming_fp else [])
            m.uc.mem_write(new_saved,struct.pack('<%dI'%len(saved),*saved))
            frame=b'\x6c'*104;m.uc.mem_write(old_top,frame)
            for i,value in enumerate(old_regs):m.uc.reg_write(getattr(A,'UC_ARM_REG_R'+str(i+4)),value)
            for i,value in enumerate(old_fp):m.uc.reg_write(getattr(A,'UC_ARM_REG_S'+str(i+16)),value)
            m.uc.reg_write(A.UC_ARM_REG_CONTROL,0)
            m.uc.reg_write(A.UC_ARM_REG_PSP,old_top);m.uc.reg_write(A.UC_ARM_REG_SP,0x2003f000)
            m.uc.reg_write(A.UC_ARM_REG_LR,old_lr)
            m.hooks[0x80074790]=lambda a:put32(m,0x808e291c,task_b) or 0
            m.uc.hook_add(UC_HOOK_CODE,m._hook,begin=0x80074790,end=0x80074790)
            stopped=[]
            def end(uc,address,size,user):stopped.append(address);uc.emu_stop()
            h=m.uc.hook_add(UC_HOOK_CODE,end,begin=0x8003439a,end=0x8003439a)
            m.uc.emu_start(0x80034341,0x8003439c,count=1000);m.uc.hook_del(h)
            assert stopped==[0x8003439a],hex(m.uc.reg_read(A.UC_ARM_REG_PC))
            old_saved=old_regs+[old_lr]+(old_fp if outgoing_fp else [])
            address=old_top-4*len(old_saved)
            assert struct.unpack('<I',m.uc.mem_read(task_a,4))[0]==address
            assert bytes(m.uc.mem_read(address,4*len(old_saved)))==struct.pack('<%dI'%len(old_saved),*old_saved)
            assert bytes(m.uc.mem_read(old_top,len(frame)))==frame
            assert [m.uc.reg_read(getattr(A,'UC_ARM_REG_R'+str(i+4))) for i in range(8)]==new_regs
            expected_fp=new_fp if incoming_fp else old_fp
            assert [m.uc.reg_read(getattr(A,'UC_ARM_REG_S'+str(i+16))) for i in range(16)]==expected_fp
            assert m.uc.reg_read(A.UC_ARM_REG_PSP)==new_saved+4*len(saved)
            assert m.uc.reg_read(A.UC_ARM_REG_LR)==new_lr
    passed('stock_software_context_switch_saves_and_restores_upper_FP_bank_for_extended_frames',
           combinations=4,limitation='Hardware exception entry/return and lazy stacking remain unverified')

    # Execute the native driver's actual aligned/misaligned split as a negative
    # control. Synthetic MMIO/DMA completion supplies the controller response.
    for op in (2,3):
        traces=[]
        for offset in (0,24):
            driver,result,reads,writes,submissions,cache,order=transfer_trace(op,8,offset)
            assert result==0
            data=[s for s in submissions if s['command']&0x200000]
            traces.append([s['blocks']>>16 for s in data])
        assert traces==[[8],[1,6,1]],traces
    passed('native_aligned_4KiB_read_and_write_use_one_request_old_alignment_uses_three')

    # Real heap arena -> worker staging -> native exFAT -> original SD driver.
    r=HeapNativeCapture(lambda **kw:ExfatFoldersSd(spc=512,clusters=1952360,**kw))
    assert r.fs.setup_card()==0;r.fs.verify_folders()
    assert r.boot(release=True)==0;r.ready()
    r.sequence=0;r.audio_call();r.begin_recording(delay=2)
    # Delayed worker fills the entire batch, then ordinary per-block progress.
    for _ in range(14):r.audio_call()
    for _ in range(24):r.tick()
    for _ in range(9):r.audio_call();r.tick()
    r.stop_recording();data=r.completed_extra()
    payload=r.d[5]+r.layout[1];assert payload%32==0
    full=[q for q in r.native_calls if q['operation']=='write' and q['args'][2]==4096]
    assert full and all(q['args'][1]%32==0 for q in full)
    direct=[q for q in r.fs.dma_effects if q[0]==3 and payload<=q[1]<payload+4096 and q[2]==8]
    assert direct and all(q[1]%32==0 for q in direct)
    assert len(data)==13312
    passed('heap_worker_native_exFAT_4KiB_payload_uses_direct_8_sector_DMA_and_exact_readback',
           batches=len(full),direct_batches=len(direct),extra_sha256=hashlib.sha256(data).hexdigest())

    report=dict(passed_groups=len(cases),results=cases,
        limitations=['Offline original instructions with modeled DMA, RTOS and physical completion',
                    'Live task FP enable/save/restore and preemption still require separate evidence',
                    'Partial sectors and fragmented files may legitimately use bounce buffers'])
    target=ROOT/'analysis/capture_performance_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(target))))
if __name__=='__main__':main()
