#!/usr/bin/env python3
"""One compiled hook pair observes capture and completion on the same CPU."""
import json
import struct
from unicorn import UC_HOOK_CODE, UC_PROT_NONE
from unicorn import arm_const as A
from verify_bridge_events import QueueRig
from verify_audio_invocation import AudioRig
from verify_native_audio import C, OUT, AID, OK, BUSY, INVALID, FAULT
from verify_read_worker import CURRENT
from verify_emulator_bridge import BR
from verify_block_exchange import P, SLOTS
from verify_extra_capture import STATE
from verify_session_detach import detach, gate
from verify_history_capture import payload
from verify_pad_reader_audit import SECONDARY, TARGETS
from verify_uncompressed_tap import B, MIX, RING, STRIDE
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, RETURN
from verify_scheduling_boundaries import stop


class Shared(QueueRig):
    outer_hook=None
    synthetic=True
    def __init__(self,bind=True):
        super().__init__();self.adapter=True
        put32(self.m,0x80446d78,AID);put32(self.m,CURRENT,AID)
        put32(self.m,SECONDARY,0x2022a789)
        assert self.m.invoke(self.m.symbols['na_bind'],[C,AID])==OK
        if bind:assert self.bind_capture()==OK
        for address,name in ((0x8001078a,'na_entry_hook'),(0x8001078e,'na_return_hook')):
            def redirect(uc,a,n,u,name=name):
                if self.adapter:uc.reg_write(A.UC_ARM_REG_PC,self.m.symbols[name]|1)
            self.m.uc.hook_add(UC_HOOK_CODE,redirect,begin=address,end=address)
        if self.synthetic:
            def callback(uc,a,n,u):uc.reg_write(A.UC_ARM_REG_PC,self.syms['audio_fixture_callback'])
            self.m.uc.hook_add(UC_HOOK_CODE,callback,begin=TARGETS[0],end=TARGETS[0])
            self.m.hooks[0x80010960]=lambda a:None
        self.m.hooks[0x80010150]=lambda a:None
    def bind_capture(self):
        return self.m.invoke(self.m.symbols['na_bind_capture'],
            [self.syms['bridge_hook'],self.syms['bridge_audio_enable']])
    audio_call=AudioRig.audio_call
    finish_take=AudioRig.finish_take
    def oc(self,name,*args):return self.m.invoke(self.m.symbols['oc_'+name],[C,*args])
    def request(self):
        assert self.oc('close',OUT)==OK;epoch=self.word(OUT)
        assert self.oc('audio_request',epoch)==OK;return epoch


