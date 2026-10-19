#!/usr/bin/env python3
"""The audio path end to end for the stereo AUX send and the linked limiters:
the original mixer (0x20224b90) and the original output stage (0x202263e0,
PLAY/STOP and MASTER gains, the compressor, the master and AUX limiters, the
recorder and USB copies, the clip, the meters and the conversion to the
converters' integers) run block by block on synthetic input lanes, stock and
with the release build's code and DSP patches in place, with the AUX gains
set through the stock channel send setters so the stereo filter is in the
loop. The gain ramp's queue send is short-circuited (the target is written
at once); the stock DSP state initialiser fills the state. No device access.
"""
import json,math,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
import unicorn.arm_const as A
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_S0,UC_ARM_REG_PC
from verify_aux_limiter import Probe as Limiter,B,STATE,PARAMS,AUX1,AUX2,f32,FULL,DELAY,PACK,NAMES,PLAN,STOCK_DSP
import verify_aux_limiter
verify_aux_limiter.INIT_DONE=0x800120ca   # one store further than the limiter suite needs: the master limiter's delay fields
from verify_stereo_aux import C,INPUT,MATRIX,RETURN
from verify_pad_protocol import ROOT

MIXER,STAGE,USB=0x20224b90,0x202263e0,0x20229538   # the mixer, the output stage, where its USB interleave begins
CONVERT=0x20228df8                                  # the stage's conversion of the four blocks to the converters' integers
MASTER_L,MASTER_R=B+0x33b8,B+0x34b8
OUT=dict(master_l=0x20010648,master_r=0x20010748,aux1=0x20010848,aux2=0x20010948)   # the converter integers
REC_L,REC_R=B+0x1610,B+0x1710                   # the recorder copy (MASTER.WAV)
u2f=lambda u:struct.unpack('<f',struct.pack('<I',u&0xffffffff))[0]
LANE_L,LANE_R=6,7                               # channel 5, a stereo channel: its left and right lanes
BLOCKS=10

def doubles(uc,start,end):
    """The emulator's Cortex-M has no double-precision arithmetic, and the
    output stage uses a little of it: the compressor's gain arithmetic and
    the clip stage convert to double, multiply and compare. Those
    instructions (decoded from the code itself) are emulated here, each from
    a hook at its own address, with IEEE doubles; every other instruction
    runs as it is."""
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);code=bytes(uc.mem_read(start,end-start))
    reg=lambda n:getattr(A,'UC_ARM_REG_'+n.upper())
    rd=lambda n:struct.unpack('<d',struct.pack('<Q',uc.reg_read(reg(n))))[0]
    wd=lambda n,v:uc.reg_write(reg(n),struct.unpack('<Q',struct.pack('<d',v))[0])
    rs=lambda n:struct.unpack('<f',struct.pack('<I',uc.reg_read(reg(n))&0xffffffff))[0]
    ws=lambda n,v:uc.reg_write(reg(n),struct.unpack('<I',struct.pack('<f',v))[0])
    def emulate(mn,ops):
        if mn=='vcvt.f64.f32':wd(ops[0],rs(ops[1]))
        elif mn=='vcvt.f32.f64':ws(ops[0],rd(ops[1]))
        elif mn=='vmul.f64':wd(ops[0],rd(ops[1])*rd(ops[2]))
        elif mn in ('vcmp.f64','vcmpe.f64'):
            a,b=rd(ops[0]),(rd(ops[1]) if ops[1][0]=='d' else float(ops[1].lstrip('#')))
            nzcv=0b0011 if (a!=a or b!=b) else 0b0010 if a>b else 0b0110 if a==b else 0b1000
            uc.reg_write(A.UC_ARM_REG_FPSCR,(uc.reg_read(A.UC_ARM_REG_FPSCR)&0x0fffffff)|nzcv<<28)
        else:raise ValueError(mn)
    # Decoded at every halfword: a linear decode loses sync at the stage's
    # literal pools. The count is the listing's; a chance match inside a pool
    # would break it.
    found=[]
    for off in range(0,len(code)-2,2):
        i=next(iter(md.disasm(code[off:off+4],start+off)),None)
        if i is None or i.size!=4 or i.mnemonic not in ('vcvt.f64.f32','vcvt.f32.f64','vmul.f64','vcmp.f64','vcmpe.f64'):continue
        ops=[o.strip() for o in i.op_str.split(',')]
        def hook(uc_,address,size,user,mn=i.mnemonic,ops=ops):emulate(mn,ops);uc_.reg_write(A.UC_ARM_REG_PC,(address+size)|1)
        uc.hook_add(UC_HOOK_CODE,hook,begin=i.address,end=i.address);found.append(i.mnemonic)
    assert len(found)==56 and found.count('vcmp.f64')==32,(len(found),found.count('vcmp.f64'))
    return found

