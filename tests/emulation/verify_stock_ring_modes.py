#!/usr/bin/env python3
"""Bounded native initialization/audio-mode audit of proposed fixed ring tails.

The size instruction is changed only in Unicorn memory. There is no firmware
output, device access, complete boot, physical ownership or timing claim.
"""
import hashlib
import json
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R11, UC_ARM_REG_S18

from verify_pad_reader_audit import AuditRig, TARGETS, SECONDARY
from verify_pad_renderer_boundary import CALLBACK
from verify_stock_ring_layout import CAPACITIES, STOCK_CAP, capacities, tails, tail_events, CANARY, OUTPUT
from verify_uncompressed_tap import B, RING, STRIDE, packed
from verify_recording_writer import C
from verify_record_events import FLAGS, CURSOR
from verify_firmware_workflow import put32, get32
from verify_pad_protocol import ROOT, IMAGE, BIAS

SIZE_SITE = 0x800121ce
EXPECTED_SHA = '64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
MD = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)


def size_instruction(cap):
    """Replace only MOVW r1's low immediate; the existing MOVT remains 3."""
    assert cap % 64 == 0 and cap >> 16 == 3 and 0 < cap <= STOCK_CAP
    imm = cap & 0xffff
    encoded = struct.pack('<HH',
        0xf240 | (imm >> 12) | (((imm >> 11) & 1) << 10),
        (((imm >> 8) & 7) << 12) | (1 << 8) | (imm & 255))
    assert list(MD.disasm_lite(encoded, SIZE_SITE)) == [
        (SIZE_SITE, 4, 'movw', f'r1, #{imm:#x}')]
    return encoded


def initialized(cap, mode=0):
    r = AuditRig()
    r.priority_changes = []
    # Only mode and kernel priority effects are supplied. Original full
    # audio initialization and recorder reset/configuration execute, including
    # native memset and every recovered capacity getter/setter.
    r.m.hooks[0x80006248] = lambda a: mode
    r.m.hooks[0x80074440] = lambda a: r.priority_changes.append(tuple(a[:2])) or 0
    assert r.raw(SIZE_SITE, 4) == IMAGE[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]
    r.m.uc.mem_write(SIZE_SITE, size_instruction(cap))
    r.m.invoke(0x80011920, [48000])
    r.m.invoke(0x8000ad48, [])
    return r


def check_sizes(r, cap):
    assert get32(r.m, B+0x53e0) == get32(r.m, B+0x53f0) == RING
    assert get32(r.m, B+0x53e8) == get32(r.m, B+0x53f8) == cap
    assert get32(r.m, C+0x50) == get32(r.m, C+0x1e94) == cap


def untouched_tails(r, cap):
    for lane in range(12):
        assert r.raw(RING+lane*STRIDE+cap*4, STRIDE-cap*4) == CANARY*(STRIDE-cap*4)


def configured(cap, playback=0):
    r = initialized(cap)
    r.seed(length=128, loop=1)
    # Explicit synthetic source/delay state; no USB/ADC/DMA driver executes.
    put32(r.m, SECONDARY, 0x2022a789)
    put32(r.m, B+0x63a0, 0x21030000)
    put32(r.m, B+0x63a4, 0x21031000)
    for lane in range(10):
        r.m.uc.mem_write(B+0x5864+lane*16,
            struct.pack('<4I', 0x21010000+lane*0x1000, 128, 127, 0))
    inputs = [(lane+1)*(i-32)*(1 << 18) for lane in range(12) for i in range(64)]
    r.m.uc.mem_write(0x2000fa48, struct.pack('<768i', *inputs))
    # Select an input contribution on each side as well as the active pad.
    r.floats(B+0x5e34, [1]+[0]*9+[0, 1]+[0]*8)
    tails(r, cap)
    put32(r.m, B+0x53e4, cap-64)
    put32(r.m, B+0x53ec, cap-64)
    put32(r.m, B+0x53f4, cap-64)
    if playback:
        put32(r.m, B+0x53d0, 1)
        r.m.uc.mem_write(B+0x53d4, bytes([playback]))
        for lane in range(12):
            for position, factor in ((cap-64, 1), (0, 2)):
                r.floats(RING+lane*STRIDE+position*4,
                    [(lane+1)*(i-32)*factor/128 for i in range(64)])
    return r


