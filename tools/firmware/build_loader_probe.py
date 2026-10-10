#!/usr/bin/env python3
"""Isolated LZ4 startup diagnostic. Prepare locally only; no device access.

Retains expanded diagnostic14, original DSP and all native capacities. No
capture code, new scatter destination, worker or global reservation is added.
"""
import json,struct
import lz4.block
import build_memory_capacity_probe as memory
import build_sd_startup_detail as detail
from build_lz4_loader_fixture import compiled as loader_compiled
from build_health_probe import ROOT,SOURCE,BIAS,SCATTER,DSP_SOURCE,DSP_DEST,DSP_BYTES,END
from build_deployment_probe import digest,validate
from plan_capture_packing import align4

ENTRY=detail.ENTRY
ELF=ROOT/'src/diagnostics/loader.elf'
OUT=ROOT/'deployment/15_loader'
STATES=detail.STATES
RESET_SITE=detail.RESET_SITE
WAIT_SITES=detail.WAIT_SITES

def compiled():
    return memory.compiled(elf_path=ELF,query_callback='loader_dispatch',
        extra_sources=('ram_activity_probe.c','sd_startup_probe.c','sd_startup_hooks.S','loader_probe.c'),
        extra_roots=('startup_sd','startup_wait','startup_reset_hook','ram_activity_dispatch','memory_capacity_dispatch'),
        extra_flags=('-DSD_STARTUP_OBSERVER=1','-DSD_STARTUP_DETAIL=1'),
        linker_script='src/diagnostics/sd_startup.ld')

def trial(code,syms):
    old=detail.ELF
    try:
        detail.ELF=ELF
        base,r=detail.trial(code,syms)
    finally:detail.ELF=old
    loader,names=loader_compiled()
    stock=SOURCE.read_bytes();dsp=stock[DSP_SOURCE-BIAS:DSP_SOURCE-BIAS+DSP_BYTES]
    block=lz4.block.compress(dsp,mode='high_compression',compression=12,store_size=False)
    assert lz4.block.decompress(block,uncompressed_size=DSP_BYTES)==dsp
    source=align4(DSP_SOURCE+len(loader));payload=struct.pack('<I',len(block))+block
    assert source+len(payload)<=ENTRY and ENTRY+len(code)<=END
    data=bytearray(base)
    data[DSP_SOURCE-BIAS:ENTRY-BIAS]=bytes(ENTRY-DSP_SOURCE)
    data[DSP_SOURCE-BIAS:DSP_SOURCE-BIAS+len(loader)]=loader
    data[source-BIAS:source-BIAS+len(payload)]=payload
    record=(source,DSP_DEST,DSP_BYTES,names['scatter_lz4']&~1)
    struct.pack_into('<4I',data,SCATTER-BIAS,*record)
    struct.pack_into('>I',data,0x1fc,sum(data[0x200:])&0xffffffff)
    data=bytes(data);validate(data)
    allowed=((0x1fc,0x200),(SCATTER-BIAS,SCATTER-BIAS+16),(DSP_SOURCE-BIAS,ENTRY-BIAS))
    assert all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(base,data)) if x!=y)
    assert data[ENTRY-BIAS:ENTRY-BIAS+len(code)]==code
    assert data[0x2851f8:]==stock[0x2851f8:]
    r.update(experiment=15,revision='isolated_lz4_startup',trial_sha256=digest(data),
        elf_sha256=digest(ELF.read_bytes()),loader_bytes=len(loader),
        stock_decoder_packed_bytes=r['packed_bytes'],packed_bytes=len(block),
        dsp_source_envelope_start=DSP_SOURCE,dsp_source=source,
        loader_sha256=digest(loader),loader_record=list(record),
        loader_failed_entry=names['scatter_lz4_failed']&~1,
        packed_dsp_bytes=len(block),source_spare_before_diagnostic=ENTRY-source-len(payload),
        protocol='6F/6E kind3 schema1: fixed application scatter source/destination/length/helper; all diagnostic14 queries retained',
        new_persistent_state_bytes=0,completion_guard_enabled=False,
        limitations=r['limitations']+[
            'Isolated decoder trial only: DSP output and all scatter destinations/lengths stay stock.',
            'Diagnostic code remains in the previously exercised loaded source span, not the proposed capture destination.',
            'New query reads four application-RAM words; it neither reads installed flash nor grants memory or storage permission.',
            'Successful boot/audio would qualify this loader path only, not combined capture startup, code publication or service margin.'])
    return data,r

def build():
    code,syms=compiled();data,r=trial(code,syms)
    path=OUT/'trial_loader/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to replace a different prepared image'
    else:path.write_bytes(data)
    (OUT/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','loader_bytes','source_spare_before_diagnostic')}))
if __name__=='__main__':build()
