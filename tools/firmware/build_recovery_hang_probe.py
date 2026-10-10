#!/usr/bin/env python3
"""Prepare an early-hang recovery check locally. No device access.

The MAIN reset handler's first instruction becomes a branch to itself, so the
application never initializes. Installing it tests whether the PLAY/STOP SD
updater still runs when MAIN hangs before any stock startup code. If the
updater lives in MAIN rather than BOOT, this image leaves the mixer unbootable
without a hardware recovery route.
"""
import json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
from unicorn.arm_const import UC_ARM_REG_PC
from build_deployment_probe import ROOT,SOURCE,STOCK_SHA,CHECKSUM_OFFSET,validate,digest,write_manifest

OUT=ROOT/'deployment/18_recovery_hang'
BIAS=0x80000e00
VECTORS=0x200
HANG=bytes.fromhex('fee7')  # b . (Thumb T2 encoding, 0xe7fe)

def candidate(stock):
    sp,reset=struct.unpack_from('<II',stock,VECTORS)
    assert reset&1 and (reset&~1)>=BIAS,'Reset vector is not a Thumb MAIN address'
    at=(reset&~1)-BIAS
    first=next(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(stock[at:at+4],reset&~1))
    data=bytearray(stock);data[at:at+2]=HANG
    struct.pack_into('>I',data,CHECKSUM_OFFSET,sum(data[0x200:])&0xffffffff)
    return bytes(data),dict(stack=sp,reset=reset,file_offset=at,
                            original=f'{first.mnemonic} {first.op_str}',original_bytes=first.bytes.hex())

def spins(data,reset):
    """Execute the patched entry: PC must stay on the branch after many steps."""
    base=BIAS&~0xfff;size=(len(data)+0x1fff)&~0xfff
    mu=Uc(UC_ARCH_ARM,UC_MODE_THUMB);mu.mem_map(base,size)
    mu.mem_write(BIAS+0x200,data[0x200:])
    mu.emu_start(reset,0,count=1000)
    return mu.reg_read(UC_ARM_REG_PC)==(reset&~1)

def build():
    stock=SOURCE.read_bytes();assert digest(stock)==STOCK_SHA;validate(stock)
    data,entry=candidate(stock);validate(data)
    diffs=[i for i,(x,y) in enumerate(zip(stock,data)) if x!=y]
    assert all(i in range(CHECKSUM_OFFSET,CHECKSUM_OFFSET+4) or
               i in range(entry['file_offset'],entry['file_offset']+2) for i in diffs)
    assert spins(data,entry['reset']),'Patched reset handler does not spin'
    path=OUT/'trial_recovery_hang/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to replace a different image'
    else:path.write_bytes(data)
    report=dict(experiment=18,status='prepared_locally_not_staged',
        purpose='Confirm the PLAY/STOP updater recovers a MAIN that hangs at reset',
        source_sha256=STOCK_SHA,trial_sha256=digest(data),path=str(path),
        reset_vector=hex(entry['reset']),patched_file_offset=hex(entry['file_offset']),
        original_instruction=entry['original'],original_bytes=entry['original_bytes'],
        replacement='b . (fee7)',
        changed_bytes=[dict(file_offset=hex(i),old=hex(stock[i]),new=hex(data[i])) for i in diffs],
        unchanged=['BOOT descriptor (empty); the update never writes BOOT',
                   'Package/component lengths, PANEL and AUDIOGUIDE regions',
                   'Every MAIN byte except the first reset instruction and the checksum'],
        limitations=['Emulation only shows the patched entry spins; bootloader behavior is unobserved.',
                     'If the SD updater is not in BOOT, installing this image requires hardware recovery.',
                     'Updater acceptance relies on the reproduced additive checksum, as in all prior trials.'])
    write_manifest(OUT/'manifest.json',report)
    print(json.dumps({k:report[k] for k in ('trial_sha256','reset_vector','original_instruction')}))
if __name__=='__main__':build()
