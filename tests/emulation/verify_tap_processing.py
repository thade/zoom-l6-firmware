#!/usr/bin/env python3
"""Original effect-return routing, gain ramps and master dynamics, offline.

Synthetic dry/returned audio and kernel queue scheduling are fixtures. The five
effect algorithms, ADC/USB and optional capture writer do not run in this suite.
"""
import hashlib,json,math,struct
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_stock_ring_modes import initialized
from verify_uncompressed_tap import B,MIX,packed
from verify_scheduling_boundaries import stop
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

TAP=0x202269f8
OUTPUT=0x202280e0
ENGINE=0x2103d000

def values(raw):return struct.unpack('<128f',raw)
def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]

class Processing:
    def __init__(self,compression=0,master=1,return_gain=.5):
        self.r=initialized(223104);r=self.r;m=r.m
        self.queue=[];self.taps=[];self.outputs=[];self.returned=[];self.delay_calls=[]
        # Original cold coefficient/table initialization and original ramp-pool
        # initializer. Only kernel mutexes, delays and 16-byte queue copying are
        # modeled. No gain target is written directly in place of a ramp.
        m.hooks[0x80077686]=lambda a:self.delay_calls.append(a[0]) or 0
        m.hooks[0x80076950]=lambda a:1
        m.hooks[0x800763d8]=lambda a:1
        m.hooks[0x800483f8]=lambda a:self.queue.append(r.raw(a[1],16)) or 0
        def receive(a):
            if not self.queue:return stop(m)
            m.uc.mem_write(a[1],self.queue.pop(0));return 0
        m.hooks[0x800483a8]=receive
        m.invoke(0x800103d8,[])
        m.invoke(0x8000d4a0,[compression])
        m.invoke(0x80010228,[])
        r.floats(B+0x6214,[master]);r.floats(B+0x61e4,[return_gain])
        r.floats(B+0x6310,[1])
        put32(m,B+0x630c,ENGINE|1)
        def engine(a):
            r.floats(B+0x29b8,self.effect)
            self.returned.append(bytes(r.raw(B+0x29b8,512)));return 0
        m.hooks[ENGINE]=engine
        m.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:self.taps.append(r.raw(MIX,512)),begin=TAP,end=TAP)
        m.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:self.outputs.append(r.raw(MIX,512)),begin=OUTPUT,end=OUTPUT)
        # Distinct clean input buffers must not acquire effect/master audio.
        r.floats(B+0x10,[float((i-320)*128) for i in range(640)])
        self.clean=r.raw(B+0x10,2560)
    def ramp(self,destination,control,value,ms=16):
        m=self.r.m;m.uc.reg_write(A.UC_ARM_REG_S0,struct.unpack('<I',struct.pack('<f',value))[0])
        m.invoke(0x80010398,[B+destination,ms,B+control])
        assert self.queue
        m.invoke(0x80010228,[])
        assert not self.queue
    def block(self,dry,effect=None):
        r=self.r;self.effect=effect if effect is not None else [0]*128
        r.floats(MIX,dry)
        r.m.invoke(0x20220000,[]) # Original engine dispatch + effect-return mix.
        wet=r.raw(MIX,512)
        r.m.invoke(0x202263e0,[]) # Entire original master body, including dynamics.
        r.m.invoke(0x80010150,[]) # Original consumed-ramp retirement.
        assert self.taps[-1]==wet
        assert r.raw(B+0x10,2560)==self.clean
        assert all(math.isfinite(v) for v in values(self.outputs[-1]))
        return self.taps[-1],self.outputs[-1]

