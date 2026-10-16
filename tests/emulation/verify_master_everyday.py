#!/usr/bin/env python3
"""Exact release image (0.2.0, experiment 40): the take chain with its on/off
switch, take history, the switchable stereo AUX and the anchors written by
the firmware, without diagnostics. Original reset and scatter
expand it; the Editor parser, the DSP code and the ring size stay stock. Behaviour on this build is checked by
`verify_master_ref.py everyday` (every group on the clean ELF) and
`verify_stereo_aux_hooks.py everyday`. No device access.
"""
import json,struct
from unicorn import UC_HOOK_CODE
from verify_pad_protocol import ROOT,IMAGE,BIAS
from unicorn import arm_const as A
from verify_overdub_prototype import Emulator
from build_master_trial import trial,MODES
from build_deployment_probe import validate,digest
from capture_jump_patches import SCATTER
from plan_capture_composed import SIZE_SITE
from plan_capture_packing import DECOMPRESS,ZERO
from plan_simple_capture import QUERY_SPEC
from scatter_codec import expand
import recipe as recipes

DATA,ANCHOR,MANIFEST,T=trial('release');TP=T['pack'];TN=TP['names'];OUT=MODES['release']['out']
EXPERIMENT26='268f1a76a4f8c49a4498cf8d9881201effe83484cd19845a6ed38b62e2c6edf9'
EXPERIMENT27='5b9bb4e56abaf1d4890e92f301804834cd5f8c2dacdb7345cf55592574d12300'
EXPERIMENT28='e22e388293f4b0ce84e09fac3fc5d9bb8db6670189fad5a1db290d0bc0944f2c'
EXPERIMENT29='510a057e866963243018a0a9025185af6071b9d79538ce4084a01f4251474fde'
EXPERIMENT30='5b3ad135ebd19d31aa5f1acd8c6030b6a870344536c881f881be58d6c70eeb31'
EXPERIMENT31='c618db4e8c1dcb3f9f7130bcde30c22c48397e0b489bfa9073a2446807ff818b'
EXPERIMENT32='8acd59d46f9274c7c2c933f28b978b03a17335036b122db2431e313e3f1c721f'
EXPERIMENT33='36f2025bb62ad9d655e02f24769fcbede910cb53a26e87782cabfa9157e04ab9'
EXPERIMENT34='47d9f90d8fab846a3a28f51a28ff22332435c6d7ad7058fb2ea585d8be8a3e59'
EXPERIMENT35='824e37c69c2086b4c4464b14ab5b698c32d154352b0aa1537095fd6cb5134932'
EXPERIMENT36='c796f4e6bd0f2b5f3d11b2594cdc882a40765af43e3d0b0b41eb4c2f6d08d5af'
EXPERIMENT38='99ded4b1fcefa1d968a7317e5df4ee65c670018c4a495cfc1ed903aa5aa70bb0'   # release 0.1.0

def boot():
    m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True);u=m.uc
    for a,n in ((0,0x1000),(0x81000000,0x1000000),(0x20210000,0x20000),(0xe000e000,0x1000)):u.mem_map(a,n)
    u.mem_write(0x80001000,DATA[0x200:0xb5ce4]);seen=[]
    h=u.hook_add(UC_HOOK_CODE,lambda u,a,n,x:seen.append(a) or u.emu_stop(),begin=0x80067a60,end=0x80067a60)
    u.emu_start(0x80001401,0x80067a62,count=100000000);u.hook_del(h)
    assert seen==[0x80067a60]
    for at in range(0x800a68dc,0x800a695c,16):
        s,d,n,helper=struct.unpack_from('<4I',IMAGE,at-BIAS)
        if d==SCATTER[1]:expected=IMAGE[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]]
        else:expected=bytes(n) if helper==ZERO else expand(IMAGE[s-BIAS:],n)[0] if helper==DECOMPRESS else IMAGE[s-BIAS:s-BIAS+n]
        assert bytes(u.mem_read(d,n))==expected,(hex(d),n)
    assert bytes(u.mem_read(MANIFEST['code_start'],len(TP['code'])))==TP['code']

