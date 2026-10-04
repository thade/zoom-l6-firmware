#!/usr/bin/env python3
"""Offline stock record cursor selection and control ordering.

Executes original instructions with explicit external callees stubbed for event
tests. Does not install hooks or claim actual UI/SD/audio task synchronization.
"""
import hashlib,json,struct
from verify_uncompressed_tap import TapRig,B,RING,STRIDE,packed
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

FLAGS=0x80570c10
CURSOR=0x80570c0c
UI=0x80578ebc
REC=0x801f8c48
TARGET=0x801f5f00
START_SAVED=0x80443154
STOP_SAVED=START_SAVED+4

def u32(r,a):return struct.unpack('<I',r.raw(a,4))[0]

def cursor_rig(flags=(0,1,0),position=128000,available=100000,rate=48000):
    r=TapRig();m=r.m
    put32(m,B,rate);put32(m,B+0x53e4,position)
    put32(m,B+0x53e8,240000);put32(m,B+0x53ec,available)
    # Tuple corresponds to getters 10638, 10658, 10668. UI meanings unbound.
    for offset,value in zip((4,0,3),flags):m.uc.mem_write(FLAGS+offset,bytes([value]))
    m.uc.mem_write(B+0x53d8,struct.pack('<Q',0xffffff00))
    return r

