#!/usr/bin/env python3
"""Linked AUX output limiters (experiment 41): the two AUX limiter blocks of
the original copied audio code run on synthetic sample blocks, stock and
with the build's two patched detector call sites and its routines in place.

Stock: each AUX limiter reads its own side, so the quiet side keeps gain 1.0
while the loud side limits. Patched, in stereo: both sides get the same gain
series, the one stock computes for the louder side; in mono, or without the
worker, every byte of state and output is as stock. The stock DSP state
initialiser fills the limiter state. No device access.
"""
import json,random,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from unicorn.arm_const import (UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,
                               UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_S20,UC_ARM_REG_S22)
from verify_stereo_aux import Rig,B,STACK,RETURN
from verify_pad_protocol import ROOT,IMAGE,BIAS
from build_master_ref import build
from plan_master_ref import plan,LINK_SPECS
from capture_jump_patches import SCATTER

ELF=build(trial=False,stereo=True,link=True);PLAN=plan(ELF,trial=False);PACK=PLAN['pack'];NAMES=PACK['names']
STOCK_DSP=IMAGE[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]]
MODE=0x80440dc8+0x30d
STATE=B+0x6260;PARAMS=B+0x6244
AUX1,AUX2=B+0x35b8,B+0x36b8
BLOCK1=(0x20227bdc,0x20227e5c);BLOCK2=(0x20227e5c,0x202280e0)   # each AUX limiter: detector loop, delay and apply
INIT=0x80011920;INIT_DONE=0x800120c4   # the stock DSP state initialiser, up to after the limiter state
RING=0x71;DELAY=0x30;FRAMES=6;FULL=2.0**31  # delay ring length and delay in samples; the threshold is integer full scale
f32=lambda x:struct.unpack('<f',struct.pack('<f',x))[0]
SAVED=(UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_SP)

class Probe(Rig):
    def __init__(self,patched,stereo=True,worker=True):
        super().__init__()
        if patched:
            self.uc.mem_write(0x20220000,PACK['dsp'])   # the build's DSP code: two call sites changed
            j=PACK['jumps'];self.uc.mem_write(j['candidate_code_start'],PACK['code'])
            self.uc.mem_write(j['globals_start'],bytes(j['globals_end']-j['globals_start']))
            self.uc.mem_write(NAMES['mr_state'],struct.pack('<I',0x21010000 if worker else 0))
        self.uc.mem_write(MODE,bytes([0xa5,0x5a]) if stereo else bytes(2))
        self.run(INIT,[48000],end=INIT_DONE)
        assert self.words(STATE,1)==(1,) and self.words(STATE+0x30,1)==(1,)   # both AUX limiters enabled
        assert self.values(STATE+4,2)==self.values(STATE+0x34,2) and self.words(STATE+0x1c,1)==self.words(STATE+0x4c,1)==(RING,) and self.words(STATE+0x24,1)==self.words(STATE+0x54,1)==(DELAY,)
        # The output level factor's smoothing state, settled at its target 1.0
        # (it ramps 2% per block from zero after start-up).
        self.floats(PARAMS+8,[1.0]);self.floats(PARAMS+0xc,[1.0])
        self.regs=[]
    def words(self,a,n):return struct.unpack('<%dI'%n,self.raw(a,4*n))
    def block(self,span):
        start,end=span;sp=STACK-0x400
        for i,reg in enumerate(SAVED[:-1]):self.uc.reg_write(reg,0x1000+i)   # the loops' own registers, then the frame
        self.uc.reg_write(UC_ARM_REG_R11,B);self.uc.reg_write(UC_ARM_REG_S20,0x4f000000);self.uc.reg_write(UC_ARM_REG_S22,0x3f800000)
        self.uc.reg_write(UC_ARM_REG_SP,sp);self.uc.reg_write(UC_ARM_REG_LR,RETURN|1)
        self.end=end;self.stopped=False
        self.uc.emu_start(start|1,RETURN+2,count=10000000);assert self.stopped,hex(start)
        self.regs.append(tuple(self.uc.reg_read(r) for r in SAVED))
        return self.values(sp+0x18,64)
    def frame(self,aux1,aux2):
        """One 64-frame block through both AUX limiters: (gains 1, gains 2, out 1, out 2)."""
        self.floats(AUX1,aux1);self.floats(AUX2,aux2)
        g1=self.block(BLOCK1);g2=self.block(BLOCK2)
        return g1,g2,self.values(AUX1,64),self.values(AUX2,64)

def signal(seed,scale,n=64*FRAMES):
    rnd=random.Random(seed);return [f32(scale*FULL*(2*rnd.random()-1)) for _ in range(n)]

def run(probe,left,right):
    out=[]
    for k in range(FRAMES):out.append(probe.frame(left[64*k:64*k+64],right[64*k:64*k+64]))
    return out

