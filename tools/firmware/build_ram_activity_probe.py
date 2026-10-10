#!/usr/bin/env python3
"""Prepare a fixed-range passive gap fingerprint trial; no device access."""
import json
import build_memory_capacity_probe as memory
from build_health_probe import ROOT

ENTRY=memory.ENTRY
ELF=ROOT/'src/diagnostics/ram-activity.elf'
OUT=ROOT/'deployment/13_ram_activity'
STATES=memory.STATES
GAP_START=0x81f26000
PAGE_BYTES=1024
PAGE_COUNT=872

def compiled():
    return memory.compiled(elf_path=ELF,query_callback='ram_activity_dispatch',
                           extra_sources=('ram_activity_probe.c',),extra_roots=('memory_capacity_dispatch',))

def trial(code,syms):
    data,r=memory.trial(code,syms,elf_path=ELF)
    r.update(experiment=13,protocol='6F/6E kind2 fixed upper-gap page fingerprints; all experiment12 queries retained',
        ram_activity_persistent_state_bytes=0,read_only_gap_interval=[GAP_START,GAP_START+PAGE_BYTES*PAGE_COUNT],
        ram_activity_page_bytes=PAGE_BYTES,ram_activity_pages=PAGE_COUNT,
        unused_memory_proven=False,
        limitations=r['limitations']+[
            'Each accepted page query reads exactly one fixed 1024-byte page twice, with configured-window checks',
            'Fingerprints are non-cryptographic FNV-1a over uint32 words plus a wrapping uint32 sum',
            'Paired fingerprints and controller reads are sequential, not atomic; changes mark uncertainty without retry',
            'CPU-visible cached reads may miss DMA writes; no cache maintenance or MPU/controller changes',
            'Even stable full coverage cannot establish unused RAM, physical address independence or reservation',
            'Software stack/instruction bounds require actual timing/headroom checks on hardware'])
    return data,r

def build():
    code,syms=compiled();data,r=trial(code,syms)
    path=OUT/'trial_ram_activity/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to replace a different prepared image'
    else:path.write_bytes(data)
    (OUT/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','native_capacity_frames')}))
if __name__=='__main__':build()
