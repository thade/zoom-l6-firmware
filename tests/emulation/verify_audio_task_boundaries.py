#!/usr/bin/env python3
"""Offline audio task control flow and exact stereo-buffer copy checks.

DSP stages and device IO are intercepted, not emulated audio. This suite does
not turn an end-of-block observation into a verified all-reader fence.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R9,UC_ARM_REG_R11
from verify_playback_lifetime import PlaybackRig
from verify_scheduling_boundaries import stop
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE
from verify_overdub_prototype import ELF

BASE=0x20010a48
CALLBACK=BASE+0x53c8
STAGES=(0x20220ac8,0x20224b90,0x20220000,0x202263e0)

class AudioRig(PlaybackRig):
    def __init__(self):
        super().__init__(())
        self.events=[];self.waits=0;self.limit=1;m=self.m
        # Original audio buffers include the older harness's default stack.
        # Use a separate synthetic stack, not a device-placement recommendation.
        m.stack=0x2003f000
        put32(m,0x8044692c,0x7700);put32(m,0x80446930,0x7800)
        put32(m,0x2000bb00,0x21028000);put32(m,0x2000bb04,0x21029000)
        put32(m,CALLBACK,0x2022a791)
        for fn in STAGES:
            m.hooks[fn]=lambda a,fn=fn:self.events.append(hex(fn)) or 0
        m.hooks[0x80033510]=lambda a:0x2102a000+a[0]*0x1000
        for fn in (0x8003b168,0x8003b280):m.hooks[fn]=lambda a:0
        def wait(a):
            assert a[:2]==[0x7700,0xffffffff]
            self.waits+=1
            if self.waits>self.limit:return stop(m)
            self.events.append('wake');return 1
        def signal(a):
            assert a[:4]==[0x7800,0,0,0]
            self.events.append('signal_subprocess');return 1
        m.hooks[0x80076950]=wait;m.hooks[0x800763d8]=signal
        m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,s,u:self.events.append('callback_returned'),
                      begin=0x8001078e,end=0x8001078e)

    def tick(self,n=1):
        self.waits=0;self.limit=n;self.events=[]
        self.m.invoke(0x80010938,[])
        return self.events

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=AudioRig();expected=['wake',*[hex(a) for a in STAGES],'callback_returned','signal_subprocess']
    assert r.tick()==expected
    passed('original_audio_task_calls_four_normal_stages_before_subprocess_signal',events=r.events)
    assert r.tick(3)==expected*3
    passed('task_repeats_complete_blocks_in_order')

    for mode,target in ((0,0x2022a791),(1,0x800124d9),(2,0x2022a791)):
        r=AudioRig();r.m.hooks[0x80006248]=lambda a,mode=mode:mode
        r.m.uc.reg_write(UC_ARM_REG_R9,BASE)
        r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,s,u:stop(r.m),begin=0x8001199e,end=0x8001199e)
        r.m.invoke(0x80011974,[])
        assert r.u32(CALLBACK)==target
    passed('original_initialization_selects_normal_or_alternative_audio_callback')

    for setter,target in ((0x8000ca98,0x80010960),(0x8000cab0,0x800133e8)):
        r=AudioRig();r.m.invoke(setter,[])
        assert r.u32(CALLBACK)==target|1
        r.m.hooks[target]=lambda a,target=target:r.events.append(hex(target)) or 0
        assert r.tick()==['wake',hex(target),'callback_returned','signal_subprocess']
    passed('runtime_callback_replacements_bypass_normal_RAM_stage_chain')

    r=AudioRig();put32(r.m,CALLBACK,0)
    assert r.tick()==['wake','callback_returned','signal_subprocess']
    passed('null_callback_still_signals_subprocess_so_signal_alone_is_not_reader_evidence')

    # Execute the original stereo block copy after dynamics; no DSP substitution.
    r=AudioRig();source=BASE+0x33b8;destination=BASE+0x1610
    marker=struct.pack('<128I',*[0x3f000000+i*137 for i in range(128)])
    r.m.uc.mem_write(source,marker);r.m.uc.mem_write(destination,b'\xa5'*512)
    r.m.uc.reg_write(UC_ARM_REG_R11,BASE)
    r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,s,u:stop(r.m),begin=0x202281c6,end=0x202281c6)
    r.m.invoke(0x202280e0,[])
    assert bytes(r.m.uc.mem_read(destination,512))==marker
    assert bytes(r.m.uc.mem_read(source,512))==marker
    passed('original_post_dynamics_stereo_copy_is_64_frames_per_side',
           source=hex(source),destination=hex(destination),bytes=512)

    r=AudioRig();calls=[]
    r.m.hooks[0x80077686]=lambda a:calls.append(('delay',a[0])) or 0
    r.m.hooks[0x80010398]=lambda a:calls.append(('ramp',a[0],a[1],a[2])) or 0
    r.m.invoke(0x80002ab8,[1]);on=bytes(r.m.uc.mem_read(BASE+0x63f0,0xb0))
    assert r.u32(BASE+0x6400)==0x3f800000 and r.u32(BASE+0x643c)==0x3f800000
    r.m.invoke(0x80002ab8,[0]);off=bytes(r.m.uc.mem_read(BASE+0x63f0,0xb0))
    assert on!=off and r.u32(BASE+0x6400)==0 and r.u32(BASE+0x643c)==0
    passed('original_dynamics_control_changes_parameters_read_by_late_audio_stage',
           limitation='Ramps/delays modeled; no compressor sound or curve verified')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['DSP stage bodies and IO modeled for task ordering',
        'No all-reader fence or DMA/interrupt exclusion established',
        'Pre-dynamics tap is a static candidate; no pre-compression recording implemented',
        'Post-dynamics copy executed exactly; downstream stream/file identity still needs end-to-end validation'])
    out=ROOT/'analysis/audio_task_boundaries_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))

if __name__=='__main__':main()
