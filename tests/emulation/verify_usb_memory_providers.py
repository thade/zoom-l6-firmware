#!/usr/bin/env python3
"""Trace stock USB profile selection through descriptor construction offline.

Original decompression, selection, classification, providers, copies and the
complete descriptor builder execute. Stop BEFORE callback/controller setup.
Only startup globals and power/serial inputs are fixtures; this is not USB
enumeration, a full boot, DMA emulation or proof of physically free memory.
"""
import hashlib
import json
import struct
import sys

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2
from verify_pad_protocol import Machine, ROOT, IMAGE, STACK
from verify_memory_layout import word, mpu

sys.path.insert(0, str(ROOT/'tools/firmware'))
from audit_ram_gap_consumers import GAPS, overlaps

PROFILES = tuple(0x801f60a8 + 0x3dc*i for i in range(11))
PIDS = (0x860, 0x88f, 0x89f, 0x88e, 0x89e, 0x866,
        0x868, 0x88d, 0x89d, 0x865, 0x867)
SELECTOR = 0x80053178
LIVE = 0x802147a0
PROFILE_BYTES = 0x3cc
POINTER = 0x808e2900
MODE = 0x80214794
CONFIG = 0x802123c8
STOP = 0x80044fb0
SERIAL = 0x20021000
POOL_TABLE = 0x808e0d1c
POOLS = ((0x20003200, 0x600), (0x20003800, 12), (0x2000a420, 0x600),
         (0x20000200, 0x3000), (0x20003820, 0x6c00))

# These are bounds for observed stock writes, not proposed new allocations.
# All addresses are checked, including reads; MMIO/unknown destinations fail.
SELECT_WRITES = ((STACK-0x150, STACK), (MODE, MODE+4),
                 (0x8021479c, 0x8021479d), (LIVE, LIVE+PROFILE_BYTES),
                 (0x808e28ec, POINTER+4))
BUILD_WRITES = ((STACK-0x580, STACK), (0x801f54fc, 0x801f567e),
                (CONFIG, CONFIG+0x400), (0x8021299c, 0x80212c6a),
                (0x80213888, 0x8021388f), (0x802138a0, 0x802138a1),
                (0x802138a4, 0x8021398c), (0x8021398c, 0x80213d49),
                (0x80213d49, 0x80213d5a), (0x8021427c, 0x802142a8),
                (0x80235054, 0x80235114), (0x808e0d18, 0x808e0d1c),
                (0x808e0d58, 0x808e0e04), (0x808e2c94, 0x808e2d04),
                (0x808e2d7c, 0x808e2ddc), (0x808e2eb8, 0x808e2f64),
                (0x8095ffe0, 0x80960028))


def spans(addresses):
    result = []
    for a in sorted(addresses):
        if result and result[-1][1] == a:
            result[-1][1] = a+1
        else:
            result.append([a, a+1])
    return result


class Accesses:
    def __init__(self, m, writes, reads):
        self.m = m
        self.allowed_writes, self.allowed_reads = writes, reads
        self.writes, self.reads = set(), set()
        self.hook = m.uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self.capture)

    def capture(self, uc, access, address, size, value, data):
        assert not overlaps(address, size, GAPS), (hex(address), hex(uc.reg_read(UC_ARM_REG_PC)))
        writing = access == UC_MEM_WRITE
        allowed = self.allowed_writes if writing else self.allowed_reads
        assert any(a <= address and address+size <= b for a, b in allowed), (
            'write' if writing else 'read', hex(address), size, hex(uc.reg_read(UC_ARM_REG_PC)))
        (self.writes if writing else self.reads).update(range(address, address+size))

    def finish(self):
        self.m.uc.hook_del(self.hook)
        return dict(read_spans=spans(self.reads), write_spans=spans(self.writes))


def initialized():
    m = Machine()
    m.uc.mem_map(0x81000000, 0x1000000)
    # Actual stock initialized profile/template data, via original decompressor.
    # Remaining zero-filled synthetic globals are not a simulated full startup.
    m.invoke(0x80001994, [0x800a6980, 0x801f5400, 0x3780])
    assert tuple(struct.unpack('<H', m.uc.mem_read(p+2, 2))[0] for p in PROFILES) == PIDS
    return m


