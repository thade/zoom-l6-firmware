#!/usr/bin/env python3
"""Classify pinned direct storage callers; no image, device or admission grant.

The classifications describe entry chains, not transitive exclusion proofs.
Unexpected direct references fail instead of disappearing from the ledger.
"""
import json
from audit_handoff_dependencies import inventory,ROOT

# Each site is an original BL or tail branch, checked by the shared inventory.
# Boot-only classifications require the separately tested cold-mode restriction.
TARGETS={
 'card_setup':(0x80009a40,{
    0x8000c2b4:'USB stop body',0x8000c320:'USB change body',
    0x8002c1f0:'initial Main startup',0x8002c290:'special Main setup loop',
    0x8002cde2:'normal physical code32 subtype8',0x8002d4b6:'alternate physical code32 subtype8'}),
 'card_release':(0x80009b18,{
    0x8000c252:'USB start body',0x8000c2c4:'USB stop body',
    0x8000c380:'USB change body',0x8000c3a6:'USB change body',
    0x8002c2aa:'special Main setup loop',0x8002ce36:'normal physical code32 subtype9',
    0x8002d4ca:'alternate physical code32 subtype9'}),
 'USB_start':(0x8000c220,{
    0x8000ab00:'delayed-start helper',0x8002c344:'Main startup USB selection',
    0x8002c48c:'special Main startup USB selection'}),
 'USB_stop':(0x8000c288,{
    0x8000a184:'delayed-stop helper',0x8000ab8e:'mode/power body'}),
 'USB_change':(0x8000c2d8,{
    0x8002cdf6:'normal physical code33',0x8002d47e:'alternate physical code33'}),
 'delayed_stop':(0x8000a178,{0x8002c8d2:'category2 codea2, any subtype'}),
 'delayed_start':(0x8000aae8,{0x8002c8de:'category2 codea3, any subtype'}),
 'mode_power':(0x8000ab08,{
    0x8002d5ce:'category1 subtype0 code0',0x8002d6aa:'category1 subtype0 code2',
    0x8002d6fe:'category1 subtype0 code4',0x8002d712:'category1 subtype0 code5'}),
 'mount':(0x8005fc98,{
    0x80008790:'boot-key selection',0x80009a60:'card setup body',
    0x80009aa0:'card setup body',0x8000ac56:'format/root setup body'}),
 'detach':(0x80062230,{
    0x8000879c:'boot-key selection',0x80008830:'boot-key selection',
    0x80009986:'format failure cleanup',0x80009a8c:'card setup body',
    0x80009b1c:'card release body',0x8000ac50:'format/root setup body'}),
 'format_request':(0x800099b0,{0x8002c304:'special Main setup button branch'}),
 'format':(0x80009938,{0x800099bc:'format request body'}),
 'format_root_setup':(0x8000ac18,{0x80009952:'format body'}),
 'boot_keys':(0x800086b0,{0x8001b278:'board initialization before Main'}),
 'storage_notify':(0x80036c98,{
    0x80045d46:'independent USB worker: source exclusion still required',
    0x8005fd00:'mount body: (1,1) does not post abort',
    0x80062292:'detach body: (0,1) posts after registration mutation'}),
 'SD_notify':(0x80068508,{0x80036cca:'storage notifier, ISR or task context'})}

def audit():
    report=inventory({name:entry for name,(entry,_) in TARGETS.items()})
    report.pop('UI_mutex_slot');report.pop('constant_formations')
    for name,(_,known) in TARGETS.items():
        target=report['targets'][name]
        actual={int(v,16) for v in target['direct_references']}
        if actual!=set(known):
            raise ValueError(f'{name}: unclassified or changed references: {actual^set(known)}')
        target['classified_references']=[dict(site=hex(site),chain=chain) for site,chain in known.items()]
    report.update(status='bounded_direct_callers_classified_not_source_admission',
        direct_references=sum(len(t['direct_references']) for t in report['targets'].values()),
        findings=[
            'All listed direct mount/detach callers fall within card/USB bodies, format setup or boot-key selection.',
            'Format/root setup reaches Main only through the examined special setup branch; initial boot-mode exclusion is required.',
            'Delayed USB dispatch accepts any subtype, so Main protection must classify by category and code alone.',
            'The independent USB worker remains outside the Main packet gate; admission must establish its settled audio-only state.',
            'Notifier entry cannot serve as a blocking gate: it can run in ISR context, and detach has already changed registration.'],
        limitations=report['limitations']+[
            'Finite direct call inventory and selected native dispatch execution; no exhaustive indirect reachability or transitive lock proof.',
            'Boot exclusions, worker state and IRQ sources must be enforced, not inferred from these labels.',
            'Reset completion, old hardware work, IRQ111 and cache/buffer ownership still require physical qualification.'])
    return report

if __name__=='__main__':
    r=audit();out=ROOT/'analysis/capture_storage_ingress_audit.json'
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(status=r['status'],direct_references=r['direct_references'],report=str(out))))
