#!/usr/bin/env python3
"""Byte-checked patch plan for the master reference. JSON only, no image.

Sites: the two startup sites, recorder admission and the stop cursor setter,
the five Main receive calls and, in the trial, the Editor query parser. The
DSP code and the stock ring size stay stock; the DSP record is only repacked
so the code can reuse its consumed source span.
"""
import hashlib,json
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from build_deployment_probe import SOURCE,STOCK_SHA,validate
from capture_jump_patches import ROOT,symbols
from capture_source_reuse_layout import CODE_INTERVAL
from plan_capture_hooks import make_patch as main_patch
from plan_capture_startup import SPECS as STARTUP_SPECS,make_patch as startup_patch
from plan_capture_transitions import RECEIVERS,receive_patch
from plan_capture_packing import report as packing_report
from plan_simple_capture import QUERY_SPEC,reuse_packing,interior_branches

ELF=ROOT/'src/capture/master/master-ref.elf'
TRIAL_ELF=ROOT/'src/capture/master/master-ref-trial.elf'
RECORDER_SPECS=(
    dict(site=0x8000b158,original='40f20120',adapter='mr_admit_hook',resume=0x8000b15c,
         replay='movw r0,#0x201',purpose='stock recorder admitted its seven streams'),
    dict(site=0x80006918,original='40f6c852',adapter='mr_stop_hook',resume=0x8000691c,
         replay='movw r2,#0xdc8',purpose='stock stop cursor setter; RecStop notes the take folder'))
# Stereo AUX: the gain-ramp request entry (pass-through replays the prologue)
# and the apply veneers of mono pan and stereo balance (replaced outright).
STEREO_SPECS=(
    dict(site=0x80010398,original='10b584b0',adapter='sa_ramp',resume=0x8001039c,
         replay='push {r4,lr}; sub sp,#16 (in sa_ramp_original)',purpose='stereo AUX: AUX1 requests drive both sides'),
    dict(site=0x80002ac0,original='01230af0b5bd',adapter='sa_mono_pan',resume=0x80002ac6,
         replay='none: veneer replaced',purpose='stereo AUX: mono pan also refreshes the pair'),
    dict(site=0x800028d8,original='032888bf',adapter='sa_balance',resume=0x800028dc,
         replay='none: veneer replaced',purpose='stereo AUX: stereo balance also refreshes the pair'),
    dict(site=0x80002b78,original='46f66871',adapter='sa_reset1',resume=0x80002b7c,
         replay='none: veneer replaced',purpose='stereo AUX: Editor mixer reset 1, then the bulk recompute'),
    dict(site=0x80002b90,original='46f66871',adapter='sa_reset2',resume=0x80002b94,
         replay='none: veneer replaced',purpose='stereo AUX: Editor mixer reset 2, then the bulk recompute'))
PLAY_SPEC=dict(site=0x80018316,original='10b50446',adapter='mr_play_hook',resume=0x8001831a,
               replay='push {r4,lr}; mov r4,r0',purpose='stock pad start (every trigger, on Main): take history')

def plan(elf_path=None,trial=False):
    elf_path=elf_path or (TRIAL_ELF if trial else ELF)
    stock=SOURCE.read_bytes()
    if hashlib.sha256(stock).hexdigest()!=STOCK_SHA:raise ValueError('unsupported stock firmware')
    validate(stock);names=symbols(elf_path)
    if any(n in names for n in ('placement_tap_hook','placement_commit_hook','sc_ring_frames')):
        raise ValueError('master reference builds must not hook the DSP or resize the ring')
    p=reuse_packing(elf_path,dsp=False);p['names']=names;at=dict(code_interval=CODE_INTERVAL)
    patches=[startup_patch(stock,s,names[s['adapter']],**at) for s in STARTUP_SPECS]
    if trial:patches.append(main_patch(stock,QUERY_SPEC,names['health_parser'],**at))
    patches+=[main_patch(stock,s,names[s['adapter']],**at) for s in RECORDER_SPECS]
    if 'mr_play_hook' in names:patches.append(main_patch(stock,PLAY_SPEC,names['mr_play_hook'],**at))
    if 'sa_ramp' in names:patches+=[main_patch(stock,s,names[s['adapter']],**at) for s in STEREO_SPECS]
    patches+=[receive_patch(stock,site,old,names['mr_main_receive'],adapter='mr_main_receive',**at)
              for site,old in RECEIVERS]
    ordered=sorted(patches,key=lambda x:x['site'])
    for a,b in zip(ordered,ordered[1:]):
        if a['site']+len(bytes.fromhex(a['patch']))>b['site']:raise ValueError('MAIN patches overlap')
    # Replayed instructions are re-executed at a new address: none may read PC.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.detail=True
    for q in patches:
        if q['adapter'].startswith('startup_') or q['adapter']=='mr_main_receive':continue
        for i in md.disasm(bytes.fromhex(q['original']),q['site']):
            if 'pc' in i.op_str:raise ValueError(f"displaced PC-relative instruction at {q['site']:#x}")
    interiors=interior_branches(stock,patches)
    if interiors:raise ValueError('direct branch enters a displaced span: '+str(interiors))
    pack=packing_report(p)
    return dict(status='offline_master_ref_trial_plan' if trial else 'offline_master_ref_plan_not_deployable',
        firmware_sha256=STOCK_SHA,pack=p,elf_sha256=hashlib.sha256(elf_path.read_bytes()).hexdigest(),
        patches=ordered,DSP_patches=[],packing=pack,code_bytes=len(p['code']),
        globals_bytes=p['jumps']['globals_end']-p['jumps']['globals_start'],patch_sites=len(patches),
        limitations=['JSON only; no container, checksum, staging or installation',
            'Code/globals reuse the consumed DSP source span executed from in experiment 16',
            'Pad playback of a stock master in place is unproven on hardware',
            'Linear direct-branch scan cannot exclude indirect entries into displaced spans'])

def main():
    r=plan();r.pop('pack');out=ROOT/'analysis/master_ref_plan.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(patch_sites=r['patch_sites'],code_bytes=r['code_bytes'],
        globals_bytes=r['globals_bytes'],spare_bytes=r['packing']['spare_bytes'],report=str(out))))
if __name__=='__main__':main()
