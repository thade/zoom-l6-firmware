#!/usr/bin/env python3
"""Prepare expanded passive startup journal; no device access."""
import json
import build_memory_capacity_probe as memory
import build_sd_startup_probe as startup
from build_health_probe import ROOT

ENTRY=startup.ENTRY
ELF=ROOT/'src/diagnostics/sd-startup-detail.elf'
OUT=ROOT/'deployment/14_sd_startup_detail'
STATES={**memory.STATES,'startup_trace':724}
RESET_SITE=startup.RESET_SITE
WAIT_SITES=startup.WAIT_SITES

def compiled():
    return memory.compiled(elf_path=ELF,query_callback='startup_dispatch',
        extra_sources=('ram_activity_probe.c','sd_startup_probe.c','sd_startup_hooks.S'),
        extra_roots=('startup_sd','startup_wait','startup_reset_hook','ram_activity_dispatch','memory_capacity_dispatch'),
        extra_flags=('-DSD_STARTUP_OBSERVER=1','-DSD_STARTUP_DETAIL=1'),
        linker_script='src/diagnostics/sd_startup.ld')

def trial(code,syms):
    old_elf,old_states=startup.ELF,startup.STATES
    try:
        startup.ELF,startup.STATES=ELF,STATES
        data,r=startup.trial(code,syms)
    finally:
        startup.ELF,startup.STATES=old_elf,old_states
    r.update(revision='startup_detail',startup_schema=2,startup_persistent_state_bytes=724,
        protocol='6D/6C schema2: summary/reset, eight PIO samples with request code/argument, first-command snapshot; diagnostic13 queries retained')
    r['limitations']=[s.replace('first four PIO completions','first eight PIO completions') for s in r['limitations']]
    r['limitations']+=[
        'First-command snapshot is inside native clock-enabled command entry, not the clock-gated outer dispatcher entry/return',
        'Software42 nested CMD55 prefixes preserve the enclosing request code/argument; observations do not prove physical identity',
        'A clear reset at first command is a later snapshot, not a measured reset-completion boundary']
    return data,r

def build():
    code,syms=compiled();data,r=trial(code,syms)
    path=OUT/'trial_sd_startup_detail/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to replace a different prepared image'
    else:path.write_bytes(data)
    (OUT/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','native_capacity_frames')}))

if __name__=='__main__':build()
