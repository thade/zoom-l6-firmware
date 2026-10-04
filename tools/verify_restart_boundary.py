#!/usr/bin/env python3
"""Negative control: forcibly reopening gateways is NOT a restart protocol.

Private fixture writes bypass the shipped closed-gateway guard. Demonstrates
that a new generation rejects old envelopes but cannot identify late raw taps.
"""
import hashlib,json,struct
from verify_transport_shutdown import DrainRig,finished,shutdown,gate
from verify_control_transport import T,QHANDLE
from verify_request_router import ROUTER
from verify_emulator_bridge import BR
from verify_block_exchange import P,SLOTS,OBS
from verify_extra_capture import STATE,ELF
from verify_extra_lifecycle import LIFE
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

def force_fresh(r):
    # UNSUPPORTED TEST-ONLY reset. There is deliberately no product API for it.
    r.m.uc.mem_write(STATE,bytes(0x20000))
    put32(r.m,gate(r),0);put32(r.m,r.syms['bridge_gateway_readers'],0)
    r.observe();assert r.xcall('exchange_init',SLOTS,32,OBS)==0
    assert r.life('life_prepare',0,2)==0
    put32(r.m,BR+12,124)
    assert r.m.invoke(r.syms['bridge_bind'],[BR,P,LIFE,STATE])==0
    assert r.m.invoke(r.syms['rr_init'],[ROUTER,BR,124])==0
    assert r.m.invoke(r.syms['ct_init'],[T,ROUTER,QHANDLE])==0

def main():
    r=DrainRig();finished(r);oldwire=list(r.sent)
    # Old outer hook returns; its ordinary DSP invocation could be paused
    # between that hook and its later tap/commit sites.
    r.m.invoke(r.syms['bridge_hook'],[0,0]);assert shutdown(r)==0
    force_fresh(r)
    before=r.raw(T,r.tlayout[0]);callbacks=len(r.callback_args)
    r.wire.extend(oldwire);r.dispatch_all()
    assert r.raw(T,r.tlayout[0])==before and len(r.callback_args)==callbacks
    # Resume the OLD invocation at its untagged tap. It carries no session ID.
    # New exchange accepts its samples without any new-session outer hook.
    left=0x20013e00;right=0x20013f00
    r.m.uc.mem_write(left,struct.pack('<64f',*([12345.0]*64)))
    r.m.uc.mem_write(right,struct.pack('<64f',*([-12345.0]*64)))
    r.m.invoke(r.syms['bridge_hook'],[1,0])
    assert word(r.m,P+16)==1 and word(r.m,P+20)==1 and word(r.m,BR+16)==0
    assert r.raw(SLOTS+r.xlayout[2],256)==struct.pack('<64f',*([12345.0]*64))
    results=[dict(case='old_generation_envelopes_rejected_after_forced_same_address_rebind',passed=True),
      dict(case='negative_control_late_untagged_audio_tap_joins_new_generation_after_naive_reopen',passed=True,
           observed_defect=True)]
    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Deliberately bypasses closed gateways using fixture memory writes; NOT a supported restart',
        'Models an old DSP invocation paused between separate hooks; complete DSP invocation scheduling remains unbound',
        'Demonstrates generation ambiguity; does not establish an audible corruption scenario or hardware behavior'])
    path=ROOT/'analysis/restart_boundary_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),observed_defect=True,report=str(path)),indent=2))
if __name__=='__main__':main()