def main():
    cases=[]
    def passed(name,**details):cases.append(dict(case=name,**details))
    dry=[(i-32)*2**20 for i in range(64)]+[(31-i)*2**19 for i in range(64)]
    effect=[(i%7-3)*2**18 for i in range(64)]+[(i%5-2)*2**17 for i in range(64)]
    for gain in (0,.25,.5,1):
        r=Processing(return_gain=gain)
        tap,output=r.block(dry,effect)
        assert tap==packed([f32(a+b*gain) for a,b in zip(dry,effect)])
        assert len(r.returned)==1
    passed('Original effect callback, return scaling and stereo addition reach the pre-master tap exactly',
           engine='controlled returned samples; five effect algorithms not executed')

    r=Processing(return_gain=.5);r.ramp(0x61e4,0x61f0,1)
    nonzero=[2**24]*64+[-2**23]*64
    blocks=[r.block([0]*128,nonzero)[0] for _ in range(16)]
    assert blocks[-1]==packed(nonzero) and blocks[0]!=blocks[-1]
    assert 0<values(blocks[0])[0]<values(blocks[-1])[0]
    assert r.r.raw(B+0x61f0,4)==bytes(4)
    passed('Original queued effect-return ramp advances through real DSP samples and settles before capture')

    snapshots=[];processed=[]
    for enabled in (0,1):
        r=Processing(compression=enabled,return_gain=.5)
        for _ in range(24):r.block([2**29]*64+[-2**29]*64,effect)
        snapshots.append(r.taps);processed.append(r.outputs)
        assert r.delay_calls==[20,20]
    assert snapshots[0]==snapshots[1]
    assert processed[0]!=processed[1] and processed[0][-1]!=processed[1][-1]
    # Stock lookahead/history still runs with the compressor control disabled;
    # ordinary output need not be sample-aligned with this earlier tap.
    passed('Original dynamics setter, coefficient tables and both active master stages alter ordinary output while the tap stays identical',
           blocks_per_state=24,scope='routing separation; no measured acoustic curve or device timing')

    reference=Processing(compression=1)
    ramped=Processing(compression=1);ramped.ramp(0x6214,0x6220,.25)
    for _ in range(24):
        reference.block([2**29]*128,effect);ramped.block([2**29]*128,effect)
    assert reference.taps==ramped.taps and reference.outputs!=ramped.outputs
    assert ramped.r.raw(B+0x6220,4)==bytes(4)
    assert any(v!=2**29 for v in values(reference.taps[-1])) # Wet return present.
    passed('Master gain ramp is downstream of capture even with active dynamics and a nonzero effect return')

    # Multiple dry levels show a level-dependent dynamics response, preventing
    # a constant non-unity output gain from masquerading as active compression.
    ratios=[]
    for level in (2**25,2**28,2**31):
        r=Processing(compression=1)
        for _ in range(32):tap,output=r.block([level]*64+[-level]*64)
        assert tap==packed([level]*64+[-level]*64)
        ratios.append(max(map(abs,values(output)))/level)
    assert max(ratios)-min(ratios)>.2
    passed('Downstream enabled dynamics response changes with input level; all pre-master samples remain exact',
           tested_levels=[2**25,2**28,2**31],output_peak_ratios=ratios)

    r=Processing(compression=1,master=0)
    for _ in range(24):tap,output=r.block(dry,effect)
    assert any(values(tap)) and output==bytes(512)
    passed('Master silence does not erase the pre-master wet mix or contaminate the ten clean input buffers')

    r=Processing(compression=0);left=[];right=[]
    for block in range(6):
        impulse=[0]*128
        if not block:impulse[0]=2**24;impulse[64]=-2**23
        tap,output=r.block(impulse)
        assert tap==packed(impulse)
        left.extend(values(output)[:64]);right.extend(values(output)[64:])
    assert [(i,v) for i,v in enumerate(left) if v]==[(48,2**24)]
    assert [(i,v) for i,v in enumerate(right) if v]==[(48,-2**23)]
    passed('Stock master body retains a 48-frame delay in this initialized 48-kHz configuration with compression disabled',
           delay_frames=48,delay_ms=1,scope='this original DSP body; not total ADC/monitor/recording latency')

    out=ROOT/'analysis/tap_processing_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),device_access=False,
        limitations=['ARM MAX executes original double-precision DSP; not processor identification or M7 interrupt/FP proof.',
            'Dry samples and effect-engine output are synthetic; original effect return routing and downstream DSP execute.',
            'Original cold initialization, dynamics setter, coefficient tables, ramp producer/worker and retirement execute.',
            'Kernel mutex/queue progress and delays modeled; no scheduler, ADC/USB, five effect algorithms or timing claims.',
            'This qualifies signal routing at the already tested capture site, not the entire capture writer or hardware audio.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
