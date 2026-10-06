#!/usr/bin/env python3
"""Capture-only storage release leads; bounded stock inventory, no bindings."""
import json
from audit_handoff_dependencies import inventory
from capture_jump_patches import ROOT,BIAS
from build_deployment_probe import SOURCE
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS

TARGETS={'card_setup':0x80009a40,'mount':0x8005fc98,'detach':0x80062230,
    'card_release':0x80009b18,'volume_status':0x8005ec00,'volume_callback':0x8004bd98,
    'pad_directories':0x80048690,'directory_root':0x80048500,
    'reload_submit':0x80008d68,'reload_UI':0x8002d568,
    'USB_request':0x8003b7e0,'USB_stop':0x8003b8a0,
    'USB_outer_start':0x8000c220,'USB_outer_stop':0x8000c288,'USB_outer_change':0x8000c2d8,
    'public_open':0x8005ffe8,'public_read':0x80060620,'public_write':0x800622b0,
    'public_close':0x8005c1f8}
WINDOWS=((0x8005fc98,0x8005ffd0),(0x8005ec00,0x8005ec2a),
    (0x80009a40,0x80009b44),(0x80048500,0x800485b0),
    (0x80048690,0x800488e4),(0x8004bd98,0x8004bdd0),
    (0x80062230,0x800622ac),(0x8001bf88,0x8001bfd4),
    (0x8000c220,0x8000c3d0),(0x8005ffe8,0x80060050),
    (0x80060424,0x800604e8),(0x8005c1f8,0x8005c388),
    (0x8002b100,0x8002b140),(0x80035168,0x800351c0))

def audit():
    r=inventory(TARGETS)
    r.pop('UI_mutex_slot');r.pop('constant_formations')
    r.update(status='storage_release_unbound',scope='capture-only; no pad publication ownership overlay',
        callback_leads=[dict(site='0x8005fd9a..0x8005fda2',callback='0x8004bd99',
            registration_call='0x8005fdac -> 0x80052ce0',
            note='Indirect callback construction; no direct reference to the status setter is expected here')],
        facts=[
            'Stock mount returns the signed status byte at 0x801f8f5a; examined supported geometry yields 2',
            'Outer card setup ignores mount result and can return zero on absent media',
            'Pad-directory setup ignores root helper result and treats non-not-found lookup errors as existing directories',
            'Detach clears registration before waiting for status-zero callback; status bits remain stale meanwhile',
            'Public file-domain ownership does not exclude the examined detach mutation',
            'Open takes domains 1/2 then resources 6/5/4; close takes domains 1/2 then resource 4',
            'Extra cancellation can finish without sending ordinary recorder STOP on the tested capture-only path',
            'Outer USB transitions mutate before their mailbox requests and ignore lower failure returns',
            'Outer card release continues cleanup after a modeled detach error; returning busy at detach is insufficient',
            'Capture-only software write error can reach CLOSE without a physical join; direct ports remain unsuitable for device binding',
            'Worker release API requires caller-established storage authorization; it is not a recovered readiness provider'],
        next_requirements=[
            'Observe actual mount/registration and target-directory outcomes within one storage generation',
            'Serialize outer mount/detach/USB transitions against added I/O before their first mutations',
            'Normal pad/recorder I/O may coexist on stock file locks; capture-only does not require pad publication exclusion',
            'Retain buffers/caller frames through physical SD completion or checked failure recovery',
            'Keep Main event processing available; no wait on work which needs the same blocked task'],
        limitations=r['limitations']+[
            'Task/callback progress, geometry responses, file-driver effects and RTOS locking are fixtures in tests',
            'No native release provider, complete transition caller coverage, hardware join or firmware image'])
    return r

def main():
    r=audit();out=ROOT/'analysis/capture_storage_inventory.json'
    out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(r,indent=2)+'\n')
    stock=SOURCE.read_bytes();md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    listing=[]
    for lo,hi in WINDOWS:
        listing.append(f'BOUND {lo:08x}..{hi:08x}')
        listing.extend(f'{a:08x} {op:10} {args}' for a,n,op,args in md.disasm_lite(stock[lo-BIAS:hi-BIAS],lo))
    (ROOT/'analysis/capture_storage_disassembly.txt').write_text('\n'.join(listing)+'\n')
    print(json.dumps(dict(status=r['status'],direct_references=sum(len(t['direct_references']) for t in r['targets'].values()),report=str(out))))

if __name__=='__main__':main()
