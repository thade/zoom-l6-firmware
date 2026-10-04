#!/usr/bin/env python3
"""Offline original DSP windows plus an explicitly modeled pre-gain tap.

No firmware patch, file writer, hardware access, or complete DSP emulation.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_CPU_ARM_CORTEX_M7,UC_ARM_REG_FPEXC,
    UC_ARM_REG_R4,UC_ARM_REG_R11,UC_ARM_REG_S18)
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT,IMAGE,BIAS
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop

B=0x20010a48
MIX=B+0x33b8
STAGING=B+0x1610
RING=0x81429800
STRIDE=0xea600

def packed(values):return struct.pack('<%df'%len(values),*values)

class TapRig:
    def __init__(self,cpu_model=UC_CPU_ARM_CORTEX_M7,mclass=True):
        self.m=Emulator(cpu_model,mclass);m=self.m
        m.stack=0x2003f000
        m.uc.mem_map(0x20220000,0x10000)
        m.uc.mem_write(0x20220000,IMAGE[0x800a9408-BIAS:0x800a9408-BIAS+0xd6dc])
        m.uc.mem_map(0x81000000,0x1000000)
        m.uc.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        self.floats(B+0x54f4,[1]*4)
        self.floats(B+0x60b4,[1])
        self.floats(B+0x6214,[1,1,1])
        put32(m,B+0x53e0,RING)
        put32(m,B+0x53e8,128)

    def floats(self,address,values):self.m.uc.mem_write(address,packed(values))
    def raw(self,address,n=512):return bytes(self.m.uc.mem_read(address,n))
    def window(self,start,end):
        m=self.m
        h=m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,s,u:stop(m),begin=end,end=end)
        try:m.invoke(start,[])
        finally:m.uc.hook_del(h)
    def pad(self,index,left,right,gain=1):
        p=0x21028000+index*0x1000
        self.floats(p,left*2);self.floats(p+0x400,right*2)
        self.m.uc.mem_write(B+0x5404+index*0x3c,struct.pack('<15I',
            1,p,p+0x400,0,0,128,0,128,0,0x3f800000,0,0,0,0,0))
        self.floats(B+0x54f4+index*4,[gain])
    def mix(self):
        self.window(0x20220ac8,0x20221792)
        self.m.invoke(0x20224b90,[])
    def gain(self,value):
        self.floats(B+0x6214,[value])
        self.m.uc.reg_write(UC_ARM_REG_R4,B)
        self.window(0x202269f8,0x20227136)
    def stock_staging(self):
        self.m.uc.reg_write(UC_ARM_REG_R11,B)
        self.window(0x202280e0,0x202281c6)
    def enqueue(self,position=0):
        m=self.m;put32(m,B+0x53e4,position)
        m.uc.reg_write(UC_ARM_REG_R11,B);m.uc.reg_write(UC_ARM_REG_R4,64)
        m.uc.reg_write(UC_ARM_REG_S18,0x3f800000)
        self.window(0x2022a55a,0x2022a77a)
    def read_stream(self,index,channels=2,position=0):
        # Original function arguments 5/6: channel count and bytes/sample.
        self.m.uc.mem_write(self.m.stack,struct.pack('<2I',channels,4))
        n=self.m.invoke(0x80018fd0,[position,0x21030000,64,index])
        assert n==64*channels*4
        return self.raw(0x21030000,n)

def main():
    results=[]
    def passed(case,**details):results.append(dict(case=case,passed=True,**details))
    left=[(i-32)/128 for i in range(64)]
    right=[(63-i)/128 for i in range(64)]
    live=[i/256 for i in range(64)]
    r=TapRig();r.pad(0,left,right)
    r.floats(B+0x10,live)
    r.floats(B+0x5e34,[1]+[0]*9+[.5]+[0]*9)
    clean=r.raw(B+0x10,2560)
    r.mix()
    mixed_l=[a+b for a,b in zip(left,live)]
    mixed_r=[a+b*.5 for a,b in zip(right,live)]
    expected=packed(mixed_l+mixed_r)
    assert r.raw(MIX)==expected
    assert r.raw(B+0x10,2560)==clean
    passed('original_pad_renderer_and_mixer_include_pad_and_live_input_without_changing_input_buffers')
    saved=r.raw(MIX)
    r.gain(.5)
    gained=packed([v*.5 for v in mixed_l+mixed_r])
    assert r.raw(MIX)==gained and saved==expected
    passed('original_master_gain_changes_mix_after_candidate_capture_boundary')
    r.stock_staging()
    assert r.raw(STAGING)==gained
    passed('original_later_staging_copy_takes_current_mix',limitation='Dynamics between gain and staging deliberately not executed')
    # Proposed substitution is modeled by host memory writes, not a device hook.
    r.m.uc.mem_write(STAGING,saved)
    r.enqueue()
    assert r.raw(MIX)==gained
    assert r.raw(RING+10*STRIDE,256)==packed(mixed_l)
    assert r.raw(RING+11*STRIDE,256)==packed(mixed_r)
    assert r.raw(B+0x10,2560)==clean
    passed('modeled_saved_tap_substitution_reaches_original_ring_copies_without_changing_mix_or_input_buffers')
    interleaved=packed([v for pair in zip(mixed_l,mixed_r) for v in pair])
    assert r.read_stream(10)==interleaved
    passed('original_stream_10_stereo_reader_returns_exact_saved_tap_samples')
    for position in (0,64):
        r.m.uc.mem_write(STAGING,saved);r.enqueue(position)
        assert r.read_stream(10,position=position)==interleaved
        assert struct.unpack('<I',r.raw(B+0x53e4,4))[0]==(position+64)%128
    passed('original_ring_write_and_reader_agree_at_both_block_positions_including_wrap')
    # A sentinel in channel 0 is untouched by replacing/writing the master pair.
    sentinel=packed([.0625+i/512 for i in range(64)])
    r.m.uc.mem_write(RING,sentinel);r.m.uc.mem_write(STAGING,saved);r.enqueue()
    assert r.read_stream(0,channels=1)==sentinel
    passed('master_pair_substitution_does_not_change_existing_channel_zero_ring_data')
    r=TapRig();r.pad(0,left,right,.5);r.pad(1,right,left,.25)
    r.floats(B+0x60b4,[.5]);r.mix()
    want_l=[(a*.5+b*.25)*.5 for a,b in zip(left,right)]
    want_r=[(b*.5+a*.25)*.5 for a,b in zip(left,right)]
    assert r.raw(MIX)==packed(want_l+want_r)
    passed('two_pad_contributions_and_pad_gains_remain_in_pre_master_capture')
    r=TapRig();r.mix();assert r.raw(MIX)==bytes(512)
    passed('inactive_pads_and_zero_input_produce_zero_mix')
    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
      limitations=['Bounded original instruction windows with synthetic state; not a full running mixer',
        'Cortex-M7 is an emulator configuration, not physical processor identification',
        'Dynamics, effects returns, gain ramps, alternative callbacks and recorder-playback override not tested here',
        'Pre-gain capture and staging replacement modeled in host; no installed or compiled tap hook',
        'Ring producer and stream reader executed; file writer/destination, sustained timing and synchronization unverified',
        'Input buffer/ring isolation tested; complete live stem production not executed'])
    out=ROOT/'analysis/uncompressed_tap_verification.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))

if __name__=='__main__':main()
