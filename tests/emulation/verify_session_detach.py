#!/usr/bin/env python3
"""Permanent hook/worker gateway; modeled interleavings, never device access."""
import hashlib,json,struct
from unicorn import UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_PROT_NONE
from verify_control_drain import DrainRig
from verify_bridge_events import QueueRig
from verify_emulator_bridge import BR
from verify_control_transport import T
from verify_block_exchange import P,SLOTS
from verify_extra_capture import STATE,ELF
from verify_extra_lifecycle import LIFE
from verify_history_capture import payload
from verify_record_scheduler import word
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32

def detach(r,session=123,ptr=BR):return r.m.invoke(r.syms['bridge_detach'],[ptr,session])
def gate(r):return r.syms['bridge_gateway_readers']
def finish(r):
    r.start();r.admit();r.block();r.stop();assert r.pump()==0

def peer_detach(r,peer):
    # Separate emulator CPU, shared protocol state copied explicitly. Peer
    # only closes gateway and waits; it must not reach exchange/file state.
    peer.m.uc.mem_write(BR,r.raw(BR,r.blayout[0]))
    put32(peer.m,gate(peer),word(r.m,gate(r)))
    assert detach(peer)==11
    put32(r.m,gate(r),word(peer.m,gate(peer)))

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))

    r=DrainRig();r.block();r.request();r.dispatch_all();r.block();r.request(1)
    assert r.close()==0
    full=lambda:r.m.invoke(r.syms['ct_detach_capture'],[T,123])
    assert full()==11 # Stop callback not delivered.
    r.dispatch_all();assert full()==10 # Control marker submitted.
    r.dispatch_all();assert full()==11 and word(r.m,gate(r))==0 # File still active.
    assert r.pump()==0;r.validate(payload(64,128));assert not r.opened
    assert full()==0 and full()==0 and r.step()==12 and not r.eligible()
    calls=len(r.calls);cursor=r.cursor;r.block()
    assert r.cursor==(cursor+64)%r.capacity and len(r.calls)==calls
    assert word(r.m,r.syms['emulator_bridge_current'])==0
    passed('combined_control_and_file_completion_detaches_exact_WAV_session_with_stock_audio_continuing')

    r=QueueRig();assert detach(r)==11 and word(r.m,gate(r))==0
    assert detach(r,122)==12 and detach(r,ptr=0xdead0000)==12
    assert r.m.invoke(r.syms['bridge_step'],[0xdead0000,123])==12
    finish(r);assert detach(r)==0 and detach(r,122)==12
    fresh=BR+0x300;put32(r.m,fresh+12,124)
    assert r.m.invoke(r.syms['bridge_bind'],[fresh,P,LIFE,STATE])==12
    passed('nonterminal_detach_keeps_gateway_open_wrong_pointers_rejected_and_rebind_disabled')

    # Pause a real compiled hook before global pointer load and after pointer
    # load (at first actor-counter read). Both must already own gateway count.
    for after_pointer in (False,True):
        r=QueueRig();peer=QueueRig();finish(r);seen=[]
        address=r.qaddr(8) if after_pointer else r.syms['emulator_bridge_current']
        def pause(uc,access,addr,size,value,user):
            if seen:return
            seen.append(True);assert word(r.m,gate(r))==1
            peer_detach(r,peer);assert word(r.m,gate(r))==0x80000001
        handle=r.m.uc.hook_add(UC_HOOK_MEM_READ,pause,begin=address,end=address+3)
        r.m.uc.ctl_remove_cache(0x10010000,0x10020000) # Refresh memory observers on translated code.
        r.m.invoke(r.syms['bridge_hook'],[1,0]);r.m.uc.hook_del(handle)
        assert seen==[True] and word(r.m,gate(r))==0x80000000
        assert detach(r)==0
    passed('hooks_paused_before_and_after_session_pointer_load_prevent_early_acknowledgement')

    r=QueueRig();peer=QueueRig();finish(r);seen=[]
    def worker_before_pointer(uc,access,addr,size,value,user):
        if seen:return
        seen.append(True);assert word(r.m,gate(r))==1;peer_detach(r,peer)
    address=r.syms['emulator_bridge_current']
    handle=r.m.uc.hook_add(UC_HOOK_MEM_READ,worker_before_pointer,begin=address,end=address+3)
    r.m.uc.ctl_remove_cache(0x10010000,0x10020000) # Refresh memory observers on translated code.
    assert r.step()==0;r.m.uc.hook_del(handle)
    assert seen==[True] and detach(r)==0
    passed('worker_paused_before_pointer_validation_remains_counted_until_return')

    r=QueueRig();peer=QueueRig();r.start();r.admit();r.block();r.stop();seen=[]
    def worker_return(uc,access,addr,size,value,user):
        if value or seen or word(r.m,BR+r.blayout[2])!=3:return
        seen.append(True);assert word(r.m,gate(r))==1
        assert word(r.m,r.qaddr(3))==1;peer_detach(r,peer)
    address=r.qaddr(3)
    handle=r.m.uc.hook_add(UC_HOOK_MEM_WRITE,worker_return,begin=address,end=address+3)
    r.m.uc.ctl_remove_cache(0x10010000,0x10020000) # Refresh memory observers on translated code.
    assert r.pump()==0;r.m.uc.hook_del(handle)
    assert seen==[True] and not r.opened and detach(r)==0
    passed('terminal_phase_visible_before_worker_returns_does_not_allow_early_detach')

    for operation in ('audio','close_read'):
        r=QueueRig();peer=QueueRig();r.start();r.admit();r.block();r.stop();seen=[];original=r.hit
        def during_io(op):
            if op==operation and not seen:
                seen.append(True);peer_detach(r,peer)
                assert word(r.m,gate(r))==1 # Nonterminal refusal must not close.
            return original(op)
        r.hit=during_io;assert r.pump()==0 and seen==[True] and not r.opened
        assert detach(r)==0;r.assert_ordinary()
    passed('active_audio_write_and_final_read_close_prevent_detach_without_disabling_completion')

    r=QueueRig();r.start();r.admit();r.block();r.inject=('audio',1,'short')
    r.assert_failed();assert not r.opened and detach(r)==0 and r.step()==12
    passed('failed_optional_capture_can_detach_after_worker_cancellation_but_is_never_eligible')

    for outstanding in ('actor','queue_gate','lease'):
        r=QueueRig();finish(r)
        if outstanding=='actor':put32(r.m,r.qaddr(8),0x80000001)
        elif outstanding=='queue_gate':put32(r.m,r.qaddr(0),1)
        else:assert r.claim(0)[0]==0
        assert detach(r)==11
        if outstanding=='actor':put32(r.m,r.qaddr(8),0x80000000)
        elif outstanding=='queue_gate':put32(r.m,r.qaddr(0),0)
        else:assert r.release(0)==0
        assert detach(r)==0
    passed('outstanding_actor_queue_gate_or_exchange_reader_prevents_acknowledgement')

    r=QueueRig();finish(r);assert detach(r)==0;calls=len(r.calls)
    # Fault on any accidental guest dereference of old Bridge, Capture, Life,
    # Exchange or sample slots. Permanent gateway/code remain mapped.
    for addr,size in ((STATE,0x10000),(LIFE,0x1000),(P,0x1000),(BR,0x1000),(SLOTS,0x20000)):
        r.m.uc.mem_protect(addr,size,UC_PROT_NONE)
    for kind in range(10):r.m.invoke(r.syms['bridge_hook'],[kind,0])
    assert r.step()==12 and detach(r)==0
    cursor=r.cursor;r.block();assert r.cursor==(cursor+64)%r.capacity
    assert len(r.calls)==calls and word(r.m,gate(r))==0x80000000
    passed('post_detach_hooks_stale_worker_and_idempotent_detach_never_access_protected_session_memory')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['One permanent gateway; close irreversible; no session rearm or physical memory placement',
        'Single serialized detach manager with stable state and drained control ownership required',
        'Protection test proves only hook/worker/detach entry points, not all Transport/direct router/path users',
        'Two independent emulator CPUs copy protocol state at selected memory accesses; no full RTOS execution',
        'File API calls are synchronous fixtures; real SD/DMA completion, cache ordering and timing remain unproved'])
    path=ROOT/'analysis/session_detach_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))
if __name__=='__main__':main()
