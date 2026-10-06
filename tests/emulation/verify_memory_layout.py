#!/usr/bin/env python3
"""Audit stock startup metadata, allocator bounds and MPU register writes.

Read-only with respect to the mixer and firmware file. Scheduler calls and MMIO
are fixtures. This is not a full boot, a physical RAM test or a free-space proof.
"""
import hashlib
import json
import struct

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from verify_pad_protocol import BIAS, IMAGE, Machine, ROOT, STACK

HEAP_STATE = 0x801f901c
HEAP_RAW = 0x808e2fdd
HEAP_SIZE = 0x7d000
HEAP_START = (HEAP_RAW + 7) & ~7
HEAP_END = (HEAP_RAW + HEAP_SIZE) & ~7
SENTINEL = HEAP_END - 8
INITIAL_FREE = SENTINEL - HEAP_START
GAP = (0x80960078, 0x80bb9400)


def word(m, address):
    return struct.unpack('<I', m.uc.mem_read(address, 4))[0]


def startup():
    methods = {0x80001994: 'decompress', 0x80079498: 'copy', 0x800794a8: 'zero'}
    rows = []
    for address in range(0x800a68dc, 0x800a695c, 16):
        source, destination, length, helper = struct.unpack_from('<4I', IMAGE, address-BIAS)
        method = methods[helper & ~1]
        rows.append(dict(table_entry=hex(address), source=hex(source),
                         start=hex(destination), end=hex(destination+length),
                         bytes=length, method=method, helper=hex(helper & ~1)))
        assert destination+length <= GAP[0] or destination >= GAP[1]
    assert any(r['start'] == '0x801f8b80' and r['end'] == hex(GAP[0]) for r in rows)
    assert any(r['start'] == hex(GAP[1]) for r in rows)
    assert any(int(r['start'], 16) <= HEAP_RAW and
               HEAP_RAW+HEAP_SIZE <= int(r['end'], 16) and r['method'] == 'zero'
               for r in rows)
    length = struct.unpack_from('<I', IMAGE, 0x2851f8)[0]
    assert length == 0xb5ae4
    return dict(entries=rows, main_length_field=length,
                main_effective_end=hex(0x80001000+length),
                unassigned_by_scatter_table=dict(start=hex(GAP[0]), end=hex(GAP[1]),
                                                bytes=GAP[1]-GAP[0]),
                caveat='Metadata coverage only; absence is not proof of unused memory or loader behavior')


def allocator():
    m = Machine()
    # Stock scatter initialization zeroes this state. Other startup is not run.
    m.hooks[0x80074780] = lambda args: 0
    m.hooks[0x80077540] = lambda args: 0
    write_count = 0
    ranges = [(HEAP_START, HEAP_END), (HEAP_STATE, HEAP_STATE+0x1c),
              (STACK-0x100, STACK)]

    def check_write(uc, access, address, size, value, data):
        nonlocal write_count
        assert any(start <= address and address+size <= end for start, end in ranges), hex(address)
        write_count += 1
    m.uc.hook_add(UC_HOOK_MEM_WRITE, check_write)

    assert m.invoke(0x8006de78, [0]) == 0
    assert word(m, HEAP_STATE) == SENTINEL
    assert word(m, HEAP_STATE+4) == INITIAL_FREE
    assert word(m, HEAP_STATE+0x14) == HEAP_START
    assert word(m, HEAP_START) == SENTINEL
    assert word(m, HEAP_START+4) == INITIAL_FREE
    assert bytes(m.uc.mem_read(SENTINEL, 8)) == bytes(8)
    live = {}
    allocations = []

    def allocate(size):
        pointer = m.invoke(0x8006de78, [size])
        if pointer:
            assert pointer % 8 == 0
            block_size = word(m, pointer-4) & 0x7fffffff
            assert HEAP_START <= pointer-8 < pointer+size <= pointer-8+block_size <= SENTINEL
            assert all(pointer-8+block_size <= p-8 or p-8+n <= pointer-8 for p, n in live.items())
            live[pointer] = block_size
        allocations.append(dict(requested=size, returned=hex(pointer)))
        return pointer

    def release(pointer):
        m.invoke(0x80073f48, [pointer])
        if pointer:
            del live[pointer]

    pointers = [allocate(n) for n in (1, 7, 8, 9, 4096, 65536)]
    assert all(pointers)
    for pointer in pointers[::2] + pointers[1::2]:
        release(pointer)
    release(0)
    assert not live and word(m, HEAP_STATE+4) == INITIAL_FREE
    assert word(m, HEAP_START+4) == INITIAL_FREE

    # Exhaustion cannot silently grow this heap into adjacent memory.
    assert allocate(INITIAL_FREE) == 0
    assert allocate(0xffffffff) == 0
    whole = allocate(INITIAL_FREE-16)
    assert whole and word(m, HEAP_STATE+4) == 0
    assert allocate(1) == 0
    release(whole)
    assert word(m, HEAP_STATE+4) == INITIAL_FREE
    assert word(m, HEAP_STATE+0x14) == HEAP_START
    assert word(m, HEAP_START) == SENTINEL
    assert word(m, HEAP_START+4) == INITIAL_FREE
    return dict(raw_start=hex(HEAP_RAW), configured_bytes=HEAP_SIZE,
                aligned_start=hex(HEAP_START), sentinel=hex(SENTINEL), end=hex(HEAP_END),
                initial_free_bytes=INITIAL_FREE, allocations=allocations,
                writes_checked=write_count, final_free_bytes=word(m, HEAP_STATE+4),
                modeled_calls=['0x80074780', '0x80077540'],
                caveat='One allocator in isolated zero-initialized state; no live RTOS heap headroom measurement')