def main():
    cases=[]
    def passed(case,**d):cases.append(dict(case=case,**d))

    # 1. The plan: exactly the two detector sites change in the DSP code.
    dsp=PACK['dsp'];assert len(dsp)==len(STOCK_DSP)
    sites={q['site']:q for q in PLAN['DSP_patches']};assert sorted(sites)==[s['site'] for s in LINK_SPECS]
    changed={i for i in range(len(dsp)) if dsp[i]!=STOCK_DSP[i]}
    spans={i for q in sites.values() for i in range(q['site']-SCATTER[1],q['site']-SCATTER[1]+q['bytes'])}
    assert changed<=spans and all(dsp[q['site']-SCATTER[1]:q['site']-SCATTER[1]+12]==bytes.fromhex(q['patch']) for q in sites.values())
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    for q in sites.values():
        ins=[f'{i.mnemonic} {i.op_str}'.strip() for i in md.disasm(bytes.fromhex(q['patch']),q['site'])]
        assert ins==[f"movw r0, #{q['target']&0xffff:#x}",f"movt r0, #{q['target']>>16:#x}",'blx r0','nop'],ins
        assert q['target']==NAMES[q['adapter']] and q['decoded_original']==['vldr s0, [r5]','bl #0x2022d63a','vcmp.f32 s0, s16'],q
    assert {q['adapter'] for q in PLAN['patches']}>={'sa_ramp','mr_main_receive'} and not any(0x20220000<=q['site']<0x2022e000 for q in PLAN['patches'])
    passed('plan_changes_only_the_two_AUX_detector_call_sites_of_the_DSP_code',
           sites=[hex(s) for s in sorted(sites)],routines={q['adapter']:hex(q['target']) for q in sites.values()},
           code_bytes=len(PACK['code']),spare_bytes=PLAN['packing']['spare_bytes'])

    left=signal(1,3.0);right=signal(2,0.1)   # left over full scale, right well under
    louder=[f32(max(abs(l),abs(r))) for l,r in zip(left,right)]

    # 2. Stock: the quiet side never limits while the loud side does.
    stock=run(Probe(False),left,right)
    assert all(g==1.0 for _,g2,_,_ in stock for g in g2) and min(g for g1,_,_,_ in stock for g in g1)<0.5
    # The delay stage: output n is input n-DELAY times gain n (quiet side: times 1.0).
    outs=[x for _,_,_,o2 in stock for x in o2];ins=[0.0]*DELAY+right
    assert outs==ins[:len(outs)]
    passed('stock_AUX_limiters_are_independent_and_delay_by_48_samples',
           loud_side_minimum_gain=min(g for g1,_,_,_ in stock for g in g1),delay_samples=DELAY,ring_samples=RING)

    # 3. Stock, fed the louder of both sides on side 1: the linked gain series.
    reference=run(Probe(False),louder,right)
    expected=[g1 for g1,_,_,_ in reference]

    # 4. Patched, stereo: both sides get the linked gains and their own delayed samples times them.
    linked=run(Probe(True),left,right)
    assert [g1 for g1,_,_,_ in linked]==expected and [g2 for _,g2,_,_ in linked]==expected
    gains=[g for g1,_,_,_ in linked for g in g1]
    for side,src in ((2,left),(3,right)):
        outs=[x for fr in linked for x in fr[side]];ins=[0.0]*DELAY+src
        assert outs==[f32(i*g) for i,g in zip(ins,gains)],side
    assert min(gains)<0.5
    passed('patched_in_stereo_both_sides_use_the_louder_side_so_the_gains_match_bit_for_bit',
           frames=FRAMES,minimum_gain=min(gains),gains_below_unity=sum(g<1.0 for g in gains))

    # 5. Patched, mono (and stereo without the worker): as stock, state, output and registers alike.
    for label,probe in (('mono',Probe(True,stereo=False)),('stereo_without_worker',Probe(True,worker=False))):
        assert run(probe,left,right)==stock,label
    stock_probe=Probe(False);run(stock_probe,left,right)
    mono_probe=Probe(True,stereo=False);run(mono_probe,left,right)
    assert mono_probe.regs==stock_probe.regs and mono_probe.raw(STATE,0x60)==stock_probe.raw(STATE,0x60)
    passed('patched_in_mono_or_without_the_worker_is_stock_bit_for_bit',registers_compared=[r for r in ('r4','r5','r6','r7','r8','r9','r10','r11','sp')])

    # 6. The routines keep the loops' registers in stereo too, and leave the envelopes equal.
    linked_probe=Probe(True);run(linked_probe,left,right)
    assert [r[:-1] for r in linked_probe.regs]==[r[:-1] for r in stock_probe.regs]
    assert linked_probe.values(STATE+0xc,1)==linked_probe.values(STATE+0x3c,1)
    passed('routines_preserve_the_loop_registers_and_both_envelopes_agree',envelope=linked_probe.values(STATE+0xc,1)[0])

    # 7. The release recipe carries the two DSP edits and rebuilds the image.
    from build_master_trial import trial
    from build_deployment_probe import SOURCE
    import recipe as recipes
    image,_,report,t=trial('linked');stock=SOURCE.read_bytes()
    recipe=recipes.make(stock,image,t['pack'],'linked')
    edits=recipe['span']['dsp_edits']
    assert recipe['format']==2 and [e[0] for e in edits]==[q['site']-SCATTER[1] for q in sorted(sites.values(),key=lambda q:q['site'])]
    assert [recipes.unb64(e[1]).hex() for e in edits]==[q['patch'] for q in sorted(sites.values(),key=lambda q:q['site'])]
    assert recipes.rebuild(stock,recipe)==image and report['DSP_patches']==PLAN['DSP_patches']
    assert recipes.stock_bytes(stock,recipe)==recipes.stock_bytes(stock,dict(recipe,span=dict(recipe['span'],dsp_edits=[])))   # our 24 bytes occur nowhere in stock
    passed('recipe_carries_the_two_twelve_byte_DSP_edits_and_rebuilds_the_image',image_sha256=recipe['image_sha256'],edits=edits)

    result=dict(passed=True,passed_groups=len(cases),results=cases,
        limitations=['The AUX limiter blocks run on synthetic blocks with the stock-initialised state; the mixer stages before them and the output conversion after them are not run here',
                     'The output level factor is set to its settled value; the stock ramp towards it is not exercised',
                     'No hardware measurement: see docs/research/aux_limiter_link_findings.txt for the jack test'])
    (ROOT/'analysis/aux_limiter_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