def run_callbacks(cap, target, playback):
    r = configured(cap, playback)
    events, tail_hook = tail_events(r, cap)
    accesses = []
    def observe(uc, access, address, size, value, _):
        accesses.append(dict(pc=hex(uc.reg_read(UC_ARM_REG_PC)), access=access,
                             address=address, bytes=size))
    ring_hook = r.m.uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, observe,
        begin=RING, end=RING+12*STRIDE-1)
    snapshots = []
    try:
        for block in range(2):
            r.full(target)
            snapshots.append(r.raw(B+0x10, 0x53b8))
            if target == CALLBACK:
                assert get32(r.m, B+0x53e4) == block*64
                assert get32(r.m, B+0x53ec) == cap
                expected_play_cursor = block*64 if playback == 2 else cap-64
                assert get32(r.m, B+0x53f4) == expected_play_cursor
            else:
                assert get32(r.m, B+0x53e4) == get32(r.m, B+0x53f4) == cap-64
        check_sizes(r, cap)
        untouched_tails(r, cap)
    finally:
        r.m.uc.hook_del(ring_hook)
        r.m.uc.hook_del(tail_hook)
    assert not events
    if target == CALLBACK:
        assert accesses
        if playback != 2:
            assert sum(e['access'] == UC_MEM_WRITE for e in accesses) == 12*64*2
    else:
        assert not accesses
    samples = b''.join(r.raw(RING+lane*STRIDE+(cap-64)*4, 256) +
        r.raw(RING+lane*STRIDE, 256) for lane in range(12))
    return snapshots, samples, len(accesses)


