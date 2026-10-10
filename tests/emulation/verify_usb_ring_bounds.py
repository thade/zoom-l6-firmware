#!/usr/bin/env python3
"""Original USB ring lengths, clearing and wrap spans for recovered formats.

No physical USB/DMA/cache or mixer access. Advertised formats are read from
stock profiles; pool pairs were independently recovered from the USB worker.
Valid cursors/counts are inputs, not a proof of every caller or host request.
"""
import hashlib
import json
import struct
from itertools import product

from verify_usb_memory_providers import (initialized, select, PROFILES, POOLS,
    POOL_TABLE, LIVE, Accesses, ROOT, IMAGE, STACK, word)

META = 0x20023000
OUTPUT = 0x20023100
STATES = (0x808e2f80, 0x808e2e54)
STATE_RANGES = ((0x808e2e54, 0x808e2eb1), (0x808e2f80, 0x808e2fdd))
POOL_RANGES = tuple((a, a+n) for a, n in POOLS)
WRITES = STATE_RANGES + POOL_RANGES + ((STACK-0x200, STACK), (OUTPUT, OUTPUT+16))
READS = WRITES + ((0x80001000, 0x800b6ae4), (0x801f5400, 0x801f8b80),
                 (0x80214794, 0x802147a0), (0x808e28ec, 0x808e2904),
                 (POOL_TABLE, POOL_TABLE+40), (META, META+16))


def put(m, address, value):
    m.uc.mem_write(address, struct.pack('<I', value))


def metadata_cases(m):
    cases = set()
    for block in (0x3c, 0x160, 0x284):
        count = word(m, LIVE+block)
        assert 0 < count <= 6
        rates = struct.unpack('<'+'I'*count, m.uc.mem_read(LIVE+block+4, 4*count))
        directions = []
        # Metadata bytes 8..11 select the second advertised direction;
        # bytes 12..15 select the first. Stock initial values corroborate this.
        for off in (0xa0, 0x1c):
            n = word(m, LIVE+block+off)
            assert 0 < n <= 8
            directions.append([struct.unpack('<4I', m.uc.mem_read(
                LIVE+block+off+4+16*i, 16)) for i in range(n)])
        for rate, a, b in product(rates, *directions):
            assert all(v < 256 for v in (*a, *b))
            # Some shared profiles advertise an absent direction as all zero.
            # This suite tests duplex active rings, not host activation of an
            # absent interface. Passing a zero format to 70298 yields stride 0.
            if a == (0, 0, 0, 0) or b == (0, 0, 0, 0):
                continue
            assert a[1] and a[3] and b[1] and b[3], (rate, a, b)
            cases.add((rate, a, b))
    return sorted(cases)


def geometry(m, index):
    state = STATES[index]
    stride, base, capacity = (word(m, state+off) for off in (0x10, 0x14, 0x18))
    active = word(m, state+0x30)
    declared_base, declared_bytes = POOLS[3+index]
    assert base == declared_base
    assert 0 < stride <= 48 and capacity == declared_bytes//stride, (index, stride, capacity, active)
    assert 0 < active <= capacity and active % 8 == 0, (index, stride, capacity, active)
    return dict(base=base, bytes_per_frame=stride, capacity_frames=capacity,
                active_frames=active, active_bytes=active*stride,
                declared_bytes=declared_bytes)


