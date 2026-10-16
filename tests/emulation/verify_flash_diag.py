#!/usr/bin/env python3
"""Experiment 39's diagnostic build: the read-only flash query (kind 8) and
status schema 7, executed with the build's own code; the stock serial-flash
read is modelled over a synthetic flash whose MAIN, PANEL and AUDIOGUIDE
regions hold the installed image and Zoom's stock file. Decoded by the
backup tool's own decoder. No device access.
"""
import json,random,struct,sys
from verify_pad_protocol import ROOT,INPUT
import verify_master_ref as V
from build_master_ref import build
from plan_master_ref import plan
from capture_jump_patches import symbols
from build_master_trial import trial
sys.path.insert(0,str(ROOT/'tools/device'))
import l6_flash_backup as F
from l6_padref_probe import request as status_request,decode as status_decode

def main():
    cases=[]
    def passed(case,**d):cases.append(dict(case=case,**d))
    elf=build(trial=True,stereo=True,flash=True);P=plan(elf,trial=True)
    V.PLAN=P;V.PACK=P['pack'];V.N=symbols(elf);N=V.N
    image=trial('flash_diag')[0];stock=F.STOCK.read_bytes()
    rnd=random.Random(39);flash=bytearray(rnd.randbytes(F.FLASH))
    for name,base in F.PACKAGE.items():
        lo,hi=F.REGIONS[name];flash[lo:hi]=(image if name=='MAIN' else stock)[base:base+hi-lo]
    r=V.MasterRig();m=r.m;replies=[];reads=[]
    def flash_read(a):
        off,dst,n=a[0],a[1],a[2]
        if not dst or off+n>F.FLASH:return 0xffffffff
        reads.append((off,n));m.uc.mem_write(dst,bytes(flash[off:off+n]));return 0
    m.hooks[0x8001aee8]=flash_read
    m.hooks[0x80031648]=lambda a:replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    m.uc.mem_write(0x80629b60,b'\x02')
    def query(packet):
        m.uc.mem_write(INPUT,struct.pack('<I',len(packet))+packet+bytes(16));return m.invoke(N['mr_query'],[INPUT])
    # Reads anywhere decode to the flash's bytes (each region; the last block).
    got={}
    for k,off in enumerate((0,0x1000,0x065000,0x2ea000,0x2fa000,0x3fa000,F.FLASH-F.CHUNK)):
        assert query(F.request(off,F.CHUNK,k))==1;d=F.decode(replies[-1])
        assert (d['offset'],d['length'],d['status'],d['token'])==(off,F.CHUNK,0,k) and d['data']==bytes(flash[off:off+F.CHUNK]),hex(off)
        got[hex(off)]=d['data'][:4].hex()
    assert query(F.request(0x1234,7,1))==1 and F.decode(replies[-1])['data']==bytes(flash[0x1234:0x123b])   # odd length
    passed('flash_reads_return_the_flash_bytes_through_the_builds_own_query',reads=len(reads),sample=got)
    # Bad requests and a busy recorder are refused without a read.
    n=len(reads)
    for packet,status in ((F.request(0,0,2),1),(F.request(0,257,3),1),(F.request(F.FLASH-128,256,4),1)):
        assert query(packet)==1 and F.decode(replies[-1])['status']==status
    for state in (1,2):
        m.uc.mem_write(0x80578ebc,bytes([state]));assert query(F.request(0,16,5))==1 and F.decode(replies[-1])['status']==2
    m.uc.mem_write(0x80578ebc,b'\x00');V.put32(m,0x80578ec0,1)
    assert query(F.request(0,16,6))==1 and F.decode(replies[-1])['status']==2;V.put32(m,0x80578ec0,0)
    assert len(reads)==n and query(bytes((0xf0,0x52,0,0,0x6f,8,1,0,0,0,0,0x80,0,0xf7)))==0   # 8-bit byte: not ours
    passed('bad_requests_and_a_busy_recorder_are_refused_without_reading')
    # Status schema 7: chain, Main readiness, anchors and flash counters.
    for name,value in (('anchor_pending',5),('anchor_existed',1),('anchor_created',2),('anchor_failed',0),
                       ('anchor_listed',2),('anchor_status',0)):r.set(name,value)
    V.put32(m,N['mr_main_ready'],2989)
    assert query(status_request(9))==1;s=status_decode(replies[-1])
    assert s['schema']==7 and s['chain_on'] and s['main_ready']==2989 and s['anchor_created']==2 and s['anchor_pending']==5
    assert s['flash_reads']==len(reads) and s['flash_refused']==3
    passed('status_schema_7_reports_chain_anchors_and_flash_counters',flash_reads=s['flash_reads'],flash_refused=s['flash_refused'])
    result=dict(passed=True,groups=len(cases),results=cases)
    (ROOT/'analysis/flash_diag_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