def refill(cap, lane, channels, width, stale_cache=False):
    """Actual song-refill worker/registered writer; read bytes and lock are fixtures."""
    r = initialized(cap); tails(r, cap); m = r.m
    m.hooks[0x8001aaa0] = lambda a: 0
    m.hooks[0x8001aab8] = lambda a: 0
    put32(m, C+0x1ea8, 64); put32(m, C+0x1e8c, cap-32)
    put32(m, C+0x21d8, 1 << lane)
    put32(m, C+0x21dc, (1 << lane) if channels == 2 else 0)
    for index in range(12):
        m.uc.mem_write(C+0x21e0+index, bytes([width*8]))
        put32(m, C+0x221c+index*4, 100000)
        put32(m, C+0x224c+index*4, 100000)
    values = [(i-32)*(ch+1) for i in range(64) for ch in range(channels)]
    if width == 4:
        source = packed([v/128 for v in values])
        expected = packed([v/128*2**31 for v in values])
    else:
        source = b''.join(v.to_bytes(width, 'little', signed=True) for v in values)
        expected = packed([v*(1 << (32-width*8)) for v in values])
    calls = []
    def read(a):
        assert a[0] == lane and a[2] % 512 == 0
        calls.append(tuple(a[:3]))
        # Public file task/SD/sector completion is outside this fixture.
        m.uc.mem_write(a[1], (source*((a[2]+len(source)-1)//len(source)))[:a[2]])
        return 0
    m.hooks[0x21038000] = read
    put32(m, C+0x3ab0, 0x21038001)
    if stale_cache: put32(m, C+0x1e94, STOCK_CAP)
    events, h = tail_events(r, cap)
    m.invoke(0x80038b50, [])
    assert get32(m, C+0x21ec+lane*4) == 64 and len(calls) == 1
    if stale_cache:
        assert get32(m, C+0x1e8c) == cap+32
        m.invoke(0x80038b50, [])
        assert events
    else:
        assert get32(m, C+0x1e8c) == 32
        m.uc.mem_write(m.stack, struct.pack('<2I', channels, 4))
        assert m.invoke(0x80018fd0, [cap-32, OUTPUT, 64, lane]) == len(expected)
        assert r.raw(OUTPUT, len(expected)) == expected
        check_sizes(r, cap); untouched_tails(r, cap); assert not events
    m.uc.hook_del(h)
    return len(events)


def main():
    results = []
    def passed(case, **details):
        results.append(dict(case=case, passed=True, **details))

    assert hashlib.sha256(IMAGE).hexdigest() == EXPECTED_SHA
    assert size_instruction(STOCK_CAP) == IMAGE[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]
    assert list(MD.disasm_lite(IMAGE[SIZE_SITE+4-BIAS:SIZE_SITE+8-BIAS], SIZE_SITE+4)) == [
        (SIZE_SITE+4, 4, 'movt', 'r1, #3')]
    passed('stock_hash_and_exact_existing_shared_capacity_instruction_verified', site=hex(SIZE_SITE))

    # Direct references in a bounded linear MAIN disassembly are leads only.
    targets = (0x80011920, 0x800026a0, 0x8000ad48, 0x800381d0, 0x800381b0)
    refs = {f'{target:#x}': [] for target in targets}
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS); md.skipdata = True
    for pc, size, op, arg in md.disasm_lite(IMAGE[0x600:0xa0000], BIAS+0x600):
        if op in ('bl', 'b', 'b.w') and arg[1:] in refs:
            refs[arg[1:]].append(hex(pc))
    assert refs == {'0x80011920': ['0x800026b0'], '0x800026a0': ['0x8001b280'],
        '0x8000ad48': ['0x8001b29e'], '0x800381d0': ['0x8000ad7e'],
        '0x800381b0': ['0x8000ad92']}
    passed('bounded_direct_startup_and_capacity_setter_reference_inventory', references=refs,
           complete_call_graph=False)

    baselines = {(target, mode): run_callbacks(STOCK_CAP, target, mode)
                 for target in TARGETS for mode in (0, 1, 2)}
    for cap in CAPACITIES:
        for mode in (0, 1, 2):
            r = initialized(cap, mode)
            check_sizes(r, cap)
            expected_callback = 0x800124d9 if mode == 1 else CALLBACK | 1
            assert get32(r.m, B+0x53c8) == expected_callback
            assert get32(r.m, B+0x53e4) == get32(r.m, B+0x53f4) == get32(r.m, B+0x53ec) == 0
            assert r.priority_changes[0][1] == 30
        passed(f'complete_original_audio_and_recorder_initializers_propagate_one_size_in_all_selector_modes_{cap}',
               capacity=cap, initializer=hex(0x80011920), recorder_initializer=hex(0x8000ad48))

        r = initialized(cap); tails(r, cap)
        events, h = tail_events(r, cap)
        put32(r.m, B+0x53e4, cap-64); put32(r.m, B+0x53f4, cap-64)
        put32(r.m, C+0x50, STOCK_CAP); put32(r.m, C+0x1e94, STOCK_CAP)
        r.m.invoke(0x80011920, [48000]); r.m.invoke(0x8000ad48, [])
        r.m.uc.hook_del(h)
        check_sizes(r, cap); untouched_tails(r, cap)
        assert not events and get32(r.m, B+0x53e4) == get32(r.m, B+0x53f4) == 0
        passed(f'original_reinitialization_reuses_changed_instruction_resets_cursors_and_refreshes_caches_{cap}',
               tail_accesses=len(events), live_reinitialization_authorized=False)

        for mode in (0, 1, 2):
            counts = {}
            for target in TARGETS:
                actual = run_callbacks(cap, target, mode)
                assert actual == baselines[(target, mode)]
                counts[hex(target)] = actual[2]
            passed(f'all_four_complete_audio_callbacks_match_stock_across_wrap_playback_{mode}_{cap}',
                   ring_accesses=counts, tail_accesses=0, playback_flag=mode,
                   effects_configuration='idle/no active effects processor')

        r = initialized(cap); tails(r, cap)
        events, h = tail_events(r, cap)
        # Original setters and start/stop helpers change activity/positions,
        # without changing the physical arena or its size in these states.
        for fn, args in ((0x80019418, [cap-64]), (0x80019428, [cap]),
            (0x80019438, [0]), (0x80019450, []), (0x80018e10, []),
            (0x80019438, [1]), (0x8000ca98, []), (0x8000cab0, [])):
            r.m.invoke(fn, args); check_sizes(r, cap)
        r.m.uc.hook_del(h); untouched_tails(r, cap); assert not events
        passed(f'examined_native_activity_cursor_and_selector_setters_preserve_layout_{cap}', tail_accesses=0)

        r = initialized(cap)
        for flags, available, history in (((0, 1, 0), cap, 0),
            ((1, 0, 0), cap, 24000), ((0, 0, 1), cap, 96000),
            ((1, 0, 0), 1234, 1234)):
            put32(r.m, B+0x53e4, 64); put32(r.m, B+0x53ec, available)
            for offset, value in zip((4, 0, 3), flags):
                r.m.uc.mem_write(FLAGS+offset, bytes([value]))
            assert r.m.invoke(0x80018f10, []) == (64-history) % cap
            assert get32(r.m, CURSOR) == (64-history) % cap
            assert r.m.invoke(0x80002460, []) == 64
        for read, endpoint in ((cap-64, 17), (64, 64), (64, cap-17)):
            put32(r.m, C+8, 0xfff)
            for lane in range(12):
                put32(r.m, C+0x20+lane*4, read)
                put32(r.m, C+0x484+lane*4, 500000)
            r.m.invoke(0x800382a8, [endpoint])
            for lane in range(12):
                assert get32(r.m, C+0x4e4+lane*4) == 500000+(endpoint-read) % cap
        passed(f'original_lookback_clamp_and_twelve_stop_endpoints_use_reduced_bound_{cap}')

        for width in (2, 3, 4):
            for lane in range(12): refill(cap, lane, 1, width)
            for lane in range(0, 12, 2): refill(cap, lane, 2, width)
            sample_format = 'float32' if width == 4 else f'PCM{width*8}'
            passed(f'original_song_refill_worker_registered_writer_and_ack_wrap_all_{sample_format}_lanes_{cap}',
                   mono_lanes=12, stereo_pairs=6, tail_accesses=0,
                   native_callback='0x80002d10 -> 0x80019498', file_read_and_lock='modeled')

    events = refill(CAPACITIES[0], 10, 2, 4, stale_cache=True)
    passed('negative_control_stale_playback_cache_advances_refill_into_reserved_tail_on_next_request',
           tail_accesses=events, production_patch=False)

    # A counterexample to live shrinking: coherent sizes do not make an old
    # producer cursor valid. Native DSP copies first, then wraps the cursor.
    r = initialized(STOCK_CAP); cap = CAPACITIES[0]
    capacities(r, cap); put32(r.m, C+0x50, cap); put32(r.m, C+0x1e94, cap)
    check_sizes(r, cap); tails(r, cap)
    put32(r.m, B+0x53e4, cap+64)
    r.m.uc.reg_write(UC_ARM_REG_R11, B); r.m.uc.reg_write(UC_ARM_REG_S18, 0x30000000)
    events, h = tail_events(r, cap)
    r.window(0x20229b74, 0x2022a77a)
    r.m.uc.hook_del(h)
    assert events and r.raw(RING+cap*4+256, 256) != CANARY*256
    passed('negative_control_live_shrink_with_stale_cursor_writes_reserved_tails_even_with_coherent_caches',
           tail_accesses=len(events), production_patch=False)

    report = dict(passed=True, groups=len(results), results=results, firmware_sha256=EXPECTED_SHA,
        image_created=False, device_access=False,
        limitations=[
            'Size changes only in emulator memory; full physical startup, exclusive tail ownership and safe live resizing are not established.',
            'Mode/kernel priority effects and initial hardware state are fixtures; original full buffer and recorder initializers execute.',
            'All four original callbacks execute completely, including normal DSP, with synthetic inputs and idle effects; USB/ADC/DMA drivers do not execute.',
            'Original recorded-song refill/registered writer/ack execute; file data, read completion and lock scheduling are modeled.',
            'ARM MAX permits original double-precision instructions; it is not physical chip identification.',
            'Selected control/lookback/stop states and bounded direct references are not an exhaustive indirect-call or alternate-mode audit.',
            'No physical/cache completion, producer scheduling, service/catch-up or ordinary backlog budget is proved.',
            'Current history API is contiguous; no segmented history implementation or native writer change is included.'])
    out = ROOT/'analysis/stock_ring_modes_verification.json'
    out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, groups=len(results), report=str(out))))


if __name__ == '__main__':
    main()
