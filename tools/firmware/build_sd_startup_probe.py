#!/usr/bin/env python3
"""Prepare passive first SD enumeration diagnostic; never access a device."""
import json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
import build_memory_capacity_probe as memory
import build_ram_activity_probe as activity
import build_sd_command_probe as command
from build_health_probe import ROOT,SOURCE,BIAS,SCATTER,DSP_SOURCE,END
from build_added_code_probe import branch
from build_deployment_probe import validate,digest,write_manifest
from build_sd_completion_probe import bl

ENTRY=memory.ENTRY
ELF=ROOT/'src/diagnostics/sd-startup.elf'
OUT=ROOT/'deployment/14_sd_startup'
STATES={**memory.STATES,'startup_trace':364}
RESET_SITE=0x80069c14
WAIT_SITES=(0x8006a566,0x80069e5a,0x80069d64,0x8006aa1a,0x8006a904)

def compiled():
    return memory.compiled(elf_path=ELF,query_callback='startup_dispatch',
        extra_sources=('ram_activity_probe.c','sd_startup_probe.c','sd_startup_hooks.S'),
        extra_roots=('startup_sd','startup_wait','startup_reset_hook','ram_activity_dispatch','memory_capacity_dispatch'),
        extra_flags=('-DSD_STARTUP_OBSERVER=1',),linker_script='src/diagnostics/sd_startup.ld')

def trial(code,syms):
    previous,previous_elf=command.STATES,activity.ELF
    try:
        command.STATES=STATES
        activity.ELF=ELF
        base,r=activity.trial(code,syms)
    finally:command.STATES,activity.ELF=previous,previous_elf
    data=bytearray(base);stock=SOURCE.read_bytes()
    # Replace the inherited outer dispatcher detour, retaining its normal
    # read/write counters behind the first-enumeration wrapper.
    for p in r['patches']:
        if p['site']==0x80068378:
            p.update(symbol='startup_sd',target=syms['startup_sd']&~1,
                     new=branch(p['site'],syms['startup_sd']&~1).hex())
            data[p['site']-BIAS:p['site']-BIAS+4]=bytes.fromhex(p['new'])
    for site in WAIT_SITES:
        old=stock[site-BIAS:site-BIAS+4];assert old==bl(site,0x800328c0)
        new=bl(site,syms['startup_wait']&~1);data[site-BIAS:site-BIAS+4]=new
        r['patches'].append(dict(symbol='startup_wait',site=site,old=old.hex(),new=new.hex()))
    old=stock[RESET_SITE-BIAS:RESET_SITE-BIAS+6]
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    assert [(i.mnemonic,i.op_str) for i in md.disasm(old,RESET_SITE)]==[
        ('ldr','r0, [r4, #8]'),('orr','r0, r0, #0x8000000')]
    new=branch(RESET_SITE,syms['startup_reset_hook']&~1)+bytes.fromhex('00bf')
    data[RESET_SITE-BIAS:RESET_SITE-BIAS+6]=new
    r['patches'].append(dict(symbol='startup_reset_hook',site=RESET_SITE,old=old.hex(),new=new.hex()))
    struct.pack_into('>I',data,0x1fc,sum(data[0x200:])&0xffffffff)
    data=bytes(data);validate(data)
    allowed=[(0x1fc,0x200),(SCATTER-BIAS+12,SCATTER-BIAS+16),(DSP_SOURCE-BIAS,END-BIAS)]
    allowed += [(p['site']-BIAS,p['site']-BIAS+len(bytes.fromhex(p['new']))) for p in r['patches']]
    assert len(data)==len(stock) and data[0x2851f8:]==stock[0x2851f8:]
    assert all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(stock,data)) if x!=y)
    r.update(experiment=14,trial_sha256=digest(data),
        protocol='6D/6C kinds1 summary /2 first reset /3..6 first four PIO completions; diagnostic13 queries retained',
        startup_persistent_state_bytes=364,startup_wait_sites=list(WAIT_SITES),
        startup_reset_site=RESET_SITE,completion_guard_enabled=False,
        limitations=r['limitations']+[
            'Observes first unit-zero enumeration attempt, whether successful or not; later attempts cannot replace it',
            'First reset sample precedes native initial clocks while the controller clock gate is enabled',
            'Raw IRQ association is temporal, not hardware request identity or a previous-source exclusion proof',
            'Only the first four PIO completions are retained; omissions, overlap and busy epochs invalidate completeness',
            'An unchanged card-ready result is not physical completion; extra capture and all guards remain disabled'])
    return data,r

def build():
    code,syms=compiled();data,r=trial(code,syms)
    path=OUT/'trial_sd_startup/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to replace a different prepared image'
    else:path.write_bytes(data)
    write_manifest(OUT/'manifest.json',r)
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','native_capacity_frames')}))
if __name__=='__main__':build()
