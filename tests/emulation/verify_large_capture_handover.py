#!/usr/bin/env python3
"""Large capture rings are prepared by the worker; audio adoption stays bounded.

Uses synthetic memory/DSP/files. Counts executed instructions, not device time.
"""
import json
import struct
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from verify_session_manager import ManagerRig, MAN, RESET, ACTIVATE, LIVE, STOPPED
from verify_block_exchange import P, SLOTS, OBS
from verify_pad_protocol import ROOT
from verify_record_scheduler import word


def begin_cost(count):
    r=ManagerRig(slot_count=count)
    size=r.xlayout[1]
    r.m.uc.mem_write(SLOTS,b'\xa5'*(count*size))
    assert r.xcall('exchange_prepare',SLOTS,count)==0
    for index in range(count):
        assert word(r.m,SLOTS+index*size)==0
        assert r.raw(SLOTS+index*size+4,4)==b'\xa5'*4
    # Preparation alone must not publish usable sample history.
    r.key(0)
    assert r.xcall('exchange_claim',OBS+32,OBS+64)==18
    instructions=[];slot_writes=[]
    code=r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,s,u:instructions.append(a))
    writes=r.m.uc.hook_add(UC_HOOK_MEM_WRITE,
        lambda uc,access,a,s,v,u:slot_writes.append((a,s)),begin=SLOTS,end=SLOTS+count*size-1)
    assert r.xcall('exchange_begin',OBS)==0
    r.m.uc.hook_del(code);r.m.uc.hook_del(writes)
    assert not slot_writes
    # The same preparation cannot reset a live exchange for a second time.
    before=r.raw(P,r.xlayout[0])
    assert r.xcall('exchange_begin',OBS)==12
    assert r.raw(P,r.xlayout[0])==before
    return len(instructions)


def main():
    costs={n:begin_cost(n) for n in (2,32,4096)}
    assert len(set(costs.values()))==1, costs
    results=[dict(case='constant_begin_work_no_slot_writes_and_single_use_preparation',instructions=costs)]

    r=ManagerRig(slot_count=4096)
    r.audio_call()
    first=r.take(2)
    # This includes manager RESET, worker staging, audio adoption and activation.
    assert word(r.m,P+4)==4095
    second=r.take(3)
    assert bytes(r.disk[first[1]])==first[2]
    assert r.result()==second[:2] and r.result(1)==first[:2]
    results.append(dict(case='large_ring_manager_rearms_and_preserves_two_complete_takes'))

    # Observe the entire first audio callback after a worker prepares a large ring.
    r.request();r.dispatch_all();r.audio_call();r.tick();r.request(1);r.dispatch_all()
    r.drive(lambda:r.mstate()==RESET,with_audio=False)
    size=r.xlayout[1]
    cleared=[];reset_steps=[];prepared=[]
    payload_before=[r.raw(SLOTS+i*size+4,size-4) for i in range(4096)]
    hook=r.m.uc.hook_add(UC_HOOK_MEM_WRITE,
        lambda uc,access,a,s,v,u:cleared.append((a,s)),begin=SLOTS,end=SLOTS+4096*size-1)
    for _ in range(1024):
        if r.mstate()==ACTIVATE:break
        state=r.mstate();cleared.clear();r.tick()
        if state==RESET:
            assert not cleared
            reset_steps.append(1)
        else:prepared.extend(cleared)
    r.m.uc.hook_del(hook)
    assert r.mstate()==ACTIVATE and prepared==[(SLOTS+i*size,4) for i in range(4096)]
    assert [r.raw(SLOTS+i*size+4,size-4) for i in range(4096)]==payload_before
    touched=[]
    hook=r.m.uc.hook_add(UC_HOOK_MEM_WRITE,
        lambda uc,access,a,s,v,u:touched.append((a,s)),begin=SLOTS,end=SLOTS+4096*size-1)
    r.audio_call()
    r.m.uc.hook_del(hook)
    assert touched and all(SLOTS<=a and a+s<=SLOTS+size for a,s in touched)
    assert r.tick()==0 and r.mstate()==LIVE
    results.append(dict(case='reset_preserves_payload_prepare_resets_ownership_then_first_audio_writes_only_first_slot',
                        reset_steps=len(reset_steps),reset_slot_bytes=0,prepare_slot_bytes=sum(s for _,s in prepared),
                        avoided_bulk_clear_bytes=4096*size,retained_sample_bytes=4096*512,slot_writes=len(touched)))

    # Cancel during multi-step clearing; never publish the partially reset ring.
    r.request();r.dispatch_all();r.audio_call();r.tick();r.request(1);r.dispatch_all()
    r.drive(lambda:r.mstate()==RESET,with_audio=False)
    r.tick()
    assert r.mstate()==RESET
    r.cancel();r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert not r.opened and word(r.m,r.syms['emulator_bridge_current'])==0
    assert r.resume()==0
    r.drive(lambda:r.mstate()==LIVE)
    r.take(1)
    results.append(dict(case='cancel_partway_through_large_reset_then_resume_and_record'))

    r=ManagerRig()
    before=r.raw(SLOTS,0x20000)
    for pointer,count in ((SLOTS,0),(SLOTS,1),(SLOTS,3),(SLOTS,8192),
                          (SLOTS+4,32),(0xfffffff8,4096)):
        assert r.xcall('exchange_prepare',pointer,count)==12
        assert r.raw(SLOTS,0x20000)==before
    # Unsupported audio mode consumes preparation and leaves capture faulted.
    assert r.xcall('exchange_prepare',SLOTS,32)==0
    r.m.uc.mem_write(OBS+8,struct.pack('<I',0))
    assert r.xcall('exchange_begin',OBS)==18
    r.observe()
    assert r.xcall('exchange_begin',OBS)==12
    results.append(dict(case='invalid_counts_alignment_overflow_and_bad_mode_rejected'))

    footprint={name:word(r.m,r.syms[name]) for name in
               ('ct_layout','rr_layout','bridge_layout','exchange_layout','life_layout','extra_layout','manager_layout')}
    footprint['slots']=4096*r.xlayout[1]
    footprint['subtotal']=sum(footprint.values())
    report=dict(passed=True,groups=len(results),results=results,footprint=footprint,
                slot_bytes=4096*r.xlayout[1],frames=4096*64,seconds_at_48k=4096*64/48000,
                limits=['Synthetic owned RAM, DSP, filesystem and scheduling',
                        'Instruction counts are not device latency measurements',
                        'No physical buffer address selected or firmware staged'])
    (ROOT/'analysis/large_capture_handover_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(results),begin_instructions=costs,slot_bytes=report['slot_bytes'])))


if __name__=='__main__':main()
