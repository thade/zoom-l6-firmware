#!/usr/bin/env python3
"""Compiled bounded command queue and original three-argument pad handlers.
Task scheduling, state getters and audio/UI effects are modeled. No device.
"""
import json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_CPU_ARM_CORTEX_M7
from verify_overdub_prototype import Emulator
from verify_simple_handoff import Simple
from verify_firmware_workflow import put32
from verify_pad_protocol import REGS
from verify_pad_reload import BUSY_WORD

STATE=0x2201f400;PORT=0x2102e000;COMMAND=0x2102e040
MAIN=0x7100;WORKER=0x7101

class Commands(Simple):
    emulator_factory=staticmethod(lambda:Emulator(cpu_model=UC_CPU_ARM_CORTEX_M7,mclass=True))
    def __init__(self):
        super().__init__();self.task=MAIN;self.events=[];self.calls=[];self.playing_pad=[False]*4
        self.mode=[0]*4;self.record_target=0xffffffff;self.after_start=None
        m=self.m
        m.hooks[0x800770e8]=lambda a:self.task
        m.hooks[0x800061f0]=lambda a:1
        m.hooks[0x80006238]=lambda a:self.mode[a[0]]
        m.hooks[0x80002440]=lambda a:int(self.playing_pad[a[0]])
        m.hooks[0x80006290]=m.hooks[0x800060d0]=m.hooks[0x8000a220]=lambda a:0
        m.hooks[0x80034da8]=lambda a:self.record_target
        m.hooks[0x80002c60]=self.start_pad;m.hooks[0x80002d08]=self.stop_pad
        for fn in (0x80008430,0x80008428,0x80020548,0x8000aad0):
            m.hooks[fn]=lambda a,fn=fn:self.events.append((hex(fn),a[0])) or 0
        m.hooks[0x80034f40]=lambda a:self.events.append(('record_toggle',a[0])) or 0
        m.uc.mem_write(PORT,struct.pack('<3I',MAIN,WORKER,self.syms['pc_stock_execute']|1))
        self.pc_layout=struct.unpack('<5I',m.uc.mem_read(self.syms['pc_layout'],20))
        assert self.pc('init',PORT)==0
        def observe(uc,a,n,u):
            assert self.word(1)==0 and self.word(3)==1 and self.task==MAIN
            source=0 if a==0x8003f4d8 else 1
            self.calls.append((source,*[uc.reg_read(reg) for reg in REGS[:3]]))
        for addr in (0x8003f4d8,0x800408b0):
            m.uc.hook_add(UC_HOOK_CODE,observe,begin=addr,end=addr)
    def word(self,index):return struct.unpack('<I',self.m.uc.mem_read(STATE+self.pc_layout[index],4))[0]
    def pc(self,name,*args,task=MAIN):
        self.task=task
        return self.m.invoke(self.syms['pc_'+name],[STATE,*args])
    def submit(self,source=0,pad=0,argument=0,event=1):
        self.m.uc.mem_write(COMMAND,struct.pack('<4I',source,pad,argument,event))
        return self.pc('submit',COMMAND)
    def start_pad(self,a):
        self.events.append(('start',a[0]));self.playing_pad[a[0]]=True
        if self.after_start:self.after_start(self)
        return 0
    def stop_pad(self,a):
        self.events.append(('stop',a[0]));self.playing_pad[a[0]]=False;return 0

