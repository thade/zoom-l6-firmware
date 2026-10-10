#!/usr/bin/env python3
"""Execute encoded MAIN/DSP hooks; card, scheduling and deep DSP remain models."""
import hashlib,json,struct,sys
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_capture_integration import IntegrationRig,record
from verify_capture_placement import PlacementRig,seed,run_raw,dsp_frame,REGS,FP,STATUS
from verify_capture_native_files import NativeCapture,failed,UI,FS1
from verify_native_mount import MountedTree,MountedTreeSd
from verify_capture_packing import edit_memory,expand_payloads,startup,DECOMPRESS,ZERO,DEST,LENGTH
from verify_capture_startup import Boot,WORKER as STARTUP_WORKER,SCHEDULER
from verify_record_scheduler import request_setup,word
from verify_control_transport import QHANDLE
from verify_control_transport import TASK
from sd_registers import PRESENT,CLOCK_STABLE,DAT0_HIGH
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,INPUT,RETURN
from verify_scheduling_boundaries import stop
sys.path.insert(0,str(ROOT/'tools/firmware'))
from plan_capture_hooks import ELF,SPECS,plan,make_patch
from capture_jump_patches import symbols
from plan_capture_packing import packing,SCATTER

PLAN=plan();PACK=packing(ELF)
MAIN_SITES={p['site'] for p in PLAN['patches']}
RAM_SITES={p['site'] for p in PLAN['DSP_patches']}
CONTROL_SPECS=tuple(p for p in SPECS if p['adapter'].startswith('ct_'))
CONTROL_ARGS={0x800483f8:[QHANDLE,INPUT],0x80034f40:[0xffffffff],
              0x80034d18:[],0x80034e58:[],0x80035038:[0xffffffff],0x800350d8:[]}
# BL adapters reach a native callee before the plan's fallthrough resume. The
# saved LR must still be that resume, with the Thumb bit. CBZ/BLX is below.
CALL_BOUNDARIES={0x8001078e:0x80010150,0x8000b78c:0x80037e98}

class HooksRig(PlacementRig):
    elf_path=ELF
    patch_plan=PLAN
    packed=PACK
    stop_entry=0x80034f40
    def __init__(self,patched=True,**kwargs):
        self.patched=patched
        IntegrationRig.__init__(self,**kwargs)
        if patched:
            for p in self.patch_plan['patches']:self.m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
    def load_capture_elf(self,elf):
        # Metadata comes from ELF; all code/global bytes come through original
        # startup decoder/zero routines, with no direct PT_LOAD copy.
        u=self.m.uc;pack=self.packed;j=pack['jumps']
        u.mem_write(DEST,b'\xa5'*LENGTH)
        u.mem_write(j['candidate_code_start'],b'\xa5'*len(pack['code']))
        n=j['globals_end']-j['globals_start']
        u.mem_write(j['globals_start'],b'\xa5'*n)
        edit_memory(u,pack) # Reused destinations initially contain DSP input.
        expand_payloads(self.m,pack)
        assert self.raw(DEST,LENGTH)==pack['dsp']
        assert self.raw(j['candidate_code_start'],len(pack['code']))==pack['code']
        assert self.raw(j['globals_start'],n)==bytes(n)
        if not self.patched:
            for p in self.patch_plan['DSP_patches']:
                self.m.uc.mem_write(p['site'],bytes.fromhex(p['original']))
    def redirect(self,address,name,always=False):
        if address not in MAIN_SITES|RAM_SITES:
            IntegrationRig.redirect(self,address,name,always)
    def window(self,start,end):
        if start==0x8001078a and end==0x8001078c:
            # The complete patch includes CBZ/BLX. Stop at the original callback
            # entry, then run selected DSP windows as the existing harness does.
            # The actual branch establishes the original callback LR.
            end=0x2022a790
        return PlacementRig.window(self,start,end)
    def request(self,ui=0):
        if not ui or self.stop_entry==0x80034f40:return IntegrationRig.request(self,ui)
        request_setup(self.m,ui);self.m.hooks[0x800763d8]=self.kernel_send
        self.m.invoke(self.stop_entry,[0xffffffff])

class HookNativeCapture(NativeCapture,HooksRig):
    pass

