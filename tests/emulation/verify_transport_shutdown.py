#!/usr/bin/env python3
"""Installed transport entry lifetime and unlink, offline only."""
import hashlib,json,struct
from unicorn import UC_HOOK_MEM_READ,UC_PROT_NONE
from verify_control_drain import DrainRig
from verify_control_transport import T,TASK,OTHER,PRODUCER,QHANDLE
from verify_request_router import ROUTER
from verify_emulator_bridge import BR
from verify_block_exchange import P,SLOTS
from verify_extra_capture import STATE,ELF
from verify_extra_lifecycle import LIFE
from verify_history_capture import payload
from verify_record_scheduler import word
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
from verify_auto_requests import ENTRIES

def gate(r):return r.syms['ct_gateway_readers']
def shutdown(r,session=123,ptr=T):return r.m.invoke(r.syms['ct_shutdown'],[ptr,session])
def finished(r):
    r.block();r.request();r.dispatch_all();r.block();r.request(1);assert r.close()==0
    r.dispatch_all();assert r.pump()==0;r.validate(payload(64,128))
    assert r.poll()==10;r.dispatch_all();assert r.poll()==0

def peer_shutdown(r,peer):
    # Independent CPU and stack; copy synthetic session and permanent globals.
    # Execute peer manager only at caller pauses outside critical sections.
    peer.m.uc.mem_write(0x10010000,r.raw(0x10010000,0x10000))
    peer.m.uc.mem_write(STATE,r.raw(STATE,0x20000))
    peer.m.uc.mem_write(SLOTS,r.raw(SLOTS,0x20000))
    put32(peer.m,TASK,OTHER)
    assert shutdown(peer)==11
    # Manager may retire Bridge but must not unlink live transport yet.
    assert word(peer.m,peer.syms['ct_active'])==T
    r.m.uc.mem_write(0x10010000,peer.raw(0x10010000,0x10000))
    r.m.uc.mem_write(BR,peer.raw(BR,r.blayout[0]))

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=DrainRig();assert shutdown(r)==12 # Admission not closed.
    finished(r);assert shutdown(r)==0 and shutdown(r)==0
    assert word(r.m,T)==0 and word(r.m,ROUTER)==0 and word(r.m,r.syms['ct_active'])==0
    assert word(r.m,gate(r))==0x80000000
    for q in r.slots():assert word(r.m,q)==0
    assert shutdown(r,122)==12 and shutdown(r,ptr=0xdead0000)==12
    passed('control_file_and_gateway_shutdown_clears_owned_links_and_is_idempotent')

    # Old gateway is reserved before loading active, for wrappers, a replayed
    # callback, raw queue send, and explicit scope operations.
    for entry in ('wrapper','callback','send','scope'):
        r=DrainRig();peer=DrainRig();finished(r);seen=[];address=r.syms['ct_active']
        arg=0x21034000
        if entry=='callback':r.m.uc.mem_write(arg,r.sent[0][4:])
        if entry=='send':r.m.uc.mem_write(arg,struct.pack('<8I',0x8004b891,0,0,0,0,0,0,0))
        def pause(uc,access,addr,size,value,user):
            if seen:return
            seen.append(True);assert word(r.m,gate(r))==1
            peer_shutdown(r,peer);assert word(r.m,gate(r))==0x80000001
        handle=r.m.uc.hook_add(UC_HOOK_MEM_READ,pause,begin=address,end=address+3)
        r.m.uc.ctl_remove_cache(0x10010000,0x10020000)
        if entry=='wrapper':r.request(0,1)
        elif entry=='callback':r.m.invoke(r.syms['ct_dispatch'],[arg])
        elif entry=='send':assert r.m.invoke(r.syms['ct_queue_send'],[QHANDLE,arg])==0
        else:assert r.scope(0)==0
        r.m.uc.hook_del(handle)
        assert seen==[True] and word(r.m,gate(r))==0x80000000
        assert shutdown(r)==0
    passed('paused_wrapper_callback_sender_and_scope_before_active_load_block_unlink')

    r=DrainRig();peer=DrainRig();finished(r);seen=[]
    # Existing task slot, closed admission, no Request/actor reservation: only
    # the new permanent caller ownership covers this stack cookie lifetime.
    def inside_stock(a):
        if not seen:
            seen.append(True);assert word(r.m,gate(r))==1;peer_shutdown(r,peer)
        return 0
    from verify_record_scheduler import request_setup
    request_setup(r.m,0,1);r.m.hooks[0x8000ac70]=inside_stock
    r.m.invoke(0x80034f40,[0xffffffff])
    assert seen==[True] and word(r.m,gate(r))==0x80000000 and shutdown(r)==0
    passed('ordinary_wrapper_stack_cookie_after_admission_close_is_owned_until_return')

    r=DrainRig();r.block();r.send_result=0xffffffff;r.request();assert r.close()==0
    assert shutdown(r)==11 and word(r.m,gate(r))==0 and word(r.m,T)==ROUTER
    passed('uncertain_old_send_prevents_shutdown_and_keeps_transport_available_for_resolution')

    r=DrainRig();finished(r);old_wire=list(r.sent);assert shutdown(r)==0
    calls=len(r.calls)
    # Entire session region includes Transport, Router, owned Requests, Bridge,
    # Life, Capture and Exchange. Any guest use after fence now faults.
    r.m.uc.mem_protect(STATE,0x20000,UC_PROT_NONE)
    r.m.uc.mem_protect(SLOTS,0x20000,UC_PROT_NONE)
    assert shutdown(r)==0 and r.poll()==12 and r.close()==12
    assert r.scope(0)==12 and r.rr('begin',0xdead0000)==12
    assert r.m.invoke(r.syms['ct_detach_capture'],[T,123])==12
    assert r.m.invoke(r.syms['ct_init'],[T,ROUTER,QHANDLE])==12
    # Closed callbacks do not even inspect stale/unreadable argument storage.
    r.m.invoke(r.syms['ct_dispatch'],[STATE]);r.m.invoke(r.syms['ct_drain_marker'],[STATE])
    r.wire.extend(old_wire);r.dispatch_all()
    from verify_record_scheduler import request_setup
    for address in ENTRIES:
        request_setup(r.m,1,0);r.m.invoke(address,[0xffffffff])
    r.dispatch_all()
    for kind in range(10):r.m.invoke(r.syms['bridge_hook'],[kind,0])
    assert r.step()==12
    cursor=r.cursor;r.block();assert r.cursor==(cursor+64)%r.capacity and len(r.calls)==calls
    assert word(r.m,gate(r))==0x80000000
    passed('protected_entire_session_survives_all_wrappers_replayed_envelopes_direct_entries_and_audio')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Permanent closed gateways and single manager; no reopening/reset/rearm',
        'Only installed transport/hook/worker entries fenced; direct legacy rr/bridge/file APIs require external lifetime ownership',
        'Independent CPUs with explicit shared-state transfer at selected pauses; no full RTOS scheduling',
        'No real SD/DMA completion, cache/timing, physical RAM placement or recovery proof'])
    path=ROOT/'analysis/transport_shutdown_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))
if __name__=='__main__':main()
