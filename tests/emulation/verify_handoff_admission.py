#!/usr/bin/env python3
"""Bounded entry/return audit. Original code runs with modeled side effects.
No admission hook or changed runtime gate is installed by these tests.
"""
import importlib.util,json,struct
from verify_pad_protocol import ROOT,IMAGE,BIAS
from verify_storage_readiness import callees
from verify_overdub_prototype import Emulator
from verify_control_drain import DrainRig
from verify_record_scheduler import word
from verify_control_transport import T

def trigger(entry,result,mode=0,playing=0):
    m=Emulator();events=[]
    end=0x8003f038 if entry==0x8003efb0 else 0x8004b890
    for fn in callees(entry,end):m.hooks[fn]=lambda a:0
    m.hooks[0x800061f0]=lambda a:1
    m.hooks[0x80006238]=lambda a:mode
    m.hooks[0x80002440]=lambda a:playing
    m.hooks[0x80002c60]=lambda a:events.append(('start',a[0],result)) or result
    m.hooks[0x80002d08]=lambda a:events.append(('stop',a[0])) or 0
    for fn in (0x80008430,0x80008428):
        m.hooks[fn]=lambda a,fn=fn:events.append((hex(fn),a[0])) or 0
    m.invoke(entry,[2,0]);return events

def main():
    groups=[]
    def passed(name,**data):groups.append(dict(case=name,**data))
    path=ROOT/'tools/firmware/audit_handoff_admission.py'
    spec=importlib.util.spec_from_file_location('admission_inventory',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.inventory()
    refs=lambda key:{int(r['address'],16) for r in result['entries'][key]['direct_references']}
    assert refs('pad_command_a')=={0x8002d192}
    assert refs('pad_command_b')=={0x8002c730,0x8002c79a,0x8002c7ae,0x8002cac6}
    assert refs('pad_start_restart')=={0x8003efd8,0x8003f016,0x8004b864}
    assert refs('background_scan')=={0x800366f0}
    assert {0x8000c252,0x8000c380,0x8000c3a6}<=refs('card_release')
    assert {0x8000879c,0x80008830,0x80009986,0x80009a8c,0x80009b1c,0x8000ac50}<=refs('detach')
    assert refs('recorder_start_backend')=={0x8004b8c0,0x8004b9f2}
    passed('pinned_image_inventory_covers_flash_and_copied_RAM_and_exposes_independent_entries')

    for entry in (0x8003efb0,0x8004b828):
        for value in (0,1,0xffffffff):
            events=trigger(entry,value)
            assert events==[('start',2,value),('0x80008430',2)]
    passed('both_outer_pad_controls_ignore_start_return_and_continue_side_effects',
           implication='Returning a fabricated BUSY at pad_start does not defer the original command')

    for entry in (0x8003efb0,0x8004b828):
        events=trigger(entry,0,mode=1,playing=1)
        assert events[0]==('stop',2) and not any(e[0]=='start' for e in events)
    passed('same_outer_pad_controls_can_stop_instead_of_start',
           implication='Blocking entire control families can obstruct stop/drain requests')

    r=DrainRig();assert r.close()==0 and r.poll()==10
    r.request(0,entry=0x80034e58)
    assert struct.unpack_from('<I',r.sent[-1])[0]==0x8004b891
    later=r.wire.pop();r.dispatch_all();r.wire.append(later)
    assert r.poll()==0 and len(r.wire)==1 and word(r.m,T+16)==0
    passed('current_capture_drain_acknowledges_earlier_work_while_new_stock_transport_remains_queued',
           implication='The capture-only transport drain cannot be reused as the handoff exclusion gate')

    # Pin the call/return boundaries for which ownership must span a worker body.
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for address,mnemonic,size in ((0x8001078c,'blx',2),(0x80034c20,'blx',2),
                                 (0x800362b4,'blx',2),(0x80036c7c,'bl',4),
                                 (0x80036184,'bl',4)):
        ins=next(md.disasm(IMAGE[address-BIAS:address-BIAS+4],address))
        assert ins.mnemonic==mnemonic and ins.size==size
    passed('audio_and_worker_return_sites_match_original_instruction_lengths')
    out=dict(passed=True,groups=len(groups),results=groups,
             limitations=result['limitations']+['Pad state/side effects, RTOS and queue delivery are modeled.'])
    (ROOT/'analysis/handoff_admission_verification.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(groups),cases=[g['case'] for g in groups]),indent=2))

if __name__=='__main__':main()
