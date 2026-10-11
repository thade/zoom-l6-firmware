#!/usr/bin/env python3
"""Prepare the master-reference trial (experiment 24) locally. No device access.

Writes the trial image and the PAD1 anchor file: a short silent 48 kHz stereo
32-bit float WAV with the same 512-byte header layout as the extra files the
stock validator and loader accepted in experiment 21. Staging copies the
anchor to A:\\SOUND_PAD\\PAD1\\MASTER.WAV.
"""
import json,struct
from build_deployment_probe import ROOT,SOURCE,STOCK_SHA,validate,digest,write_manifest
from build_master_ref import build
from build_simple_trial import assemble,require
from plan_master_ref import plan

OUT=ROOT/'deployment/24_master_ref'
ANCHOR_FRAMES=4800   # 0.1 s of silence

def anchor():
    h=bytearray(512);payload=ANCHOR_FRAMES*8
    h[0:4]=b'RIFF';struct.pack_into('<I',h,4,payload+504);h[8:16]=b'WAVEfmt '
    struct.pack_into('<IHHIIHH',h,16,16,3,2,48000,384000,8,32)
    h[36:40]=b'JUNK';struct.pack_into('<I',h,40,460);h[504:508]=b'data';struct.pack_into('<I',h,508,payload)
    return bytes(h)+bytes(payload)

def trial():
    stock=SOURCE.read_bytes();require(digest(stock)==STOCK_SHA,'unsupported stock firmware')
    validate(stock);elf=build(trial=True);t=plan(elf,trial=True);p=t['pack']
    data=assemble(stock,t);names=p['names'];wav=anchor()
    report=dict(experiment=24,mode='master',status='prepared_locally_not_staged',trial_sha256=digest(data),
        stock_sha256=STOCK_SHA,elf_sha256=digest(elf.read_bytes()),patches=t['patches'],DSP_patches=[],
        metadata_edits=p['edits'],code_bytes=len(p['code']),globals_bytes=t['globals_bytes'],
        spare_bytes=t['packing']['spare_bytes'],
        code_start=names['placement_code_start'],code_end=names['placement_load_end'],
        globals_start=names['placement_globals_start'],globals_end=names['placement_globals_end'],
        code_source=p['code_source'],worker_stack_words=2048,native_capacity_frames=240000,files_created=False,
        anchor=dict(card_path='A:\\SOUND_PAD\\PAD1\\MASTER.WAV',bytes=len(wav),sha256=digest(wav),
                    format='48 kHz stereo 32-bit float, 0.1 s silence, 512-byte header'),
        protocol='6F/6E kind7 schema1; recorder/worker/handoff/heap words and the assigned path',
        unchanged=['Stock DSP code, ring size, recorder, SD driver and recording files',
                   'MAIN length, container descriptors, PANEL and AUDIOGUIDE regions'],
        limitations=['First hardware run of pad 1 playing a stock master in place from A:\\RECORDER',
            'Stock reload keeps the reference only while PAD1 lists MASTER.WAV (the anchor)',
            'Deleting the referenced take folder, and pad playback while a new take records, are untested',
            'Worker stack is measured by painting 7 KiB below its entry frame',
            'Early-hang recovery (experiment 18) is parked and unproven',
            'No installation, staging or installed-flash readback is performed by this builder'])
    return data,wav,report,t

def main():
    data,wav,report,_=trial()
    for path,content in ((OUT/'trial_master_ref'/'L6.BIN',data),(OUT/'anchor'/'MASTER.WAV',wav)):
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=content:raise SystemExit(f'Refusing to overwrite a different {path.name}')
        if not path.exists():path.write_bytes(content)
    write_manifest(OUT/'manifest.json',report)
    print(json.dumps({k:report[k] for k in ('trial_sha256','code_bytes','globals_bytes','spare_bytes')}))
if __name__=='__main__':main()
