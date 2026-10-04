#!/usr/bin/env python3
"""Offline startup-table check of the prepared USB-name image. No device access."""
import json,struct
from verify_pad_protocol import Machine
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/firmware'))
from build_deployment_probe import OUT,validate,digest,MARKER_OFFSET

def cstring(m,address):
    return bytes(m.uc.mem_read(address,40)).split(b'\0',1)[0].decode('ascii')

rows=[]
for role,want in [('stock_control','L6'),('trial_usb_name_T6','T6')]:
    b=(OUT/role/'L6.BIN').read_bytes();validate(b)
    m=Machine()
    m.uc.mem_write(0x80001000,b[0x200:0xb5ce4])
    m.invoke(0x80001994,[0x800a6980,0x801f5400,0x3780])
    config=[]
    for address in [0x801f6490,0x801f686c,0x801f6c48,0x801f7024,0x801f7bb8,0x801f7f94]:
        vid,pid=struct.unpack('<HH',m.uc.mem_read(address-12,4))
        vendor,product=struct.unpack('<II',m.uc.mem_read(address-4,8))
        assert vid==0x1686 and product==MARKER_OFFSET+0x80000e00
        assert cstring(m,vendor)=='ZOOM Corporation' and cstring(m,product)==want
        config.append(dict(vid=hex(vid),pid=hex(pid),name=cstring(m,product),table_product_pointer=hex(address)))
    assert any(x['pid']=='0x89e' for x in config)
    rows.append(dict(role=role,sha256=digest(b),recovered_usb_configurations=config))
report=dict(passed=True,images=rows,scope='Original startup decompressor and initialized USB configuration pointers; no updater emulation or device access')
(OUT/'offline_verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(passed=True,images=2,usb_configurations_per_image=6)))
