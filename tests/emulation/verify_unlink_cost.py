#!/usr/bin/env python3
"""Cost of the stock unlink (0x80061f78) on a long track file, in SD sectors.

Research for docs/research/unused_track_files_findings.txt (section 7): if
unused tracks were deleted after a take, how much card work would the stock
unlink do inside RecStop? A track file of each length is placed on a modeled
card (FAT32 with 32 KiB clusters, and exFAT with 256 KiB clusters like the
owner's card), contiguous or interleaved with the six other track files the
recorder writes at the same time. The original mount runs on the first call,
then the original unlink runs over the sector model and every SD read, write
and barrier is counted. Sector counts only; no timing, card or device claim.
"""
import hashlib,json,struct,time
from verify_native_mount import MountedTree,PARTITION,FAT
from verify_native_exfat import ExfatTree,file_entries
from verify_capture_native_files import directory_entries
from verify_record_catalogue import putstr
from verify_pad_protocol import INPUT,ROOT,IMAGE

UNLINK=0x80061f78
FIRST=16            # first data cluster used; 2-9 hold the fixture folders
STEREO=384000       # bytes per second, 48 kHz stereo 32-bit float
STREAMS=7           # files the recorder writes at once
DURATIONS=(('20 s',20),('3 min',180),('10 min',600),('30 min',1800),('60 min',3600),('93 min',5580))

def chain(n,lane,stride):return [FIRST+k*stride+lane for k in range(n)]

def fat32_files(r,n,size,lanes,stride):
    """Directory entries in PAD1 and both FAT copies for the given lanes."""
    fs=r.fat_sectors;touched={}
    for lane in lanes:
        cl=chain(n,lane,stride)
        for i,c in enumerate(cl):
            s,o=divmod(c*4,512)
            for copy in (0,1):
                key=PARTITION+FAT+copy*fs+s
                b=touched.get(key)
                if b is None:b=touched[key]=bytearray(r.sectors.get(key,bytes(512)))
                struct.pack_into('<I',b,o,0x0fffffff if i==n-1 else cl[i+1])
    for k,b in touched.items():r.sectors[k]=bytes(b)
    d=bytearray(r.sectors[r.physical(4)])
    for lane in lanes:
        e=directory_entries('TRACK%02d.WAV'%(lane+1),b'TRACK%02d WAV'%(lane+1),FIRST+lane,0x20,size)
        d[32*lane:32*lane+len(e)]=e
    r.sectors[r.physical(4)]=bytes(d)
    return len(touched)//2

def exfat_files(r,n,size,lanes,stride,contiguous):
    bitmap=bytearray((r.clusters+7)//8);bitmap[0]=0xff;touched={}
    for lane in lanes:
        cl=chain(n,lane,stride)
        for i,c in enumerate(cl):
            bitmap[(c-2)//8]|=1<<((c-2)%8)
            if contiguous:continue
            s,o=divmod(c*4,512);key=PARTITION+r.fat_offset+s
            b=touched.get(key)
            if b is None:b=touched[key]=bytearray(r.sectors.get(key,bytes(512)))
            struct.pack_into('<I',b,o,0xffffffff if i==n-1 else cl[i+1])
    for k,b in touched.items():r.sectors[k]=bytes(b)
    r.store_cluster(2,bitmap)
    r.store_cluster(6,b''.join(file_entries('TRACK%02d.WAV'%(lane+1),FIRST+lane,size,0x20,contiguous) for lane in lanes))
    return len(touched)

def unlink(r,name):
    putstr(r.m,INPUT,'A:\\SOUND_PAD\\PAD1\\'+name);r.m.hooks.pop(UNLINK,None);r.requests=[]
    t=time.time();result=r.m.invoke(UNLINK,[INPUT]);elapsed=time.time()-t
    assert result==0,hex(result)
    reads=[q for q in r.requests if q['op']==2];writes=[q for q in r.requests if q['op']==3]
    assert all(q['count']==1 for q in reads+writes)   # the stock unlink moves one sector per request
    return dict(reads=len(reads),writes=len(writes),barriers=sum(q['op']==6 for q in r.requests),emulated_s=round(elapsed,2))

def card(kind,n,size,lanes,stride,contiguous=False):
    if kind=='FAT32':
        r=MountedTree(spc=64,clusters=600000);fat_sectors=fat32_files(r,n,size,lanes,stride)
    else:
        r=ExfatTree(spc=512,clusters=1952360);fat_sectors=exfat_files(r,n,size,lanes,stride,contiguous)
    assert r.geometry()[0]==0
    return r,fat_sectors

def main():
    cases=[]
    for label,seconds in DURATIONS:
        size=STEREO*seconds
        for kind,cluster_bytes in (('FAT32',32768),('exFAT',262144)):
            n=-(-size//cluster_bytes)
            for layout in ('contiguous','interleaved'):
                stride=1 if layout=='contiguous' else STREAMS
                lanes=(0,) if layout=='contiguous' else range(STREAMS)
                r,fat_sectors=card(kind,n,size,lanes,stride,contiguous=(kind=='exFAT' and layout=='contiguous'))
                free=r.geometry()[1][1];d=unlink(r,'TRACK01.WAV')
                assert r.geometry()[1][1]-free==n and 'TRACK01.WAV' not in r.files_in_pad()
                if layout=='interleaved':assert 'TRACK02.WAV' in r.files_in_pad()
                d.update(card=kind,cluster_bytes=cluster_bytes,layout=layout,take=label,bytes=size,clusters=n,fat_sectors_in_region=fat_sectors)
                cases.append(d);print(json.dumps(d),flush=True)
    # Five of the seven files of a 10-minute take, interleaved: each unlink costs the same.
    size=STEREO*600
    for kind,cluster_bytes in (('FAT32',32768),('exFAT',262144)):
        n=-(-size//cluster_bytes);r,_=card(kind,n,size,range(STREAMS),STREAMS)
        free=r.geometry()[1][1];per=[unlink(r,'TRACK%02d.WAV'%(lane+1)) for lane in range(5)]
        assert r.geometry()[1][1]-free==5*n and set(r.files_in_pad())=={'TRACK06.WAV','TRACK07.WAV'}
        assert len({(p['reads']//10,p['writes']) for p in per})<=2
        d=dict(card=kind,cluster_bytes=cluster_bytes,layout='interleaved, five files',take='10 min',clusters=n,
               reads=sum(p['reads'] for p in per),writes=sum(p['writes'] for p in per),barriers=sum(p['barriers'] for p in per))
        cases.append(d);print(json.dumps(d),flush=True)
    report=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        limitations=['Sector counts from the original unlink over a modeled card; no SD timing, no card dump, no device access.',
            'The interleaved layout assumes the stock allocator hands clusters to the seven streams in turn; the real spread was not read from a card.',
            'FAT32 geometry is a 32 KiB-cluster volume; exFAT is the owner card\'s reported 256 KiB clusters on a virtual volume.'])
    (ROOT/'analysis/unlink_cost.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
