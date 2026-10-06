#!/usr/bin/env python3
"""Original Main event dispatch and counterexamples to binding a raw pad FIFO.
Kernel FIFO copying, task scheduling, state getters and device effects are models.
No device access, firmware image or production dispatcher hook.
"""
import json,struct
from unicorn.arm_const import UC_ARM_REG_R4
from verify_reload_queue_audit import QueueRig,BUFFER,packed
from verify_pad_protocol import ROOT,STACK
from verify_scheduling_boundaries import stop
from verify_pad_commands import Commands,WORKER

NORMAL=0x8002c43e;ALTERNATE=0x8002c406
PRESS=(0,0,23,99,98);RELEASE=(0,1,23,99,98)
COMPLETE=(1,4,26,0,0)

class Dispatch(QueueRig):
    def __init__(self,native=False):
        super().__init__();self.calls=[];self.effects=[];self.waits=[];self.playing=False
        m=self.m
        for addr in (0x80034530,0x800344e0,0x8001e4d8,0x8003bd58,0x8003f0c8,0x80030fb0):
            m.hooks[addr]=lambda a,addr=addr:self.effects.append((addr,a[:3])) or 0
        m.hooks[0x8003f0b8]=lambda a:0
        m.hooks[0x800061f0]=lambda a:1
        m.hooks[0x80006238]=lambda a:1
        m.hooks[0x80002440]=lambda a:int(self.playing)
        m.hooks[0x80034da8]=lambda a:0xffffffff
        for addr in (0x80006290,0x800060d0,0x8000a220):m.hooks[addr]=lambda a:0
        m.hooks[0x80002c60]=lambda a:self.audio('start',True,a)
        m.hooks[0x80002d08]=lambda a:self.audio('stop',False,a)
        for addr in (0x80008430,0x80008428,0x8000aad0):
            m.hooks[addr]=lambda a,addr=addr:self.effects.append((addr,a[:3])) or 0
        if not native:
            for addr in (0x800408b0,0x8003f4d8):
                m.hooks[addr]=lambda a,addr=addr:self.calls.append((addr,*a[:3])) or 0
        # Run the original category-1 dispatcher up to its reload body; this
        # fixture observes dispatch, not completion of the reload's file work.
        m.hooks[0x80008b68]=lambda a:self.effects.append(('reload',)) or 0
        original=self.receive
        def receive(a):
            self.waits.append(a[2])
            if not self.queues[self.ui]['items'] and a[2]==0xffffffff:return stop(m)
            return original(a)
        m.hooks[0x80076710]=receive
    def audio(self,op,playing,a):
        self.playing=playing;self.effects.append((op,a[0]));return 0
    def loop(self,start=NORMAL):
        # Same boundary setup as verify_reload_queue_audit; no startup claim.
        self.m.uc.reg_write(UC_ARM_REG_R4,STACK+4);self.m.invoke(start,[])
    def audio_events(self):return [e for e in self.effects if e[0] in ('start','stop')]

