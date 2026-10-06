#!/usr/bin/env python3
"""Inventory bounded v1.10 handoff admission references; never modifies firmware.

Direct branches are search leads, not proof of all callers or safe hook sites.
Copied RAM is decoded at its runtime address. Indirect dispatch is listed
separately using previously executed instruction evidence.
"""
import hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS

ROOT=Path(__file__).resolve().parents[2]
BIAS=0x80000e00
SHA='64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
TARGETS={
    'pad_command_a':0x8003f4d8,'pad_command_b':0x800408b0,
    'pad_control_a':0x8003efb0,'pad_control_b':0x8004b828,'pad_start_restart':0x80002c60,
    'background_scan':0x80036508,'initial_or_refill_prefetch':0x800369a8,
    'sample_read_producer':0x80036208,'sample_seek_producer':0x80036250,
    'record_request':0x80034f40,'play_request':0x80034e58,
    'stop_request':0x80034d18,'stop_argument':0x80035038,'stop_other':0x800350d8,
    'record_enqueue':0x8004b6d8,'play_enqueue':0x8004b698,'stop_enqueue':0x8004b718,
    'recorder_start_backend':0x8000b650,'recorder_stop_backend':0x8000b698,
    'recorder_postprocess':0x800032b0,'recorder_reopen_tail':0x800035d0,
    'assignment_request':0x80008c68,'reload_request':0x80008d68,
    'reload_ui_body':0x80008b68,'catalogue_scan':0x800082c0,
    'directory_setup':0x80009938,'card_setup':0x80009a40,'card_release':0x80009b18,
    'mount':0x8005fc98,'detach':0x80062230,
    'usb_enter':0x8000c220,'usb_leave':0x8000c288,'usb_other':0x8000c2d8,
    'usb_request':0x8003b7e0,'usb_stop_request':0x8003b8a0,
}
INDIRECT=[
    dict(domain='audio',dispatch='0x8001078c',returned='0x8001078e',
         identity='loaded callback plus invocation generation',
         completion='Whole invocation return; must also exclude future readers and mode changes'),
    dict(domain='recorder_control',dispatch='0x80034c20',returned='0x80034c22',
         queue_slot='0x801f8f38',identity='32-byte callback packet; no stock request generation',
         completion='Whole session, producer/file children, closes and postprocessing tail, then callback return'),
    dict(domain='assignment',dispatch='0x800362b4',returned='0x800362b6',
         queue_slot='0x801f8f3c',identity='32-byte callback packet; assignment contains borrowed path pointer',
         completion='Worker return AND event consumer 0x8002d568 -> 0x80008b68 with its second reload'),
    dict(domain='refill',dispatch='0x80036c7c',returned='0x80036c80',
         queue_slot='0x801f8f34',identity='16-byte pending refill packet',
         completion='Prefetch/conversion return plus publishing producer return; file children joined'),
    dict(domain='sample_file',dispatch='0x80036184',returned='0x80036188',
         seek_dispatch='0x800361bc',seek_returned='0x800361c0',
         queue_slot='0x801f8f30',identity='16-byte read/seek packet; shared notification is not identity',
         completion='Read/seek result, count, error callback and signal tail; producer joined'),
    dict(domain='audio_background',dispatch='0x2022a7a8',
         identity='RAM task dispatcher; registered sampler callback 0x800366f1',
         completion='Callback/scan return PLUS already queued refill children'),
    dict(domain='usb',dispatch='0x80045cf0',identity='Shared command/parameter slots 0x801f910c/0x801f9110',
         completion='Host-access session, verified stop, remount and reload; acknowledgement is insufficient'),
]

def inventory():
    image=(ROOT/'Reference/L6_v1.10_E/L6.BIN').read_bytes()
    assert hashlib.sha256(image).hexdigest()==SHA
    source,dest,length,helper=struct.unpack_from('<4I',image,0x800a691c-BIAS)
    assert (source,dest,length,helper)==(0x800a9408,0x20220000,0xd6dc,0x80079498)
    regions=[('main_flash',0x80001000,image[0x200:0x800a1bd4-BIAS]),
             ('copied_ram',dest,image[source-BIAS:source-BIAS+length])]
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True
    found={name:dict(entry=hex(addr),direct_references=[]) for name,addr in TARGETS.items()}
    reverse={addr:name for name,addr in TARGETS.items()}
    for region,start,data in regions:
        for ins in md.disasm(data,start):
            if ins.mnemonic in ('bl','b','b.w') and ins.op_str.startswith('#'):
                target=int(ins.op_str[1:],16)
                if target in reverse:
                    found[reverse[target]]['direct_references'].append(
                        dict(region=region,address=hex(ins.address),instruction=ins.mnemonic))
    return dict(firmware_sha256=SHA,regions=[dict(name=n,start=hex(a),bytes=len(b)) for n,a,b in regions],
                entries=found,indirect_boundaries=INDIRECT,
                limitations=['Bounded linear disassembly can miss code or misidentify embedded data.',
                    'No completeness claim for indirect callbacks, RAM aliases, ISR/DMA or physical card removal.',
                    'Reference addresses are audit leads, not installed or approved interception sites.',
                    'No gate implementation, device access, firmware output or automatic readiness decision.'])

if __name__=='__main__':
    result=inventory();out=ROOT/'analysis/handoff_admission_inventory.json'
    out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(entries=len(result['entries']),
        direct_references=sum(len(e['direct_references']) for e in result['entries'].values()),report=str(out)),indent=2))