def select(m, profile, flag):
    source = bytes(m.uc.mem_read(profile, PROFILE_BYTES))
    pid = struct.unpack_from('<H', source, 2)[0]
    copies = []

    def observe(uc, address, size, data):
        dst, src, count = (uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        if dst == LIVE:
            copies.append((src, count))
            assert bytes(uc.mem_read(src, count)) == source

    hook = m.uc.hook_add(UC_HOOK_CODE, observe, begin=0x80001754, end=0x80001754)
    trace = Accesses(m, SELECT_WRITES, SELECT_WRITES + ((0x801f5400, 0x801f8b80),))
    assert m.invoke(SELECTOR, [pid, flag]) == 1
    m.uc.hook_del(hook)
    assert copies == [(profile, PROFILE_BYTES)]
    assert word(m, POINTER) == LIVE and word(m, POINTER-4) == profile-16
    assert set(range(LIVE, LIVE+PROFILE_BYTES)) <= trace.writes
    # Execute the original getters instead of supplying their return values.
    for classification in (0, 1, 2, 3):
        assert m.invoke(0x80067050, [classification]) == (LIVE if classification == 1 else 0)
        assert m.invoke(0x80053b68, [classification]) == (profile-16 if classification == 1 else 0)
    assert m.invoke(0x80072720, []) == 1
    counts = [word(m, LIVE+n) for n in (0x58, 0xdc, 0x17c, 0x200, 0x2a0, 0x324)]
    assert max(counts) <= 8
    return dict(profile=profile, pid=pid, selector_flag=flag, mode=word(m, MODE),
                provider=word(m, POINTER), format_counts=counts, **trace.finish())


def construct(m, power, serial):
    # Original providers read these startup inputs from the native outer object.
    # A non-null serial exercises an indirect string source; no callback is run.
    m.uc.mem_write(0x802142c4, bytes([power]))
    m.uc.mem_write(0x802142c0, struct.pack('<I', SERIAL if serial else 0))
    m.uc.mem_write(SERIAL, b'RAM-AUDIT\0')
    stages = []
    snapshots = {}

    def observe(uc, address, size, data):
        lengths = {0x800704d8: 0xac, 0x80073748: 0xac,
                   0x800451d8: 0x400, 0x80043510: 0x400}
        if address in lengths:
            pointer = uc.reg_read(UC_ARM_REG_R0)
            snapshots[address] = (pointer, bytes(uc.mem_read(pointer, lengths[address])))
            stages.append(address)
        elif address == 0x80073934:
            assert uc.reg_read(UC_ARM_REG_R0) == 0  # descriptor builder returned success
            stages.append(address)
        elif address == STOP:
            stages.append(address)
            m.reached_return = True
            uc.emu_stop()

    hook = m.uc.hook_add(UC_HOOK_CODE, observe)
    reads = BUILD_WRITES + ((0x80001000, 0x800b6ae4), (0x801f5400, 0x801f8b80),
                           (LIVE, LIVE+PROFILE_BYTES), (MODE, MODE+4),
                           (0x802142c0, 0x802142d0), (0x808e0d44, 0x808e0d58),
                           (POINTER, POINTER+4), (SERIAL, SERIAL+10))
    trace = Accesses(m, BUILD_WRITES, reads)
    assert not m.hooks
    m.invoke(0x800727e8, [])
    m.uc.hook_del(hook)
    assert stages == [0x800704d8, 0x80073748, 0x800451d8, 0x80043510, 0x80073934, STOP]
    for entry, dest in ((0x800704d8, 0x808e2eb8), (0x80073748, 0x808e0d58),
                        (0x80043510, CONFIG)):
        ptr, content = snapshots[entry]
        assert STACK-0x580 <= ptr < ptr+len(content) <= STACK
        assert bytes(m.uc.mem_read(dest, len(content))) == content
        assert set(range(dest, dest+len(content))) <= trace.writes
    assert snapshots[0x800451d8] == snapshots[0x80043510]
    assert snapshots[0x80073748][0] == STACK-0xbc
    count = m.uc.mem_read(0x802138a0, 1)[0]
    assert 0 < count <= 29
    names = []
    for i in range(count):
        entry = 0x802138a4+8*i
        n, kind = bytes(m.uc.mem_read(entry, 2))
        pointer = word(m, entry+4)
        assert pointer == 0x8021398c+33*i and kind == 3
        raw = bytes(m.uc.mem_read(pointer, 33))
        assert 0 in raw
        name = raw.split(b'\0')[0]
        assert n == 2+2*len(name)
        names.append(name.decode('ascii'))
    assert ('RAM-AUDIT' in names) == serial
    return dict(power_fixture=power, serial_fixture=serial, stop_before=STOP,
                native_setup_object=snapshots[0x80073748][0],
                stack_descriptor=snapshots[0x80043510][0], string_count=count,
                lowest_stack_write=min(trace.writes), **trace.finish())


def worker_pools(selector):
    m = initialized()
    # Same scheduling/peripheral fixtures as verify_scheduling_boundaries.py.
    # No actual USB, semaphore or hardware register effects are implemented.
    for address, size in ((0x401b0000, 0x10000), (0x401f8000, 0x1000), (0xe000e000, 0x1000)):
        m.uc.mem_map(address, size)
    for offset, value in ((0, 0x7000), (12, 0x7001), (24, 0x7002)):
        m.uc.mem_write(0x801f9108+offset, struct.pack('<I', value))
    requests = []
    delivered = []

    def wait(args):
        assert args[0] == 0x7000 and not delivered
        delivered.append(selector)
        m.uc.mem_write(0x801f910c, struct.pack('<II', 1 << selector, 0))
        return 0

    def start(args):
        requests.append(bytes(m.uc.mem_read(args[0], 0x8c)))
        m.reached_return = True
        m.uc.emu_stop()
        return 0

    fixture_calls = (0x8003b580, 0x80073ec8, 0x80073f18, 0x80025f78, 0x8001bcd8,
                     0x8001bc98, 0x800684b8, 0x80026bf0, 0x8001bc20, 0x8003b5d0)
    for fn in fixture_calls:
        m.hooks[fn] = lambda args: 0
    m.hooks.update({0x80076950: wait, 0x8003b5a8: start})

    def reject_gap(uc, access, address, size, value, data):
        assert not overlaps(address, size, GAPS), (hex(address), hex(uc.reg_read(UC_ARM_REG_PC)))

    hook = m.uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, reject_gap)
    m.invoke(0x80045cf0, [])
    m.uc.hook_del(hook)
    assert len(requests) == 1
    request = requests[0]
    pid = struct.unpack_from('<H', request, 4)[0]
    assert pid == (0x89f, 0x88f, 0x89e, 0x88e, 0x89d, 0x88d)[selector-5]

    # Preserve the real worker-generated request outside its expired stack.
    # Wrapper 3b5a8 adds 4; caller 3aeb8 passes that object+0x38 to 67980.
    param = 0x20022000
    m.uc.mem_write(param, request)
    m.hooks.clear()
    table_range = (POOL_TABLE, POOL_TABLE+40)
    trace = Accesses(m, (table_range,), (table_range, (param, param+len(request))))
    m.invoke(0x80067980, [param+0x3c])
    for i, expected in enumerate(POOLS):
        pointer = m.invoke(0x80066f18, [i])
        assert pointer == POOL_TABLE+8*i
        assert struct.unpack('<II', m.uc.mem_read(pointer, 8)) == expected
        assert 0x20000000 <= expected[0] < expected[0]+expected[1] <= 0x20020000
    installed = trace.finish()

    # Original audio-state construction consumes pool IDs 3 and 4. Stop before
    # format-dependent length calculation/clearing, whose bounds are separate.
    entered = []

    def stop_length(uc, address, size, data):
        entered.append(address)
        m.reached_return = True
        uc.emu_stop()

    hook = m.uc.hook_add(UC_HOOK_CODE, stop_length, begin=0x80070298, end=0x80070298)
    states = ((0x808e2f80, 0x808e2fdd), (0x808e2e54, 0x808e2eb1), (STACK-0x100, STACK))
    trace = Accesses(m, states, states + (table_range, (0x80079f68, 0x80079f78),
                                        (0x80214798, 0x8021479c)))
    m.invoke(0x80070068, [PROFILES[PIDS.index(pid)]-16, 1])
    m.uc.hook_del(hook)
    assert entered == [0x80070298]
    for state, pool_id in ((0x808e2f80, 3), (0x808e2e54, 4)):
        assert word(m, state+4) == POOL_TABLE+8*pool_id
        assert word(m, state+0x14) == POOLS[pool_id][0]
    return dict(selector=selector, pid=pid, pool_base_length_pairs=POOLS,
                installed_table=installed, audio_state=trace.finish(),
                stop_before=0x80070298,
                modeled_worker_calls=[*fixture_calls, 0x80076950, 0x8003b5a8],
                limitation='Provider bounds only; downstream length arithmetic, transfers and DMA remain unexecuted')


