#!/usr/bin/env python3
"""Compiled first-session startup with cold optional-runtime state.

Fixture DSP/files/queues remain synthetic. No device boot or native task creation
is simulated; no host-side optional-session binding is done after the cold reset.
"""
import json
import struct
from elftools.elf.elffile import ELFFile
from unicorn import UC_PROT_NONE, UC_PROT_ALL
from verify_session_manager import ManagerRig, MAN, RESET, PREPARE, ACTIVATE, LIVE, STOPPED, BLOCKED
from verify_session_handover import HandoverRig, DESC
from verify_control_transport import T, QHANDLE
from verify_request_router import ROUTER
from verify_emulator_bridge import BR
from verify_block_exchange import P, SLOTS
from verify_extra_capture import ELF, STATE
from verify_extra_lifecycle import LIFE
from verify_record_scheduler import word
from verify_pad_protocol import ROOT


class ColdRig(ManagerRig):
    def __init__(self, count=32):
        # Reuse the modeled hardware/file/queue plumbing. Discard its optional
        # session before constructing the cold state used by every test below.
        HandoverRig.__init__(self)
        assert self.life('life_cancel_quiesced')==16 and not self.opened
        self.disk={};self.calls=[];self.counts={};self.wire=[];self.sent=[]
        with ELF.open('rb') as f:
            elf=ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type']=='PT_LOAD' and seg['p_flags']&2:
                    self.m.uc.mem_write(seg['p_vaddr'],bytes(seg['p_memsz']))
                    if seg['p_filesz']:self.m.uc.mem_write(seg['p_vaddr'],seg.data())
        self.mlayout=struct.unpack('<7I',self.raw(self.syms['manager_layout'],28))
        n=count*self.xlayout[1]
        if n>0x20000:self.m.uc.mem_map(SLOTS+0x20000,((n+4095)&~4095)-0x20000)
        names=('ct_layout','rr_layout','bridge_layout','exchange_layout','life_layout','extra_layout')
        addresses=(T,ROUTER,BR,P,LIFE,STATE)
        self.arenas=[(a,word(self.m,self.syms[name])) for a,name in zip(addresses,names)]+[(SLOTS,n)]
        # Owned arenas intentionally start dirty. Only compiled RESET may clear.
        for a,size in self.arenas:self.m.uc.mem_write(a,b'\xa5'*size)
        self.m.uc.mem_write(MAN,bytes(self.mlayout[0]))
        self.m.uc.mem_write(DESC,struct.pack('<10I',*addresses,SLOTS,count,123,QHANDLE))
        assert word(self.m,self.syms['ct_active'])==0
        assert word(self.m,self.syms['emulator_bridge_current'])==0

    def boot(self,pad=0,serial=1):
        return self.m.invoke(self.syms['manager_boot'],[MAN,DESC,pad,serial])

    def ready(self):self.drive(lambda:self.mstate()==LIVE)


def main():
    results=[]
    def passed(case,**kw):results.append(dict(case=case,**kw))

    r=ColdRig(4096);before=list(r.calls)
    assert r.boot()==0 and r.mstate()==RESET and r.calls==before
    for name in ('ct_gateway_readers','bridge_gateway_readers'):
        assert word(r.m,r.syms[name])==0x80000000
    assert not r.opened
    # Ordinary audio/control can run while optional storage is still dirty.
    slot_pages=(4096*r.xlayout[1]+4095)&~4095
    r.m.uc.mem_protect(STATE,0x20000,UC_PROT_NONE)
    r.m.uc.mem_protect(SLOTS,slot_pages,UC_PROT_NONE)
    try:r.audio_call();r.request(1);r.dispatch_all()
    finally:
        r.m.uc.mem_protect(STATE,0x20000,UC_PROT_ALL)
        r.m.uc.mem_protect(SLOTS,slot_pages,UC_PROT_ALL)
    assert not r.calls
    r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    assert r.tick()==11 and word(r.m,r.syms['ct_active'])==0
    r.audio_call();assert r.tick()==0 and r.mstate()==LIVE
    assert r.session==123 and word(r.m,P+4)==4095
    first=r.take(2);second=r.take(3)
    assert bytes(r.disk[first[1]])==first[2] and r.result()==second[:2]
    r.assert_ordinary()
    passed('cold_4096_slot_boot_defers_optional_admission_then_records_two_exact_takes')

    # Wrong descriptors must be rejected before closing gateways or doing IO.
    for field,value in ((7,3),(7,8192),(8,0),(9,0),(6,SLOTS+4),(0,STATE)):
        r=ColdRig();r.m.uc.mem_write(DESC+4*field,struct.pack('<I',value))
        assert r.boot()==12 and r.mstate()==0 and not r.calls
        assert word(r.m,r.syms['ct_gateway_readers'])==0
        assert word(r.m,r.syms['bridge_gateway_readers'])==0
    for pad,serial in ((4,1),(0,0)):
        r=ColdRig();assert r.boot(pad,serial)==12 and not r.calls
    r=ColdRig();r.m.uc.mem_write(MAN+4,struct.pack('<I',1))
    assert r.boot()==12 and not r.calls
    passed('invalid_spans_counts_queue_session_pad_serial_and_dirty_manager_rejected')

    r=ColdRig();assert r.boot()==0
    before=r.raw(MAN,r.mlayout[0]);assert r.boot()==12
    assert r.raw(MAN,r.mlayout[0])==before
    r.ready();before=r.raw(MAN,r.mlayout[0]);assert r.boot()==12
    assert r.raw(MAN,r.mlayout[0])==before
    passed('duplicate_boot_cannot_reset_pending_or_live_manager')

    for boundary in (RESET,ACTIVATE):
        r=ColdRig();assert r.boot()==0
        r.drive(lambda:r.mstate()==boundary,with_audio=False)
        r.cancel();r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
        assert not r.opened and word(r.m,r.syms['ct_active'])==0
        assert r.resume()==0;r.ready();r.take(1)
    passed('cancel_before_first_activation_needs_no_audio_and_resume_can_start')

    r=ColdRig();assert r.boot()==0;r.inject=('create',1,'error')
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert word(r.m,MAN+4)==13 and not r.opened
    assert word(r.m,r.syms['ct_active'])==0
    r.inject=None;assert r.resume()==0;r.ready();r.take(1)
    passed('first_file_creation_failure_stays_closed_until_explicit_resume')

    r=ColdRig();assert r.boot()==0
    r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    r.audio_call(mode=1)
    r.drive(lambda:r.mstate()==STOPPED,with_audio=False)
    assert not r.opened and word(r.m,r.syms['ct_active'])==0
    assert r.resume()==0;r.ready();r.take(1)
    passed('first_audio_failure_can_retire_and_retry_before_control_ever_opens')

    r=ColdRig();assert r.boot()==0
    r.drive(lambda:r.mstate()==ACTIVATE,with_audio=False)
    r.inject=('close_write',1,'error');r.cancel()
    r.drive(lambda:r.mstate()==BLOCKED,with_audio=False)
    assert r.resume()==12 and word(r.m,r.syms['ct_active'])==0
    passed('uncertain_first_file_close_blocks_reuse')

    report=dict(passed=True,groups=len(results),results=results,
                limits=['Cold state of optional runtime only, not the entire mixer',
                        'Synthetic owned RAM, file API, DSP and scheduler/queue delivery',
                        'Existing native queue must be supplied; native worker creation not implemented',
                        'Boot entry requires exclusive initialization before hooks/callers can enter',
                        'No firmware transferred or installed'])
    (ROOT/'analysis/manager_boot_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(results))))


if __name__=='__main__':main()
