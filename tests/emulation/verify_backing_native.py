#!/usr/bin/env python3
"""Review regression tests: original loader/prefetch/close instructions execute.
Storage, RIFF parsing, conversion, fencing and rename are modeled. No hardware.
"""
import json,struct
from unicorn.arm_const import UC_ARM_REG_LR,UC_ARM_REG_R4
from verify_simple_handoff import Simple,H,HP,NATIVE,GATE
from verify_stock_pad_adapter import SETTINGS
from verify_firmware_workflow import put32
from verify_session_manager import MAN
from verify_pad_protocol import IMAGE,BIAS

def word(r,p):return struct.unpack('<I',r.m.uc.mem_read(p,4))[0]
def retained(r):
    n=word(r,NATIVE+r.nlayout[2])
    return list(struct.unpack('<'+str(n)+'I',r.m.uc.mem_read(NATIVE+r.nlayout[3],n*4)))
def blocked(r):
    assert r.locked and word(r,H+r.layout[2])==1
    assert r.m.invoke(r.syms['manager_step'],[MAN])==11
    before=(dict(r.counts),dict(r.handles),r.paths(),len(r.prefetch_reads),r.seals)
    assert r.step()==10
    assert before==(dict(r.counts),dict(r.handles),r.paths(),len(r.prefetch_reads),r.seals)

def fail_close(r,predicate,number=1):
    """Fail the REAL public-close early branch, before it calls the driver.
    Unlike the older fixture, the handle remains allocated and readable.
    """
    seen=[];failed=[]
    def lock(a):
        if r.m.uc.reg_read(UC_ARM_REG_LR)!=0x8005c305:return 0
        h=r.m.uc.reg_read(UC_ARM_REG_R4);path=r.handles[h][0]
        if predicate(path):
            seen.append(h)
            if len(seen)==number:
                put32(r.m,0x801f91c0+0xa8,0xffffd825);failed.append(h);return 1
        return 0
    r.m.hooks[0x80001848]=lock
    return failed

def main():
    groups=[]
    def passed(s):groups.append(s)
    # Verify the actual trampoline entry against the pinned vendor image.
    assert IMAGE[0x8005c1f8-BIAS:0x8005c200-BIAS]==bytes.fromhex('2de9f04786b00446')
    r=Simple();assert r.step()==0
    path=r.paths()[0];data=bytes(r.files[path][512:])
    assert r.converted[-1]==(0,data) and r.prefetch_reads==[(path,len(data))]
    assert len(data)%512==0
    r.next()
    # Model a valid song ending one stereo frame before a capture block edge.
    tmp=r.capture.result()[1];raw=r.files[tmp];del raw[-8:]
    struct.pack_into('<I',raw,4,len(raw)-8);struct.pack_into('<I',raw,508,len(raw)-512)
    assert r.step()==0
    path=r.paths()[0];data=bytes(r.files[path][512:])
    assert len(data)%512!=0 and r.converted[-1]==(0,data)
    assert r.prefetch_reads[-1]==(path,len(data))
    assert word(r,0x80735180+0x32c)==0x80036209
    passed('real_prefetch_uses_checked_synchronous_read_and_accepts_exact_final_partial_block')

    for kind in ('error','short'):
        r=Simple();assert r.step()==0;r.next();old=r.paths();old_data=bytes(r.files[old[0]][512:])
        r.read_failures=[kind]
        assert r.step()==7 and r.paths()==old and not r.locked
        assert r.converted[-1]==(0,old_data)
        assert r.m.invoke(r.syms['manager_step'],[MAN])==10
        assert not retained(r)
    passed('failed_or_short_initial_read_rolls_back_with_a_verified_read_of_the_previous_backing')

    for kind in ('error','short'):
        r=Simple();assert r.step()==0;r.next();r.read_failures=[kind,kind]
        assert r.step()==10;blocked(r)
    passed('failed_or_short_rollback_read_cannot_release_the_fence')

    r=Simple();assert r.step()==0;r.next();r.read_failures=[None,'error']
    r.counts={};r.fail=('settings_write',2,'short')
    assert r.step()==10;blocked(r)
    passed('settings_write_failure_requires_verified_rollback_audio_before_release')

    r=Simple();r.m.hooks[0x800369a8]=lambda a:0
    assert r.step()==7 and not r.locked and not r.prefetch_reads
    r=Simple();assert r.step()==0;r.next();r.m.hooks[0x800369a8]=lambda a:0
    assert r.step()==10;blocked(r)
    passed('stubbed_or_skipped_prefetch_cannot_falsely_verify_assignment_or_rollback')

    for number in (1,2):
        r=Simple();assert r.step()==0;r.next();r.counts={}
        failed=fail_close(r,lambda path:path==SETTINGS,number)
        assert r.step()==10;blocked(r)
        assert len(failed)==1 and retained(r)==failed
        h=failed[0];assert h in r.handles and r.m.uc.mem_read(h,1)==b'\x40'
        assert r.counts['settings_write']==2 # no second save or rollback
        assert r.counts['settings_open']==number
    passed('settings_write_and_readback_close_errors_retain_open_handle_without_retry_or_release')

    r=Simple();failed=fail_close(r,lambda path:path.endswith('.WAV'))
    assert r.step()==10;blocked(r)
    assert failed and failed[0] in retained(r) and failed[0] in r.handles
    passed('stock_loader_prevalidation_close_failure_is_observed_even_if_stock_ignores_it')

    r=Simple();assert r.step()==0;old=r.paths()[0];r.next()
    failed=fail_close(r,lambda path:path==old)
    assert r.step()==10;blocked(r)
    assert failed and failed[0] in retained(r) and failed[0] in r.handles
    passed('old_sample_unload_close_failure_is_retained_before_new_backing_can_be_activated')

    r=Simple();assert r.step()==0;r.next();r.read_failures=['error']
    new=r.capture.result()[1][:-3]+'WAV'
    failed=fail_close(r,lambda path:path==new,2)
    assert r.step()==10;blocked(r)
    assert failed and failed[0] in retained(r) and failed[0] in r.handles
    passed('rollback_unload_close_failure_retains_ownership_and_blocks_release')

    r=Simple();put32(r.m,0x80735180+0x32c,0x12345679)
    assert r.step()==10;blocked(r)
    passed('unexpected_read_callback_is_not_overwritten_or_treated_as_safe')

    r=Simple();r.m.uc.mem_write(0x8005c1f8,IMAGE[0x8005c1f8-BIAS:0x8005c200-BIAS])
    r.m.uc.ctl_remove_cache(0x8005c1f8,0x8005c208)
    assert r.m.invoke(r.syms['bn_init'],[NATIVE+0x200,GATE,HP])==2
    assert r.step()==10 and not r.seals
    passed('native_adapter_requires_close_interception_before_it_can_acquire_the_gate')

    print(json.dumps(dict(passed_groups=len(groups),cases=groups),indent=2))

if __name__=='__main__':main()