def stub(r,events,address,value=0):
    def call(args):
        events.append((address,tuple(args[:4]),r.raw(UI,1)[0]))
        return value
    r.m.hooks[address]=call

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    cases=[((0,1,0),128000,100000,0),
           ((1,1,1),128000,100000,24000),
           ((0,0,1),128000,100000,96000),
           ((0,0,0),128000,100000,0),
           ((1,0,0),128000,1234,1234),
           ((0,0,1),64,100000,96000),
           ((1,0,0),64,0,0)]
    details=[]
    for flags,pos,avail,history in cases:
        r=cursor_rig(flags,pos,avail);m=r.m
        selected=m.invoke(0x80018f10,[])
        assert selected==(pos-history)%240000 and u32(r,CURSOR)==selected
        assert struct.unpack('<Q',r.raw(B+0x53d8,8))[0]==0xffffff00+history
        assert r.raw(FLAGS+2,1)==b'\x01'
        assert u32(r,B+0x53e4)==pos and u32(r,B+0x53ec)==avail
        details.append(dict(flags=flags,write_cursor=pos,available=avail,lookback=history,selected=selected))
    passed('original_start_cursor_selects_history_clamps_to_available_and_wraps_with_counter_carry',cases=details)

    # Original stereo reader receives the selected ring cursor. Known different
    # samples at historical/current positions make a mistaken start observable.
    for flags,history in (((1,0,0),24000),((0,0,1),96000)):
        r=cursor_rig(flags);m=r.m;selected=m.invoke(0x80018f10,[])
        for channel,value in ((10,.25),(11,-.5)):
            r.floats(RING+channel*STRIDE+selected*4,[value]*64)
            r.floats(RING+channel*STRIDE+128000*4,[.875]*64)
        assert r.read_stream(10,position=selected)==packed([.25,-.5]*64)
        assert r.read_stream(10,position=128000)==packed([.875,.875]*64)
    passed('original_stereo_reader_distinguishes_selected_history_from_current_audio')

    # Request selects and stores its start before admission. Fail the first
    # admission check and verify there is no start dispatch.
    r=cursor_rig((1,0,0));events=[]
    stub(r,events,0x80006290,1);stub(r,events,0x80007c20)
    stub(r,events,0x8004b6d8)
    r.m.invoke(0x80034f40,[0xffffffff])
    assert u32(r,START_SAVED)==104000
    assert [x[0] for x in events]==[0x80006290,0x80007c20]
    assert events[-1][1][0]==6 and r.raw(UI,1)==b'\0'
    passed('rejected_record_request_still_selects_and_stores_cursor_without_start_dispatch')

    # The real backend reads the saved cursor and copies it to all 12 stream
    # positions. Move the current audio cursor between request and backend to
    # model setup latency: original code must still use the saved position.
    for flags,history in (((0,1,0),0),((1,0,0),24000),((0,0,1),96000)):
        r=cursor_rig(flags);m=r.m;events=[]
        selected=m.invoke(0x80018f10,[]);m.invoke(0x80006908,[selected])
        put32(m,B+0x53e4,128000+640)
        m.uc.mem_write(REC+0xa,b'\x01')
        for fn in (0x80002908,0x8001aaa0,0x80002cb0,0x8001aab8,
                   0x80002a98,0x80002d28,0x80002ad8,0x80002a90,
                   0x8000b090):stub(r,events,fn)
        m.invoke(0x8000b168,[0])
        assert struct.unpack('<12I',r.raw(0x8077ca30+0x20,48))==(selected,)*12
        assert selected==128000-history and selected!=u32(r,B+0x53e4)
        assert [e[0] for e in events][-1]==0x8000b090
    passed('original_backend_uses_saved_start_for_all_twelve_streams_despite_later_write_cursor',
           limitation='Audio advance and setup delay are modeled; file creation and scheduler are stubbed')

    # Real RecStart and b650. Only unrelated UI/lock callees and the deeper
    # b168 backend are stubbed; executing b650 distinguishes early return.
    for enabled in (0,1):
        r=cursor_rig();m=r.m;events=[]
        m.uc.mem_write(TARGET,b'\xff');m.uc.mem_write(REC+0x2c,bytes([enabled]))
        m.uc.mem_write(REC+0xa,b'\x01')
        for fn in (0x80008a60,0x8001e4d8,0x80007c20,0x80008a70,
                   0x8000b320,0x8000b330,0x80076950,0x800763d8,0x8000b168):stub(r,events,fn)
        m.invoke(0x8004b9a0,[])
        backend=[e for e in events if e[0]==0x8000b168]
        assert len(backend)==enabled and r.raw(UI,1)==b'\x01'
        assert r.raw(REC+8,1)==bytes([enabled])
        assert r.raw(B+0x53d4,1)==bytes([enabled])
        if enabled:assert backend[0][1][0]==0 and backend[0][2]==0
        assert events[-1][0]==0x800763d8 and events[-1][2]==1
    passed('record_UI_flag_is_set_even_when_original_backend_start_returns_early',
           limitation='Synthetic disabled-state negative control; not evidence this state occurs in normal device use')

    # RecStop retains ordinary negative target; stop cursor store and backend
    # precede UI clearing. Backend completion itself is intentionally modeled.
    for target in (0xff,2):
        r=cursor_rig();m=r.m;events=[]
        m.uc.mem_write(TARGET,bytes([target]));m.uc.mem_write(UI,b'\x01')
        arg=0x21033000;put32(m,arg,0)
        for fn in (0x8001e4d8,0x80007c20,0x8000b698,0x8000acf0,
                   0x8000b9b8,0x80008a80,0x80008880,0x80008890,0x800068c8,
                   0x8000bab8,0x8000bbe8,0x80020360,0x80008a60,0x80076950,
                   0x800763d8,0x80006968,0x80006740):stub(r,events,fn)
        stub(r,events,0x80002460,54321)
        m.invoke(0x8004ba40,[arg])
        backend=[e for e in events if e[0]==0x8000b698]
        assert len(backend)==1 and backend[0][1][0]==(0xffffffff if target==255 else target)
        assert backend[0][2]==1 and r.raw(UI,1)==b'\0'
        assert u32(r,STOP_SAVED)==54321 and r.raw(TARGET,1)==b'\xff'
        assert next(e for e in events if e[0]==0x800763d8)[2]==0
    passed('stop_callback_stores_cursor_and_calls_backend_before_clearing_record_UI_flag',
           limitation='Stop cursor value and backend are stubbed; no producer/pad-reader fence is proved')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        history_bytes=dict(half_second=24000*8,two_seconds=96000*8,full_five_second_ring=240000*8),
        current_extra_buffer_bytes=128*512,
        limitations=['Original functions with synthetic state; no running device, scheduler, ADC or SD IO',
          'Flag getters are real; mapping their values to user-facing modes remains unverified',
          'No sample-aligned start/stop bridge, spare RAM allocation or installed hook',
          'History capacity must also cover record setup latency and storage stalls',
          'No automatic pad assignment; earlier pad-reader fence remains unbound'])
    target=ROOT/'analysis/record_events_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(target)),indent=2))

if __name__=='__main__':main()
