#!/usr/bin/env python3
"""Offline RAM callback dispatcher and pad playback boundary investigation.

Runs original firmware against synthetic RAM. No device or installed patch.
"""
import hashlib
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_FPEXC
from verify_stream_producer import ProducerRig
from verify_scheduling_boundaries import BASE, stop
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, IMAGE, BIAS
from verify_overdub_prototype import ELF
from verify_work_ownership import OK, BUSY

REGISTRY=0x80570c18
AUDIO=0x20015e4c


class PlaybackRig(ProducerRig):
    def __init__(self,pads=()):
        super().__init__(pads)
        m=self.m
        self.mapping=struct.unpack_from('<4I',IMAGE,0x800a691c-BIAS)
        source,destination,length,helper=self.mapping
        assert self.mapping==(0x800a9408,0x20220000,0xd6dc,0x80079498)
        m.uc.mem_map(destination,0x10000)
        m.uc.mem_write(destination,IMAGE[source-BIAS:source-BIAS+length])
        m.uc.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        put32(m,0x20010a48,48000)
        put32(m,0x80446930,0x6600)

    def u32(self,address):return struct.unpack('<I',self.m.uc.mem_read(address,4))[0]

    def register(self,address):self.m.invoke(0x80002870,[address|1])

    def callbacks(self):return [self.u32(REGISTRY+0x14+4*i) for i in range(5)]

    def dispatch(self,wait_result=1):
        calls=[]
        def wait(a):
            assert a[:2]==[0x6600,0xffffffff]
            calls.append('wait')
            if len(calls)>1:return stop(self.m)
            return wait_result
        self.m.hooks[0x80076950]=wait
        self.m.invoke(0x2022a7a8,[])
        self.invariant()

    def connect_callback(self):
        def redirect(uc,address,size,unused):
            # Dispatcher passes the callback address in r0, NOT a parent ticket.
            uc.reg_write(UC_ARM_REG_R0,0)
            uc.reg_write(UC_ARM_REG_PC,self.m.symbols['od_emulator_stream_scan'])
        self.m.uc.hook_add(UC_HOOK_CODE,redirect,begin=0x800366f0,end=0x800366f0)

    def seed_audio(self,pad=0,length=128,loop=0):
        p=AUDIO+pad*0x3c
        self.m.uc.mem_write(p,struct.pack('<15I',1,0x21028000,0x21029000,
            0,0,128,0,length,loop,0x3f800000,0,0,0,0,0))
        for buffer in (0x21028000,0x21029000):
            self.m.uc.mem_write(buffer,struct.pack('<128f',*([0.25]*128)))
        return p


