#!/usr/bin/env python3
"""Build a minimal L6 v1.10 USB-name trial and an untouched stock control.

Writes only inside the repository deployment directory, never to a device/card.
Package acceptance and recovery are unknown until separately tested on hardware.
"""
import hashlib,json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'Reference/L6_v1.10_E/L6.BIN'
OUT=ROOT/'deployment/01_usb_marker'
STOCK_SHA='64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
MARKER_OFFSET=0xa1d55
CHECKSUM_OFFSET=0x1fc

def digest(b):return hashlib.sha256(b).hexdigest()
def validate(b):
    assert len(b)==0x395200
    assert struct.unpack_from('<II',b,0x6c)==(0,0), 'BOOT descriptor changed'
    assert struct.unpack_from('<II',b,0x78)==(0x100,0x395100)
    assert struct.unpack_from('>I',b,CHECKSUM_OFFSET)[0]==sum(b[0x200:])&0xffffffff
    assert b[0x2851fc:0x285200]==b'0110' and b[0x2951fc:0x295200]==b'0100'

def build():
    stock=SOURCE.read_bytes();assert digest(stock)==STOCK_SHA
    validate(stock);assert stock[MARKER_OFFSET-5:MARKER_OFFSET+3]==b'ZOOM L6\0'
    candidate=bytearray(stock);candidate[MARKER_OFFSET]=ord('T')
    struct.pack_into('>I',candidate,CHECKSUM_OFFSET,sum(candidate[0x200:])&0xffffffff)
    candidate=bytes(candidate);validate(candidate)
    diffs=[i for i,(x,y) in enumerate(zip(stock,candidate)) if x!=y]
    assert diffs==[0x1ff,MARKER_OFFSET]
    assert candidate[:0x1fc]==stock[:0x1fc]
    assert candidate[0x285200:]==stock[0x285200:]
    products=[]
    for label,data in [('stock_control',stock),('trial_usb_name_T6',candidate)]:
        p=OUT/label/'L6.BIN';p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists():assert p.read_bytes()==data,'Refusing to replace a different image'
        else:p.write_bytes(data)
        assert p.read_bytes()==data
        products.append(dict(role=label,path=str(p),bytes=len(data),sha256=digest(data)))
    report=dict(purpose='Minimal main-image data modification; USB name L6 -> T6',
        source_sha256=STOCK_SHA,images=products,
        changed_bytes=[dict(file_offset=hex(i),old=hex(stock[i]),new=hex(candidate[i])) for i in diffs],
        checksum_before=hex(struct.unpack_from('>I',stock,CHECKSUM_OFFSET)[0]),
        checksum_after=hex(struct.unpack_from('>I',candidate,CHECKSUM_OFFSET)[0]),
        unchanged=['Package/component lengths','BOOT descriptor (empty)','Application version 0110',
                   'Panel and voice-guide regions','All bytes except one name character and checksum byte'],
        deployment_status='Prepared locally only; not copied to card or installed',
        limitations=['Reproduced additive checksum is not proof of updater acceptance',
                     'Stock reinstall, modified-image boot and restoration must be observed separately',
                     'Name change may affect software which matches product strings exactly',
                     'No tested recovery after modified firmware; no bootloader dump'])
    (OUT/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':build()