def control_continuations(rig):
    for spec in CONTROL_SPECS:
        for patched in (False,True):
            r=rig(patched=patched,enabled=False);seed(r,10,0)
            seen=[]
            def first_stock(uc,address,size,user):
                seen.append(address);stop(r.m)
            # Observe the first instruction reached beyond the displaced span,
            # before any native callee or append-only fixture can hide a skip.
            resume=spec['resume']
            hook=r.m.uc.hook_add(UC_HOOK_CODE,first_stock,begin=resume,end=resume+32)
            try:r.m.invoke(spec['site'],CONTROL_ARGS[spec['site']])
            finally:r.m.uc.hook_del(hook)
            assert seen==[resume],(spec['adapter'],patched,seen,hex(resume))
    return len(CONTROL_SPECS)*2

def dsp_continuations(rig):
    for spec in rig.patch_plan['DSP_patches']:
        states=[]
        for patched in (False,True):
            r=rig(patched=patched,enabled=False);seed(r,10,0)
            if spec['adapter']=='placement_commit_hook':
                dsp_frame(r,r.m.uc.reg_read(A.UC_ARM_REG_SP))
                r.m.uc.reg_write(A.UC_ARM_REG_R0,0x11223344)
                r.m.uc.reg_write(A.UC_ARM_REG_R1,0x53ec)
            states.append(run_raw(r,spec['site'],spec['resume']))
        assert states[0]==states[1],spec['adapter']
    return len(rig.patch_plan['DSP_patches'])*2

def queue_arguments(rig):
    for mode in (0,1,2,0xffffffff):
        snapshots=[]
        for patched in (False,True):
            r=rig(patched=patched,enabled=False);seed(r,10,0)
            calls=[]
            r.m.hooks[0x800763d8]=lambda args:calls.append(tuple(args[:4])) or 1
            r.m.uc.mem_write(INPUT,b'B'*32);r.m.uc.reg_write(A.UC_ARM_REG_R3,mode)
            value=r.m.invoke(0x800483f8,[QHANDLE,INPUT])
            assert calls==[(QHANDLE,INPUT,0xffffffff,0)],(patched,mode,calls)
            snapshots.append((value,calls))
        assert snapshots[0]==snapshots[1]
    return 8

def native_queue_fifo(rig):
    for mode in (0,1,2,0xffffffff):
        snapshots=[]
        for patched in (False,True):
            r=rig(patched=patched,enabled=False);seed(r,10,0)
            m=r.m;base=0x21036000
            m.uc.mem_write(QHANDLE,bytes(0x50))
            m.uc.mem_write(base,b'A'*32+bytes(96));m.uc.mem_write(INPUT,b'B'*32)
            for offset,value in ((0,base),(4,base+32),(8,base+128),(12,base+96),
                                 (0x38,1),(0x3c,4),(0x40,32)):
                put32(m,QHANDLE+offset,value)
            # Original send-position selection and queue-copy instructions run.
            # Only the scheduler-state query is supplied for this ready queue.
            m.hooks.pop(0x800763d8,None);m.hooks[0x800770f8]=lambda args:1
            trapped=[]
            hook=m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:trapped.append(a) or stop(m),
                               begin=0x800764ac,end=0x800764ac)
            m.uc.reg_write(A.UC_ARM_REG_R3,mode)
            try:value=m.invoke(0x800483f8,[QHANDLE,INPUT])
            finally:m.uc.hook_del(hook)
            assert not trapped,(patched,mode,'kernel assertion')
            assert word(m,QHANDLE+0x38)==2
            p=word(m,QHANDLE+12);messages=[]
            for _ in range(2):
                p+=32
                if p>=base+128:p=base
                messages.append(bytes(m.uc.mem_read(p,32)))
            assert messages==[b'A'*32,b'B'*32],(patched,mode,messages)
            snapshots.append((value,r.raw(QHANDLE,0x50),r.raw(base,128)))
        assert snapshots[0]==snapshots[1],mode
    return 8

