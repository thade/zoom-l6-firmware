#!/usr/bin/env python3
"""Prepare isolated source-reuse marker diagnostic locally; no device access."""
import json,struct
import lz4.block
import build_memory_capacity_probe as memory
import build_loader_probe as previous
from build_lz4_loader_fixture import compiled as loader_compiled
from build_health_probe import ROOT,SOURCE,BIAS,SCATTER,DSP_SOURCE,DSP_DEST,DSP_BYTES,END
from build_deployment_probe import digest,validate,write_manifest
from plan_capture_packing import align4,TABLE_END,TABLE_END_LITERAL,TABLE_LIMIT,ZERO
from capture_source_reuse_layout import CODE_START,GLOBALS_START

ELF=ROOT/'src/diagnostics/source-reuse.elf'
OUT=ROOT/'deployment/16_source_reuse'
ENTRY=previous.ENTRY;STATES=previous.STATES
MARKER=bytes.fromhex('44f63640704700bf') # movw r0,#0x4c36; bx lr; nop
ZERO_BYTES=16

def compiled():
    return memory.compiled(elf_path=ELF,query_callback='source_reuse_dispatch',
        extra_sources=('ram_activity_probe.c','sd_startup_probe.c','sd_startup_hooks.S',
                       'loader_probe.c','source_reuse_probe.c'),
        extra_roots=('startup_sd','startup_wait','startup_reset_hook','ram_activity_dispatch',
                     'memory_capacity_dispatch','loader_dispatch'),
        extra_flags=('-DSD_STARTUP_OBSERVER=1','-DSD_STARTUP_DETAIL=1'),
        linker_script='src/diagnostics/sd_startup.ld')

def trial(code,syms):
    old=previous.ELF
    try:
        previous.ELF=ELF;base,r=previous.trial(code,syms)
    finally:previous.ELF=old
    loader,names=loader_compiled(source_reuse=True);helper=names['scatter_lz4']&~1
    stock=SOURCE.read_bytes();dsp=stock[DSP_SOURCE-BIAS:DSP_SOURCE-BIAS+DSP_BYTES]
    def packed(data):
        b=lz4.block.compress(data,mode='high_compression',compression=12,store_size=False)
        assert lz4.block.decompress(b,uncompressed_size=len(data))==data
        return struct.pack('<I',len(b))+b
    dsp_payload=packed(dsp);marker_payload=packed(MARKER)
    marker_source=align4(CODE_START+len(dsp_payload))
    assert DSP_SOURCE+len(loader)<=CODE_START<CODE_START+len(MARKER)<=GLOBALS_START
    assert GLOBALS_START+ZERO_BYTES<=marker_source<marker_source+len(marker_payload)<=ENTRY
    assert TABLE_END+32<=TABLE_LIMIT and stock[TABLE_END-BIAS:TABLE_END+32-BIAS]==bytes(32)
    records=[(CODE_START,DSP_DEST,DSP_BYTES,helper),
        (marker_source,CODE_START,len(MARKER),helper),(0,GLOBALS_START,ZERO_BYTES,ZERO)]
    data=bytearray(base);data[DSP_SOURCE-BIAS:ENTRY-BIAS]=bytes(ENTRY-DSP_SOURCE)
    for address,blob in ((DSP_SOURCE,loader),(CODE_START,dsp_payload),(marker_source,marker_payload)):
        data[address-BIAS:address-BIAS+len(blob)]=blob
    data[SCATTER-BIAS:TABLE_END+32-BIAS]=b''.join(struct.pack('<4I',*q) for q in records)+stock[SCATTER+16-BIAS:TABLE_END-BIAS]
    struct.pack_into('<I',data,TABLE_END_LITERAL-BIAS,TABLE_END+32)
    struct.pack_into('>I',data,0x1fc,sum(data[0x200:])&0xffffffff)
    data=bytes(data);validate(data)
    allowed=((0x1fc,0x200),(TABLE_END_LITERAL-BIAS,TABLE_END_LITERAL-BIAS+4),
             (SCATTER-BIAS,TABLE_END+32-BIAS),(DSP_SOURCE-BIAS,ENTRY-BIAS))
    assert len(data)==len(base) and all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(base,data)) if x!=y)
    assert data[ENTRY-BIAS:ENTRY-BIAS+len(code)]==code and data[0x2851f8:]==stock[0x2851f8:]
    r.update(experiment=16,revision='isolated_source_reuse_marker',trial_sha256=digest(data),
        elf_sha256=digest(ELF.read_bytes()),loader_bytes=len(loader),loader_sha256=digest(loader),
        loader_record=list(records[0]),loader_failed_entry=names['scatter_lz4_failed']&~1,
        dsp_source=CODE_START,scatter_records=[list(q) for q in records],marker_hex=MARKER.hex(),
        marker_value=0x4c36,new_zeroed_bytes=ZERO_BYTES,new_persistent_state_bytes=ZERO_BYTES,
        source_spare_before_diagnostic=ENTRY-marker_source-len(marker_payload),
        protocol='6F/6E kind4 schema1: execute fixed marker, zero/CCR snapshot, DSP/code scatter records and zero extent; previous queries retained')
    # Replace only the inherited isolated-loader qualification notes; retain
    # the full observation limitations of the underlying diagnostics.
    r['limitations']=r['limitations'][:-4]+[
        'Original DSP and all original scatter destinations/lengths remain unchanged; two explicit records publish an eight-byte marker and zero 16 bytes.',
        'DSP expands first, code overwrites consumed input second, and marker globals are zeroed third; the live decoder and unread input are separate.',
        'A fixed marker query qualifies this tiny executable publication path only; it does not execute the combined capture payload or grant complete source ownership.',
        'No capture worker, additional recording, storage guard, allocation, reset/retry or native buffer change is introduced.',
        'Application-RAM records and executed marker do not establish installed-flash readback, physical alias exclusion or timing headroom.']
    return data,r

def build():
    code,syms=compiled();data,r=trial(code,syms)
    path=OUT/'trial_source_reuse/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to replace a different prepared image'
    else:path.write_bytes(data)
    write_manifest(OUT/'manifest.json',r)
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','loader_bytes','source_spare_before_diagnostic')}))
if __name__=='__main__':build()
