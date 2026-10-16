#!/usr/bin/env python3
"""Build the master-reference images locally: the 0.1.0 release and every
earlier experiment, byte for byte. No device access.

Every mode must reproduce its image's hash exactly; all but `release` are
pinned to the commit their image was built from (24-26, 28-30, 32 and 33 were
installed; 27 and 31 were prepared and superseded before installation).

reference    (24) pad 1 plays the last take's master
chain        (25) pads 1-4 play the last four takes, newest on pad 1
minimum      (26) as chain; takes under 2 s stay off the pads
everyday     (27) 26 without diagnostics (no status query, no stack paint)
history      (28) the chain plus HISTORY.TXT in each take folder
daily        (29) 28 without diagnostics
stereo       (30) 28 plus an always-on stereo AUX pair (AUX 1 left, AUX 2 right)
daily_stereo (31) 30 without diagnostics
switch       (32) 30 with the mono/stereo switch (hold AUX 1 + AUX 2 for 1.5 s)
daily_switch (33) 32 without diagnostics, with the switch review fixes
review       (34) 33 plus the release review fixes
chain_switch (35) 34 plus the PAN + LEVEL chain on/off switch
tolerant     (36) 35 with misread-tolerant switch holds
panel_diag   (37) diagnostic: 36 with the status query and switch diagnostics
release      (38) version 0.1.0: 36 with EFX + PAN for the chain, armed ~4 s after power-on (default)

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
D='deployment/'
# Each mode: its experiment, output folder and image name, the commit its
# sources are pinned to and the image hash that must come out (installed or
# released images rebuild byte for byte), the pads it uses, whether it is a
# diagnostic (trial) build, and its features.
MODES=dict(
    reference=dict(experiment=24,out=ROOT/D/'24_master_ref',image='trial_master_ref',pin='5765dbf',pads=1,
                   sha='cb6d34fd9d5f576469e89d440d8affad40345d62611d87a1c36e2b7705d72574'),
    chain=dict(experiment=25,out=ROOT/D/'25_take_chain',image='trial_take_chain',pin='2fc1c7d',pads=4,
               sha='e3168b78c7d159678b7e7cc9762d5b724eaa05cd9ae740433a3ce678456e6713'),
    minimum=dict(experiment=26,out=ROOT/D/'26_short_takes',image='trial_short_takes',pin='da89fc3',pads=4,minimum=True,
                 sha='268f1a76a4f8c49a4498cf8d9881201effe83484cd19845a6ed38b62e2c6edf9'),
    everyday=dict(experiment=27,out=ROOT/D/'27_everyday',image='everyday',pin='068a5cc',pads=4,trial=False,minimum=True,
                  sha='5b9bb4e56abaf1d4890e92f301804834cd5f8c2dacdb7345cf55592574d12300'),
    history=dict(experiment=28,out=ROOT/D/'28_take_history',image='trial_take_history',pin='5c39ab8',pads=4,minimum=True,history=True,
                 sha='e22e388293f4b0ce84e09fac3fc5d9bb8db6670189fad5a1db290d0bc0944f2c'),
    daily=dict(experiment=29,out=ROOT/D/'29_daily',image='daily',pin='f8f2170',pads=4,trial=False,minimum=True,history=True,
               sha='510a057e866963243018a0a9025185af6071b9d79538ce4084a01f4251474fde'),
    stereo=dict(experiment=30,out=ROOT/D/'30_stereo_aux',image='trial_stereo_aux',pin='cce6f50',pads=4,minimum=True,history=True,stereo=True,
                sha='5b3ad135ebd19d31aa5f1acd8c6030b6a870344536c881f881be58d6c70eeb31'),
    daily_stereo=dict(experiment=31,out=ROOT/D/'31_daily_stereo',image='daily_stereo',pin='cda0f26',pads=4,trial=False,minimum=True,
                      history=True,stereo=True,sha='c618db4e8c1dcb3f9f7130bcde30c22c48397e0b489bfa9073a2446807ff818b'),
    switch=dict(experiment=32,out=ROOT/D/'32_aux_switch',image='trial_aux_switch',pin='3f8e199',pads=4,minimum=True,history=True,
                stereo=True,switch=True,sha='8acd59d46f9274c7c2c933f28b978b03a17335036b122db2431e313e3f1c721f'),
    daily_switch=dict(experiment=33,out=ROOT/D/'33_daily_switch',image='daily_switch',pin='cccb5b6',pads=4,trial=False,minimum=True,
                      history=True,stereo=True,switch=True,sha='36f2025bb62ad9d655e02f24769fcbede910cb53a26e87782cabfa9157e04ab9'),
    review=dict(experiment=34,out=ROOT/D/'34_release_review',image='review',pin='1c3e4bf',pads=4,trial=False,minimum=True,
                history=True,stereo=True,switch=True,sha='47d9f90d8fab846a3a28f51a28ff22332435c6d7ad7058fb2ea585d8be8a3e59'),
    chain_switch=dict(experiment=35,out=ROOT/D/'35_release',image='release',pin='e258bd6',pads=4,trial=False,minimum=True,
                      history=True,stereo=True,switch=True,chain_switch=True,
                      sha='824e37c69c2086b4c4464b14ab5b698c32d154352b0aa1537095fd6cb5134932'),
    # Release 0.1.0: experiment 35 with misread-tolerant switch holds. Built from
    # the current sources (so a ZIP download builds it too); once installed it is
    # held to its published hash, and pinned to the v0.1.0 tag when these
    # sources change.
    tolerant=dict(experiment=36,out=ROOT/D/'36_release',image='release',pin='2a2b910',pads=4,trial=False,minimum=True,
                  history=True,stereo=True,switch=True,chain_switch=True,
                  sha='c796f4e6bd0f2b5f3d11b2594cdc882a40765af43e3d0b0b41eb4c2f6d08d5af'),
    # Diagnostic: 36 with the status query and the panel switch diagnostics
    # (key changes, hold events, poll intervals, startup ticks).
    panel_diag=dict(experiment=37,out=ROOT/D/'37_panel_diag',image='panel_diag',pin='f975842',pads=4,minimum=True,history=True,
                    stereo=True,switch=True,chain_switch=True,diag=True,
                    sha='b4c1c3c7fd99fa64627abdc52d9615be04e9bb3e8c3df5b37af637413d9985ae'),
    # Release 0.1.0: 36 with the chain switched by EFX + PAN and the switches
    # armed 1 s after Main is ready; installed 16 October 2026. Built from the
    # current sources (so a ZIP download builds it too) and held to its
    # published hash; pin it to the v0.1.0 tag when these sources change.
    release=dict(experiment=38,out=ROOT/D/'38_release',image='release',pads=4,trial=False,minimum=True,
                 history=True,stereo=True,switch=True,chain_switch=True,version='0.1.0',
                 sha='99ded4b1fcefa1d968a7317e5df4ee65c670018c4a495cfc1ed903aa5aa70bb0'))

@contextlib.contextmanager
def trial_elf(m):
    """The ELF: current sources, or the pinned commit's in a temporary tree."""
    if 'pin' not in m:yield build(trial=m.get('trial',True),stereo=m.get('stereo',False),diag=m.get('diag',False));return
    archive=subprocess.run(['git','archive',m['pin'],*PINNED_SOURCES],cwd=ROOT,capture_output=True,check=True).stdout
    with tempfile.TemporaryDirectory(prefix='l6-pinned-') as tree:
        tarfile.open(fileobj=io.BytesIO(archive)).extractall(tree,filter='data')
        yield build(trial=m.get('trial',True),root=Path(tree),stereo=m.get('stereo',False),diag=m.get('diag',False))

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
    diagnostic=m.get('trial',True)
    with trial_elf(m) as elf:t=plan(elf,trial=diagnostic);elf_sha=digest(elf.read_bytes())
    p=t['pack']
    data=assemble(stock,t);names=p['names'];wav=anchor()
    # The features the mode promises are the hooks the plan patched.
    adapters={q['adapter'] for q in t['patches']}
    for hook,wanted in (('health_parser',diagnostic),('mr_play_hook',m.get('history',False)),('sa_ramp',m.get('stereo',False))):
        require((hook in adapters)==wanted,f'{mode}: {hook} patched: {hook in adapters}, expected {wanted}')
    if 'sha' in m:require(digest(data)==m['sha'],f'{mode}: image {digest(data)} differs from the expected {m["sha"]}')
    pads=[f'A:\\SOUND_PAD\\PAD{n}\\MASTER.WAV' for n in range(1,m['pads']+1)]
    report=dict(experiment=m['experiment'],mode='master' if mode=='reference' else mode,version=m.get('version'),
        minimum_take_seconds=2 if m.get('minimum') else None,
        take_history=m.get('history',False),stereo_aux=m.get('stereo',False),
        aux_switch=m.get('switch',False),chain_switch=m.get('chain_switch',False),status='built',expected_sha256=m.get('sha'),trial_sha256=digest(data),
        stock_sha256=STOCK_SHA,elf_sha256=elf_sha,patches=t['patches'],DSP_patches=[],
        metadata_edits=p['edits'],code_bytes=len(p['code']),globals_bytes=t['globals_bytes'],
        spare_bytes=t['packing']['spare_bytes'],
        code_start=names['placement_code_start'],code_end=names['placement_load_end'],
        globals_start=names['placement_globals_start'],globals_end=names['placement_globals_end'],
        code_source=p['code_source'],worker_stack_words=2048,diagnostics=diagnostic,native_capacity_frames=240000,files_created=False,
        anchor=dict(card_path=pads[0],card_paths=pads,bytes=len(wav),sha256=digest(wav),
                    format='48 kHz stereo 32-bit float, 0.1 s silence, 512-byte header'),
        protocol=('6F/6E kind7 schema1; recorder/worker/handoff/heap words and the assigned path' if mode=='reference'
                  else 'none: no status query' if not diagnostic
                  else '6F/6E kind7 schema6; schema 5 with the panel switch diagnostics in place of the AUX gain rows' if m.get('diag')
                  else '6F/6E kind7 schema5; as schema 4 plus the AUX mode, toggles and refusals' if mode=='switch'
                  else '6F/6E kind7 schema4; as schema 3 plus the AUX1 and AUX2 gain rows' if mode=='stereo'
                  else '6F/6E kind7 schema3; as schema 2 plus history written/failed/status/entries and pad files played' if mode=='history'
                  else '6F/6E kind7 schema2; recorder/worker/handoff/heap words, chain mask and each pad\'s saved take'),
        unchanged=['Stock DSP code, ring size, recorder, SD driver and recording files',
                   'MAIN length, container descriptors, PANEL and AUDIOGUIDE regions'],
        limitations=(['First hardware run of pad 1 playing a stock master in place from A:\\RECORDER',
            'Stock reload keeps the reference only while PAD1 lists MASTER.WAV (the anchor)'] if mode=='reference' else
            ['First hardware run of four queued assignments per take (one per pad)',
             'Stock reload keeps each reference only while that pad folder lists MASTER.WAV',
             'Four masters play from A:\\RECORDER while a take records: card load is untested']+
            (['Takes under 2 s (96,000 frames, from the master header) are refused as short'] if m.get('minimum') else [])+
            (['First hardware run of the AUX 1 + AUX 2 hold switch, its LED feedback and the mode bytes in the internal settings',
              'Starts in mono until switched; factory reset leaves the mode as it was'] if mode=='switch' else [])+
            (['First hardware run of the review fixes: refusal during pad recordings, the LED show ending from Main, stock mono without the worker',
              'Keeps the mode stored by experiment 32 (stereo when last switched to stereo)'] if mode=='daily_switch' else [])+
            (['History newest first, at most 100 lines (OMITTED), version 2; file calls also wait during pad recordings and playback'] if m['experiment']>=34 else [])+
            (['First hardware run of the PAN + LEVEL chain on/off switch and its persistence'] if m.get('chain_switch') else [])+
            (['First hardware run of the stereo AUX pair: jack order, separation, level, delay and the per-bus limiters are unmeasured',
              'Startup restore relies on the stock bulk recompute after the direct unity reset'] if mode=='stereo' else [])+
            (['First hardware run of the pad-start hook (0x80018316) and of writing HISTORY.TXT into take folders'] if mode=='history' else [])+
            (['Power loss during the history write (directory sector shared with the take files) is untested'] if m.get('history') else [])+
            (['Stereo AUX is always on; mono-channel pan, scene recall and Editor changes are verified in emulation only'] if mode=='daily_stereo' else [])+
            (['No status query: hardware behaviour is checked by ear and from the saved pad paths'] if not diagnostic else []))+[
            *(['Deleting a referenced take folder is untested'] if m['experiment']<29 else []),
            *(['Worker stack is measured by painting 7 KiB below its entry frame'] if diagnostic else []),
            'Early-hang recovery (experiment 18) is parked and unproven',
            'No installation, staging or installed-flash readback is performed by this builder'])
    return data,wav,report,t

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('mode',nargs='?',choices=MODES,default='release')
    mode=a.parse_args().mode;m=MODES[mode];out=m['out']
    data,wav,report,_=trial(mode)
    for path,content in ((out/m['image']/'L6.BIN',data),(out/'anchor'/'MASTER.WAV',wav)):
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=content:raise SystemExit(f'Refusing to overwrite a different {path.name}')
        if not path.exists():path.write_bytes(content)
    write_manifest(out/'manifest.json',report)
    print(json.dumps({k:report[k] for k in ('trial_sha256','code_bytes','globals_bytes','spare_bytes')}))
if __name__=='__main__':main()
