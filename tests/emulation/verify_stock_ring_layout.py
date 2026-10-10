#!/usr/bin/env python3
"""Bounded original-instruction tests of a proposed fixed stock-ring layout.

Reduced capacities/tail canaries are host-seeded proposals, not owned device RAM.
Only exercised readers/writers are covered. No production patch or device IO.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R6,UC_ARM_REG_R8
from verify_uncompressed_tap import TapRig,B,RING,STRIDE,packed
from verify_recording_writer import WriterRig,C
from verify_firmware_workflow import put32,get32
from verify_pad_protocol import ROOT,IMAGE

STOCK_CAP=240000
CAPACITIES=(231552,223104)
SOURCE=0x21030000
OUTPUT=0x21031000
CANARY=b'\xa5'

def capacities(r,cap,alternate=None):
    put32(r.m,B+0x53e8,cap)
    put32(r.m,B+0x53f0,RING);put32(r.m,B+0x53f8,cap if alternate is None else alternate)

def tails(r,cap):
    for lane in range(12):r.m.uc.mem_write(RING+lane*STRIDE+cap*4,CANARY*(STRIDE-cap*4))

def tail_events(r,cap):
    events=[]
    def observe(uc,access,address,size,value,user):
        lane=(address-RING)//STRIDE
        if 0<=lane<12 and (address-RING)%STRIDE+size>cap*4:
            events.append(dict(lane=lane,address=hex(address),bytes=size,access=access))
    handle=r.m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,observe,begin=RING,end=RING+12*STRIDE-1)
    return events,handle

def alternate_write(r,lane,channels,cap,width=4):
    values=[((i-32)*(ch+1))/128 for i in range(64) for ch in range(channels)]
    if width==4:
        source=packed(values); expected=packed([v*2**31 for v in values])
    else:
        integers=[(i-32)*(ch+1)*32 for i in range(64) for ch in range(channels)]
        source=b''.join(v.to_bytes(width,'little',signed=True) for v in integers)
        expected=packed([v*(1<<(32-width*8)) for v in integers])
    r.m.uc.mem_write(SOURCE,source);r.m.uc.mem_write(r.m.stack,struct.pack('<2I',channels,width))
    result=r.m.invoke(0x80019498,[SOURCE,64,cap-32,lane])
    assert result==64*channels*width
    # This alternate writer scales normalized float data into internal
    # +/-2^31 units. The ordinary reader returns those stored float bits.
    r.m.uc.mem_write(r.m.stack,struct.pack('<2I',channels,4))
    assert r.m.invoke(0x80018fd0,[cap-32,OUTPUT,64,lane])==len(expected)
    return expected

def initialize(r):
    r.m.uc.reg_write(UC_ARM_REG_R8,B);r.m.uc.reg_write(UC_ARM_REG_R6,0)
    from unicorn.arm_const import UC_ARM_REG_R2
    r.m.uc.reg_write(UC_ARM_REG_R2,0x53f0)
    r.window(0x800121a0,0x800121e4)

def main():
    results=[]
    def passed(case,**details):results.append(dict(case=case,passed=True,**details))
    r=TapRig();initialize(r)
    assert get32(r.m,B+0x53e0)==get32(r.m,B+0x53f0)==RING
    assert get32(r.m,B+0x53e8)==get32(r.m,B+0x53f8)==STOCK_CAP
    passed('original_initialization_sets_two_descriptors_to_the_same_physical_arena',base=hex(RING),capacity=STOCK_CAP)
    for cap in CAPACITIES:
        r=TapRig();capacities(r,cap);tails(r,cap);events,handle=tail_events(r,cap)
        for lane in range(12):
            expected=alternate_write(r,lane,1,cap)
            assert r.raw(OUTPUT,len(expected))==expected
        r.m.uc.hook_del(handle);assert not events
        assert r.m.invoke(0x80002468,[])==r.m.invoke(0x80002458,[])==cap
        passed(f'all_twelve_mono_lanes_write_and_read_across_reduced_wrap_{cap}',capacity=cap,tail_accesses=len(events),both_capacity_getters=cap)
        r=TapRig();capacities(r,cap);tails(r,cap);events,handle=tail_events(r,cap)
        for lane in range(0,12,2):
            expected=alternate_write(r,lane,2,cap)
            assert r.raw(OUTPUT,len(expected))==expected
        r.m.uc.hook_del(handle);assert not events
        passed(f'all_six_stereo_pairs_write_and_read_across_reduced_wrap_{cap}',capacity=cap,tail_accesses=len(events))
        r=WriterRig();capacities(r,cap);tails(r,cap);events,handle=tail_events(r,cap)
        r.position=cap-64
        left=[(i-32)/32 for i in range(64)];right=[(31-i)/16 for i in range(64)]
        r.master_block([v*2**31 for v in left],[v*2**31 for v in right])
        assert get32(r.m,B+0x53e4)==0
        assert r.read_stream(10,position=cap-64)==packed([v for pair in zip(left,right) for v in pair])
        r.position=0;r.master_block([v*2**31 for v in left],[v*2**31 for v in right])
        assert get32(r.m,B+0x53e4)==64
        r.m.uc.hook_del(handle);assert not events
        passed(f'original_DSP_master_blocks_wrap_at_reduced_capacity_without_touching_tails_{cap}',capacity=cap,tail_accesses=len(events))
        # Exercise signed PCM inputs too: they share this alternate descriptor.
        for width in (2,3):
            r=TapRig();capacities(r,cap);tails(r,cap);events,handle=tail_events(r,cap)
            for lane in range(12):
                expected=alternate_write(r,lane,1,cap,width)
                assert r.raw(OUTPUT,len(expected))==expected
            for lane in range(0,12,2):
                expected=alternate_write(r,lane,2,cap,width)
                assert r.raw(OUTPUT,len(expected))==expected
            r.m.uc.hook_del(handle);assert not events
            passed(f'all_mono_and_stereo_PCM{width*8}_writers_wrap_without_touching_tails_{cap}',capacity=cap,tail_accesses=len(events))
        # The actual DSP recording-copy window includes all twelve lanes.
        from unicorn.arm_const import UC_ARM_REG_R11,UC_ARM_REG_S18
        r=TapRig();capacities(r,cap);tails(r,cap);events,handle=tail_events(r,cap)
        lanes=[[((lane+1)*(i-32))/128 for i in range(64)] for lane in range(12)]
        for lane in range(12):r.floats(B+0xc10+lane*256,[v*2**31 for v in lanes[lane]])
        put32(r.m,B+0x53e4,cap-64)
        r.m.uc.reg_write(UC_ARM_REG_R11,B);r.m.uc.reg_write(UC_ARM_REG_S18,0x30000000)
        r.window(0x20229b74,0x2022a77a)
        assert get32(r.m,B+0x53e4)==0
        for lane in range(12):assert r.read_stream(lane,channels=1,position=cap-64)==packed(lanes[lane])
        r.m.uc.hook_del(handle);assert not events
        passed(f'original_DSP_all_twelve_lane_copy_uses_reduced_bound_{cap}',capacity=cap,tail_accesses=len(events))
        # The second descriptor supplies the DSP recording-playback override.
        from unicorn.arm_const import UC_ARM_REG_S16
        r=TapRig();capacities(r,cap);tails(r,cap);events,handle=tail_events(r,cap)
        put32(r.m,B+0x53d0,1);r.m.uc.mem_write(B+0x53d4,b'\x02')
        put32(r.m,B+0x53f4,cap-64)
        values=[[(i+1)/64 for i in range(64)],[-(i+1)/32 for i in range(64)]]
        for lane,v in zip((10,11),values):r.floats(RING+lane*STRIDE+(cap-64)*4,v)
        r.m.uc.reg_write(UC_ARM_REG_R8,B);r.m.uc.reg_write(UC_ARM_REG_S16,0)
        r.window(0x20221792,0x202219f8)
        assert get32(r.m,B+0x53f4)==0 and r.raw(B+0x37b8,512)==packed(values[0]+values[1])
        r.m.uc.hook_del(handle);assert not events
        passed(f'original_DSP_playback_reads_master_pair_then_wraps_alternate_descriptor_{cap}',capacity=cap,tail_accesses=len(events))
        r.window(0x8000ad7a,0x8000ad96)
        assert get32(r.m,C+0x50)==get32(r.m,C+0x1e94)==cap
        passed(f'original_recorder_configuration_caches_both_reduced_capacities_{cap}',capacity=cap)
        # 512/1024 current 528-byte slots fit exactly in eight fixed tails.
        slots_per_tail=(STOCK_CAP-cap)*4//528
        assert slots_per_tail in (64,128) and slots_per_tail*528==(STOCK_CAP-cap)*4
        spans=[(RING+lane*STRIDE+cap*4,RING+(lane+1)*STRIDE) for lane in range(8)]
        assert all(start%32==0 and end-start==slots_per_tail*528 for start,end in spans)
        assert all(a[1]<=b[0] for a,b in zip(spans,spans[1:]))
        passed(f'fixed_eight_tail_arithmetic_{slots_per_tail*8}_slots',ordinary_frames=cap,ordinary_seconds=cap/48000,
               slots=slots_per_tail*8,retained_seconds=slots_per_tail*8*64/48000,
               tail_spans=[list(map(hex,span)) for span in spans],device_owned=False)
    r=TapRig();cap=CAPACITIES[0];capacities(r,cap,STOCK_CAP);tails(r,cap);events,handle=tail_events(r,cap)
    expected=alternate_write(r,0,1,cap)
    r.m.uc.hook_del(handle)
    assert events and r.raw(OUTPUT,len(expected))!=expected
    assert r.raw(RING+cap*4,128)!=CANARY*128
    passed('negative_control_shrinking_only_recording_descriptor_corrupts_proposed_tail',tail_accesses=len(events),production_patch=False)
    r=TapRig();capacities(r,CAPACITIES[0]);initialize(r)
    assert get32(r.m,B+0x53e8)==get32(r.m,B+0x53f8)==STOCK_CAP
    passed('original_reinitialization_restores_full_capacity_and_invalidates_a_prior_tail_layout',effective_capacity=STOCK_CAP)
    r=TapRig();initialize(r);r.window(0x8000ad7a,0x8000ad96)
    capacities(r,CAPACITIES[0])
    assert get32(r.m,B+0x53e8)==CAPACITIES[0] and get32(r.m,C+0x50)==get32(r.m,C+0x1e94)==STOCK_CAP
    passed('negative_control_late_descriptor_shrink_leaves_stale_recorder_capacity_caches',descriptor_capacity=CAPACITIES[0],cached_capacity=STOCK_CAP)
    report=dict(passed_groups=len(results),results=results,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
       production_changes=False,device_access=False,
       limitations=['Host-seeded capacities and tail canaries; complete cold-init/mode switching and all access paths are not executed.',
        'Original PCM16/PCM24/float32 alternate writers, float32 reader, capacity getters, initialization and DSP twelve-lane copy windows execute.',
        'USB callers, alternate MAIN audio callback, reconfiguration and producer scheduling require further audit.',
        'No complete ownership, initialization placement, buffer-backlog margin, actual service or catch-up claim. Fixed tails remain unavailable on hardware.',
        'Current history API is contiguous; arithmetic spans are not an allocation for that API.'])
    out=ROOT/'analysis/stock_ring_layout_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out))))

if __name__=='__main__':main()
