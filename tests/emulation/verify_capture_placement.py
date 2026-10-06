#!/usr/bin/env python3
"""Execute candidate RAM jump bytes and relocated capture code, offline only.

The application copier is original. MAIN extension loading, physical memory,
full DSP frames, RTOS scheduling and synchronous file completion are fixtures.
"""
import hashlib,json,struct,sys
from unicorn import UcError,UC_HOOK_CODE,UC_PROT_NONE,UC_ERR_FETCH_PROT
from unicorn import arm_const as A
from verify_capture_integration import IntegrationRig,record
from verify_pad_protocol import ROOT,IMAGE,RETURN
from verify_uncompressed_tap import B
from verify_firmware_workflow import put32
from verify_session_manager import STOPPED
from verify_scheduling_boundaries import stop
sys.path.insert(0,str(ROOT/'tools/firmware'))
from capture_jump_patches import ELF,SCATTER,SPECS,BIAS,plan,make_patch

REPORT=plan()
RAM_SITES={p['site'] for p in REPORT['patches']}
REGS=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(13)]
FP=[getattr(A,'UC_ARM_REG_S'+str(i)) for i in range(32)]
STATUS=[A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR]

def copy_ram(r,patched=True):
    """Modify emulator source only, then run the original startup copy helper."""
    source,dest,length,helper=SCATTER
    original=IMAGE[source-BIAS:source-BIAS+length];expected=bytearray(original)
    if patched:
        for p in REPORT['patches']:
            offset=p['site']-dest;expected[offset:offset+p['bytes']]=bytes.fromhex(p['patch'])
    r.m.uc.mem_write(source,bytes(expected))
    r.m.uc.mem_write(dest,b'\xa5'*length)
    r.m.invoke(helper,[source,dest,length])
    assert r.raw(dest,length)==expected
    return original,bytes(expected)

def dsp_frame(r,frame):
    # Original callback frame at the commit site:
    # local area 0x120, d8-d15 (0x40), alignment word, r4-r11 and saved PC.
    u=r.m.uc
    raw=b'\xa5'*0x120+struct.pack('<16I',*[u.reg_read(x) for x in FP[16:]])
    raw+=b'\x5a'*4+struct.pack('<9I',*[u.reg_read(x) for x in REGS[4:12]],RETURN|1)
    assert len(raw)==0x188
    u.mem_write(frame,raw)
    return raw

class PlacementRig(IntegrationRig):
    elf_path=ELF
    def __init__(self,patched=True,**kw):
        super().__init__(**kw)
        self.copied=copy_ram(self,patched)
    def redirect(self,address,name,always=False):
        # No PC interception at either tested site. Fetch and execute the bytes.
        if address not in RAM_SITES:super().redirect(address,name,always)
    def window(self,start,end):
        if start!=0x20229b82 or end!=0x2022a77a:return super().window(start,end)
        # Run the actual prologue to create the saved frame, then the selected
        # ring window and actual epilogue. The middle DSP remains omitted.
        m=self.m;top=m.stack
        super().window(0x202263e0,0x202263ec)
        frame=m.uc.reg_read(A.UC_ARM_REG_SP);assert top-frame==0x188
        saved=self.raw(frame,0x188)
        m.stack=frame
        try:
            m.invoke(start,[])
            assert m.uc.reg_read(A.UC_ARM_REG_SP)==top
            assert self.raw(frame,len(saved))==saved
        finally:m.stack=top

def seed(r,flags,misalign):
    # Warm Unicorn's lazy guest FPU before seeding status sentinels.
    r.gain(1);u=r.m.uc
    for i,x in enumerate(REGS):u.reg_write(x,0x12340000+i*0x101)
    for i,x in enumerate(FP):u.reg_write(x,0x3f000000+i*123)
    u.reg_write(A.UC_ARM_REG_R4,B);u.reg_write(A.UC_ARM_REG_R11,B)
    u.reg_write(A.UC_ARM_REG_SP,r.m.stack+misalign)
    u.reg_write(A.UC_ARM_REG_LR,0x20001001)
    u.reg_write(A.UC_ARM_REG_APSR,(flags<<28)|0x080f0000)
    u.reg_write(A.UC_ARM_REG_FPSCR,0x01400000)

