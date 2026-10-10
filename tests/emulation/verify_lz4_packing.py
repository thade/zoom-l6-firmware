#!/usr/bin/env python3
"""Alternative loader boundaries and actual original scatter entry, offline."""
import hashlib,json,random,struct
import lz4.block
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_pad_protocol import Machine,ROOT,IMAGE,BIAS,RETURN
from plan_capture_lz4 import packing,report
from plan_capture_packing import DECOMPRESS,ZERO
from capture_jump_patches import SCATTER
from scatter_codec import expand

P=packing();S=0x21000100;D=0x21020000

def decode(encoded,capacity,expected=None,*,source=S,destination=D,declared=None):
    m=Machine();m.uc.mem_map(0x21000000,0x40000)
    m.uc.mem_write(SCATTER[0],P['loader'])
    m.uc.mem_write(S-16,b'\x5a'*(len(encoded)+32));m.uc.mem_write(S,encoded)
    m.uc.mem_write(D-16,b'\xa5'*(min(capacity,65536)+32))
    n=len(encoded) if declared is None else declared
    def read(u,k,a,size,v,x):assert source<=a and a+size<=source+n,(hex(a),size,n)
    def write(u,k,a,size,v,x):assert destination<=a and a+size<=destination+capacity,(hex(a),size,capacity)
    m.uc.hook_add(UC_HOOK_MEM_READ,read,begin=S-16,end=S+len(encoded)+15)
    m.uc.hook_add(UC_HOOK_MEM_WRITE,write,begin=D-16,end=D+min(capacity,65536)+15)
    m.uc.reg_write(A.UC_ARM_REG_SP,0x20010000);m.uc.reg_write(A.UC_ARM_REG_LR,RETURN|1)
    for reg,value in zip((A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2,A.UC_ARM_REG_R3),
                         (source,n,destination,capacity)):m.uc.reg_write(reg,value)
    m.uc.emu_start(P['names']['scatter_lz4_decode']|1,RETURN+2,count=2000000)
    assert m.reached_return,'Decoder exceeded bounded instruction budget'
    status=m.uc.reg_read(A.UC_ARM_REG_R0)
    assert bytes(m.uc.mem_read(D-16,16))==b'\xa5'*16
    assert bytes(m.uc.mem_read(D+min(capacity,65536),16))==b'\xa5'*16
    if expected is not None:
        assert status==0 and bytes(m.uc.mem_read(D,capacity))==expected
    return status

def startup(candidate=True,corrupt=False,pack=P):
    P=pack
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for address,size in ((0x80000000,0x2000000),(0x20000000,0x40000),(0x20210000,0x20000),(0,0x1000)):
        u.mem_map(address,size);u.mem_write(address,b'\xa5'*size)
    u.mem_write(0x80001000,IMAGE[0x200:0xb5ce4]) # Original payload length ONLY.
    if candidate:
        u.mem_write(SCATTER[0],P['source_blob'])
        for e in P['edits']:
            assert bytes(u.mem_read(e['address'],len(bytes.fromhex(e['old']))))==bytes.fromhex(e['old'])
            u.mem_write(e['address'],bytes.fromhex(e['new']))
        if corrupt:u.mem_write(P['code_source'],b'\xff'*4)
    reached=[];helpers=[]
    def end(u,a,n,x):reached.append(a);u.emu_stop()
    for pc in (0x80067a60,P['names']['scatter_lz4_failed']&~1):
        u.hook_add(UC_HOOK_CODE,end,begin=pc,end=pc)
    def helper(u,a,n,x):helpers.append((a,*[u.reg_read(r) for r in (A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2)]))
    for pc in (DECOMPRESS,ZERO,0x80079498,P['names']['scatter_lz4']&~1):
        u.hook_add(UC_HOOK_CODE,helper,begin=pc,end=pc)
    u.emu_start(0x80001401,0x80067a62,count=100000000)
    if corrupt:
        assert reached==[P['names']['scatter_lz4_failed']&~1]
        expected=P['dsp'] if P.get('source_reuse') else b'\xa5'*SCATTER[2]
        assert bytes(u.mem_read(SCATTER[1],SCATTER[2]))==expected
        return dict(stopped_before_Main=True)
    assert reached==[0x80067a60] and u.reg_read(A.UC_ARM_REG_SP)==0x2021fff0
    assert len(helpers)==(10 if candidate else 8)
    hashes=[]
    for table in range(0x800a68dc,0x800a695c,16):
        src,dest,n,method=struct.unpack_from('<4I',IMAGE,table-BIAS)
        expected=(bytes(n) if method==ZERO else
                  expand(IMAGE[src-BIAS:],n)[0] if method==DECOMPRESS else IMAGE[src-BIAS:src-BIAS+n])
        if candidate and dest==SCATTER[1]:expected=P['dsp']
        actual=bytes(u.mem_read(dest,n));assert actual==expected
        hashes.append(dict(destination=dest,bytes=n,sha256=hashlib.sha256(actual).hexdigest()))
    if candidate:
        j=P['jumps'];a=j['candidate_code_start'];z=j['candidate_load_end']
        assert bytes(u.mem_read(a,z-a))==P['code']
        assert bytes(u.mem_read(j['globals_start'],j['globals_end']-j['globals_start']))==bytes(j['globals_end']-j['globals_start'])
        ordered=[(ZERO,0,j['globals_start'],j['globals_end']-j['globals_start']),
            (P['names']['scatter_lz4']&~1,P['code_source'],a,len(P['code'])),
            (P['names']['scatter_lz4']&~1,P['dsp_source'],SCATTER[1],len(P['dsp']))]
        if P.get('source_reuse'):
            expected=bytearray(P['source_blob'])
            expected[a-SCATTER[0]:z-SCATTER[0]]=P['code']
            expected[j['globals_start']-SCATTER[0]:j['globals_end']-SCATTER[0]]=bytes(j['globals_end']-j['globals_start'])
            assert bytes(u.mem_read(SCATTER[0],SCATTER[2]))==expected
            assert helpers[4:7]==[ordered[2],ordered[1],ordered[0]]
        else:
            assert bytes(u.mem_read(a-16,16))==bytes(u.mem_read(z,16))==b'\xa5'*16
            assert bytes(u.mem_read(SCATTER[0],SCATTER[2]))==P['source_blob']
            assert helpers[4:7]==ordered
    return dict(hashes=hashes,helpers=helpers)

