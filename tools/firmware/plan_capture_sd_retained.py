#!/usr/bin/env python3
"""Combined capture/Main/SD footprint and byte patches. JSON only, no BIN.

Faults retain native frames indefinitely. Source admission is a null port until
explicitly supplied by an offline test. Startup PIO failures are retained,
but its initial physical source/reset qualification remains unbound.
The alternative loader is selected only for this separate experiment.
"""
import json
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from capture_jump_patches import ROOT,BIAS,SCATTER,symbols
from build_deployment_probe import SOURCE
from plan_capture_hooks import SPECS as HOOKS,make_patch
from plan_capture_startup import SPECS as STARTUP,make_patch as startup_patch
from plan_capture_transitions import RECEIVERS,receive_patch
from plan_capture_composed import CAP,RING,STRIDE,SIZE_SITE
from plan_capture_lz4 import packing,report as lz4_report
from plan_capture_packing import align4
from scatter_codec import compress

ELF=ROOT/'src/capture/capture-only-sd-retained.elf'
# Complete displaced instructions; every adapter replays these exact bytes.
SD_SPECS=tuple(dict(site=a,original=b,adapter=n,resume=a+len(bytes.fromhex(b))) for a,b,n in (
    (0x800688d0,'2de9f04f93b048f6446b','sdp_enumerate'),
    (0x80069c58,'2de9f04f9db08946','sdp_startup_read'),
    (0x80068db0,'2de9f04188b048f64462','sdp_read'),
    (0x80068e40,'2de9f04f89b048f64462','sdp_write'),
    (0x8006a348,'2de9f04f8bb00478','sdp_command'),
    (0x800328c0,'ddf800c0cdf800c0','sdp_wait'),
    (0x8006eab6,'cc0503ea0203cef8003003d5','sdp_irq_hook'),
    (0x80069fec,'4af820bc','sdp_program_direct_read'),
    (0x8006a180,'3760410a','sdp_program_bounce_read'),
    (0x8006abf0,'48f8204c','sdp_program_direct_write'),
    (0x8006adac,'3760bbf1010f','sdp_program_bounce_write')))

def plan(pack=None,*,elf_path=ELF):
    p=packing(elf_path) if pack is None else pack
    from capture_source_reuse_layout import CODE_INTERVAL
    interval=CODE_INTERVAL if p.get('source_reuse') else (0x800b6b00,0x801f5400)
    stock=SOURCE.read_bytes();n=symbols(elf_path)
    patches=[make_patch(stock,s,n[s['adapter']],code_interval=interval) for s in HOOKS]
    patches += [startup_patch(stock,s,n[s['adapter']],code_interval=interval) for s in STARTUP]
    patches += [receive_patch(stock,a,b,n['storage_main_receive'],code_interval=interval) for a,b in RECEIVERS]
    patches += [make_patch(stock,s,n[s['adapter']],code_interval=interval) for s in SD_SPECS]
    old='4af68011';new='46f28071'
    if stock[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]!=bytes.fromhex(old):
        raise ValueError('native capacity instruction differs')
    patches.append(dict(site=SIZE_SITE,original=old,patch=new,bytes=4,
        purpose='native capacity 223104; eight segmented history tails'))
    ordered=sorted(patches,key=lambda q:q['site'])
    if any(a['site']+len(bytes.fromhex(a['patch']))>b['site'] for a,b in zip(ordered,ordered[1:])):
        raise ValueError('combined MAIN patch overlap')
    # Independently decode every new direct branch. Existing startup adapters
    # use absolute literal jumps and keep their separate verifier.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for q in patches:
        if q.get('adapter') in {s['adapter'] for s in HOOKS+SD_SPECS}:
            insn=next(md.disasm(bytes.fromhex(q['patch']),q['site']))
            assert insn.mnemonic=='b.w' and int(insn.op_str[1:],0)==q['target']&~1
    md.skipdata=True;interiors=[]
    for a,size,mnemonic,operands in md.disasm_lite(stock[0x200:0xb5ce4],0x80001000):
        if mnemonic.startswith('b') or mnemonic in ('cbz','cbnz'):
            try:target=int(operands.rsplit('#',1)[1],0)
            except (IndexError,ValueError):continue
            if any(q['site']<target<q['resume'] for q in patches if q.get('adapter') in
                   {s['adapter'] for s in HOOKS+SD_SPECS}):
                interiors.append(dict(site=a,target=target))
    if interiors:raise ValueError('direct branch enters displaced span: '+str(interiors))
    dsp_stock=compress(p['dsp']);code_stock=compress(p['code'])
    stock_spare=SCATTER[0]+SCATTER[2]-(align4(SCATTER[0]+len(dsp_stock))+len(code_stock))
    j=p['jumps'];lr=lz4_report(p)
    return dict(status='offline_combined_retained_SD_not_deployable',
        firmware_sha256=j['firmware_sha256'],elf_sha256=j['placement_elf_sha256'],
        patches=patches,DSP_patches=j['patches'],direct_interior_branches=interiors,
        packing=dict(lr,globals=[j['globals_start'],j['globals_end']]),
        stock_decoder_spare_bytes=stock_spare,raw_code_bytes=len(p['code']),
        globals_bytes=j['globals_end']-j['globals_start'],
        heap_requested_bytes=9887,worker_stack_bytes=16384,
        history=dict(bytes=540672,slots=1024,seconds=65536/48000,
            spans=[[RING+i*STRIDE+CAP*4,RING+(i+1)*STRIDE] for i in range(8)]),
        fault_policy='retain native caller, unit token and buffer until reboot; no recovery port',
        startup='worker W_WAITING; source, admission, completion and cache ports zero',
        limitations=[
            'Combined code and patch plan, not a whole-board or concurrent eight-stream hardware test.',
            'Startup PIO event failures retain native frames; initial reset/source exclusion remains unbound.',
            'With ports zero, installed block hooks would hold native file IO too; this is not a bootable passive diagnostic.',
            'Positive source admission in tests is still an explicit model; no physical ownership claim.',
            'Larger globals are a footprint envelope only; neither globals nor code/history spans are owned.',
            'Isolated LZ4 startup is hardware-qualified for original DSP; this combined code/global destination is not.',
            'No installer, image, checksum, card access, worker release or pad handoff.'])

if __name__=='__main__':
    r=plan();out=ROOT/'analysis/capture_sd_retained_plan.json'
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(raw_code_bytes=r['raw_code_bytes'],globals_bytes=r['globals_bytes'],
        stock_decoder_spare_bytes=r['stock_decoder_spare_bytes'],
        lz4_spare_bytes=r['packing']['spare_bytes'],report=str(out))))
