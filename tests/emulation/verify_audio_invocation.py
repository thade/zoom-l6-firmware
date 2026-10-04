#!/usr/bin/env python3
"""Original callback dispatch/return, synthetic DSP body, pinned audio lifetime."""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_PROT_NONE
from unicorn import arm_const as A
from verify_bridge_events import QueueRig
from verify_session_detach import detach,gate,peer_detach
from verify_emulator_bridge import BR
from verify_block_exchange import P,SLOTS
from verify_extra_capture import STATE,ELF
from verify_extra_lifecycle import LIFE
from verify_history_capture import values,payload
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

class AudioRig(QueueRig):
    def __init__(self):
        super().__init__();self.install()
    def install(self):
        self.adapter=True
        assert self.m.invoke(self.syms['bridge_audio_enable'],[])==0
        for address,name in ((0x8001078a,'emulator_audio_outer_hook'),(0x8001078e,'emulator_audio_return_hook'),
                             (0x2022a790,'audio_fixture_callback')):
            def redirect(uc,a,size,u,name=name):
                if self.adapter:uc.reg_write(A.UC_ARM_REG_PC,self.syms[name])
            self.m.uc.hook_add(UC_HOOK_CODE,redirect,begin=address,end=address)
        self.m.hooks[0x80010150]=lambda a:None
        self.m.hooks[0x80010960]=lambda a:None
    def audio_call(self,mode=0,callback=0x2022a791):
        samples=[values(self.sequence+i) for i in range(64)]
        self.floats(0x20013e00,[v[0]*2**31 for v in samples])
        self.floats(0x20013f00,[v[1]*2**31 for v in samples])
        put32(self.m,self.syms['audio_fixture_mode'],mode)
        put32(self.m,0x20015e10,callback)
        self.m.uc.reg_write(A.UC_ARM_REG_R0,callback)
        before=len(self.calls);self.window(0x8001078a,0x80010792)
        assert len(self.calls)==before,'Audio dispatch performed file IO'
        self.cursor=word(self.m,0x20015e2c)
        if callback==0x2022a791:self.sequence+=64
    def finish_take(self):
        self.start();self.admit();self.audio_call();self.stop();assert self.pump()==0

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=AudioRig();r.start();r.admit()
    for _ in range(6):r.audio_call();assert r.pump()==11
    r.stop();assert r.pump()==0;r.validate(payload(0,384))
    assert word(r.m,gate(r))==0 and word(r.m,r.syms['bridge_audio_calls'])==0
    passed('original_dispatch_and_return_hold_one_session_across_six_exact_audio_blocks',frames=384)

    for phase in (0,1,2):
        r=AudioRig();peer=AudioRig();r.finish_take();seen=[]
        def checkpoint(a):
            if a[0]==phase and not seen:
                seen.append(True)
                assert word(r.m,r.syms['bridge_audio_calls'])==1 and word(r.m,gate(r))==1
                peer_detach(r,peer)
                assert word(r.m,gate(r))==0x80000001
            return None
        r.m.hooks[r.syms['audio_fixture_checkpoint']&~1]=checkpoint
        r.audio_call();assert seen==[True] and word(r.m,r.syms['bridge_audio_calls'])==0
        assert word(r.m,gate(r))==0x80000000 and detach(r)==0
    passed('detach_waits_between_outer_and_tap_between_tap_and_commit_and_before_return')

    for mode in (1,2,8):
        r=AudioRig();r.start();r.admit();r.audio_call(mode)
        assert word(r.m,BR+16)==32 and word(r.m,gate(r))==0
        assert word(r.m,r.syms['bridge_audio_calls'])==0;r.assert_failed()
    passed('missing_tap_missing_commit_and_duplicate_tap_cancel_optional_capture_and_release_scope')

    for callback in (0,0x80010961):
        r=AudioRig();r.audio_call(callback=callback)
        assert word(r.m,BR+16)==18 and word(r.m,gate(r))==0
        assert word(r.m,r.syms['bridge_audio_calls'])==0;r.assert_failed()
    passed('original_null_and_alternate_callback_paths_reach_cleanup_without_leaking_reservations')

    r=AudioRig();r.start();r.admit();r.audio_call(4)
    assert word(r.m,BR+16)==31 and word(r.m,gate(r))==0
    assert word(r.m,r.syms['bridge_audio_calls'])==0;r.assert_failed()
    passed('nested_callback_suppresses_taps_cancels_optional_capture_and_drains_outer_ownership')

    r=AudioRig();r.start();r.admit();r.audio_call();r.stop()
    # Start a real original outer dispatch then stop the emulator at callback
    # entry, leaving ordinary invocation suspended. Do not simulate a return.
    r.m.uc.reg_write(A.UC_ARM_REG_R0,0x2022a791)
    r.window(0x8001078a,0x8001078c)
    assert word(r.m,gate(r))==1 and word(r.m,r.syms['bridge_audio_calls'])==1
    # Worker APIs run on a separate emulated CPU; files/disk copied as fixtures.
    peer=AudioRig()
    peer.m.uc.mem_write(STATE,r.raw(STATE,0x20000));peer.m.uc.mem_write(SLOTS,r.raw(SLOTS,0x20000))
    peer.m.uc.mem_write(0x10010000,r.raw(0x10010000,0x10000))
    peer.disk={k:bytearray(v) for k,v in r.disk.items()};peer.opened={k:list(v) for k,v in r.opened.items()}
    peer.next_handle=r.next_handle
    assert peer.pump()==11 and not peer.eligible() and detach(peer)==11
    passed('suspended_invocation_blocks_final_eligibility_and_detach_until_its_return',
           limitation='Non-returning callbacks retain ownership; no forced recovery or timeout release')

    # Strict mode excludes the bare-tap defect even in a fresh live session.
    # It cannot invent a current outer invocation from the current pointer.
    r=AudioRig();before=r.raw(P,r.xlayout[0]);r.m.invoke(r.syms['bridge_hook'],[1,0])
    r.m.invoke(r.syms['bridge_hook'],[2,0]);assert r.raw(P,r.xlayout[0])==before
    r.start();r.admit();r.audio_call();r.stop();assert r.pump()==0;r.validate(payload(0,64))
    passed('unscoped_tap_and_commit_cannot_join_current_session_strict_mode')

    r=AudioRig();r.finish_take();assert detach(r)==0
    for addr,size in ((STATE,0x20000),(SLOTS,0x20000)):r.m.uc.mem_protect(addr,size,UC_PROT_NONE)
    r.audio_call();r.audio_call(callback=0);r.audio_call(callback=0x80010961)
    assert word(r.m,gate(r))==0x80000000 and word(r.m,r.syms['bridge_audio_calls'])==0
    passed('post_detach_normal_null_and_alternate_dispatches_do_not_touch_protected_session')

    from verify_control_drain import DrainRig
    from verify_transport_shutdown import shutdown
    from types import MethodType
    r=DrainRig();AudioRig.install(r);r.audio_call=MethodType(AudioRig.audio_call,r)
    r.audio_call();r.request();r.dispatch_all()
    for _ in range(3):r.audio_call();assert r.pump()==11
    r.request(1);assert r.close()==0;r.dispatch_all()
    assert shutdown(r)==10;r.dispatch_all();assert shutdown(r)==11
    assert r.pump()==0;r.validate(payload(64,256));assert shutdown(r)==0
    r.m.uc.mem_protect(STATE,0x20000,UC_PROT_NONE)
    r.m.uc.mem_protect(SLOTS,0x20000,UC_PROT_NONE)
    r.audio_call();assert shutdown(r)==0
    passed('strict_audio_adapter_integrates_with_owned_requests_control_drain_and_full_shutdown',frames=192)

    # Differential live-state check at continuation, including replayed stock BL.
    for start,end in ((0x8001078a,0x8001078c),(0x8001078e,0x80010792)):
        snapshots=[]
        for enabled in (False,True):
            r=AudioRig();r.hooks_enabled=False;r.adapter=enabled;r.gain(1)
            regs=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(13)]
            fp=[getattr(A,'UC_ARM_REG_S'+str(i)) for i in range(32)]
            for i,reg in enumerate(regs):r.m.uc.reg_write(reg,0x12340000+i*0x101)
            r.m.uc.reg_write(A.UC_ARM_REG_R0,0x2022a791)
            for i,reg in enumerate(fp):r.m.uc.reg_write(reg,0x3f000000+i*123)
            r.m.uc.reg_write(A.UC_ARM_REG_APSR,0xa80f0000);r.m.uc.reg_write(A.UC_ARM_REG_FPSCR,0x01400000)
            r.window(start,end)
            snapshots.append([r.m.uc.reg_read(x) for x in regs+fp+[A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_APSR,A.UC_ARM_REG_FPSCR]])
        assert snapshots[0]==snapshots[1]
    passed('entry_and_return_adapters_preserve_integer_FPU_status_stack_and_original_BL_continuation')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Original BLX executes; displaced CBZ/return BL semantics replayed; DSP body/cursor advance are synthetic',
        'Strict mode explicitly enabled for new adapter; historical isolated tests retain legacy mode',
        'Single audio producer with balanced returns; nesting cancels; arbitrary concurrent producer scheduling unsupported',
        'No session reopening, lost-return recovery, real SD/DMA or physical timing/cache proof'])
    path=ROOT/'analysis/audio_invocation_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))
if __name__=='__main__':main()
