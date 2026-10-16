#!/usr/bin/env python3
"""Back up the L6's whole 4 MiB serial flash (bootloader included) through the
experiment 39 diagnostic firmware's read-only flash query; no control writes.

Reads every 256-byte block twice, re-reads any block whose passes differ, and
checks the result against what is known: the MAIN region must equal the
installed image's MAIN component and the PANEL and AUDIOGUIDE regions must
equal Zoom's stock file (custom images never change them). Writes the backup,
its SHA-256 and a manifest to the ignored Reference/flash-backup/ folder: it is
Zoom's code, never commit or publish it.

Keep the mixer idle and untouched while it runs (no settings changes, so no
settings saves): about 5-10 minutes per pass. Quit ZOOM L6 Editor first, and
start at least 30 s after power-on and 15 s after the last change (settings
are saved about 10 s after a change and once during start-up).

  l6_flash_backup.py --session --installed deployment/39_flash_diag/flash_diag/L6.BIN
"""
import argparse,hashlib,json,sys,tempfile,time
from pathlib import Path
from l6_health_probe import sample
ROOT=Path(__file__).resolve().parents[2]
FLASH=0x400000;CHUNK=256;BATCH=1024
REGIONS=dict(BOOT=(0x000000,0x065000),MAIN=(0x065000,0x2ea000),PANEL=(0x2ea000,0x2fa000),
             AUDIOGUIDE=(0x2fa000,0x3fa000),TAIL=(0x3fa000,0x400000))
PACKAGE=dict(MAIN=0x200,PANEL=0x285200,AUDIOGUIDE=0x295200)   # each region's start in an L6.BIN package
STOCK=ROOT/'Reference/L6_v1.10_E/L6.BIN'

def request(offset,length,token):
    v=[(offset>>(7*i))&127 for i in range(4)]+[length&127,length>>7]
    return bytes((0xf0,0x52,0,0,0x6f,8,token,*v,0xf7))
def decode(packet):
    if len(packet)<15 or packet[:6]!=bytes((0xf0,0x52,0,0,0x6e,8)) or packet[-1]!=0xf7:return None
    offset=sum(packet[7+i]<<(7*i) for i in range(4));length=packet[11]|packet[12]<<7;status=packet[13]
    data=bytearray();body=packet[14:-1];i=0
    while status==0 and i<len(body):
        top=body[i];group=body[i+1:i+8];i+=1+len(group)
        data+=bytes(b|((top>>k)&1)<<7 for k,b in enumerate(group))
    if status==0 and len(data)!=length:raise ValueError('flash reply length mismatch')
    return dict(kind=8,token=packet[6],offset=offset,length=length,status=status,data=bytes(data))

def read_blocks(offsets,logdir,label):
    """One editor session per batch; returns {offset: bytes}."""
    out={}
    for b in range(0,len(offsets),BATCH):
        part=offsets[b:b+BATCH];tokens=iter(i%128 for i in range(len(part)));queue=iter(part)
        rows=sample(Path(logdir)/f'{label}-{b:06d}.jsonl',query_builder=lambda k,t:request(next(queue),CHUNK,t),
                    reply_decoder=decode,kinds=(8,)*len(part),reply_matcher=lambda d,k,t:d['token']==t,
                    token_builder=lambda k:next(tokens))
        for off,row in zip(part,rows):
            if row['offset']!=off or row['status']:raise SystemExit(f'block {off:#x}: status {row["status"]} (2 = refused: keep the mixer idle)')
            out[off]=row['data']
        print(f'{label}: {min(b+BATCH,len(offsets))}/{len(offsets)} blocks',file=sys.stderr)
    return out

def main():
    a=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--installed',type=Path,required=True,help='the L6.BIN installed on the mixer')
    a.add_argument('--session',action='store_true',help='open an editor session first (ZOOM L6 Editor closed)')
    a.add_argument('--out',type=Path,default=ROOT/'Reference/flash-backup')
    args=a.parse_args()
    if args.session:
        from l6_transfer_mode import session
        if not session([])['session']:raise SystemExit('No editor session: is the L6 connected and out of transfer mode?')
    installed,stock=args.installed.read_bytes(),STOCK.read_bytes()
    offsets=list(range(0,FLASH,CHUNK));start=time.time()
    with tempfile.TemporaryDirectory(prefix='l6-flash-') as logs:
        first=read_blocks(offsets,logs,'pass1');second=read_blocks(offsets,logs,'pass2')
        differ=[o for o in offsets if first[o]!=second[o]]
        for attempt in range(3):
            if not differ:break
            again=read_blocks(differ,logs,f'retry{attempt}')
            for o in differ:
                if again[o] in (first[o],second[o]):first[o]=second[o]=again[o]
            differ=[o for o in differ if first[o]!=second[o]]
    if differ:raise SystemExit(f'{len(differ)} blocks never read the same twice, first at {differ[0]:#x}')
    image=b''.join(first[o] for o in offsets)
    checks={}
    for name,base in PACKAGE.items():
        lo,hi=REGIONS[name];ref=(installed if name=='MAIN' else stock)[base:base+hi-lo]
        checks[name]=image[lo:hi]==ref
    args.out.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%d-%H%M%S');path=args.out/f'l6-flash-{stamp}.bin'
    path.write_bytes(image)
    report=dict(file=str(path),bytes=len(image),sha256=hashlib.sha256(image).hexdigest(),seconds=round(time.time()-start),
                regions={k:dict(start=hex(lo),end=hex(hi),sha256=hashlib.sha256(image[lo:hi]).hexdigest()) for k,(lo,hi) in REGIONS.items()},
                matches_known=checks,installed_sha256=hashlib.sha256(installed).hexdigest())
    (args.out/f'l6-flash-{stamp}.json').write_text(json.dumps(report,indent=1)+'\n')
    print(json.dumps(report,indent=1))
    if not all(checks.values()):raise SystemExit('backup does not match the known regions: do not rely on it')
if __name__=='__main__':main()