def queue_fixture_rejects_bad_arguments(rig):
    r=rig(enabled=False)
    for timeout,mode in ((0,0),(0xffffffff,1),(0xffffffff,2)):
        try:r.kernel_send([QHANDLE,INPUT,timeout,mode])
        except AssertionError:pass
        else:raise AssertionError('queue fixture hid unsupported timeout/mode')
    assert not r.sent and not r.wire
    return 3

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    assert len(PLAN['patches'])==15 and len(PLAN['DSP_patches'])==2
    assert PLAN['packing']['spare_bytes']>=0 and not PLAN['direct_interior_branches']
    for p in SPECS:
        target=next(x['target'] for x in PLAN['patches'] if x['site']==p['site'])
        corrupt=bytearray(IMAGE);corrupt[p['site']-0x80000e00]^=1
        for stock,address in ((corrupt,target),(IMAGE,target&~1),(IMAGE,0x10010001)):
            try:make_patch(stock,p,address)
            except ValueError:pass
            else:raise AssertionError('unsafe patch inputs accepted')
    passed('all_MAIN_and_DSP_patch_spans_are_byte_checked_complete_nonoverlapping_and_fit_stock_payload',
           MAIN_patches=15,DSP_patches=2,spare_bytes=PLAN['packing']['spare_bytes'])

    hashes,helpers=startup(True,PACK)
    assert len(hashes)==8 and len(helpers)==10 and helpers[4][3]==96
    passed('original_complete_scatter_entry_decodes_hooks_build_and_initializes_all_96_global_bytes')

    b=Boot(pack=PACK,names=symbols(ELF),patches=PLAN['patches']);b.boot();b.guard()
    assert b.kernel_entered and b.word(SCHEDULER)==1 and b.optional_calls==1
    assert b.word(STARTUP_WORKER+8)==4 and b.word(STARTUP_WORKER+16)==0
    passed('all_MAIN_jumps_present_during_original_boot_keep_optional_worker_asleep_without_file_work',
           original_tasks_and_idle=36,optional_calls=1,traced_added_stack_bytes=0x2021fff0-b.minimum_sp)

    passed('six_control_adapters_reach_the_exact_plan_resume_before_any_following_stock_instruction',
           comparisons=control_continuations(HooksRig))
    passed('both_DSP_adapters_match_stock_at_the_exact_plan_resume',comparisons=dsp_continuations(HooksRig))
    passed('common_sender_preserves_all_four_kernel_arguments_for_varied_incoming_R3',
           comparisons=queue_arguments(HooksRig))
    passed('original_kernel_queue_preserves_existing_message_FIFO_and_avoids_assertion_for_varied_R3',
           comparisons=native_queue_fifo(HooksRig))
    passed('common_queue_fixture_rejects_unsupported_timeout_and_mode_before_mutation',
           rejected=queue_fixture_rejects_bad_arguments(HooksRig))

    # Mid-function observers must preserve every integer/FPU/status register
    # apart from the exact original displaced effects, including flags and LR.
    for spec in (p for p in SPECS if p['adapter'].startswith('emulator_') and p['site']!=0x8001078a):
        site=spec['site'];end=CALL_BOUNDARIES.get(site,spec['resume'])
        count=0
        for flags in range(16):
            for alignment in (0,4):
                states=[]
                for patched in (False,True):
                    r=HooksRig(patched=patched,enabled=False);seed(r,flags,alignment)
                    r.m.hooks.pop(end,None)
                    if site==0x80034fc0:
                        sp=r.m.uc.reg_read(A.UC_ARM_REG_SP)
                        r.m.uc.mem_write(sp,struct.pack('<4I',0x11111111,0x22222222,0x33333333,0x20001001))
                    states.append(run_raw(r,site,end))
                    if site in CALL_BOUNDARIES:assert r.m.uc.reg_read(A.UC_ARM_REG_LR)==(spec['resume']|1)
                assert states[0]==states[1],(hex(site),flags,alignment)
                count+=1
        passed('actual_MAIN_jump_replays_stock_integer_FPU_flags_stack_and_LR_at_'+hex(site),comparisons=count)

    callback_spec=next(p for p in SPECS if p['adapter']=='emulator_audio_outer_hook')
    count=0
    for callback in (0,0x2022a791):
        for flags in range(16):
            for alignment in (0,4):
                states=[]
                for patched in (False,True):
                    r=HooksRig(patched=patched,enabled=False);seed(r,flags,alignment)
                    r.m.uc.reg_write(A.UC_ARM_REG_R0,callback)
                    end=callback&~1 if callback else callback_spec['resume']
                    states.append(run_raw(r,callback_spec['site'],end))
                    if callback:assert r.m.uc.reg_read(A.UC_ARM_REG_LR)==(callback_spec['resume']|1)
                assert states[0]==states[1],(callback,flags,alignment)
                count+=1
    passed('actual_whole_callback_entry_replays_null_branch_and_original_callback_LR',comparisons=count)

    for entry,args in CONTROL_ARGS.items():
        snapshots=[]
        for patched in (False,True):
            r=HooksRig(patched=patched,enabled=False);seed(r,10,0)
            request_setup(r.m,1,0);r.m.hooks[0x800763d8]=r.kernel_send
            if entry==0x800483f8:r.m.uc.mem_write(INPUT,struct.pack('<8I',0x8004b891,1,2,3,4,5,6,7))
            value=r.m.invoke(entry,args)
            # High-level stock producers initialize callback/argument only;
            # the remaining queue words are unused stack padding. The sender
            # case supplies all eight words and must preserve every byte.
            n=32 if entry==0x800483f8 else 8
            snapshots.append((value,[r.m.uc.reg_read(x) for x in REGS[4:12]+FP[16:]],
                              r.m.uc.reg_read(A.UC_ARM_REG_SP),[x[:n] for x in r.sent],[x[:n] for x in r.wire]))
        assert snapshots[0]==snapshots[1],hex(entry)
    passed('all_six_actual_control_entry_jumps_preserve_stock_returns_saved_registers_stack_and_queue_effects')

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    for fs in (MountedTree,MountedTreeSd):
        r=HookNativeCapture(filesystem=fs)
        assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        extra=r.completed_extra()
        assert len(extra)==13312 and r.fs.geometry()==(0,(65526,65516,512,8))
        assert not any(n.startswith('emulator_') or n in ('ct_queue_send','ct_record_request') for n in r.entries)
        assert r.entries and set(r.entries)=={'ct_emulator_admit'}
        passed('actual_MAIN_DSP_jumps_complete_exact_take_through_native_mount_'+fs.__name__,
               frames=1600,extra_bytes=len(extra),extra_sha256=hashlib.sha256(extra).hexdigest())

    r=HookNativeCapture(filesystem=MountedTree)
    r.fs.fail=lambda q:q['op']==2 and q['sector']==2048+32+8
    assert r.boot(release=True)==0;failed(r);r.sequence=0
    assert record(r,delay=2,blocks=23)==ordinary and not r.fs.files_in_pad()
    passed('actual_hooks_preserve_ordinary_recording_after_optional_native_mount_failure')

    for endpoint in (0x80034d18,0x80034e58,0x80035038,0x800350d8,0x8002d7b8,0x80008a20):
        r=HookNativeCapture(filesystem=MountedTree);r.stop_entry=endpoint
        assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary and len(r.completed_extra())==13312
    passed('actual_active_control_entry_jumps_and_two_stock_tail_aliases_stop_an_exact_capture',paths=6)

    for nominal in (False,True):
        r=HookNativeCapture(filesystem=MountedTreeSd)
        assert r.boot(release=True)==0;r.ready();r.sequence=0;r.begin_recording(delay=2)
        sector=r.fs.physical(8,1)
        if nominal:r.fs.finish_pending=sector
        else:r.fs.inject=(3,sector,'data')
        for _ in range(12):
            r.audio_call();r.tick()
            if r.fs.stalled:break
        assert r.fs.stalled
        if nominal:put32(r.m,PRESENT,CLOCK_STABLE|0x206)
        r.retained((UI,FS1));frame=r.fs.frame();requests=list(r.fs.requests)
        r.resume_sd();r.retained((UI,FS1))
        assert r.fs.frame()==frame and r.fs.requests==requests
        r.other_task(word(r.m,TASK),r.audio_call)
        stock=r.other_task(word(r.m,TASK),r.stop_recording)
        assert r.fs.frame()==frame and r.fs.requests==requests
        assert all(stock[h][512:] for h in range(1,8))
        if nominal:
            r.fs.finish_pending=r.fs.busy_sector=None
            put32(r.m,PRESENT,CLOCK_STABLE|DAT0_HIGH)
        else:r.fs.join_allowed=True
        r.resume_sd();assert not r.fs.owner() and r.locks.tokens=={UI}
        assert sum(q['op']==3 and q['sector']==sector for q in r.fs.requests)==1
        if nominal:r.completed_extra()
        else:failed(r)
        passed('actual_hooks_keep_capture_stack_and_file_token_while_stock_audio_STOP_run_until_MODEL_join_'+str(nominal))

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        hooks_elf_sha256=PLAN['hooks_elf_sha256'],limitations=PLAN['limitations']+[
            'Whole-callback instructions execute at entry/return; selected DSP windows are manually scheduled in between',
            'Deep recorder-file setup still uses ct_emulator_admit; isolated original admission jump is tested separately',
            'Original startup scatter tested separately from recording; worker registration/release are explicit fixture calls',
            'Ordinary file bytes, card bytes/state, DMA/IRQ/cache and physical joins remain models'])
    (ROOT/'analysis/capture_hooks_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
