#!/usr/bin/env python3
"""Exact short-take trial image and anchor file (experiment 26).

The installed images of experiments 24 and 25 must still rebuild byte for byte.

Original reset and scatter expand the image; the stock DSP code and ring size
are unchanged. The status query runs on the trial build after an emulated take
and is decoded by the device probe. No device or card access.
"""
import json,struct,sys
from unicorn import UC_HOOK_CODE
from verify_master_ref import MasterRig,MasterBoot,MASTER,H_ASSIGNED,config,take_master
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT
import verify_health_probe as health
from build_deployment_probe import digest
from build_master_trial import trial,MODES,ANCHOR_FRAMES
from verify_record_catalogue import putstr
from build_deployment_probe import validate
from capture_jump_patches import SCATTER
from plan_capture_composed import SIZE_SITE
from plan_capture_packing import DECOMPRESS,ZERO
from scatter_codec import expand
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_padref_probe import request,decode,validate_samples,validate_take

IMAGE24,ANCHOR,MANIFEST,T=trial('minimum');TP=T['pack'];TN=TP['names'];OUT=MODES['minimum']['out']
EXPERIMENT24='cb6d34fd9d5f576469e89d440d8affad40345d62611d87a1c36e2b7705d72574'
EXPERIMENT25='e3168b78c7d159678b7e7cc9762d5b724eaa05cd9ae740433a3ce678456e6713'

def boot():
    m=health.machine(False);u=m.uc
    for a,n in ((0,0x1000),(0x81000000,0x1000000),(0x20210000,0x20000),(0xe000e000,0x1000)):u.mem_map(a,n)
    u.mem_write(0x80001000,IMAGE24[0x200:0xb5ce4]);seen=[]
    h=u.hook_add(UC_HOOK_CODE,lambda u,a,n,x:seen.append(a) or u.emu_stop(),begin=0x80067a60,end=0x80067a60)
    u.emu_start(0x80001401,0x80067a62,count=100000000);u.hook_del(h)
    assert seen==[0x80067a60]
    for at in range(0x800a68dc,0x800a695c,16):
        s,d,n,helper=struct.unpack_from('<4I',IMAGE,at-BIAS)
        if d==SCATTER[1]:expected=IMAGE[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]]  # stock DSP, now decompressed
        else:expected=bytes(n) if helper==ZERO else expand(IMAGE[s-BIAS:],n)[0] if helper==DECOMPRESS else IMAGE[s-BIAS:s-BIAS+n]
        assert bytes(u.mem_read(d,n))==expected,(hex(d),n)
    assert bytes(u.mem_read(MANIFEST['code_start'],len(TP['code'])))==TP['code']
    g=MANIFEST['globals_start'],MANIFEST['globals_end']
    assert bytes(u.mem_read(g[0],g[1]-g[0]))==bytes(g[1]-g[0])

class TrialRig(MasterRig):
    def query(self):
        replies=[];self.m.hooks[0x80031648]=lambda a:replies.append(bytes(self.m.uc.mem_read(a[0],a[1]))) or 0
        self.m.uc.mem_write(INPUT,struct.pack('<I',8)+request(7)+bytes(16));self.m.uc.mem_write(0x80629b60,b'\x02')
        assert self.m.invoke(TN['mr_query'],[INPUT])==1
        return decode(replies[-1])

