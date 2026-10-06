#!/usr/bin/env python3
"""Emulator PC redirections through compiled register-preserving adapters.

Original instructions remain unmodified. Control events and the file worker are
serialized fixtures in this suite; verify_bridge_events adds controlled queue
interleavings. Neither is real RTOS transport or a flashable patch.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_block_exchange import ExchangeRig,P
from verify_extra_capture import STATE,ELF
from verify_extra_lifecycle import LIFE
from verify_history_capture import values,payload
from verify_uncompressed_tap import B,MIX,STAGING
from verify_record_events import REC,TARGET
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

BR=0x22018000
HOOKS={0x8001078a:'emulator_outer_hook',0x202269f8:'emulator_tap_hook',
       0x2022a776:'emulator_commit_hook',0x80006908:'emulator_start_hook',
       0x80006918:'emulator_stop_hook',0x8000b158:'emulator_admit_hook',
       0x80034fc0:'emulator_reject_hook'}

class BridgeRig(ExchangeRig):
    outer_hook='emulator_outer_hook'
    def __init__(self,count=8):
        super().__init__(count=count);m=self.m
        self.blayout=struct.unpack('<6I',self.raw(self.syms['bridge_layout'],24))
        put32(m,B+0x53c8,0x2022a791);put32(m,BR+12,123)
        assert self.life('life_prepare',0,1)==0
        assert m.invoke(self.syms['bridge_bind'],[BR,P,LIFE,STATE])==0
        self.hooks_enabled=True;self.entries=[]
        for address,name in HOOKS.items():
            if name=='emulator_outer_hook':
                name=self.outer_hook
                if name is None:continue
            def redirect(uc,a,size,user,name=name):
                if self.hooks_enabled:
                    self.entries.append(name);uc.reg_write(A.UC_ARM_REG_PC,self.syms[name])
            m.uc.hook_add(UC_HOOK_CODE,redirect,begin=address,end=address)
        put32(m,0x8077ca30+0x440,0x557);m.uc.mem_write(TARGET,b'\xff')
        self.original_ram=self.raw(0x8077ca30,0x4000)
    def step(self,session=123):return self.m.invoke(self.syms['bridge_step'],[BR,session])
    def eligible(self):return self.m.invoke(self.syms['bridge_verified_path'],[BR,123])
    def pump(self):
        for _ in range(2048):
            status=self.step()
            if status!=10:return status
        raise AssertionError('Bridge did not yield within fixture bound')
    def block(self):
        before=len(self.calls);m=self.m
        m.uc.reg_write(A.UC_ARM_REG_R0,struct.unpack('<I',self.raw(B+0x53c8,4))[0])
        self.window(0x8001078a,0x8001078c)
        samples=[values(self.sequence+i) for i in range(64)]
        self.floats(MIX,[v[0]*2**31 for v in samples]+[v[1]*2**31 for v in samples])
        self.gain(.5);self.stock_staging();samples=struct.unpack('<128f',self.raw(STAGING))
        self.position=self.cursor;self.master_block(list(samples[:64]),list(samples[64:]))
        self.cursor=struct.unpack('<I',self.raw(B+0x53e4,4))[0];self.sequence+=64
        assert len(self.calls)==before,'Audio hook performed IO'
    def start(self):self.window(0x80034f44,0x80034f4c)
    def admit(self):
        self.m.uc.reg_write(A.UC_ARM_REG_R6,REC)
        self.window(0x8000b158,0x8000b160)
    def stop(self):self.window(0x8004ba44,0x8004ba4c)
    def assert_failed(self):
        assert self.pump() not in (0,10,11)
        assert not self.eligible() and not self.life('life_verified_path')
        assert not self.opened;self.assert_ordinary()

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=BridgeRig();r.block();r.start()
    assert r.step()==11 # Snapshot before stock admission cannot start a file.
    r.block();r.block();r.admit();assert r.pump()==11
    for _ in range(9):r.block();assert r.pump()==11
    r.stop();assert r.pump()==0 and r.eligible()
    r.validate(payload(64,768))
    assert set(HOOKS.values())-{'emulator_reject_hook'}<=set(r.entries)
    passed('original_audio_and_event_sites_through_compiled_hooks_produce_exact_verified_704_frame_file',
           limitation='DSP windows, admission handles and interleaving supplied by fixture; no full running device')

    # Compare live register state at the displaced instruction's continuation,
    # with and without the compiled call. Seed every scalar FP register.
    snapshots=[]
    for enabled in (False,True):
        r=BridgeRig();m=r.m
        # Unicorn lazily initializes FPSCR at its first guest FP instruction.
        # Warm the guest FP path before seeding status/register sentinels.
        r.hooks_enabled=False;r.gain(1);r.hooks_enabled=enabled
        regs=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(13)]
        for i,reg in enumerate(regs):m.uc.reg_write(reg,0x12340000+i*0x101)
        m.uc.reg_write(A.UC_ARM_REG_R4,B)
        fp=[getattr(A,'UC_ARM_REG_S'+str(i)) for i in range(32)]
        for i,reg in enumerate(fp):m.uc.reg_write(reg,0x3f000000+i*123)
        m.uc.reg_write(A.UC_ARM_REG_APSR,0xa80f0000)
        m.uc.reg_write(A.UC_ARM_REG_FPSCR,0x01400000)
        r.window(0x202269f8,0x202269fc)
        snapshots.append([m.uc.reg_read(reg) for reg in regs+fp+
            [A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR]])
    assert snapshots[0]==snapshots[1],[(i,hex(x),hex(y)) for i,(x,y) in enumerate(zip(*snapshots)) if x!=y]
    passed('tap_trampoline_preserves_live_integer_FPU_status_and_stack_state_at_continuation')

    r=BridgeRig();r.block();r.start()
    put32(r.m,0x8077ca30+0x440,0x157) # missing ordinary master registration
    r.original_ram=r.raw(0x8077ca30,0x4000)
    r.admit();r.assert_failed()
    passed('missing_required_stock_registration_cancels_prepared_optional_file')

    r=BridgeRig();r.block()
    r.m.hooks[0x80006290]=lambda a:1;r.m.hooks[0x80007c20]=lambda a:0
    r.m.invoke(0x80034f40,[0xffffffff])
    assert 'emulator_start_hook' in r.entries and 'emulator_reject_hook' in r.entries
    r.assert_failed()
    passed('original_rejected_record_request_closes_optional_file_without_starting_capture')

    r=BridgeRig(count=2);r.start();r.admit()
    for _ in range(3):r.block()
    r.assert_failed()
    before=r.cursor;r.block();assert r.cursor==(before+64)%r.capacity
    passed('overwritten_required_generation_automatically_cancels_extra_file_and_stock_ring_keeps_advancing')

    r=BridgeRig();r.start();r.admit();r.block();assert r.pump()==11
    put32(r.m,B+0x53c8,0x80010961)
    r.m.uc.reg_write(A.UC_ARM_REG_R0,0x80010961)
    before=len(r.calls);r.window(0x8001078a,0x8001078c)
    assert len(r.calls)==before;r.assert_failed()
    passed('outer_entry_notices_alternative_callback_and_defers_file_cancellation_to_worker')

    r=BridgeRig();r.start();r.admit();r.block()
    put32(r.m,B+0x53c8,0);r.m.uc.reg_write(A.UC_ARM_REG_R0,0)
    r.window(0x8001078a,0x8001078e);r.assert_failed()
    passed('null_callback_follows_original_skip_branch_and_cancels_optional_take')

    r=BridgeRig(count=2);r.start();r.admit();r.block()
    assert r.claim(0)[0]==0
    r.block();r.block() # Third block is dropped while the reader holds slot 0.
    assert r.step()==11 and r.opened
    assert r.release(0)==0;r.assert_failed()
    passed('held_slot_gap_reaches_automatic_file_cancellation_after_reader_release')

    r=BridgeRig();r.block()
    # Models a stock cursor observed between its store and exchange publication.
    put32(r.m,B+0x53e4,128)
    r.start();r.assert_failed()
    passed('unresolved_event_snapshot_is_cancelled_not_reinterpreted_on_a_later_ring_lap')

    r=BridgeRig();r.start();r.admit();r.block()
    r.inject=('audio',1,'short');r.stop();r.assert_failed()
    passed('worker_short_write_closes_extra_file_and_never_exposes_eligible_path')

    r=BridgeRig();r.start();r.admit();r.block()
    before=r.raw(BR,r.blayout[0]);assert r.step(122)==12
    assert r.raw(BR,r.blayout[0])==before and r.opened
    r.stop();assert r.pump()==0;r.validate(payload(0,64))
    passed('wrong_session_worker_request_cannot_modify_current_take')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        bridge_state_bytes=r.blayout[0],hook_sites={hex(a):n for a,n in HOOKS.items()},
        limitations=['PC interception in emulator, not patched firmware or installed hooks',
          'This suite serializes hooks/worker; verify_bridge_events adds controlled interleavings; real RTOS scheduling unbound',
          'Admission checks registered handles/mask, not full real SD readiness or successful future IO',
          'Tested ordinary topology only; alternate configurations conservatively reject extra capture',
          'No full DSP, arbitrary instruction preemption, hardware cache or timing proof',
          'Device memory, bootloader/recovery, pad-reader fence and assignment remain unresolved'])
    target=ROOT/'analysis/emulator_bridge_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(target)),indent=2))

if __name__=='__main__':main()