class Full(Shared):
    synthetic=False
    cpu_options=dict(cpu_model=A.UC_CPU_ARM_MAX,mclass=False)
    def __init__(self):
        super().__init__()
        # ARM MAX executes the stock double-precision DSP, but not MRS IPSR.
        # Shared synthetic-callback tests use the real probe on Cortex-M7.
        self.m.hooks[self.m.symbols['na_thread_context']&~1]=lambda a:1
        for i in range(10):
            self.m.uc.mem_write(B+0x5864+i*16,struct.pack('<4I',0x21010000+i*0x1000,128,127,0))
        put32(self.m,B+0x63a0,0x21030000);put32(self.m,B+0x63a4,0x21031000)
        self.floats(B+0x5e34,[1]+[0]*9+[1]+[0]*9)
        # Earlier stock gain stage must be nonzero too; zero-initialized
        # synthetic state would mute the signal before the capture tap.
        self.floats(B+0x61bc,[1])
        self.snapshots=[]
        def snapshot(uc,a,n,u):self.snapshots.append(self.raw(MIX,512))
        self.m.uc.hook_add(UC_HOOK_CODE,snapshot,begin=self.syms['emulator_tap_hook']&~1,
                           end=self.syms['emulator_tap_hook']&~1)
    def full(self,target=TARGETS[0]):
        put32(self.m,B+0x53c8,target|1)
        before=len(self.calls);self.window(0x8001077c,0x80010792)
        assert len(self.calls)==before,'Audio path performed file IO'
        self.cursor=self.word(B+0x53e4)


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    r=Shared();r.start();r.admit();epoch=r.request()
    order=[]
    for name,syms in (('na_begin',r.m.symbols),('bridge_hook',r.syms),('na_end',r.m.symbols)):
        def observe(uc,a,n,u,name=name):
            if name=='bridge_hook':
                kind=uc.reg_read(A.UC_ARM_REG_R0)
                order.append((name,kind))
                if kind==11:
                    assert r.word(gate(r))==1
                    if len(order)<6:assert r.word(C+344)!=epoch
            else:
                order.append((name,))
                if name=='na_end':assert r.word(gate(r))==0
        r.m.uc.hook_add(UC_HOOK_CODE,observe,begin=syms[name]&~1,end=syms[name]&~1)
    for _ in range(6):r.audio_call();assert r.pump()==11
    assert r.oc('audio_poll',epoch)==OK
    assert order[:5]==[('na_begin',),('bridge_hook',10),('bridge_hook',1),('bridge_hook',2),('bridge_hook',11)]
    assert order[5]==('na_end',)
    r.stop();assert r.pump()==0;r.validate(payload(0,384))
    passed('one_shared_pair_records_exact_samples_and_acknowledges_only_after_capture_releases_scope')

    r=Shared();r.start();r.admit();epoch=r.request()
    r.m.uc.reg_write(A.UC_ARM_REG_R0,TARGETS[0]|1)
    r.window(0x8001078a,0x8001078c)
    saved=r.m.uc.context_save();stack=r.m.stack;r.m.stack=0x20030000
    assert r.oc('audio_poll',epoch)==BUSY and r.word(gate(r))==1
    assert r.word(r.syms['bridge_audio_calls'])==1
    r.m.stack=stack;r.m.uc.context_restore(saved)
    h=r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:stop(r.m),begin=0x80010792,end=0x80010792)
    r.m.uc.emu_start(0x8001078d,RETURN+2,count=10000000);r.m.uc.hook_del(h)
    assert r.oc('audio_poll',epoch)==OK and r.word(gate(r))==0
    passed('suspended_original_dispatch_retains_both_observers_until_the_actual_return')

    r=Shared();r.m.uc.reg_write(A.UC_ARM_REG_R0,TARGETS[0]|1)
    r.window(0x8001078a,0x8001078c)
    saved=r.m.uc.context_save();stack=r.m.stack;r.m.stack=0x20030000
    epoch=r.request();r.m.stack=stack;r.m.uc.context_restore(saved)
    h=r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:stop(r.m),begin=0x80010792,end=0x80010792)
    r.m.uc.emu_start(0x8001078d,RETURN+2,count=10000000);r.m.uc.hook_del(h)
    assert r.oc('audio_poll',epoch)==BUSY and r.word(gate(r))==0
    r.audio_call();assert r.oc('audio_poll',epoch)==OK
    passed('request_after_shared_entry_requires_another_complete_callback')

    for mode in (1,2,8):
        r=Shared();r.start();r.admit();epoch=r.request();r.audio_call(mode)
        assert r.oc('audio_poll',epoch)==OK and r.word(gate(r))==0
        r.assert_failed()
    passed('capture_protocol_failures_cancel_optional_file_without_leaking_scope_or_faking_audio_failure')

    for callback,expected in ((0,BUSY),(TARGETS[1]|1,OK)):
        r=Shared();epoch=r.request();r.audio_call(callback=callback)
        assert r.oc('audio_poll',epoch)==expected and r.word(gate(r))==0
        r.assert_failed()
    passed('null_dispatch_cannot_acknowledge_and_alternate_callback_completion_does_not_validate_capture')

    r=Shared();r.finish_take();assert detach(r)==OK
    r.m.uc.mem_protect(STATE,0x20000,UC_PROT_NONE)
    r.m.uc.mem_protect(SLOTS,0x20000,UC_PROT_NONE)
    epoch=r.request();r.audio_call();assert r.oc('audio_poll',epoch)==OK
    r.audio_call(callback=0);r.audio_call(callback=TARGETS[1]|1)
    assert r.word(gate(r))==0x80000000 and r.word(r.syms['bridge_audio_calls'])==0
    passed('completion_remains_available_after_capture_detach_without_touching_protected_session')

    for wrong in (CURRENT,0x80446d78):
        r=Shared();epoch=r.request();put32(r.m,wrong,AID+1);r.audio_call()
        assert r.oc('audio_poll',epoch)==FAULT
        assert r.word(gate(r))==0 and r.word(r.syms['bridge_audio_calls'])==0
    passed('wrong_task_never_enters_or_releases_capture_scope')

    r=Shared();epoch=r.request()
    r.m.invoke(r.m.symbols['na_observe_begin'],[TARGETS[0]|1])
    put32(r.m,CURRENT,AID+1);r.m.invoke(r.m.symbols['na_observe_end'],[])
    assert r.oc('audio_poll',epoch)==FAULT and r.word(gate(r))==1
    put32(r.m,CURRENT,AID);r.m.invoke(r.m.symbols['na_observe_end'],[])
    assert r.word(gate(r))==0 and r.oc('audio_poll',epoch)==FAULT
    passed('wrong_task_return_cannot_release_the_real_audio_invocation')

    r=Shared();epoch=r.request();r.audio_call()
    r.m.invoke(r.m.symbols['na_observe_end'],[])
    assert r.oc('audio_poll',epoch)==FAULT and r.word(gate(r))==0
    assert r.word(r.syms['bridge_audio_calls'])==0
    passed('duplicate_shared_return_faults_completion_without_underflowing_capture_reservations')

    r=Shared();epoch=r.request()
    r.m.invoke(r.m.symbols['na_observe_begin'],[TARGETS[0]|1])
    r.m.invoke(r.m.symbols['na_observe_begin'],[TARGETS[0]|1])
    assert r.oc('audio_poll',epoch)==FAULT and r.word(gate(r))==1
    for _ in range(2):r.m.invoke(r.m.symbols['na_observe_end'],[])
    assert r.word(gate(r))==0 and r.word(r.syms['bridge_audio_calls'])==0
    r.assert_failed()
    passed('nested_shared_entry_faults_completion_and_drains_balanced_capture_scopes')

    for start,end in ((0x8001078a,0x8001078c),(0x8001078e,0x80010792)):
        for align in (0,4):
            snapshots=[]
            for enabled in (False,True):
                r=Shared();r.adapter=enabled;r.hooks_enabled=False;r.gain(1);r.m.stack-=align
                regs=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(13)]
                fp=[getattr(A,'UC_ARM_REG_S'+str(i)) for i in range(32)]
                for i,reg in enumerate(regs):r.m.uc.reg_write(reg,0x12340000+i*0x101)
                r.m.uc.reg_write(A.UC_ARM_REG_R0,TARGETS[0]|1)
                for i,reg in enumerate(fp):r.m.uc.reg_write(reg,0x3f000000+i*123)
                r.m.uc.reg_write(A.UC_ARM_REG_APSR,0xa80f0000)
                r.m.uc.reg_write(A.UC_ARM_REG_FPSCR,0x01400000)
                r.window(start,end)
                snapshots.append([r.m.uc.reg_read(x) for x in regs+fp+[
                    A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR]])
            assert snapshots[0]==snapshots[1],(hex(start),align,[(i,hex(a),hex(b)) for i,(a,b) in enumerate(zip(*snapshots)) if a!=b])
    passed('both_observers_preserve_all_live_integer_FP_flags_and_original_stack_alignment')

    r=Shared(bind=False)
    assert r.m.invoke(r.m.symbols['na_bind_capture'],[0,r.syms['bridge_audio_enable']])==INVALID
    put32(r.m,r.syms['bridge_audio_calls'],1);assert r.bind_capture()==BUSY
    put32(r.m,r.syms['bridge_audio_calls'],0);assert r.bind_capture()==OK
    assert r.bind_capture()==INVALID
    r=Shared(bind=False);r.audio_call(callback=0);assert r.bind_capture()==BUSY
    passed('capture_binding_requires_valid_ports_and_quiescence_and_rejects_replacement_or_late_binding')

    r=Full();r.start();r.admit();epoch=r.request()
    r.pad(0,[2**28]*64,[-2**28]*64);put32(r.m,B+0x5404+32,1)
    for _ in range(4):r.full();assert r.pump()==11
    assert len(r.snapshots)==4 and any(v!=0 for v in struct.unpack('<128f',r.snapshots[0]))
    assert r.oc('audio_poll',epoch)==OK
    r.stop();assert r.pump()==0
    expected=bytearray()
    for raw in r.snapshots:
        samples=struct.unpack('<128f',raw)
        expected.extend(struct.pack('<128f',*[v/2**31 for pair in zip(samples[:64],samples[64:]) for v in pair]))
    r.validate(bytes(expected))
    passed('full_original_normal_DSP_with_shared_hooks_records_exact_observed_pre_gain_samples')

    snapshots=[]
    for enabled in (False,True):
        r=Full();r.adapter=enabled;r.hooks_enabled=enabled
        r.pad(0,[2**28]*64,[-2**28]*64);put32(r.m,B+0x5404+32,1)
        # Nonzero delayed input as well as pad playback exercises clean stems.
        r.floats(0x21010000,[2**26]*128)
        r.floats(B+0x6214,[.5])
        r.full();r.full()
        snapshots.append((r.raw(B,0x63b0),*[r.raw(RING+STRIDE*i,1024) for i in range(12)]))
    assert snapshots[0]==snapshots[1]
    passed('full_DSP_state_and_twelve_stock_ring_lanes_match_with_shared_observers_enabled_or_disabled')

    for target in TARGETS[1:]:
        r=Full();epoch=r.request();r.full(target)
        assert r.oc('audio_poll',epoch)==OK and r.word(gate(r))==0
        assert r.word(r.syms['bridge_audio_calls'])==0
        r.assert_failed()
    passed('all_original_alternate_DSP_callbacks_complete_with_capture_cleanup_through_shared_return')

    out=ROOT/'analysis/shared_audio_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Both separately built ELFs execute on one CPU via integer-only function ports; no installed firmware patches',
        'Cortex-M7 runs controlled callback fixture; ARM MAX runs full stock DSP with only IPSR query modeled',
        'Input routing, filesystem, queue scheduling, native task identity and output continuation are fixtures',
        'No physical timing, stack headroom, cache/DMA or global caller coverage proof',
        'Historical capture-only hooks remain for isolated tests and must not be installed alongside shared hooks']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