def run_raw(r,start,end=RETURN):
    m=r.m;h=None
    if end!=RETURN:h=m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,s,u:stop(m),begin=end,end=end)
    m.reached_return=False
    try:
        m.uc.emu_start(start|1,RETURN+2,count=1000000)
        assert m.reached_return,'candidate instruction sequence did not reach its continuation'
    finally:
        if h:m.uc.hook_del(h)
    return [m.uc.reg_read(x) for x in REGS+FP+STATUS]

def main():
    cases=[]
    def passed(case,**kw):cases.append(dict(case=case,**kw))
    # Thumb LDR.W uses Align(PC,4). Commit needs a two-byte NOP before the
    # aligned literal; neither jump clobbers scratch registers, SP, LR or flags.
    for p,size,disp in zip(REPORT['patches'],(8,10),(0,4)):
        patch=bytes.fromhex(p['patch']);assert len(patch)==size and p['literal_address']%4==0
        assert struct.unpack_from('<HH',patch)==(0xf8df,0xf000|disp)
        assert struct.unpack_from('<I',patch,size-4)[0]==p['target']
        assert abs(p['target']-(p['site']+4))>=1<<24 # B.W cannot span this
        corrupt=bytearray(IMAGE);corrupt[p['source_file_offset']]^=1
        try:make_patch(corrupt,p,p['target'])
        except ValueError:pass
        else:raise AssertionError('changed stock bytes accepted')
        for bad in (p['target']&~1,0x10010001,0x801f5401):
            try:make_patch(IMAGE,p,bad)
            except ValueError:pass
            else:raise AssertionError('invalid target accepted')
    assert not REPORT['direct_interior_branches']
    assert REPORT['globals_start']==0x80960080 and REPORT['globals_end']==0x809600dc
    assert REPORT['candidate_code_start']>REPORT['original_loaded_end']
    assert all(s['address']>=REPORT['candidate_code_start'] for s in REPORT['segments'])
    passed('exact_complete_instruction_spans_aligned_literals_and_invalid_inputs',patch_bytes=[8,10],
           code_bytes=REPORT['candidate_load_end']-REPORT['candidate_code_start'])

    r=PlacementRig(enabled=False);original,copied=r.copied
    expected_offsets={a for p in REPORT['patches'] for a in range(p['site']-SCATTER[1],p['resume']-SCATTER[1])}
    assert all(i in expected_offsets for i,(a,b) in enumerate(zip(original,copied)) if a!=b)
    assert not r.entries
    passed('stock_application_copier_delivers_two_patch_spans_and_preserves_all_other_RAM_code_bytes',
           copier=hex(SCATTER[3]),copied_bytes=SCATTER[2])

    # CMP legitimately changes flags. Compare the complete continuation state
    # with stock rather than demand that the incoming flags remain unchanged.
    count=0
    for flags in range(16):
        for selector in (0,0x80000000):
            for misalign in (0,4):
                states=[]
                for patched in (False,True):
                    r=PlacementRig(patched=patched,enabled=False);seed(r,flags,misalign)
                    put32(r.m,B+0x6220,selector)
                    states.append(run_raw(r,0x202269f8,0x20226a00))
                    assert not r.entries
                assert states[0]==states[1],('tap',flags,selector,misalign)
                count+=1
    passed('actual_tap_jump_and_replay_match_stock_integer_FPU_status_stack_and_LR',comparisons=count)

    count=0
    for flags in range(16):
        for misalign in (0,4):
            states=[]
            for patched in (False,True):
                r=PlacementRig(patched=patched,enabled=False);seed(r,flags,misalign)
                frame=r.m.uc.reg_read(A.UC_ARM_REG_SP);saved=dsp_frame(r,frame)
                r.m.uc.reg_write(A.UC_ARM_REG_R1,0x53ec)
                r.m.uc.reg_write(A.UC_ARM_REG_R0,0x11223344)
                states.append(run_raw(r,0x2022a776))
                assert r.raw(frame,len(saved))==saved
                assert r.raw(B+0x53ec,4)==struct.pack('<I',0x11223344)
                assert r.m.uc.reg_read(A.UC_ARM_REG_SP)==frame+0x188
                assert not r.entries
            assert states[0]==states[1],('commit',flags,misalign)
            count+=1
    # Also enter before the consumed IT block and exercise both conditional
    # MOV paths. A hook must never inherit an active IT condition.
    for capacity in (32,128):
        for misalign in (0,4):
            states=[]
            for patched in (False,True):
                r=PlacementRig(patched=patched,enabled=False);seed(r,10,misalign)
                top=r.m.uc.reg_read(A.UC_ARM_REG_SP)
                r.m.uc.reg_write(A.UC_ARM_REG_LR,RETURN|1)
                run_raw(r,0x202263e0,0x202263ec)
                frame=r.m.uc.reg_read(A.UC_ARM_REG_SP);assert top-frame==0x188
                saved=r.raw(frame,0x188)
                put32(r.m,B+0x53ec,0);r.m.uc.reg_write(A.UC_ARM_REG_R0,capacity)
                states.append(run_raw(r,0x2022a766))
                assert r.raw(frame,len(saved))==saved
                assert r.m.uc.reg_read(A.UC_ARM_REG_SP)==top
                assert struct.unpack('<I',r.raw(B+0x53ec,4))[0]==min(64,capacity)
            assert states[0]==states[1]
    passed('actual_commit_jump_replays_store_and_epilogue_with_matching_FPU_integer_flags_and_frame',
           register_comparisons=count,original_prologue_and_preceding_IT_comparisons=4)

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2)
    r=PlacementRig();assert r.boot(release=True)==0;r.ready();r.sequence=0
    result=record(r,delay=2);extra=r.completed_extra()
    assert result==ordinary and extra[512:]!=result[7][512:]
    assert 'emulator_tap_hook' not in r.entries and 'emulator_commit_hook' not in r.entries
    passed('relocated_capture_composition_uses_real_RAM_jumps_and_produces_exact_extra_plus_seven_unchanged_files',
           frames=24*64,extra_bytes=len(extra),stock_files=7)

    r=PlacementRig();assert r.boot(release=True)==0;r.ready();r.sequence=0
    r.inject=('audio',1,'short');assert record(r,delay=2)==ordinary
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert r.result()==12 and not r.opened
    passed('relocated_short_write_withholds_extra_result_and_preserves_ordinary_files')

    r=PlacementRig(enabled=False)
    start=REPORT['candidate_code_start']&~0xfff;end=(REPORT['candidate_load_end']+4095)&~4095
    r.m.uc.mem_protect(start,end-start,UC_PROT_NONE)
    try:run_raw(r,0x202269f8,0x20226a00)
    except UcError as error:
        assert error.errno==UC_ERR_FETCH_PROT
        assert r.m.uc.reg_read(A.UC_ARM_REG_PC)==REPORT['patches'][0]['target']&~1
    else:raise AssertionError('jump worked without loaded extension')
    passed('copied_RAM_patch_cannot_execute_when_candidate_MAIN_extension_is_not_loaded')

    report=dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        placement_elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=REPORT['limitations']+[
            'Placement ELF is directly loaded by emulator; vendor bootloader is absent from update image',
            'Global BSS is zeroed by synthetic memory, not an installed startup initializer',
            'Composition runs original DSP prologue/ring/epilogue; middle DSP uses selected windows only',
            'Other hooks, startup authorization, public files, queues and task identities remain models',
            'No physical cache/MPU, elapsed timing, SD/DMA, power loss or device verification'])
    out=ROOT/'analysis/capture_placement_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