def main():
    checks = []
    for profile in PROFILES:
        for flag in (0, 1):
            for power in (0, 1):
                m = initialized()
                selected = select(m, profile, flag)
                if power == 0:
                    checks.append(dict(case='original_profile_selection', passed=True, **selected))
                result = construct(m, power, serial=bool(power))
                checks.append(dict(case='original_caller_through_complete_descriptor_builder',
                                   passed=True, profile=profile, selector_flag=flag, **result))
    for previous in (False, True):
        m = initialized()
        if previous:
            select(m, PROFILES[1], 1)
        before = [bytes(m.uc.mem_read(a, b-a)) for a, b in SELECT_WRITES[1:]]
        trace = Accesses(m, (SELECT_WRITES[0],), SELECT_WRITES + ((0x801f5400, 0x801f8b80),))
        assert m.invoke(SELECTOR, [0xffff, 1]) == 0
        assert before == [bytes(m.uc.mem_read(a, b-a)) for a, b in SELECT_WRITES[1:]]
        checks.append(dict(case='unknown_PID_preserves_existing_provider', passed=True,
                           previous_selection=previous, **trace.finish()))
    for selector in range(5, 11):
        checks.append(dict(case='worker_request_to_original_pool_provider_and_audio_state',
                           passed=True, **worker_pools(selector)))

    # The original MPU setup can establish cache attributes, not alias freedom.
    regions = mpu(0)
    probes = [a for start, end in GAPS for a in (start, end-1)]
    for address in probes:
        candidates = [r for r in regions if r['enabled'] and
                      int(r['start'], 16) <= address < int(r['end'], 16) and
                      (r['bytes'] < 256 or not (r['subregions_disabled'] &
                       (1 << ((address-int(r['start'], 16))*8//r['bytes']))))]
        r = max(candidates, key=lambda x: x['region'])
        assert r['region'] == 10
        assert (r['tex'], r['shareable'], r['cacheable'], r['bufferable']) == (0, False, True, True)
    checks.append(dict(case='both_gaps_use_same_highest_priority_cached_MPU_region', passed=True,
                       addresses=probes, region=regions[10], physical_aliases_tested=False))
    out = ROOT/'analysis/usb_memory_providers_verification.json'
    report = dict(passed_groups=len(checks), results=checks,
                  stock_sha256=hashlib.sha256(IMAGE).hexdigest(), device_access=False,
                  physical_ownership_proven=False, limitations=[
                      'Eleven stock profiles, selector flag 0/1 and paired power/serial fixtures; not all runtime inputs',
                      'Original decompressed templates plus zeroed startup globals; no full boot or concurrent mutations',
                      'Descriptor path stops before 80044fb0; worker has explicit scheduling/peripheral fixtures',
                      'Five supplied pool pairs are traced; dynamic lengths, endpoints, DMA and eight-pair table population unresolved',
                      'MPU writes are traced into fixture registers; no physical cache or address-independence test',
                      'No firmware generation, staging, mixer commands or capture-layout changes'])
    out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks), report=str(out))))


if __name__ == '__main__':
    main()
