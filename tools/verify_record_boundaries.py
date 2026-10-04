#!/usr/bin/env python3
"""Original record initialization, stop endpoint and final payload, offline.

Synthetic state and modeled filesystem/queues; no device access or installed
capture hook. Conditional history branches are not treated as device settings.
"""
import hashlib,json,struct
from unicorn.arm_const import UC_ARM_REG_R6,UC_ARM_REG_R8,UC_ARM_REG_R2
from verify_record_events import cursor_rig,FLAGS,CURSOR,STOP_SAVED,u32
from verify_recording_writer import WriterRig,C
from verify_uncompressed_tap import TapRig,B,RING,STRIDE,packed
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,BIAS

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=cursor_rig((1,1,1));m=r.m
    m.uc.mem_write(FLAGS,b'\xff'*5)
    m.invoke(0x80010678,[])
    assert r.raw(FLAGS,5)==bytes(5)
    assert m.invoke(0x80018f10,[])==128000
    assert r.raw(FLAGS,5)==b'\0\0\1\0\0'
    passed('original_flag_initializer_clears_all_five_bytes_and_selects_no_history')

    # The selected cursor flag set by start makes stop return current write
    # position. This is the next free sample position, not the last included one.
    for pos in (0,64,128000,239936):
        r=cursor_rig((1,0,0));m=r.m;m.invoke(0x80018f10,[])
        put32(m,B+0x53e4,pos)
        assert m.invoke(0x80002460,[])==pos
    passed('normal_start_then_stop_getter_returns_current_write_cursor_including_wrap')

    # Exercise the alternate flag-zero behavior without assigning it a UI name.
    cases=[(128000,128064,128064,0),(239936,0,0,0),
           (0,120000,120000,0),(128000,10000,128000,1)]
    for current,saved,wanted,flag in cases:
        r=cursor_rig();m=r.m
        put32(m,B+0x53e4,current);put32(m,CURSOR,saved)
        m.uc.mem_write(FLAGS+2,b'\0')
        assert m.invoke(0x80018e70,[])==wanted
        assert r.raw(FLAGS+2,1)==bytes([flag])
    passed('alternate_stop_getter_preserves_nearby_saved_cursor_and_switches_after_half_ring')

    # Every enabled stream gets an absolute file endpoint from current consumed
    # frames plus the signed ring distance to stop (one capacity correction).
    for active in (0xfff,1<<10,0):
        for read,stop,consumed in ((128000,128017,500000),(239936,32,0),(239936,32,500000),(64,64,1234)):
            r=cursor_rig();m=r.m
            put32(m,C+8,active);put32(m,C+0x50,240000)
            for i in range(12):
                put32(m,C+0x20+4*i,read);put32(m,C+0x484+4*i,consumed)
                put32(m,C+0x4e4+4*i,0xffffffff)
            m.invoke(0x800382a8,[stop])
            # Thumb ADD here preserves flags from SUBS(stop, read), so MI
            # corrects a negative ring distance, even when total is positive.
            total=consumed+(stop-read)%240000
            for i in range(12):assert u32(r,C+0x4e4+4*i)==(total if active>>i&1 else 0xffffffff)
    passed('original_stop_endpoint_conversion_updates_only_enabled_streams_with_wrap_and_prior_audio')

    # Saved endpoint -> original stop bridge -> real producer -> queued writer
    # -> WAV. Sector remainders flush at the stop boundary, including one frame.
    outputs=[]
    for start,count in ((64,1),(64,17),(64,64),(96,49)):
        r=WriterRig();m=r.m;r.header();r.position=start;r.frames=64
        left=[i/128 for i in range(128)];right=[-i/256 for i in range(128)]
        r.floats(RING+10*STRIDE,left);r.floats(RING+11*STRIDE,right)
        put32(m,C+8,1<<10);put32(m,C+0x50,128)
        put32(m,C+0x20+10*4,start)
        stop=(start+count)%128;put32(m,STOP_SAVED,stop)
        # Later audio is already present; bridge must read the saved endpoint.
        put32(m,B+0x53e4,(stop+64)%128)
        r.window(0x8000b732,0x8000b73a)
        assert u32(r,C+0x4e4+10*4)==count
        r.produce();r.drain()
        expected=packed([v for i in range(count) for v in (left[(start+i)%128],right[(start+i)%128])])
        assert r.finish()==expected
        assert sum(a[2] for a in r.reader_args)==count
        assert u32(r,C+0x440)&(1<<10)==0
        outputs.append(dict(start=start,exclusive_stop=stop,frames=count,payload_bytes=len(expected)))
    passed('saved_stop_is_exclusive_and_original_writer_flushes_exact_final_samples',cases=outputs,
           limitation='Synthetic 128-frame ring; public filesystem and work queue modeled')

    # Remove the request/consumption stubs. The original request reads the
    # per-stream cursor; original acknowledgement advances it through wrap and
    # maintains its 64-bit count. Stop after repeated laps, with a short tail.
    r=WriterRig();m=r.m;r.header();expected=[]
    del m.hooks[0x800376a0];del m.hooks[0x80037638]
    m.hooks[0x8001aaa0]=lambda a:0;m.hooks[0x8001aab8]=lambda a:0
    put32(m,C+0x50,128);put32(m,C+0x20+40,96)
    put32(m,C+0xec,10);put32(m,C+0xf0,64);put32(m,C+8,1<<10)
    for block in range(17):
        start=u32(r,C+0x20+40);count=17 if block==16 else 64
        left=[0.0]*128;right=[0.0]*128
        for i in range(64):
            left[(start+i)%128]=(block*64+i)/2048
            right[(start+i)%128]=-(block*64+i)/4096
        r.floats(RING+10*STRIDE,left);r.floats(RING+11*STRIDE,right)
        if block==16:
            put32(m,STOP_SAVED,(start+count)%128)
            r.window(0x8000b732,0x8000b73a)
            assert u32(r,C+0x4e4+40)==16*64+17
        r.produce();r.drain()
        expected.extend(v for i in range(count) for v in (left[(start+i)%128],right[(start+i)%128]))
        assert u32(r,C+0x20+40)==(start+count)%128
    assert r.finish()==packed(expected)
    assert struct.unpack('<Q',r.raw(C+0x58+10*8,8))[0]==1041
    passed('original_cursor_acknowledgement_and_writer_preserve_1041_frames_across_repeated_ring_wraps',
           frames=1041,ring_capacity=128,limitation='Accelerated wraps using a smaller synthetic ring, no real-time scheduling')

    # Confirm actual ring initialization rather than assuming test fixture size.
    r=TapRig();m=r.m
    m.uc.reg_write(UC_ARM_REG_R8,B);m.uc.reg_write(UC_ARM_REG_R6,0)
    m.uc.reg_write(UC_ARM_REG_R2,0x53f0)
    r.window(0x800121a0,0x800121e4)
    assert u32(r,B+0x53e0)==RING and u32(r,B+0x53e8)==240000
    assert u32(r,B+0x53e4)==0 and u32(r,B+0x53ec)==0
    assert STRIDE==240000*4 and RING+12*STRIDE==0x81f26000
    passed('original_ring_initialization_allocates_five_seconds_per_channel_at_48k',
           base=hex(RING),frames_per_channel=240000,channels=12,bytes=12*STRIDE,end=hex(RING+12*STRIDE))

    startup=[]
    for a in range(0x800a68dc,0x800a695c,16):
        source,dest,length,helper=struct.unpack_from('<4I',IMAGE,a-BIAS)
        startup.append(dict(entry=hex(a),source=hex(source),destination=hex(dest),
                            length=length,end=hex(dest+length),helper=hex(helper)))
    report=dict(passed_groups=len(results),results=results,startup=startup,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        unproven_gap=dict(start='0x80960078',end='0x80bb9400',bytes=0x80bb9400-0x80960078,
                         status='Not a free allocation; only absent from startup destination ranges'),
        limitations=['No dynamic device state, timing, memory headroom or actual exclusive allocation',
          'No half-second/two-second flag setter or user setting established',
          'Exact output verified with synthetic short rings and 1041-frame repeated-wrap sequence',
          'Production-duration recordings, split files and instruction-level stop concurrency untested',
          'No producer/worker or pad-reader fence is bound'])
    target=ROOT/'analysis/record_boundaries_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(target)),indent=2))

if __name__=='__main__':main()
