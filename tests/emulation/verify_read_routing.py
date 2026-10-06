#!/usr/bin/env python3
"""Compiled read routing through original prefetch call sites; no device IO."""
import json
import struct
from unicorn.arm_const import UC_ARM_REG_PC
from verify_read_callback import CallbackRig
from verify_read_producer import T0, T1, IDS
from verify_read_worker import CURRENT
from verify_reload_read_queue import READ, SECOND, MAGIC
from verify_reload_prefetch import READ_SEM
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_work_ownership import OK
from verify_pad_protocol import ROOT


class RoutedRig(CallbackRig):
    def redirect(self,uc,address,size,user):
        # Every callback entry takes the same compiled dispatcher. The fixture
        # does not select a tracked vs ordinary target or manufacture caller LR.
        self.callback_entries.append(self.word(CURRENT))
        uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rp_read_entry']|1)
    def wait_native(self,a):
        if a[0]!=READ_SEM:return 1
        # Scheduler behavior follows the actual packet, not the desired route.
        self.ordinary=struct.unpack('<4I',self.p.sent[-1])[0]!=MAGIC
        self.p.waits.append(self.word(CURRENT))
        if self.ordinary:self.suspended=True;stop(self.m)
        return self.p.wait_result
    def inactive(self,phase=0):
        for task in (T0,T1):
            put32(self.m,task,0);put32(self.m,task+4,phase)


def exact(r):
    assert len(r.converted)==8
    for pad,data in r.converted:
        raw=r.files[r.expected[pad]]
        assert data==bytes(raw[raw.find(b'data')+8:])


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    r=RoutedRig();r.run();r.consume();exact(r)
    assert r.callback_entries==[IDS[0]]*4+[IDS[1]]*4
    assert all(struct.unpack('<4I',p)[0]==MAGIC for p in r.p.sent)
    assert r.p.end()==OK
    passed('actual_caller_LR_and_native_identity_route_eight_live_reload_reads_to_tracking')

    r=RoutedRig();r.run()
    handle=r.word(0x80735b24);path,_=r.handles[handle]
    offset=r.files[path].find(b'data')+8;r.handles[handle][1]=offset
    # Execute the real carry-path BLX with fixture arguments, and stop at its
    # immediate continuation. This is not a complete carry-buffer DSP test.
    returned=[]
    r.m.hooks[0x80036b0e]=lambda a:returned.append(a[0]) or stop(r.m)
    r.execute(0x80036b0c,[0,0x21010000,16,0x80036209],0)
    assert returned==[1]
    assert struct.unpack('<4I',r.p.sent[-1])[0]==MAGIC and r.word(READ+4)==7
    assert bytes(r.m.uc.mem_read(0x21010000,16))==bytes(r.files[path][offset:offset+16])
    passed('original_carry_path_BLX_supplies_the_second_accepted_return_address')

    for phase in (0,5): # RT_IDLE and RT_DONE (old tags intentionally retained).
        r=RoutedRig();r.inactive(phase);r.run();r.consume();exact(r)
        assert len(r.callback_entries)==8 and r.word(READ+4)==r.word(SECOND+4)==0
        assert all(struct.unpack('<4I',p)[0]==0 for p in r.p.sent)
    passed('idle_and_completed_native_reload_tasks_use_stock_callback_without_read_tickets')

    r=RoutedRig()
    r.p.select=lambda role:put32(r.m,CURRENT,0x7999)
    r.run();r.consume();exact(r)
    assert len(r.callback_entries)==8 and r.word(READ+4)==r.word(SECOND+4)==0
    assert all(struct.unpack('<4I',p)[0]==0 for p in r.p.sent)
    passed('different_native_task_keeps_stock_reads_even_while_reload_scopes_exist')

    for offset,value in ((0,0),(4,0),(4,1),(8,0),(12,0)):
        r=RoutedRig();put32(r.m,T0+offset,value);r.run()
        assert not r.p.sent and not r.converted and r.p.word()&0x40000000
    passed('malformed_or_transitional_reload_state_is_never_downgraded_to_ordinary')

    for address,value in ((0x80446dc8,0x7999),(0x80446da4,0x7999),
                          (0x801f8f30,0x7999),(0x804467fc,0x7999)):
        r=RoutedRig();put32(r.m,address,value);r.run()
        assert not r.p.sent and not r.converted and r.p.word()&0x40000000
    passed('changed_native_bindings_fault_before_any_read_submission')

    r=RoutedRig();r.execute(0x80036208,[0,0x21010000,16],0)
    assert not r.p.sent and r.p.word()&0x40000000
    passed('unsupported_origin_inside_live_reload_cannot_escape_tracking_through_stock_path')

    r=RoutedRig();assert r.p.begin_read_request(0)==OK
    r.inactive();r.execute(0x80036208,[0,0x21010000,16],0)
    assert not r.p.sent and r.p.word()&0x40000000
    passed('retained_read_prevents_ordinary_fallback_even_if_enclosing_task_is_marked_idle')

    r=RoutedRig();r.inactive()
    assert r.execute(0x80036208,[4,0x21010000,16],0)==4
    assert r.execute(0x80036208,[2,0,16],0)==2
    assert not r.p.sent and not r.p.waits and not r.p.word()&0x40000000
    passed('stock_forwarder_preserves_invalid_pad_and_null_buffer_early_returns_without_recursion')

    out=ROOT/'analysis/read_routing_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Every observed stock callback entry redirects to compiled assembly and C routing; no fixture route selection',
        'Both original BLX sites supply LR; carry-site test supplies its arguments and stops before subsequent DSP',
        'Outer reload scopes, native task switching, kernel effects, files and conversion remain fixtures',
        'Ordinary routing preserves behavior, not card/file ownership or exclusion from other readers',
        'Cold installation and shared binding to actual reload ingress remain unimplemented; no live cutover proof',
        'Fault policy parks callers and may stall stock work; no device access or installed patch']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
