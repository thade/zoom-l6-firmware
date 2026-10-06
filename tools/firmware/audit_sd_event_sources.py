#!/usr/bin/env python3
"""Bounded SD signal-source leads, not an exhaustive graph or device gate."""
import json,struct
from pathlib import Path
from audit_handoff_dependencies import inventory as references,BIAS
ROOT=Path(__file__).resolve().parents[2]
TARGETS={'post_ISR':0x80032828,'post_task':0x80032888,
         'notify_SD':0x80068508,'notify_storage':0x80036c98,
         'IRQ_unit0':0x8006ea90,'IRQ_unit1':0x80053b80,'IRQ_common':0x8006ea98}
SD_IRQ_POSTS=(0x8006eb0a,0x8006eb3c,0x8006eb54,0x8006eb72,0x8006eb8c,0x8006eba4)
SD_NOTIFY_POSTS=(0x8006852a,0x80068534)

def inventory():
    bounded=references(TARGETS)
    image=(ROOT/'Reference/L6_v1.10_E/L6.BIN').read_bytes()
    descriptor=struct.unpack_from('<4I',image,0x800a07bc-BIAS)
    assert descriptor==(0x8006ea91,110,0x80053b81,111)
    return dict(firmware_sha256=bounded['firmware_sha256'],targets=bounded['targets'],
      known_SD_sources=[
        dict(kind='controller_irq',entry='0x8006ea98',post_sites=list(map(hex,SD_IRQ_POSTS)),
             event_slot='0x808e28e0 + unit*16',controller='0x402c0000',
             status='0x402c0030',signal_mask='0x402c0038',
             note='Both examined unit wrappers reach this same fixed MMIO body; runtime use of unit1 is not established'),
        dict(kind='software_notification',entry='0x80068508',post_sites=list(map(hex,SD_NOTIFY_POSTS)),
             event_slot='0x808e28e0 + unit*16',flags='0x100',
             context='Original IPSR predicate selects task or ISR post; no SD token acquired',
             outer_entry='0x80036c98',outer_condition='arg0 zero, arg1 one, callback at 0x802350e4 nonnull',
             outer_callers=[dict(site='0x80045d46',domain='USB task'),
                            dict(site='0x8005fd00',domain='mount',note='Examined arguments (1,1) do not post'),
                            dict(site='0x80062292',domain='detach',note='Examined A branch passes (0,1) and posts')])],
      IRQ_descriptors=[dict(callback=hex(descriptor[i]),irq=descriptor[i+1]) for i in (0,2)],
      other_direct_post_sites=dict(
        ISR=[s for s in bounded['targets']['post_ISR']['direct_references']
             if int(s,16) not in (*SD_IRQ_POSTS,0x8006852a)],
        task=[s for s in bounded['targets']['post_task']['direct_references'] if int(s,16)!=0x80068534]),
      required_exclusion=['Pin event, semaphore, callback registration and all users through submission/unwind',
        'Keep accepted ISR/posts runnable to completion; disable/active readback alone is not physical join',
        'Exclude relevant outer detach/USB mutations and software notification through arm-to-wait',
        'Establish no old controller/DMA/card work can reassert completion after clearing',
        'Resolve the second unit callback and any aliases/indirect post paths before binding a gate'],
      limitations=bounded['limitations']+[
        'Source classifications are bounded instruction leads, corroborated by emulation; other posts can use aliased handles',
        'No native exclusion provider, silicon identification, physical abort/reset/cache/card proof or installation'])

if __name__=='__main__':
    result=inventory();out=ROOT/'analysis/sd_event_sources_inventory.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(report=str(out),known_sources=len(result['known_SD_sources']),
        ISR_post_references=len(result['targets']['post_ISR']['direct_references']),
        task_post_references=len(result['targets']['post_task']['direct_references'])),indent=2))
