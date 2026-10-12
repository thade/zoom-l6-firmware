#!/usr/bin/env python3
"""Prepare the master-reference trials locally. No device access.

reference (experiment 24): pad 1 plays the last take's master. Rebuilt from
          the sources it was installed from.
chain     (experiment 25): pads 1-4 play the last four takes, newest on pad 1.

Writes the trial image and the anchor file: a short silent 48 kHz stereo
32-bit float WAV with the same 512-byte header layout as the extra files the
stock validator and loader accepted in experiment 21. Staging copies it to
A:\\SOUND_PAD\\PADn\\MASTER.WAV for each pad the trial uses.
"""
import argparse,contextlib,io,json,struct,subprocess,tarfile,tempfile
from pathlib import Path
from build_deployment_probe import ROOT,SOURCE,STOCK_SHA,validate,digest,write_manifest
from build_master_ref import build
from build_simple_trial import assemble,require
from plan_master_ref import plan

ANCHOR_FRAMES=4800   # 0.1 s of silence
PINNED_SOURCES=('src/capture/master','src/capture/hook_macros.inc','src/capture/retention.h',
                'src/diagnostics/health_hooks.S','tests/fixtures/capture_source_reuse.ld')
MODES=dict(reference=dict(experiment=24,out=ROOT/'deployment/24_master_ref',image='trial_master_ref',pin='5765dbf',pads=1),
           chain=dict(experiment=25,out=ROOT/'deployment/25_take_chain',image='trial_take_chain',pads=4))
OUT=MODES['reference']['out']

@contextlib.contextmanager
def trial_elf(m):
    """The trial ELF: current sources, or the pinned commit's in a temporary tree."""
    if 'pin' not in m:yield build(trial=True);return
    archive=subprocess.run(['git','archive',m['pin'],*PINNED_SOURCES],cwd=ROOT,capture_output=True,check=True).stdout
    with tempfile.TemporaryDirectory(prefix='l6-pinned-') as tree:
        tarfile.open(fileobj=io.BytesIO(archive)).extractall(tree,filter='data')
        yield build(trial=True,root=Path(tree))

def anchor():
    h=bytearray(512);payload=ANCHOR_FRAMES*8
    h[0:4]=b'RIFF';struct.pack_into('<I',h,4,payload+504);h[8:16]=b'WAVEfmt '
    struct.pack_into('<IHHIIHH',h,16,16,3,2,48000,384000,8,32)
    h[36:40]=b'JUNK';struct.pack_into('<I',h,40,460);h[504:508]=b'data';struct.pack_into('<I',h,508,payload)
    return bytes(h)+bytes(payload)

def trial(mode='reference'):
    m=MODES[mode]
    stock=SOURCE.read_bytes();require(digest(stock)==STOCK_SHA,'unsupported stock firmware')
    validate(stock)
    with trial_elf(m) as elf:t=plan(elf,trial=True);elf_sha=digest(elf.read_bytes())
    p=t['pack']
    data=assemble(stock,t);names=p['names'];wav=anchor()
    pads=[f'A:\\SOUND_PAD\\PAD{n}\\MASTER.WAV' for n in range(1,m['pads']+1)]
    report=dict(experiment=m['experiment'],mode='master' if mode=='reference' else mode,status='prepared_locally_not_staged',trial_sha256=digest(data),
        stock_sha256=STOCK_SHA,elf_sha256=elf_sha,patches=t['patches'],DSP_patches=[],
        metadata_edits=p['edits'],code_bytes=len(p['code']),globals_bytes=t['globals_bytes'],
        spare_bytes=t['packing']['spare_bytes'],
        code_start=names['placement_code_start'],code_end=names['placement_load_end'],
        globals_start=names['placement_globals_start'],globals_end=names['placement_globals_end'],
        code_source=p['code_source'],worker_stack_words=2048,native_capacity_frames=240000,files_created=False,
        anchor=dict(card_path=pads[0],card_paths=pads,bytes=len(wav),sha256=digest(wav),
                    format='48 kHz stereo 32-bit float, 0.1 s silence, 512-byte header'),
        protocol=('6F/6E kind7 schema1; recorder/worker/handoff/heap words and the assigned path' if mode=='reference'
                  else '6F/6E kind7 schema2; recorder/worker/handoff/heap words, chain mask and each pad\'s saved take'),
        unchanged=['Stock DSP code, ring size, recorder, SD driver and recording files',
                   'MAIN length, container descriptors, PANEL and AUDIOGUIDE regions'],
        limitations=(['First hardware run of pad 1 playing a stock master in place from A:\\RECORDER',
            'Stock reload keeps the reference only while PAD1 lists MASTER.WAV (the anchor)'] if mode=='reference' else
            ['First hardware run of four queued assignments per take (one per pad)',
             'Stock reload keeps each reference only while that pad folder lists MASTER.WAV',
             'Four masters play from A:\\RECORDER while a take records: card load is untested'])+[
            'Deleting a referenced take folder is untested',
            'Worker stack is measured by painting 7 KiB below its entry frame',
            'Early-hang recovery (experiment 18) is parked and unproven',
            'No installation, staging or installed-flash readback is performed by this builder'])
    return data,wav,report,t

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('mode',nargs='?',choices=MODES,default='chain')
    mode=a.parse_args().mode;m=MODES[mode];out=m['out']
    data,wav,report,_=trial(mode)
    for path,content in ((out/m['image']/'L6.BIN',data),(out/'anchor'/'MASTER.WAV',wav)):
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=content:raise SystemExit(f'Refusing to overwrite a different {path.name}')
        if not path.exists():path.write_bytes(content)
    write_manifest(out/'manifest.json',report)
    print(json.dumps({k:report[k] for k in ('trial_sha256','code_bytes','globals_bytes','spare_bytes')}))
if __name__=='__main__':main()
