#!/usr/bin/env python3
"""Print a bounded Thumb disassembly or direct-call references for stock L6 v1.10.

Use the same Capstone environment as inspect_firmware.py. Mixed code/data is not
automatically distinguished; branch tables must be interpreted separately.
"""
import argparse
import hashlib
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS

ROOT = Path(__file__).resolve().parents[1]
BIAS = 0x80000e00
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('start', type=lambda x: int(x, 0))
p.add_argument('end', nargs='?', type=lambda x: int(x, 0))
p.add_argument('--calls', action='store_true')
a = p.parse_args()
b = (ROOT/'Reference/L6_v1.10_E/L6.BIN').read_bytes()
assert hashlib.sha256(b).hexdigest() == '64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
md.skipdata = True
# Startup table explicitly copies this executable block into RAM. Disassemble
# at its destination so PC-relative branches retain their runtime meaning.
source, destination, length, helper = struct.unpack_from('<4I', b, 0x800a691c-BIAS)
assert (source,destination,length,helper)==(0x800a9408,0x20220000,0xd6dc,0x80079498)
ram=b[source-BIAS:source-BIAS+length]
if a.calls:
    for data,base in ((b[0x600:0xa0000],BIAS+0x600),(ram,destination)):
        for addr, size, mnemonic, operands in md.disasm_lite(data,base):
            if mnemonic in ('bl', 'b', 'b.w') and operands == f'#{a.start:#x}':
                print(f'{addr:08x} {mnemonic:10} {operands}')
else:
    end = a.end if a.end is not None else a.start+0x100
    assert end-a.start <= 0x2000, 'Choose a bounded range (at most 8 KiB).'
    if destination <= a.start < end <= destination+length:
        data=ram[a.start-destination:end-destination]
    else:
        assert BIAS+0x200 <= a.start < end <= BIAS+0xb5ce4
        data=b[a.start-BIAS:end-BIAS]
    for addr, size, mnemonic, operands in md.disasm_lite(data, a.start):
        print(f'{addr:08x} {mnemonic:10} {operands}')
