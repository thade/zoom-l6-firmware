#!/usr/bin/env python3
"""Offline stock target-to-recording-mask selection. No device access."""
import hashlib,json
from verify_overdub_prototype import Emulator
from verify_pad_protocol import IMAGE,ROOT

def main():
    results=[]
    for setting in (0,1):
        for target in (-1,0,1,2,3):
            m=Emulator();m.hooks[0x80006190]=lambda a,setting=setting:setting
            mask=m.invoke(0x80008990,[target&0xffffffff])
            expected=0xfff if target==-1 and setting==0 else 0xc00
            assert mask==expected
            selected=[]
            # File metadata update is outside this bounded selector test.
            m.hooks[0x80004738]=lambda a:0
            m.hooks[0x8000178e]=lambda a:m.uc.mem_write(a[0],bytes(a[2])) or a[0]
            m.hooks[0x80004288]=lambda a:selected.append(a[0]) or 1
            m.invoke(0x8000b540,[mask])
            assert selected==([*range(12)] if mask==0xfff else [10,11])
            assert list(m.uc.mem_read(0x801f8c68,12))==[int(i in selected) for i in range(12)]
            results.append(dict(setting=setting,target=target,mask=hex(mask),selected=selected,passed=True))
    report=dict(passed_cases=len(results),results=results,
                firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
                limitation='Original selection/control flow only; no recording IO, audio routing or modified mask test')
    out=ROOT/'analysis/pad_record_mode_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_cases=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