class Rig(Limiter):
    """The limiter suite's probe (memory, code, DSP patches, mode bytes, the
    initialised limiter state) plus the stock gains the output stage expects
    at start-up and the setters' ramp request short-circuited."""
    def __init__(self,patched,stereo=True,dsp=True):
        """patched: the release code and its MAIN sites; dsp=False keeps the
        stock DSP code with them, which is 0.3.0: the stereo send with the
        two AUX limiters still independent."""
        super().__init__(patched,stereo)
        if patched and not dsp:self.uc.mem_write(0x20220000,STOCK_DSP)
        if patched:   # the MAIN sites of the stereo filter (the ramp request entry and the pan, balance and reset veneers)
            for q in PLAN['patches']:
                if q['adapter'].startswith('sa_'):
                    assert self.raw(q['site'],q['bytes'])==bytes.fromhex(q['original']);self.uc.mem_write(q['site'],bytes.fromhex(q['patch']))
        # The channels' pan factors at balance centre: a mono lane to both sides,
        # a stereo pair's lanes each to their own side (stereo_aux_findings.txt).
        for j in range(10):self.floats(C+0xc0+8*j,[1.0,1.0] if j<2 else ([1.0,0.0] if j%2==0 else [0.0,1.0]))
        self.requests=[]
        self.uc.hook_add(UC_HOOK_CODE,self.core,begin=0x8001039c,end=0x8001039c)
        doubles(self.uc,STAGE,0x202291a0)
        self.snapshot=None;self.uc.hook_add(UC_HOOK_CODE,self.before_conversion,begin=CONVERT,end=CONVERT)
        # Start-up values the stage multiplies by: the live mix (PLAY/STOP off),
        # MASTER at its 0 dB mark, the soft mute open, no ramps in flight.
        self.floats(B+0x61bc,[1.0]);self.uc.mem_write(B+0x61c0,bytes(8));self.uc.mem_write(B+0x61dc,bytes(4))
        self.floats(B+0x6214,[1.0]);self.uc.mem_write(B+0x6220,bytes(8))
        self.floats(B+0x62f4,[1.0]);self.uc.mem_write(B+0x62f8,bytes(8))
        for j in range(10):self.floats(C+0x70+4*j,[1.0]);self.floats(C+0x98+4*j,[1.0])   # channel levels and the post-fader multipliers
    def before_conversion(self,uc,address,size,user):
        """The four float blocks as the conversion sees them: after the
        limiters, the clip and the meters (the conversion consumes them)."""
        self.snapshot=dict(master_l=self.values(MASTER_L,64),master_r=self.values(MASTER_R,64),aux1=self.values(B+0x35b8,64),aux2=self.values(B+0x36b8,64))
    def core(self,uc,address,size,user):
        dst,ms,state=(uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2))
        g=u2f(uc.reg_read(UC_ARM_REG_S0));self.requests.append((dst,g))
        uc.mem_write(dst,struct.pack('<f',g));uc.reg_write(UC_ARM_REG_PC,0x800103d4|1)
    def send(self,channel,aux,value,post=1):
        """The stock AUX send setters, as the Editor and the knobs use them: the
        send point per lane (aux 1 or 2), then the channel send (aux 0 or 1)."""
        for lane in ((channel,) if channel<2 else (2*channel-2,2*channel-1)):self.run(0x80002890,[lane,aux+1,post,1])
        self.run(0x8003d998,[channel,aux,value])
    def lanes(self,left,right):
        self.floats(INPUT+LANE_L*256,left);self.floats(INPUT+LANE_R*256,right)
    def block(self):
        """One 64-frame block: the mixer, then the output stage. Returns the
        AUX float blocks after the stage and the four converter outputs."""
        self.run(MIXER);self.run(STAGE,end=USB)   # up to the USB interleave, which needs the host buffer
        ints={k:struct.unpack('<64i',self.raw(a,256)) for k,a in OUT.items()}
        return self.snapshot['aux1'],self.snapshot['aux2'],ints

def tone(amplitude,n,phase=0.0,f=1000.0,rate=48000.0):
    return [f32(amplitude*FULL*math.sin(2*math.pi*f*(k+phase)/rate)) for k in range(n)]