def main():
    cases=[]
    def passed(name):cases.append(name)
    for start,root in ((NORMAL,0x800408b0),(ALTERNATE,0x8003f4d8)):
        r=Dispatch();r.seed([PRESS,RELEASE]);r.loop(start)
        assert r.calls==[(root,2,0,1),(root,2,0,0)]
        assert r.waits==[0xffffffff]*3 and not r.events()
    passed('two_original_Main_loops_decode_20_byte_packets_to_distinct_three_argument_handlers')

    r=Dispatch();r.seed([(2,3,19,1,0),(2,3,86,123,0),(2,3,90,123,0)])
    r.loop();assert r.calls==[(0x800408b0,2,1,1),(0x800408b0,2,1,1),(0x800408b0,2,1,0)]
    assert len([e for e in r.effects if e[0]==0x80030fb0])==1
    passed('category_2_routes_include_a_pre_handler_side_effect_not_owned_by_raw_command_queue')

    r=Dispatch()
    for subtype,event in enumerate((1,0,2,4,3,5,6,7,1,0)):
        r.m.uc.mem_write(BUFFER,packed((0,subtype,23,0,0)))
        assert r.m.invoke(0x80020c60,[BUFFER])==event
    passed('original_decoder_maps_event_subtype_not_payload_to_physical_command_event')

    r=Dispatch();r.seed([PRESS,COMPLETE])
    assert r.m.invoke(0x80020690,[BUFFER])==0
    assert r.events()==[COMPLETE] and bytes(r.m.uc.mem_read(BUFFER,20))==packed(PRESS)
    assert [e[0] for e in r.effects]==[0x80034530,0x800344e0]
    assert r.m.invoke(0x80020690,[BUFFER])==0
    assert bytes(r.m.uc.mem_read(BUFFER,20))==packed(COMPLETE) and not r.events()
    passed('receive_consumes_packet_and_runs_timer_helpers_before_dispatch_buffer_is_reused')

    r=Dispatch();r.seed([PRESS,COMPLETE]);accepted=[]
    def reject(a):accepted.append(tuple(a[:3]));return 1
    r.m.hooks[0x800408b0]=reject;r.loop()
    assert accepted==[(2,0,1)] and not r.events() and ('reload',) in r.effects
    passed('BUSY_from_raw_command_handler_is_ignored_and_packet_is_not_retried')

    r=Dispatch(native=True);r.seed([PRESS,PRESS,COMPLETE]);r.loop()
    assert r.audio_events()==[('start',2)] and ('reload',) in r.effects
    passed('native_press_deletes_a_later_duplicate_press_before_Main_receives_it')

    r=Dispatch(native=True);r.seed([PRESS,(2,3,86,0,0),RELEASE,COMPLETE]);r.loop()
    assert r.audio_events()==[('start',2)] and ('reload',) in r.effects
    # Toggle mode ignores release; both duplicate physical/category-2 presses
    # are removed by native queue deletion, not by Python filtering.
    passed('native_press_also_deletes_matching_category_2_press_and_preserves_completion')

    # Demonstrate an actual semantic mismatch in a naive binding: Main consumes
    # both packets while the compiled queue is held. Replay still executes the
    # real stock deletion routine, but it cannot see already diverted packets.
    r=Dispatch();q=Commands();q.mode[2]=1
    assert q.pc('try_hold',task=WORKER)==0
    results=[]
    r.m.hooks[0x800408b0]=lambda a:results.append(q.submit(1,*a[:3])) or 0
    r.seed([PRESS,PRESS,COMPLETE]);r.loop()
    assert results==[0,0] and ('reload',) in r.effects and not r.events()
    q.m.hooks[0x80020548]=lambda a:r.m.invoke(0x80020548,a[:4])
    assert q.pc('release',task=WORKER)==0 and q.pc('poll')==0 and q.pc('poll')==0
    assert [e for e in q.events if e[0] in ('start','stop')]==[('start',2),('stop',2)]
    passed('negative_control_compiled_raw_FIFO_changes_native_duplicate_press_into_start_then_stop')

    r=Dispatch();q=Commands();assert q.pc('try_hold',task=WORKER)==0
    results=[]
    r.m.hooks[0x800408b0]=lambda a:results.append(q.submit(1,*a[:3])) or 0
    r.seed([PRESS]*9+[COMPLETE]);r.loop()
    assert results==[0]*8+[1] and q.word(4)==8 and not r.events()
    assert ('reload',) in r.effects
    passed('negative_control_naive_binding_loses_ninth_packet_while_Main_continues')

    r=Dispatch();q=Commands();assert q.pc('try_hold',task=WORKER)==0
    def wait_when_full(a):
        result=q.submit(1,*a[:3])
        return stop(r.m) if result==1 else result
    r.m.hooks[0x800408b0]=wait_when_full
    r.seed([PRESS]*9+[COMPLETE]);r.loop()
    assert q.word(4)==8 and r.events()==[COMPLETE] and ('reload',) not in r.effects
    passed('negative_control_parking_Main_at_full_FIFO_prevents_queued_reload_completion_dispatch')

    # Returning failure from the kernel wait is not a supported timed-poll ABI:
    # original receiver synthesizes an all-ones packet and returns success.
    r=Dispatch();r.m.hooks[0x80076710]=lambda a:0
    r.m.uc.mem_write(BUFFER,b'?'*20)
    assert r.m.invoke(0x80020690,[BUFFER])==0
    assert bytes(r.m.uc.mem_read(BUFFER,20))==b'\xff'*20
    passed('receiver_masks_kernel_wait_failure_as_sentinel_packet_not_retry_status')

    report=dict(passed_groups=len(cases),cases=cases,limitations=[
        'Original Main loop boundaries and native handlers; modeled RTOS copying, getters, timer and device effects.',
        'Naive FIFO binding is deliberately installed only in test fixtures as a negative control.',
        'Two emulator CPUs exchange scalar values; not simultaneous RTOS execution.',
        'No production event ownership, lossless overflow policy, mode ordering or device hook is claimed.'])
    (ROOT/'analysis/pad_dispatch_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
