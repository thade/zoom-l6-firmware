#!/usr/bin/env python3
"""Segment ownership/indexing with native DSP windows; no device operations."""
import json,struct
from unicorn import UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_block_exchange import ExchangeRig,P,OBS,KEY,OUT
from verify_uncompressed_tap import B,RING,STRIDE,packed
from verify_history_capture import values
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT

FLAG=0x80000000
CAP=223104
META=0x22017400
TAIL_BYTES=67584
TAILS=tuple(RING+i*STRIDE+CAP*4 for i in range(8))

def metadata(per=128,segments=8,spans=None):
    spans=spans or [(a,TAIL_BYTES) for a in TAILS]
    return struct.pack('<18I',segments,per,*[v for pair in spans for v in pair])

class SegmentedExchange(ExchangeRig):
    def __init__(self,per=128):
        super().__init__(capacity=CAP)
        self.count=8*per
        for a in TAILS:self.m.uc.mem_write(a,b'\xa5'*TAIL_BYTES)
        self.m.uc.mem_write(META,metadata(per))
        assert self.xcall('exchange_prepare_storage',META,FLAG|self.count)==0
        assert self.xcall('exchange_begin',OBS)==0
        def access(uc,kind,a,n,value,user):
            # Only new code may access history; native code uses ordinary spans.
            pc=uc.reg_read(UC_ARM_REG_PC)
            if 0x10010000<=pc<0x10020000:
                assert any(base<=a and a+n<=base+per*528 for base in TAILS),(hex(pc),hex(a),n)
        self.tail_hook=self.m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,access,
                          begin=RING,end=RING+12*STRIDE-1)
    def slot(self,index):return TAILS[(index%self.count)//(self.count//8)]+(index%(self.count//8))*528

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=SegmentedExchange()
    # Exact samples and pointers through every boundary and three whole laps.
    for i in range(3*r.count+9):
        assert r.block()==0
        status,slot=r.claim(i*64);assert status==0 and slot==r.slot(i)
        wanted=[values(i*64+j) for j in range(64)]
        assert r.raw(slot+r.xlayout[2],512)==packed([v[0]*2**31 for v in wanted]+[v[1]*2**31 for v in wanted])
        assert r.release(i*64)==0
    assert r.claim(0)[0]==17
    passed('exact_1024_slot_mapping_and_samples_across_all_eight_segments_and_three_wraps',blocks=i+1)

    r=SegmentedExchange(per=2)
    for _ in range(14):assert r.block()==0
    first=13*64;status,slot=r.claim(first);assert status==0
    saved=r.raw(slot,528)
    for _ in range(r.count-1):assert r.block()==0
    assert r.block()==11 and r.raw(slot,528)==saved
    assert r.release(first+r.count*64)==12 and r.release(first)==0
    assert r.claim(first+r.count*64)[0]==17
    assert r.block()==0
    passed('reader_claim_in_seventh_segment_survives_producer_wrap_and_missing_generation_is_rejected')

    # Malformed descriptors fail before any history writes or publication.
    r=SegmentedExchange();before=[r.raw(a,TAIL_BYTES) for a in TAILS]
    def bad(blob,tag=FLAG|1024):
        r.m.uc.mem_write(META,blob)
        assert r.xcall('exchange_prepare_storage',META,tag)==12
        assert [r.raw(a,TAIL_BYTES) for a in TAILS]==before
        assert r.xcall('exchange_begin',OBS)==12
    for segments,per in ((0,128),(3,128),(16,64),(8,127),(8,0),(8,256)):
        bad(metadata(per,segments))
    for base,n in ((0,TAIL_BYTES),(TAILS[0]+4,TAIL_BYTES),(TAILS[0],TAIL_BYTES-1),
                   (0xfffffff8,TAIL_BYTES),(META,TAIL_BYTES),(TAILS[1],TAIL_BYTES)):
        spans=[(a,TAIL_BYTES) for a in TAILS];spans[0]=(base,n);bad(metadata(spans=spans))
    for count in (0,1,3,8192):bad(metadata(),FLAG|count)
    bad(metadata(per=0),FLAG|2)
    # Full declared ranges, not just occupied slots, must be disjoint.
    spans=[(a,TAIL_BYTES) for a in TAILS];spans[0]=(TAILS[0],STRIDE+1)
    bad(metadata(spans=spans))
    assert r.xcall('exchange_prepare_storage',META+2,FLAG|1024)==12
    assert r.xcall('exchange_prepare',META,FLAG|1024)==12
    r.m.uc.mem_write(META,metadata())
    assert r.xcall('exchange_prepare_storage',META,FLAG|1024)==0
    assert r.xcall('exchange_prepare',META,FLAG|1024)==12
    assert r.xcall('exchange_begin',OBS)==12
    passed('invalid_counts_geometry_alignment_size_wrapping_metadata_and_full_span_overlap_rejected')

    # Preparation only clears states; payload and unused tails are untouched.
    r=SegmentedExchange(per=2)
    for a in TAILS:
        assert r.raw(a+4,524)==b'\xa5'*524 and r.raw(a+528+4,524)==b'\xa5'*524
        assert r.raw(a+1056,TAIL_BYTES-1056)==b'\xa5'*(TAIL_BYTES-1056)
    r.m.uc.hook_del(r.tail_hook)
    for i in range(2,7):
        # One contiguous-compatible segment and smaller power-of-two geometries.
        per=1<<i;r.m.uc.mem_write(META,metadata(per))
        assert r.xcall('exchange_prepare_storage',META,FLAG|(8*per))==0
    passed('worker_preparation_clears_only_states_and_accepts_power_of_two_geometries')
    report=dict(passed=True,groups=len(cases),results=cases,
        limits=['Coherent emulator RAM; external spans are host-seeded, not physically reserved.',
                'Native gain/copy windows; no complete DSP, RTOS, cache, SD or DMA execution.'])
    (ROOT/'analysis/segmented_exchange_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
