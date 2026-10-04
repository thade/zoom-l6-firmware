#!/usr/bin/env python3
"""Execute original USB construction with stock/probe images in synthetic RAM.

No hardware/RTOS/USB controller is emulated. Stop before low-level USB setup;
then run the original string construction separately to its serial-name boundary.
"""
import json
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from unicorn import UC_HOOK_CODE
from verify_pad_protocol import Machine
from build_deployment_probe import validate, digest, SOURCE
from build_code_probe import OUT, BIAS, PATCH_ADDRESS, PATCH_OFFSET, OLD, NEW

PROFILES = [0x801f6484, 0x801f6860, 0x801f6c3c, 0x801f7018, 0x801f7bac, 0x801f7f88]
PARAM = 0x20021000
CONFIG = 0x20022000


def word(m, a):
    return struct.unpack('<I', m.uc.mem_read(a, 4))[0]


def string(m, a):
    return bytes(m.uc.mem_read(a, 64)).split(b'\0')[0].decode('ascii')


def stop(m):
    m.reached_return = True
    m.uc.emu_stop()


def run(image, profile, power):
    m = Machine()
    m.uc.mem_write(0x80001000, image[0x200:0xb5ce4])
    m.invoke(0x80001994, [0x800a6980, 0x801f5400, 0x3780])
    assert string(m, word(m, profile+12)) == 'L6'
    assert string(m, word(m, profile+28)) == 'ZOOM L6'
    # Original profile lookup, backed by a selected recovered stock profile.
    m.uc.mem_write(0x808e2900, struct.pack('<I', profile))
    m.uc.mem_write(PARAM, struct.pack('<IB', 0x20100, power) + bytes(0xac-5))
    # Profile classification is an input fixture, not a simulated device mode change.
    m.hooks[0x80072720] = lambda a: 1
    captured = []
    def capture(a):
        captured.append(bytes(m.uc.mem_read(a[0], 0x400)))
        stop(m)
    m.hooks[0x800451d8] = capture
    hits = []
    m.uc.hook_add(UC_HOOK_CODE, lambda uc,a,n,u: hits.append(a),
                  begin=PATCH_ADDRESS, end=PATCH_ADDRESS)
    m.invoke(0x80073748, [PARAM])
    assert len(captured) == 1 and hits == [PATCH_ADDRESS]
    config = captured[0]
    vid, pid, revision = struct.unpack_from('<HHH', config, 4)
    assert vid == 0x1686 and revision == 1
    product_pointer, vendor_pointer = struct.unpack_from('<II', config, 0x18)
    assert string(m, vendor_pointer) == 'ZOOM Corporation'
    product = string(m, product_pointer)
    # Use the original core constructor, including string allocation/copy/lengths.
    m.uc.mem_write(CONFIG, config)
    m.uc.hook_add(UC_HOOK_CODE, lambda uc,a,n,u: stop(m),
                  begin=0x800437d0, end=0x800437d0)
    m.invoke(0x80043510, [CONFIG])
    indexes = bytes(m.uc.mem_read(0x80213d49, 2))
    strings = []
    for index in indexes:
        assert index > 0
        entry = 0x802138a4 + (index-1)*8
        length, dtype = bytes(m.uc.mem_read(entry, 2))
        name = string(m, word(m, entry+4))
        assert dtype == 3 and length == 2+2*len(name)
        strings.append(name)
    assert strings == ['ZOOM Corporation', product]
    return config, dict(profile=hex(profile), power_fixture=power, vid=hex(vid),
                        pid=hex(pid), revision=revision, product=product,
                        manufacturer=strings[0], instruction_executions=len(hits))


def main():
    stock = SOURCE.read_bytes()
    trial = (OUT/'trial_code_name_ZOOM_L6/L6.BIN').read_bytes()
    for image in (stock, trial): validate(image)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    disassembly = []
    for data, expected in [(OLD, 'r0, [r5, #0xc]'), (NEW, 'r0, [r5, #0x1c]')]:
        instructions = list(md.disasm(data, PATCH_ADDRESS))
        assert len(instructions) == 1 and instructions[0].size == 2
        i = instructions[0]
        assert i.mnemonic == 'ldr' and i.op_str == expected
        disassembly.append(i.mnemonic+' '+i.op_str)
    assert stock[PATCH_OFFSET:PATCH_OFFSET+2] == OLD
    assert trial[PATCH_OFFSET:PATCH_OFFSET+2] == NEW
    rows = []
    for profile in PROFILES:
        for power in (0, 1):
            original, a = run(stock, profile, power)
            changed, b = run(trial, profile, power)
            assert a['product'] == 'L6' and b['product'] == 'ZOOM L6'
            # Only the product pointer differs in the entire 1024-byte configuration.
            assert original[:0x18] == changed[:0x18] and original[0x1c:] == changed[0x1c:]
            assert a['pid'] == b['pid']
            rows.append(dict(stock=a, trial=b, other_configuration_bytes_identical=True))
    report = dict(passed=True, paired_cases=len(rows), original_code_runs=2*len(rows),
                  stock_sha256=digest(stock), trial_sha256=digest(trial),
                  disassembly=disassembly, results=rows,
                  scope='Original decompression, USB configuration construction and manufacturer/product string construction',
                  limitations=['Synthetic selected profile and power flag; no full boot or RTOS simulation',
                               'Stopped before controller setup and before serial-name construction',
                               'No USB wire transaction, updater or hardware execution tested'])
    (OUT/'offline_verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, paired_cases=len(rows), original_code_runs=2*len(rows))))


if __name__ == '__main__':
    main()