def wrap_cases(m, index, g):
    state = STATES[index]
    base, stride, active = g['base'], g['bytes_per_frame'], g['active_frames']
    # Critical-section wrappers and feedback-update observation are fixtures.
    # Buffer pointer arithmetic and consume/clear instructions execute unchanged.
    for fn in (0x800525d0, 0x80053b88):
        m.hooks[fn] = lambda args: 0
    m.hooks[0x800707f8] = lambda args: 1
    claim = (0x8006ffb0, 0x8006ff28)[index]
    consume = (0x800701f8, 0x80070190)[index]
    checked = 0
    for cursor, count in product((0, active//2, active-1), (0, 1, min(64, active), active)):
        put(m, state+8, 0)
        put(m, state+0x24, cursor)
        m.uc.mem_write(state+0x3c, b'\x01')
        m.uc.mem_write(state+0x48, b'\x01\x01')  # active; disable adaptive feedback for this case
        for flag in (0x808e2eb0, 0x808e2fdc):
            m.uc.mem_write(flag, b'\x01')
        m.uc.mem_write(base, b'\xa5'*g['declared_bytes'])
        m.invoke(claim, [OUTPUT, count])
        first, n1, second, n2 = struct.unpack('<4I', m.uc.mem_read(OUTPUT, 16))
        assert first == base+cursor*stride
        assert n1 == min(count, active-cursor) and n2 == count-n1
        assert second == (base if n2 else 0)
        for pointer, frames in ((first, n1), (second, n2)):
            if frames:
                assert base <= pointer < pointer+frames*stride <= base+active*stride
        m.invoke(consume, [])
        assert word(m, state+0x24) == (cursor+count) % active
        if index == 0:
            expected = bytearray(b'\xa5'*g['declared_bytes'])
            expected[cursor*stride:(cursor+n1)*stride] = bytes(n1*stride)
            expected[:n2*stride] = bytes(n2*stride)
            assert bytes(m.uc.mem_read(base, len(expected))) == expected
        else:
            assert bytes(m.uc.mem_read(base, g['declared_bytes'])) == b'\xa5'*g['declared_bytes']
        checked += 1
    # Busy or disabled states supply no pointer. A null pointer, not the returned
    # count alone, is the stock caller's guard; do not invent a stronger ABI.
    for locked in (False, True):
        put(m, state+8, int(locked))
        m.uc.mem_write(state+0x3c, bytes([int(locked)]))
        m.invoke(claim, [OUTPUT, 64])
        assert word(m, OUTPUT) == word(m, OUTPUT+8) == 0
        checked += 1
    m.hooks.clear()
    return checked


def main():
    rows = []
    for profile in PROFILES:
        for flag in (0, 1):
            m = initialized()
            select(m, profile, flag)
            # Exact pairs separately verified through original worker -> 67980.
            m.uc.mem_write(POOL_TABLE, b''.join(struct.pack('<II', *p) for p in POOLS))
            trace = Accesses(m, WRITES, READS)
            variants = []
            for rate, a, b in metadata_cases(m):
                m.uc.mem_write(META, struct.pack('<II8B', 0, rate, *a, *b))
                assert m.invoke(0x80070068, [META, 1]) == 1
                for timing_table in range(4):
                    pair = []
                    for index, state in enumerate(STATES):
                        pool_base, pool_bytes = POOLS[3+index]
                        m.uc.mem_write(pool_base, b'\xa5'*pool_bytes)
                        m.invoke(0x80070298, [state, META, 1, timing_table])
                        g = geometry(m, index)
                        assert bytes(m.uc.mem_read(pool_base, pool_bytes)) == (
                            bytes(g['active_bytes']) + b'\xa5'*(pool_bytes-g['active_bytes']))
                        pair.append(g)
                    variants.append(dict(rate=rate, first_format=a, second_format=b,
                                         timing_table=timing_table, rings=pair))
            # Use the final actual geometry; exercise both wrapping directions.
            wraps = sum(wrap_cases(m, index, geometry(m, index)) for index in range(2))
            rows.append(dict(profile=profile, selector_flag=flag, passed=True,
                             format_timing_cases=len(variants), variants=variants,
                             wrap_and_inactive_cases=wraps, **trace.finish()))
    out = ROOT/'analysis/usb_ring_bounds_verification.json'
    report = dict(passed_groups=len(rows), results=rows, stock_sha256=hashlib.sha256(IMAGE).hexdigest(),
                  format_timing_cases=sum(r['format_timing_cases'] for r in rows),
                  wrap_and_inactive_cases=sum(r['wrap_and_inactive_cases'] for r in rows),
                  physical_ownership_proven=False, device_access=False, limitations=[
                      'Nonzero duplex formats/rates and four timing-table selectors; absent directions and host negotiation not run',
                      'Pool pairs are fixtures pinned by separate original worker/provider audit',
                      'Valid cursors and request counts no larger than active ring; caller enforcement unresolved',
                      'Critical sections and feedback are fixtures during wrap checks; no concurrency or DMA',
                      'USB endpoint transfers, bootloader users and physical aliases remain outside this scope',
                      'No mixer commands, firmware or capture-layout changes'])
    out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('passed_groups', 'format_timing_cases', 'wrap_and_inactive_cases')}))


if __name__ == '__main__':
    main()
