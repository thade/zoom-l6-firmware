#!/usr/bin/env python3
"""Public close guard before stock filesystem locking; all effects offline."""
import json
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_pad_file import Native, Guarded, OUT
from verify_read_ingress import CTX
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, RETURN
from verify_work_ownership import OK, BUSY, CONFLICT, STALE


def install(r):
    def redirect(uc,a,n,u):uc.reg_write(UC_ARM_REG_PC,r.m.symbols['pf_close']|1)
    r.m.uc.hook_add(UC_HOOK_CODE,redirect,begin=0x8005c1f8,end=0x8005c1f8)


def resume(r,context):
    r.m.uc.context_restore(context);r.m.reached_return=False
    r.m.uc.emu_start(r.m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=10000000)
    assert r.m.reached_return


def begin(r,handle,owner=0x7999):
    assert r.pf('close_begin',handle,owner,OUT)==OK
    return r.word(OUT)


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    r=Guarded();install(r);owner=r.run()
    assert r.reads==8 and r.verify(owner) and r.retire()==OK
    passed('public_close_guard_nests_inside_guarded_original_unload_and_complete_reload')

    r=Native();install(r);handle,pin=r.pin();closes=r.counts.get('close',0)
    locks=[];r.m.hooks[0x8001bf88]=lambda a:locks.append(a[0]) or 0
    r.m.invoke(0x8005c1f8,[handle]);context=r.m.uc.context_save()
    assert not locks and handle in r.handles and r.counts.get('close',0)==closes
    # The waiting close has not taken the locks that the original public read
    # will acquire. Execute that public read before retiring the modeled pin.
    path,_=r.handles[handle];offset=r.files[path].find(b'data')+8
    r.handles[handle][1]=offset;r.sync(handle)
    assert r.m.invoke(0x80060620,[handle,OUT+64,16,OUT+32])==0
    assert r.word(OUT+32)==16 and locks
    assert r.pf('drop',0,pin)==OK
    resume(r,context)
    assert handle not in r.handles and r.counts.get('close',0)==closes+1
    assert r.pf('pin',CTX,0,0,OUT)==CONFLICT
    passed('pinned_close_waits_before_stock_lock_calls_allowing_the_original_read_to_finish')

    r=Native();install(r);handle=r.word(0x807348d4)
    r.fail=('close',r.counts.get('close',0)+1,'error')
    assert r.m.invoke(0x8005c1f8,[handle])==0xffffd825
    assert r.pf('pin',CTX,0,0,OUT)==CONFLICT
    r.fail=None;r.m.invoke(0x800092a0,[0,0])
    _,pin=r.pin();assert r.pf('drop',0,pin)==OK
    passed('close_error_is_returned_unchanged_and_pad_admission_requires_a_fresh_guarded_load')

    r=Native();install(r);handle=r.word(0x807348d4);closes=r.counts.get('close',0)
    original=r.m.hooks[0x8005c388];latch=r.m.symbols['pad_files']+8
    def hold(a):
        result=original(a);put32(r.m,latch,1);return result
    r.m.hooks[0x8005c388]=hold
    r.m.invoke(0x8005c1f8,[handle]);context=r.m.uc.context_save()
    assert r.counts.get('close',0)==closes+1
    put32(r.m,latch,0);resume(r,context)
    assert r.counts.get('close',0)==closes+1 and r.pf('pin',CTX,0,0,OUT)==CONFLICT
    passed('busy_close_completion_retries_metadata_without_repeating_original_close')

    r=Native();handle=r.word(0x807348d4);token=begin(r,handle)
    assert r.pf('pin',CTX,0,0,OUT)==BUSY and r.pf('change_begin',0,0x7888)==BUSY
    assert r.pf('close_end',handle,0x7888,token)==CONFLICT
    assert r.pf('close_end',handle,0x7999,token)==OK
    assert r.pf('close_end',handle,0x7999,token)==STALE
    assert r.pf('pin',CTX,0,0,OUT)==CONFLICT
    passed('close_reservation_excludes_new_reads_and_mutation_and_rejects_wrong_or_stale_completion')

    r=Native();handle=r.word(0x807348d4)
    assert r.pf('change_begin',0,0x7999)==OK
    assert r.pf('close_begin',handle,0x7888,OUT)==BUSY
    token=begin(r,handle)
    assert r.pf('close_end',handle,0x7999,token)==OK
    assert r.pf('pin',CTX,0,0,OUT)==BUSY # Outer mutation is still held.
    assert r.pf('change_end',0,0x7999)==OK
    assert r.pf('pin',CTX,0,0,OUT)==CONFLICT
    passed('nested_close_does_not_release_outer_mutation_or_clear_read_revocation')

    r=Native();tickets=[begin(r,0x1000+16*i) for i in range(8)]
    assert r.pf('close_begin',0x2000,0x7999,OUT)==BUSY
    assert r.pf('close_end',0x1000,0x7999,tickets[0])==OK
    fresh=begin(r,0x1000)
    assert fresh>tickets[-1] and r.pf('close_end',0x1000,0x7999,tickets[0])==STALE
    assert r.pf('close_end',0x1000,0x7999,fresh)==OK
    passed('bounded_close_slots_and_nonreused_tokens_prevent_old_completion_releasing_new_work')

    r=Native();install(r);handle=r.word(0x807348d4)
    put32(r.m,0x807348d4+0x22c,handle);put32(r.m,0x80735b24+20,handle)
    r.m.invoke(0x8005c1f8,[handle])
    assert r.pf('pin',CTX,0,0,OUT)==CONFLICT and r.pf('pin',CTX,1,1,OUT)==CONFLICT
    r.m.invoke(0x800092a0,[0,0]);_,pin=r.pin()
    assert r.pf('drop',0,pin)==OK and r.pf('pin',CTX,1,1,OUT)==CONFLICT
    passed('direct_close_revokes_all_linked_pads_and_reload_reopens_only_its_own_admission')

    r=Native();handle=r.word(0x807348d4);token=begin(r,handle)
    put32(r.m,0x807348d4+0x22c,handle);put32(r.m,0x80735b24+20,handle)
    assert r.pf('pin',CTX,1,1,OUT)==BUSY
    assert r.pf('close_end',handle,0x7999,token)==OK
    assert r.pf('pin',CTX,1,1,OUT)==CONFLICT
    passed('handle_association_published_during_close_is_revoked_before_close_reservation_releases')

    out=ROOT/'analysis/pad_close_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Public close guard executes before original close lock calls; RTOS lock effects are fixture supplied',
        'This removes one lock-inversion boundary, not a complete caller or deadlock audit',
        'Only tracked reads use pins; ordinary/refill reads, seeks and card teardown remain uncovered',
        'Public close hooks and guarded loader publication must activate together; lower/direct bypasses remain possible',
        'No device IO, installed firmware, physical allocation, IRQ timing or startup release']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