def main():
    cases=[]
    def passed(case,**details):cases.append(dict(case=case,**details))

    old=trial('reference')[0];assert digest(old)==EXPERIMENT24==digest((MODES['reference']['out']/'trial_master_ref/L6.BIN').read_bytes())
    old=trial('chain')[0];assert digest(old)==EXPERIMENT25==digest((MODES['chain']['out']/'trial_take_chain/L6.BIN').read_bytes())
    passed('experiment_24_and_25_installed_images_rebuild_byte_for_byte_from_their_pinned_sources',
           experiment24=EXPERIMENT24,experiment25=EXPERIMENT25)
    assert (OUT/'trial_short_takes/L6.BIN').read_bytes()==IMAGE24 and (OUT/'anchor/MASTER.WAV').read_bytes()==ANCHOR
    validate(IMAGE24);assert len(IMAGE24)==len(IMAGE) and IMAGE24[0x2851f8:]==IMAGE[0x2851f8:]
    adapters=sorted(p['adapter'] for p in MANIFEST['patches'])
    assert len(adapters)==10 and adapters.count('mr_main_receive')==5 and not MANIFEST['DSP_patches']
    assert {'mr_admit_hook','mr_stop_hook','health_parser','startup_init_hook','startup_idle_hook'}<=set(adapters)
    assert IMAGE24[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]==IMAGE[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]==bytes.fromhex('4af68011')
    assert MANIFEST['experiment']==26 and MANIFEST['minimum_take_seconds']==2 and len(MANIFEST['anchor']['card_paths'])==4 and not MANIFEST['files_created'] and MANIFEST['native_capacity_frames']==240000
    # The query's bounds words read the scatter records that place the code.
    words=struct.unpack_from('<IIII',IMAGE24,0x800a6930-BIAS)[:2]+struct.unpack_from('<II',IMAGE24,0x800a6940-BIAS)
    assert (words[0],words[0]+words[1],words[2],words[2]+words[3])==tuple(
        MANIFEST[k] for k in ('code_start','code_end','globals_start','globals_end')),words
    passed('exact_image_has_ten_sites_and_leaves_the_DSP_code_and_ring_size_stock',
           trial_sha256=MANIFEST['trial_sha256'],code_bytes=MANIFEST['code_bytes'],
           globals_bytes=MANIFEST['globals_bytes'],spare_bytes=MANIFEST['spare_bytes'])

    boot()
    passed('original_reset_and_scatter_expand_the_image_with_the_stock_DSP_code')

    b=MasterBoot();b.boot()
    assert b.created==[(b'L6PadRef\0',2048,1)] and b.word(TN['mr_startup_status'])==4
    passed('original_startup_registers_the_worker_at_priority_1_with_an_8_KiB_stack')

    # Anchor: the 512-byte header layout experiment 21's accepted files used.
    h=ANCHOR[:512]
    assert h[:4]==b'RIFF' and h[8:16]==b'WAVEfmt ' and h[36:40]==b'JUNK' and h[504:508]==b'data'
    assert struct.unpack_from('<IHHIIHH',h,16)==(16,3,2,48000,384000,8,32)
    assert struct.unpack_from('<I',h,4)[0]==len(ANCHOR)-8 and struct.unpack_from('<I',h,508)[0]==ANCHOR_FRAMES*8
    assert ANCHOR[512:]==bytes(ANCHOR_FRAMES*8) and MANIFEST['anchor']['bytes']==len(ANCHOR)
    passed('anchor_is_a_short_silent_48_kHz_stereo_float_WAV',bytes=len(ANCHOR),sha256=MANIFEST['anchor']['sha256'])

    # Status: idle samples, then one emulated take decoded by the probe.
    r=TrialRig();r.set('task',0x80900000)
    r.m.uc.mem_write(TN['mr_startup_status'],struct.pack('<I',4))   # as the boot group registered it
    idle=[r.query()]
    idle[0].update(free_bytes=140936,minimum_free_bytes=140000,stack_used=1024,ccr=0x70200,
                   code_start=MANIFEST['code_start'],code_end=MANIFEST['code_end'],
                   globals_start=MANIFEST['globals_start'],globals_end=MANIFEST['globals_end'])
    later=dict(idle[0],ticks=idle[0]['ticks']+1000,polls=idle[0]['polls']+30)
    validate_samples([idle[0],later],MANIFEST)
    hand=[take_master(9),'A:\\SOUND_PAD\\PAD2\\GLORY_BOX.WAV',take_master(8),'A:\\RECORDER\\261011_140007\\MASTER_01.WAV']
    for p,path in enumerate(hand):putstr(r.m,config(p),path)
    before=r.query();assert before['pads']==['261011_140009','#GLORY_BOX.WAV','261011_140008','#MASTER_01.WAV'],before['pads']
    r.take();r.settle();r.deliver();assert r.field('handoff_state')==H_ASSIGNED
    after=r.query();after.update(stack_used=1024,minimum_free_bytes=140000)
    before.update(stack_used=1024)
    take=validate_take(before,after)
    assert take['assigned_path']==MASTER and take['take_folder']=='261011_130947' and take['master_bytes']==20_000_910
    # Pad 2's hand-picked sound is overwritten; pad 3 already holds its take;
    # pad 4's non-take keeps its place past the end of the chain.
    assert after['pads']==['261011_130947','261011_140009','261011_140008','#MASTER_01.WAV'] and after['chain_mask']==0b11
    for bad in (dict(last_status=4),dict(handoff_state=4),dict(stop_faults=1),dict(chain_mask=1),
                dict(pads=[after['pads'][0],'#GLORY_BOX.WAV']+after['pads'][2:]),
                dict(pads=after['pads'][:3]+['261011_140008']),dict(pads=before['pads'])):
        try:validate_take(before,dict(after,**bad))
        except ValueError:continue
        raise AssertionError(f'probe accepted {bad}')
    passed('status_query_reports_each_pads_saved_take_and_the_probe_validates_the_shift',take=take)

    result=dict(passed=True,passed_groups=len(cases),results=cases,trial_sha256=MANIFEST['trial_sha256'],
        limitations=['Query fields that depend on hardware (heap, caches, stack) are supplied in the probe check',
                     'Anchor acceptance rests on the experiment 21 header evidence; the RIFF parser is modeled here'])
    (ROOT/'analysis/master_ref_trial_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