def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))

    r=PlaybackRig();m=r.m
    # Run stock sampler init, but omit hardware/queue initialization helpers.
    m.hooks[0x80036688]=lambda a:0
    m.hooks[0x80036348]=lambda a:0
    assert m.invoke(0x80009848,[])==0
    assert r.callbacks()==[0x800366f1,0,0,0,0]
    assert bytes(m.uc.mem_read(REGISTRY+0x10,1))==b'\x01'
    passed('stock_sampler_initialization_registers_real_stream_callback')

    # Check the task descriptor that feeds original task creation.
    row=struct.unpack_from('<6I',IMAGE,0x800a1c04-BIAS)
    assert row[0]==0x2022a7a9 and row[5]==0x80446d7c
    name=IMAGE[row[1]-BIAS:].split(b'\0',1)[0].decode()
    assert name=='AudioSubProcess'
    passed('dispatcher_is_AudioSubProcess_task',entry=hex(row[0]),name=name)

    r=PlaybackRig();seen=[]
    for i in range(6):
        addr=0x21000200+i*0x10
        r.m.hooks[addr]=lambda a,i=i:seen.append(i) or 0
        r.register(addr)
        if i==2:r.register(addr) # duplicate must not add another slot
    assert r.callbacks()==[0x21000201+i*0x10 for i in range(5)]
    r.dispatch();assert seen==list(range(5))
    passed('five_slot_callback_registry_duplicate_and_capacity_behavior')
    r.m.invoke(0x2022a830,[0x21000221])
    seen.clear();r.dispatch();assert seen==[0,1,3,4]
    passed('callback_removal_compacts_and_preserves_order')

    r=PlaybackRig((0,1));r.register(0x800366f0);r.connect_callback()
    r.dispatch();assert r.entered==1 and len(r.queue)==2 and r.word()==1
    counts,executed=r.run_worker();assert counts==[1,1,0] and executed==[1,1]
    passed('real_RAM_dispatcher_to_guarded_scan_to_original_worker')

    r=PlaybackRig((0,));r.register(0x800366f0);r.connect_callback()
    assert r.promotion()[0]==OK
    before=r.state(0);r.dispatch()
    assert r.entered==0 and not r.queue and r.state(0)==before
    passed('promotion_blocks_actual_callback_route_before_scan')

    r=PlaybackRig();seen=[]
    r.m.hooks[0x21000200]=lambda a:seen.append('callback') or 0
    r.register(0x21000200);r.dispatch(wait_result=0)
    assert seen==['callback']
    passed('dispatcher_does_not_check_wait_result_before_callbacks',
           limitation='Injected failure return, not an observed device scheduler failure')

    r=PlaybackRig((0,));p=r.seed_audio();put32(r.m,p,0)
    r.m.uc.mem_write(BASE+0x1c,b'\x01')
    r.m.hooks[0x80009740]=lambda a:1
    observations=[]
    def delay(a):
        observations.append(dict(audio_active=r.u32(p),stream_active=r.state(0)[0],pending=r.pending(0)))
        r.m.uc.mem_write(BASE+0x1c,b'\x00') # modeled worker completion
        return 0
    r.m.hooks[0x80077686]=delay
    r.m.hooks[0x80036750]=lambda a:0 # asynchronous file seek is separate coverage
    r.m.hooks[0x80036300]=lambda a:128
    r.m.invoke(0x80002c60,[0])
    assert observations==[dict(audio_active=1,stream_active=0,pending=1)]
    assert r.u32(p)==1 and r.state(0)[0]==1 and r.pending(0)==0
    passed('restart_enables_audio_before_pending_drain_then_reenables_stream',observations=observations)

    r=PlaybackRig((0,));p=r.seed_audio();put32(r.m,p+0x24,0)
    r.m.uc.mem_write(BASE+0x1c,b'\x01')
    r.m.invoke(0x80018350,[0])
    assert r.u32(p)==0 and r.state(0)[0]==1 and r.pending(0)==1
    passed('audio_stop_leaves_stream_enabled_and_pending_work_untouched')

    r=PlaybackRig((0,));p=r.seed_audio();observations=[]
    def fade(a):
        observations.append((r.u32(p),r.state(0)[0]))
        put32(r.m,p+0x24,0) # model audio renderer reaching zero gain
        return 0
    r.m.hooks[0x80077686]=fade;r.m.invoke(0x80018350,[0])
    assert observations==[(1,1)] and r.u32(p)==0 and r.state(0)[0]==1
    passed('fade_stop_waits_with_audio_and_stream_still_active')

    r=PlaybackRig((0,));before=r.state(0)
    r.m.invoke(0x80002c60,[0]) # original loaded getter returns zero
    assert r.state(0)==before and r.u32(AUDIO)==0
    passed('restart_of_unloaded_pad_returns_before_audio_or_stream_changes')

    r=PlaybackRig((0,));p=r.seed_audio();put32(r.m,p+0x24,0)
    r.m.invoke(0x80018350,[0]);assert r.u32(p)==0
    assert r.scan()==OK and len(r.queue)==1
    r.run_worker()
    passed('refill_can_be_submitted_after_audio_stop')

    r=PlaybackRig((0,));r.m.uc.mem_write(BASE+0x1c,b'\x01')
    put32(r.m,0x807348d4,0x21003000)
    observed=[]
    r.m.hooks[0x8005c1f8]=lambda a:observed.append((a[0],r.pending(0),r.state(0)[0])) or 0
    r.m.hooks[0x80006998]=lambda a:0
    r.m.invoke(0x800096f8,[0])
    assert observed==[(0x21003000,1,0)] and r.pending(0)==1
    passed('isolated_unload_closes_handle_without_waiting_for_pending_refill',
           limitation='Caller synchronization may prevent this state on device; this is not a stock bug claim')

    # Negative control: refill tickets alone cannot protect a playback session.
    r=PlaybackRig((0,));p=r.seed_audio()
    assert r.scan()==OK;r.run_worker()
    assert r.word()==0 and r.u32(p)==1 and r.state(0)[0]==1
    assert r.promotion()[0]==OK
    passed('negative_control_refill_only_gate_admits_promotion_during_playback')

    # A manually held owner demonstrates the needed lifetime, not a device binding.
    r=PlaybackRig((0,));r.seed_audio()
    status,ticket=r.reserve(kind=6);assert status==OK
    assert r.call('offer',ticket)==OK and r.call('submitted',ticket,1)==OK
    assert r.claim(ticket,kind=6)==OK
    assert r.scan(ticket)==OK;r.run_worker()
    assert r.word()==1 and r.promotion()[0]==BUSY and r.pending(0)==0
    put32(r.m,AUDIO+0x24,0);r.m.invoke(0x80018350,[0])
    assert r.word()==1 and r.promotion()[0]==BUSY
    passed('modeled_session_owner_blocks_promotion_between_refills_and_after_sound_stop',
           limitation='Owner created manually; no automatic playback admission or release policy installed')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['Offline selected stock routines with synthetic RAM and scheduling',
          'Critical sections, wait effects, file seek and fade progress modeled',
          'No continuous playback ownership installed; negative control demonstrates the gap',
          'Natural completion path statically traced; default emulator CPU rejects VMAXNM.F32 at 0x20220be0',
          'No physical audio, device memory placement, flash update or recovery validation'])
    out=ROOT/'analysis/playback_lifetime_verification.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))

if __name__=='__main__':main()