def mpu(initial_ccr):
    m = Machine()
    m.uc.mem_map(0xe000e000, 0x2000)
    # RAM-backed register fixtures, not emulated MPU/cache behavior.
    m.uc.mem_write(0xe000ed14, struct.pack('<I', initial_ccr))
    pairs = []
    rbar = None

    def capture(uc, access, address, size, value, data):
        nonlocal rbar
        if address == 0xe000ed9c:
            rbar = value
        elif address == 0xe000eda0:
            assert rbar is not None and size == 4
            pairs.append((rbar, value))
            rbar = None
    m.uc.hook_add(UC_HOOK_MEM_WRITE, capture)

    def stop(uc, address, size, data):
        m.reached_return = True
        uc.emu_stop()
    m.uc.hook_add(UC_HOOK_CODE, stop, begin=0x8001b51a, end=0x8001b51a)
    m.invoke(0x8001b320, [])
    assert word(m, 0xe000ed94) == 5
    assert len(pairs) == 13
    assert [base & 15 for base, attr in pairs] == list(range(13))
    # Bit positions: Arm CMSIS Core/Include/core_cm7.h, MPU_RBAR/RASR definitions.
    rows = []
    for base, attr in pairs:
        assert base & 16
        size = 1 << (((attr >> 1) & 31)+1)
        start = (base & ~31) & ~(size-1)
        rows.append(dict(region=base & 15, rbar=hex(base), rasr=hex(attr),
                         start=hex(start), end=hex(start+size), bytes=size,
                         enabled=bool(attr & 1), execute_never=bool(attr & (1 << 28)),
                         access_permission=(attr >> 24) & 7, tex=(attr >> 19) & 7,
                         shareable=bool(attr & (1 << 18)), cacheable=bool(attr & (1 << 17)),
                         bufferable=bool(attr & (1 << 16)), subregions_disabled=(attr >> 8) & 255))
    external = rows[10]
    assert external['start'] == '0x80000000' and external['end'] == '0x82000000'
    assert external['enabled'] and not external['execute_never']
    assert external['access_permission'] == 3 and external['subregions_disabled'] == 0
    return rows


def main():
    layout = startup()
    heap = allocator()
    regions = mpu(0)
    assert mpu(0x30000) == regions
    report = dict(passed=True, stock_sha256=hashlib.sha256(IMAGE).hexdigest(),
                  startup=layout, allocator=heap, mpu_regions=regions,
                  mpu_fixtures='CCR cache flags clear/set; CCSIDR=0; stop before cache re-enable',
                  limits=['Not a full boot, MPU/cache model, DMA or physical RAM test',
                          'No assertion that candidate gap is unused by all firmware or bootloader paths',
                          'No proof that bytes beyond the main length field are loaded',
                          'No firmware generated or staged'])
    (ROOT/'analysis/memory_layout_verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, heap_free_bytes=INITIAL_FREE,
                          candidate_gap_bytes=GAP[1]-GAP[0], mpu_regions=len(regions))))


if __name__ == '__main__':
    main()
