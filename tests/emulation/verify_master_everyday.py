#!/usr/bin/env python3
"""Exact everyday image (experiment 27): the experiment 26 behaviour without
diagnostics. Original reset and scatter expand it; the Editor parser, the DSP
code and the ring size stay stock. Behaviour on this build is checked by
`verify_master_ref.py everyday` (every group on the clean ELF). No device access.
"""
import json,struct
from unicorn import UC_HOOK_CODE
from verify_pad_protocol import ROOT,IMAGE,BIAS
import verify_health_probe as health
from build_master_trial import trial,MODES
from build_deployment_probe import validate,digest
from capture_jump_patches import SCATTER
from plan_capture_composed import SIZE_SITE
from plan_capture_packing import DECOMPRESS,ZERO
from plan_simple_capture import QUERY_SPEC
from scatter_codec import expand

DATA,ANCHOR,MANIFEST,T=trial('everyday');TP=T['pack'];TN=TP['names'];OUT=MODES['everyday']['out']
EXPERIMENT26='268f1a76a4f8c49a4498cf8d9881201effe83484cd19845a6ed38b62e2c6edf9'

def boot():
    m=health.machine(False);u=m.uc
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

    assert digest(trial('minimum')[0])==EXPERIMENT26
    assert (OUT/'everyday/L6.BIN').read_bytes()==DATA and (OUT/'anchor/MASTER.WAV').read_bytes()==ANCHOR
    validate(DATA);assert len(DATA)==len(IMAGE) and DATA[0x2851f8:]==IMAGE[0x2851f8:]
    adapters=sorted(p['adapter'] for p in MANIFEST['patches'])
    assert len(adapters)==9 and adapters.count('mr_main_receive')==5 and 'health_parser' not in adapters
    q=QUERY_SPEC['site']-BIAS;assert DATA[q:q+4]==IMAGE[q:q+4]==bytes.fromhex(QUERY_SPEC['original'])
    assert DATA[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]==IMAGE[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]
    assert not any(n in TN for n in ('mr_query','health_parser','mr_stack_low'))
    assert MANIFEST['experiment']==27 and not MANIFEST['diagnostics'] and MANIFEST['minimum_take_seconds']==2
    words=struct.unpack_from('<II',DATA,0x800a6930-BIAS)+struct.unpack_from('<II',DATA,0x800a6940-BIAS)
    assert (words[0],words[0]+words[1],words[2],words[2]+words[3])==tuple(
        MANIFEST[k] for k in ('code_start','code_end','globals_start','globals_end'))
    passed('exact_image_has_nine_sites_and_leaves_the_editor_parser_DSP_code_and_ring_size_stock',
           trial_sha256=MANIFEST['trial_sha256'],code_bytes=MANIFEST['code_bytes'],
           globals_bytes=MANIFEST['globals_bytes'],spare_bytes=MANIFEST['spare_bytes'],experiment26=EXPERIMENT26)
    boot()
    passed('original_reset_and_scatter_expand_the_image_with_the_stock_DSP_code')
    result=dict(passed=True,passed_groups=len(cases),results=cases,trial_sha256=MANIFEST['trial_sha256'])
    (ROOT/'analysis/master_everyday_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