def main():
    cases=[]
    def passed(s):cases.append(s)
    r=Commands();assert r.pc('try_hold',task=WORKER)==0
    assert r.submit(0,2,0x12345678,1)==0
    r.m.uc.mem_write(COMMAND,b'\xff'*16)
    assert r.pc('poll')==1 and not r.calls
    assert r.pc('release',task=WORKER)==0 and not r.calls
    assert r.pc('poll')==0 and r.calls==[(0,2,0x12345678,1)]
    assert r.pc('poll')==1 and r.word(4)==0
    passed('held_command_is_owned_by_value_and_executes_once_on_Main_after_IO_free_release')

    r=Commands();r.mode[0]=2
    assert r.pc('try_hold',task=WORKER)==0
    assert r.submit(0,0,0,1)==0 and r.submit(0,0,0,0)==0
    assert r.pc('release',task=WORKER)==0
    assert r.pc('poll')==0 and r.pc('poll')==0
    assert [e for e in r.events if e[0] in ('start','stop')]==[('start',0),('stop',0)]
    assert not r.playing_pad[0]
    passed('press_and_release_keep_original_order_and_native_mode_semantics')

    r=Commands();r.mode[0]=1
    assert r.pc('try_hold',task=WORKER)==0
    assert r.submit()==0 and r.submit()==0
    assert r.pc('release',task=WORKER)==0
    assert r.pc('poll')==0 and r.pc('poll')==0
    assert [e for e in r.events if e[0] in ('start','stop')]==[('start',0),('stop',0)]
    passed('two_toggle_commands_are_not_reclassified_or_coalesced_into_two_starts')

    r=Commands();assert r.pc('try_hold',task=WORKER)==0
    assert r.submit(0,0,10,1)==0 and r.submit(0,1,11,1)==0
    assert r.pc('release',task=WORKER)==0 and r.pc('poll')==0
    assert r.submit(0,2,12,1)==0
    assert r.pc('poll')==0 and r.pc('poll')==0
    assert [c[2] for c in r.calls]==[10,11,12]
    passed('new_commands_after_release_cannot_overtake_the_deferred_backlog')

    # Negative control: raw arguments alone do not freeze interpretation.
    r=Commands();r.mode[0]=2;r.playing_pad[0]=True
    assert r.pc('try_hold',task=WORKER)==0 and r.submit(0,0,0,0)==0
    r.mode[0]=0
    assert r.pc('release',task=WORKER)==0 and r.pc('poll')==0
    assert r.calls==[(0,0,0,0)] and r.playing_pad[0]
    assert not any(e[0]=='stop' for e in r.events)
    passed('negative_control_mode_change_before_replay_changes_release_meaning_requires_dispatcher_policy')

    r=Commands();r.record_target=2
    assert r.pc('try_hold',task=WORKER)==0
    assert r.submit(1,2,0,1)==0 and not r.events
    assert r.pc('release',task=WORKER)==0 and r.pc('poll')==0
    assert ('record_toggle',0xffffffff) in r.events and not any(e[0]=='start' for e in r.events)
    passed('full_source_1_handler_retains_record_plus_pad_branch_instead_of_forcing_playback')

    r=Commands();r.mode[0]=2;r.playing_pad[0]=True
    assert r.submit(0,0,0,0)==0 and r.pc('try_hold',task=WORKER)==1
    assert r.pc('poll')==0 and not r.playing_pad[0]
    assert r.pc('try_hold',task=WORKER)==0
    passed('already_accepted_stop_finishes_before_command_admission_can_be_held')

    r=Commands();assert r.pc('try_hold',task=WORKER)==0;r.submit()
    # Execute original reload UI body's control flow on the same Main CPU.
    # Deep stop/load/save effects remain fixtures; no gate blocks this event.
    for fn in (0x800075a8,0x80002ce8,0x80009840,0x80009930,0x80006b18):
        r.m.hooks[fn]=lambda a,fn=fn:r.events.append(('reload',hex(fn))) or 0
    r.m.hooks[0x8000ac90]=lambda a:0
    put32(r.m,BUSY_WORD,1);r.task=MAIN;r.m.invoke(0x80008b68,[])
    assert struct.unpack('<I',r.m.uc.mem_read(BUSY_WORD,4))[0]==0
    assert len([e for e in r.events if e[0]=='reload'])==6 and not r.calls
    assert r.word(2)==1 and r.word(4)==1
    passed('pad_queue_hold_does_not_park_Main_or_prevent_original_reload_consumer_progress')

    r=Commands();assert r.pc('try_hold',task=WORKER)==0
    for i in range(8):assert r.submit(0,i%4,i,1)==0
    assert r.submit(0,0,999,1)==1 and r.word(4)==8
    assert r.pc('release',task=WORKER)==0
    for i in range(8):assert r.pc('poll')==0
    assert [c[2] for c in r.calls]==list(range(8))
    assert r.submit(0,0,999,1)==0 and r.pc('poll')==0 and r.calls[-1][2]==999
    passed('full_queue_consumes_nothing_and_upstream_retry_preserves_all_accepted_commands')

    r=Commands();r.submit(0,1,7,1)
    def contend(r):put32(r.m,STATE+r.pc_layout[1],1)
    r.after_start=contend
    assert r.pc('poll')==1 and r.word(3)==2 and len(r.calls)==1
    put32(r.m,STATE+r.pc_layout[1],0)
    assert r.pc('try_hold',task=WORKER)==1
    assert r.pc('poll')==0 and len(r.calls)==1 and r.word(4)==0
    passed('completion_contention_retries_bookkeeping_without_reexecuting_a_command')

    r=Commands();r.submit();seen=[]
    def concurrent(r):
        peer=Commands();peer.m.uc.mem_write(STATE,bytes(r.m.uc.mem_read(STATE,r.pc_layout[0])))
        seen.append(peer.pc('try_hold',task=WORKER))
    r.after_start=concurrent
    assert r.pc('poll')==0 and seen==[1]
    passed('concurrent_hold_cannot_succeed_while_original_command_is_still_executing')

    r=Commands();assert r.pc('try_hold')==2
    assert r.pc('release',task=WORKER)==2
    assert r.pc('poll',task=WORKER)==2
    assert r.submit(2)==2 and r.submit(0,4)==2
    assert not r.calls and not r.word(4)
    passed('task_identity_and_command_validation_reject_without_consumption')
    print(json.dumps(dict(passed_groups=len(cases),cases=cases),indent=2))

if __name__=='__main__':main()