def main():
    cases=[]
    def passed(case,**details):cases.append(dict(case=case,**details))
    rng=random.Random(610)
    streams=[bytes(n) for n in (1,4,5,12,13,19,255,1024,65536)]
    streams += [b'ABCD'*300,b'A'*400,bytes(range(256))*200,
                *[bytes(rng.randrange(256) for _ in range(n)) for n in (1,5,12,13,15,16,270,4096)]]
    streams += [P['dsp'],P['code']]
    for stream in streams:
        block=lz4.block.compress(stream,mode='high_compression',compression=12,store_size=False)
        assert decode(block,len(stream),stream)==0
    passed('Compiled ARM decoder agrees with independent LZ4 encoder/decompressor for complete real payloads and boundary streams',streams=len(streams))
    bad=[(b'',1),(b'\xf0',15),(b'\xf0\xff',300),(b'\x10',1),
         (b'\x10A\x00\x00',20),(b'\x10A\x02\x00',20),
         (b'\x1fA\x01\x00',300),(b'\x10A\x01',20),
         (b'\x00',1),(b'\x50ABCDE',4),(b'\x50ABCDE',6),
         (b'\x10A\x01\x00\x10B',6)]
    for block,n in bad:assert decode(block,n)==12
    valid=lz4.block.compress(b'abcdefgh'*64,store_size=False)
    for length in range(len(valid)):assert decode(valid[:length],512)==12
    passed('Truncations, invalid distances, length overflows, size mismatches and invalid terminal sequences are rejected within declared bounds',cases=len(bad)+len(valid))
    for kw in (dict(source=0),dict(destination=0),dict(source=0xfffffff0,declared=32),
               dict(destination=0xfffffff0),dict(destination=S),dict(destination=S+2)):
        assert decode(b'\xf0\x31'+b'A'*64,64,**kw)==12
    passed('Null, wrapping and overlapping input/output spans are rejected before unsafe accesses')
    # Valid and invalid mutations need not share an output. Any accepted result
    # must agree with the independent decoder, and all accesses remain bounded.
    checked=0
    for i in range(len(valid)):
        for value in (0,255,valid[i]^0x80):
            block=valid[:i]+bytes([value])+valid[i+1:]
            status=decode(block,512)
            if status==0:decode(block,512,lz4.block.decompress(block,uncompressed_size=512))
            else:assert status==12
            checked+=1
    passed('Deterministic malformed mutations retain bounds; accepted outputs agree with independent decoder',mutations=checked)
    baseline=startup(False);candidate=startup()
    assert baseline['hashes'][:4]+baseline['hashes'][5:]==candidate['hashes'][:4]+candidate['hashes'][5:]
    passed('Actual original entry and scatter loop initialize all original regions, exact patched DSP, exact capture code and zero globals',**candidate)
    passed('Malformed compressed-size header halts startup before exposing partial code or entering Main',**startup(corrupt=True))
    r=report(P);out=ROOT/'analysis/lz4_packing_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,packing=r,
        limitations=['No device update, default-build selection, physical ownership, cache or startup timing proof.',
            'Host lz4 4.4.5 provides an independent codec; this is a bounded deterministic corpus, not exhaustive fuzzing.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),spare_bytes=r['spare_bytes'],loader_bytes=r['loader_bytes'],report=str(out))))

if __name__=='__main__':main()