def main():
    cases=[]
    def passed(case,**details):cases.append(dict(case=case,**details))

    for mode,sha in (('minimum',EXPERIMENT26),('everyday',EXPERIMENT27),('history',EXPERIMENT28),
                     ('daily',EXPERIMENT29),('stereo',EXPERIMENT30),('daily_stereo',EXPERIMENT31),
                     ('switch',EXPERIMENT32),('daily_switch',EXPERIMENT33),('review',EXPERIMENT34),
                     ('chain_switch',EXPERIMENT35),('tolerant',EXPERIMENT36),('release_0_1_0',EXPERIMENT38)):
        assert digest(trial(mode)[0])==sha==MODES[mode]['sha'],mode
        local=MODES[mode]['out']/MODES[mode]['image']/'L6.BIN'   # an installed image kept locally
        assert not local.exists() or digest(local.read_bytes())==sha,mode
    local=OUT/MODES['release']['image']/'L6.BIN'
    assert not local.exists() or local.read_bytes()==DATA and (OUT/'anchor/MASTER.WAV').read_bytes()==ANCHOR
    validate(DATA);assert len(DATA)==len(IMAGE) and DATA[0x2851f8:]==IMAGE[0x2851f8:]
    adapters=sorted(p['adapter'] for p in MANIFEST['patches'])
    assert len(adapters)==15 and adapters.count('mr_main_receive')==5 and 'mr_play_hook' in adapters and 'health_parser' not in adapters
    assert {'sa_ramp','sa_mono_pan','sa_balance','sa_reset1','sa_reset2'}<=set(adapters)
    q=QUERY_SPEC['site']-BIAS;assert DATA[q:q+4]==IMAGE[q:q+4]==bytes.fromhex(QUERY_SPEC['original'])
    assert DATA[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]==IMAGE[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]
    assert not any(n in TN for n in ('mr_query','health_parser','mr_stack_low'))
    assert MANIFEST['experiment']==40 and MANIFEST['version']=='0.2.0' and MANIFEST['chain_switch'] and not MANIFEST['diagnostics'] and MANIFEST['minimum_take_seconds']==2
    assert MANIFEST['anchors_written'] and 'mr_main_waits' in TN
    assert MANIFEST['take_history'] and MANIFEST['stereo_aux'] and MANIFEST['aux_switch']
    assert {'sa_toggle','panel_poll','panel_restore','panel_show','mr_chain_toggles'}<=set(TN)
    words=struct.unpack_from('<II',DATA,0x800a6930-BIAS)+struct.unpack_from('<II',DATA,0x800a6940-BIAS)
    assert (words[0],words[0]+words[1],words[2],words[2]+words[3])==tuple(
        MANIFEST[k] for k in ('code_start','code_end','globals_start','globals_end'))
    passed('exact_image_has_fifteen_sites_and_leaves_the_editor_parser_DSP_code_and_ring_size_stock',
           trial_sha256=MANIFEST['trial_sha256'],code_bytes=MANIFEST['code_bytes'],
           globals_bytes=MANIFEST['globals_bytes'],spare_bytes=MANIFEST['spare_bytes'],
           rebuilt=dict(experiment26=EXPERIMENT26,experiment27=EXPERIMENT27,experiment28=EXPERIMENT28,
                        experiment29=EXPERIMENT29,experiment30=EXPERIMENT30,
                        experiment31=EXPERIMENT31,experiment32=EXPERIMENT32,experiment33=EXPERIMENT33,
                        experiment34=EXPERIMENT34,experiment35=EXPERIMENT35,
                        experiment36=EXPERIMENT36,experiment38=EXPERIMENT38))
    boot()
    passed('original_reset_and_scatter_expand_the_image_with_the_stock_DSP_code')
    # The browser patcher's recipe rebuilds this image from stock (make()
    # checks it), ships no stock bytes, and the committed copy is current.
    recipe=recipes.make(IMAGE,DATA,TP,MANIFEST['version'])
    assert recipes.stock_bytes(IMAGE,recipe)==0 and recipes.rebuild(IMAGE,recipe)==DATA
    shelf=ROOT/'patcher/recipes';committed=json.loads((shelf/f"{MANIFEST['version']}.json").read_text())
    assert committed==recipe,'patcher/recipes is stale: run tools/firmware/build_release.py'
    assert json.loads((shelf/'index.json').read_text())['current']==MANIFEST['version']
    passed('the_patcher_recipe_rebuilds_the_image_without_stock_bytes',ops=len(recipe['ops']),
           skeleton_bytes=len(recipes.unb64(recipe['span']['skeleton'])))
    result=dict(passed=True,passed_groups=len(cases),results=cases,trial_sha256=MANIFEST['trial_sha256'])
    (ROOT/'analysis/master_everyday_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