def dbfs(values):
    rms=math.sqrt(sum(v*v for v in values)/len(values))/FULL
    return round(20*math.log10(rms),2) if rms>0 else None

def run(rig,left,right):
    """BLOCKS blocks of the two lanes; the outputs concatenated."""
    out=dict(aux1_f=[],aux2_f=[],**{k:[] for k in OUT})
    for b in range(BLOCKS):
        rig.lanes(left[64*b:64*b+64],right[64*b:64*b+64]);a1,a2,ints=rig.block()
        out['aux1_f']+=a1;out['aux2_f']+=a2
        for k in OUT:out[k]+=ints[k]
    return out

def converted(value):
    """The stage's conversion (0x202291a0): above the high limit the maximum,
    below the low limit the minimum, otherwise vcvt.s32 (truncation,
    saturating) and a saturating add of -1 (qadd)."""
    if value>2147483648.0:return 2147483647
    if value<-2147483648.0:return -2147483648
    v=min(2147483647,max(-2147483648,int(value)))
    return max(-2147483648,v-1)

def main():
    cases=[]
    def passed(case,**d):cases.append(dict(case=case,**d))
    n=64*BLOCKS
    # The mixer scales a lane by a fixed factor on the way to the buses (the
    # lanes are not in the converters' units); measured here, so that the
    # tones below are set in bus units: quiet well under the limiters'
    # threshold (integer full scale), loud 1.6 times over it.
    r=Rig(True,True);r.send(4,0,100);probe=tone(0.01,64*4)
    for b in range(4):r.lanes(probe[64*b:64*b+64],[0.0]*64);r.run(MIXER)   # the channel's low cut settles; a constant would be cut
    scale=max(abs(x) for x in r.values(B+0x35b8,64))/max(abs(x) for x in probe[192:256])
    quiet=[f32(x/scale) for x in tone(0.02,n)];loud=[f32(x/scale) for x in tone(1.6,n,phase=17)]
    half=[f32(x/2) for x in quiet];quarter=[f32(x/4) for x in loud]
    silence=[0.0]*n

    # 1. The setters through the stereo filter: AUX 1 up on channel 5 gives the
    # pair its left and right lanes; in mono the stock rows.
    rows={}
    for label,patched,stereo in (('stock',False,False),('release_mono',True,False),('release_stereo',True,True)):
        r=Rig(patched,stereo);r.send(4,0,100)   # AUX 1 send up on channel 5 (post-fader)
        g=[r.values(MATRIX+row*40,10) for row in range(4)]
        rows[label]=dict(aux1=[round(x,4) for x in g[2][6:8]],aux2=[round(x,4) for x in g[3][6:8]])
        G=g[2][LANE_L]
        if stereo:assert g[2][LANE_R]==0.0 and g[3][LANE_L]==0.0 and g[3][LANE_R]==G and G>0,rows
        else:assert g[2][LANE_R]==G and g[3][LANE_L]==g[3][LANE_R]==0.0 and G>0,rows
        assert all(x==0.0 for x in g[0]) and all(x==0.0 for x in g[1])   # the master rows: untouched by an AUX send
    passed('the_stock_send_setters_give_the_aux_rows_the_stereo_filter_computes',rows=rows,lane_to_bus_scale=scale)

    # 2. Quiet tones through the whole path. Every stage is linear below the
    # limiters' threshold and a power-of-two scaling commutes exactly with
    # IEEE multiplication, so a right lane at half the left must come out at
    # exactly half, sample for sample, when both sides carry the same gain.
    def go(patched,stereo,left,right,dsp=True):
        r=Rig(patched,stereo,dsp);r.send(4,0,100);return run(r,left,right)
    stock=go(False,False,quiet,half);mono=go(True,False,quiet,half);stereo=go(True,True,quiet,half)
    assert mono==stock,'release in mono: as stock, every byte'
    assert any(stock['aux1_f']) and not any(stock['aux2_f']),'mono: both lanes to AUX 1, AUX 2 silent (its send is down)'
    left_only=go(True,True,quiet,silence);right_only=go(True,True,silence,half)
    assert any(left_only['aux1_f']) and not any(left_only['aux2_f']),'stereo: the left lane reaches AUX 1 only'
    assert any(right_only['aux2_f']) and not any(right_only['aux1_f']),'stereo: the right lane reaches AUX 2 only'
    assert stereo['aux1_f']==left_only['aux1_f'] and stereo['aux2_f']==right_only['aux2_f']
    assert stereo['aux2_f']==[f32(x/2) for x in stereo['aux1_f']],'the right output is exactly half the left'
    assert stereo['aux1_f'][:DELAY]==[0.0]*DELAY and any(stereo['aux1_f'][DELAY:DELAY+8]),'the limiter delay of 48 samples'
    assert all(stereo['aux1'][k]==converted(stereo['aux1_f'][k]) for k in range(n)) and all(stereo['aux2'][k]==converted(stereo['aux2_f'][k]) for k in range(n))
    assert set(stereo['master_l'])=={converted(0.0)} and stereo['master_l']==stock['master_l'],'no master send: the master converters carry silence'
    levels=dict(stereo_aux1=dbfs(stereo['aux1_f'][DELAY:]),stereo_aux2=dbfs(stereo['aux2_f'][DELAY:]),mono_aux1=dbfs(stock['aux1_f'][DELAY:]))
    assert round(levels['stereo_aux1']-levels['stereo_aux2'],2)==6.02
    passed('quiet_tones_reach_the_converters_with_left_on_aux1_right_on_aux2_at_exactly_half_delayed_48_samples',levels_dbfs=levels)

    # 3. A hot left and a quarter-level right through the limiters: with the
    # stock limiters (0.3.0) the right is left alone while the left limits; the
    # release build in stereo gives both sides one gain, so the right output is exactly a
    # quarter of the left, sample for sample.
    outcomes={}
    quiet_ref=go(True,True,quiet,quarter)['aux2_f']            # the right side with the left quiet: no limiting anywhere
    for label,patched,stereo,dsp in (('independent_limiters_0_3_0',True,True,False),('release_stereo',True,True,True),('release_mono',True,False,True)):
        hot=go(patched,stereo,loud,quarter,dsp);a1,a2=hot['aux1_f'],hot['aux2_f']
        unlimited=go(patched,stereo,[f32(x/64) for x in loud],[f32(x/64) for x in quarter],dsp)['aux1_f']   # the same left, 36 dB down: never limits
        limited=any(a1[k]!=f32(unlimited[k]*64) for k in range(DELAY,n))
        proportional=a2==[f32(x/4) for x in a1]
        outcomes[label]=dict(left_limited=limited,right_is_a_quarter_of_left=proportional,
                             aux1_dbfs=dbfs(a1[DELAY:]),aux2_dbfs=dbfs(a2[DELAY:]),
                             right_dip_db=round(dbfs(quiet_ref[DELAY:])-dbfs(a2[DELAY:]),2) if any(a2) else None)   # mono: AUX 2 silent, its send down
        if label.startswith('independent'):assert limited and not proportional and a2==quiet_ref,'independent limiters: the quiet side untouched'
        elif label=='release_stereo':assert limited and proportional and a2!=quiet_ref and outcomes[label]['right_dip_db']>1.0
        else:assert hot==go(False,False,loud,quarter),'mono: as stock, every byte'
        assert all(hot['aux1'][k]==converted(a1[k]) and hot['aux2'][k]==converted(a2[k]) for k in range(n))
    passed('a_hot_left_limits_and_the_release_in_stereo_turns_the_right_down_by_the_same_gain_stock_does_not',outcomes=outcomes)

    # 4. The master path is untouched by the AUX work: with a master mix of
    # the pair, the master converter outputs and the recorder copy are
    # byte-identical between stock and the release build, mono and stereo.
    for stereo in (False,True):
        outs=[]
        for patched in (False,True):
            r=Rig(patched,stereo);r.send(4,0,100)
            r.floats(MATRIX+0*40+4*LANE_L,[0.7]);r.floats(MATRIX+1*40+4*LANE_R,[0.7])   # a master mix of the pair
            o=run(r,loud,quarter);outs.append((o['master_l'],o['master_r'],r.raw(REC_L,256),r.raw(REC_R,256)))
        assert outs[0]==outs[1],stereo
        assert any(v!=converted(0.0) for v in outs[0][0]) and any(outs[0][2])
    passed('the_master_outputs_and_the_recorder_copy_are_byte_identical_stock_against_release')

    result=dict(passed=True,groups=len(cases),results=cases,limitations=[
        'The stages run one block at a time on synthetic state; the audio task, the USB interleave, DMA and the SAI interleave are not run',
        'The compressor is at its start-up state, PLAY/STOP is off and MASTER is at its 0 dB mark; the effects return stage is not run',
        'The gain ramp queue is short-circuited: targets are written at once rather than ramped by the ramp task',
        'Double-precision instructions (the compressor arithmetic and the clip) are emulated per instruction with IEEE doubles'])
    (ROOT/'analysis/output_stage_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
