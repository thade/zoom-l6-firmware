#!/usr/bin/env python3
"""Offline checks for bounded gap leads and selected concrete stock consumers.

Does not run a full boot, prove free RAM, or access/change the mixer. Scheduling,
USB hardware setup, and queue critical sections are fixtures. Stock heap and
selected memory accesses execute. Analysis assembly is never packaged as firmware.
"""
import hashlib
import json
import os
import struct
import subprocess
import sys

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_PC
from verify_pad_protocol import Machine, IMAGE, ROOT, STACK
from verify_memory_layout import HEAP_STATE, HEAP_START, HEAP_END, INITIAL_FREE, word

sys.path.insert(0, str(ROOT/'tools/firmware'))
from audit_ram_gap_consumers import GAPS, overlaps, trace_window

TABLE = 0x80960038
DEV = 0x8095ffe0
CODEPAGE = (0x8009ae40, 0x800a0b46)
OUT = ROOT/'analysis/ram_gap_consumers_verification.json'


def compiled_fixture():
    elf_path = ROOT/'analysis/ram_gap_scan.elf'
    env = dict(os.environ, ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local', ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    subprocess.run([sys.executable, '-m', 'ziglang', 'cc', '-target', 'thumb-freestanding-eabihf',
        '-mcpu=cortex_m7', '-nostdlib', '-Wl,-T,tests/fixtures/ram_gap_scan.ld', '-Wl,-e,gap_arithmetic',
        'tests/fixtures/ram_gap_scan.S', '-o', str(elf_path)],
        cwd=ROOT, env=env, check=True)
    with elf_path.open('rb') as f:
        e = ELFFile(f); section = e.get_section_by_name('.text')
        symbols = {s.name: s['st_value'] & ~1 for s in e.get_section_by_name('.symtab').iter_symbols()}
        return section['sh_addr'], section.data(), symbols


def fixture_checks(checks):
    base, code, symbols = compiled_fixture()
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS); md.detail = True
    expected = {'arithmetic': [(GAPS[1][0], 8)], 'bulk': [(GAPS[1][0]-32, 64)],
                'index': [(GAPS[1][0], 4)], 'post_index': [(GAPS[1][0], 4)],
                'multiple': [(GAPS[1][0]-4, 8)], 'literal': [(GAPS[1][0], 1)]}
    for name, wanted in expected.items():
        start = symbols['gap_'+name]
        r = trace_window(md, code, base, start-base, GAPS)
        writes = [(x['start'], x['bytes']) for x in r['accesses'] if x['mode'] == 'write']
        assert writes == wanted, (name, r, wanted)
        # Independent execution of assembled instructions confirms actual write
        # spans. Run the real memset for the bulk example, not a modeled helper.
        m = Machine(); m.uc.mem_map(0x81000000, 0x1000000); m.uc.mem_write(base, code)
        observed = []
        def capture(uc, access, address, size, value, data):
            if overlaps(address, size, GAPS): observed.append((address, size))
        m.uc.hook_add(UC_HOOK_MEM_WRITE, capture)
        m.invoke(start, [0, 0x1234, 0x5678])
        assert observed
        for address, size in observed:
            assert any(a <= address and address+size <= a+n for a, n in wanted), (name, observed)
        checks.append(dict(case='derived_'+name, passed=True, spans=wanted, actual_gap_writes=observed))
    for name in ('clobber', 'mutable_load', 'branch', 'conditional', 'call', 'outside'):
        r = trace_window(md, code, base, symbols['gap_'+name]-base, GAPS)
        assert not r['accesses'], (name, r)
        checks.append(dict(case='bounded_'+name, passed=True, stop=r['stop'],
                           limitation='Unknown/conditional/after-call paths are deliberately unresolved, not excluded'))


def watch(m, allowed):
    writes = []; reads = []
    def capture(uc, access, address, size, value, data):
        if access == UC_MEM_WRITE:
            assert any(a <= address and address+size <= b for a, b in allowed), (hex(address), hex(uc.reg_read(UC_ARM_REG_PC)))
            assert not overlaps(address, size, GAPS), hex(address)
            writes.append((address, size))
        else:
            assert not overlaps(address, size, GAPS), (hex(address), hex(uc.reg_read(UC_ARM_REG_PC)))
            if overlaps(address, size, ((TABLE, TABLE+64),)):
                reads.append((address, size))
    m.uc.hook_add(UC_HOOK_MEM_WRITE, capture)
    m.uc.hook_add(UC_HOOK_MEM_READ, capture)
    return writes, reads


def helper_checks(checks):
    # Verify all six ABI interpretations used by the static scan against actual
    # stock instructions, including spans which start below the candidate gap.
    dst = GAPS[1][0]-32; src = 0x20024000; count = 64
    payload = bytes(range(count))
    cases = ((0x80001754, [dst, src, count], payload),
             (0x80079498, [src, dst, count], payload),
             (0x8000177c, [dst, count, 0xa5], bytes([0xa5])*count),
             (0x8000178a, [dst, count], bytes(count)),
             (0x8000178e, [dst, 0xa5, count], bytes([0xa5])*count),
             (0x800794a8, [0, dst, count], bytes(count)))
    for fn, args, wanted in cases:
        m = Machine(); m.uc.mem_map(0x81000000, 0x1000000)
        m.uc.mem_write(dst, bytes([0xcc])*count); m.uc.mem_write(src, payload)
        observed = []
        def capture(uc, access, address, size, value, data):
            if 0x81000000 <= address < 0x82000000:
                assert dst <= address and address+size <= dst+count
                observed.append((address, size))
        m.uc.hook_add(UC_HOOK_MEM_WRITE, capture)
        m.invoke(fn, args)
        assert bytes(m.uc.mem_read(dst, count)) == wanted
        assert min(a for a, n in observed) == dst and max(a+n for a, n in observed) == dst+count
        checks.append(dict(case='native_bulk_ABI_'+hex(fn), passed=True, write_span=[dst, dst+count]))


def boundary_checks(checks):
    for slot in range(9):
        m = Machine(); m.hooks[0x80074780] = lambda a: 0; m.hooks[0x80077540] = lambda a: 0
        ptr = m.invoke(0x8006de78, [64])
        pairs = [[0x100+i, ptr if i == slot else HEAP_START+0x1000+i*0x10] for i in range(8)]
        m.uc.mem_write(TABLE, struct.pack('<16I', *(v for pair in pairs for v in pair)))
        writes, reads = watch(m, ((HEAP_START, HEAP_END), (HEAP_STATE, HEAP_STATE+28),
                                 (TABLE, TABLE+64), (STACK-0x100, STACK)))
        m.invoke(0x800740b8, [ptr])
        if slot < 8: pairs[slot] = [0, 0]
        assert bytes(m.uc.mem_read(TABLE, 64)) == struct.pack('<16I', *(v for pair in pairs for v in pair))
        assert word(m, HEAP_STATE+4) == INITIAL_FREE
        assert all(a+n <= GAPS[0][0] for a, n in reads)
        checks.append(dict(case='native_eight_pair_free_'+str(slot), passed=True,
            match=slot if slot < 8 else None, last_table_read_end=max(a+n for a, n in reads),
            writes=len(writes), actual_stock_heap_release=True))
    # Execute the larger constructor in its real caller. Capture its argument
    # before entering, rather than substituting a convenient synthetic object.
    for classification in (0, 2):
        m = Machine(); args = []
        m.hooks[0x8003acf0] = lambda a: 0
        for fn in (0x8003ace8, 0x8003ad48, 0x8003ad10): m.hooks[fn] = lambda a: 0
        m.hooks[0x80072720] = lambda a: args.append(m.uc.reg_read(UC_ARM_REG_R4)) or classification
        last = []
        def halt(uc, address, size, data):
            last.append(hex(address)); del last[:-16]
            if address in (0x800704d8, 0x8007286c, 0x80072870):
                m.reached_return = True; uc.emu_stop()
        # Mode2 returns directly. Stop at the next caller instruction or its
        # following MOVT (both only load a callback constant, no memory access).
        # Including the latter avoids depending on Unicorn's first-target code
        # callback after a conditional POP-to-PC.
        m.uc.hook_add(UC_HOOK_CODE, halt)
        writes, _ = watch(m, ((STACK-0x200, STACK), (DEV, DEV+0x48)))
        try:
            m.invoke(0x800727e8, [])
        except Exception as error:
            raise AssertionError((classification, args, last)) from error
        assert args == [STACK-0xbc]
        assert args[0]+0x90 <= STACK
        static = [(a, n) for a, n in writes if DEV <= a < DEV+0x48]
        assert bool(static) == (classification != 2)
        if static: assert max(a+n for a, n in static) == 0x80960028
        checks.append(dict(case='native_USB_constructor_class_'+str(classification), passed=True,
            object=args[0], object_end=args[0]+0x90, highest_fixed_write_end=max((a+n for a, n in static), default=None),
            modeled_calls=['configuration providers', '0x80072720', '0x800704d8']))
    # Allocate the largest startup queue with the ORIGINAL allocator, then
    # exhaust the same heap. There is no fixture allocator backing this check.
    for exhausted in (False, True):
        m = Machine()
        for fn in (0x80074780, 0x80077540, 0x80073ec8, 0x80073f18): m.hooks[fn] = lambda a: 0
        if exhausted: assert m.invoke(0x8006de78, [INITIAL_FREE-16])
        writes, _ = watch(m, ((HEAP_START, HEAP_END), (HEAP_STATE, HEAP_STATE+28), (STACK-0x100, STACK)))
        ptr = m.invoke(0x80076348, [4096, 20, 0])
        if exhausted:
            assert ptr == 0
        else:
            assert HEAP_START <= ptr < ptr+82000 <= HEAP_END
            assert word(m, ptr+0x3c) == 4096 and word(m, ptr+0x40) == 20
            assert word(m, ptr) == ptr+80
            m.invoke(0x80073f48, [ptr]); assert word(m, HEAP_STATE+4) == INITIAL_FREE
        checks.append(dict(case='native_queue_heap_'+str(exhausted), passed=True,
            returned=ptr, request_bytes=82000, writes=len(writes), critical_sections_modeled=True))


def character_table_checks(checks):
    m = Machine(); source = 0x20021000; dest = 0x20022000; length = 0x20023000
    entries = []
    # Both derived gap forms load these literal words out of this table.
    # Convert their four constituent characters through the stock decoder.
    for addr in (0x8009c204, 0x8009cba4):
        encoded = bytearray()
        for address in (addr, addr+2):
            row, col = divmod(address-CODEPAGE[0], 0x17a)
            assert col % 2 == 0 and 0 <= row <= 62
            high = row+0x81 if row < 31 else row-31+0xe0
            encoded.extend((high, col//2+0x40))
        m.uc.mem_write(source, bytes(encoded)+b'\0')
        assert m.invoke(0x8006fa08, [dest, source, length]) == 0
        raw = IMAGE[addr-0x80000e00:addr-0x80000e00+4]
        assert bytes(m.uc.mem_read(dest, 6)) == raw+b'\0\0'
        assert word(m, length) == 4
        entries.append(dict(address=addr, encoded=encoded.hex(), decoded=raw.decode('utf-16le'), raw=raw.hex()))
    checks.append(dict(case='derived_gap_literals_are_stock_character_conversion_entries', passed=True,
        decoder=0x8006fa08, table_range=list(CODEPAGE), entries=entries,
        limitation='Table interpretation resolves these scan leads; not a complete code reachability or ownership proof'))


def constructor_destination_checks(checks):
    # Extend the real caller through 800704d8, previously a stopping boundary.
    # That routine copies the caller's 0xac-byte setup into fixed native RAM;
    # it is not a hardware-init or general-allocation operation. Stop before
    # the subsequent 80073748 constructor and its unresolved providers.
    destination = 0x808e2eb8
    for classification in (0, 1, 2):
        m = Machine(); snapshots = []; next_args = []
        for fn in (0x8003acf0, 0x8003ace8, 0x8003ad48, 0x8003ad10):
            m.hooks[fn] = lambda a: 0
        m.hooks[0x80072720] = lambda a: classification
        def observe(uc, address, size, data):
            argument = uc.reg_read(UC_ARM_REG_R0)
            if address == 0x800704d8:
                snapshots.append(bytes(uc.mem_read(argument, 0xac)))
            elif address == 0x80073748:
                next_args.append(argument)
                m.reached_return = True; uc.emu_stop()
        m.uc.hook_add(UC_HOOK_CODE, observe)
        writes, _ = watch(m, ((STACK-0x200, STACK), (DEV, DEV+0x48),
                             (destination, destination+0xac)))
        m.invoke(0x800727e8, [])
        assert next_args == [STACK-0xbc]
        copied = [(a, n) for a, n in writes if destination <= a < destination+0xac]
        if classification == 2:
            assert not snapshots and not copied
        else:
            assert len(snapshots) == 1
            assert bytes(m.uc.mem_read(destination, 0xac)) == snapshots[0]
            assert min(a for a, n in copied) == destination
            assert max(a+n for a, n in copied) == destination+0xac
        checks.append(dict(case='native_USB_setup_destination_class_'+str(classification),
            passed=True, stack_object=next_args[0], destination=destination,
            destination_end=destination+0xac, bytes_copied=0 if classification == 2 else 0xac,
            next_unexecuted_constructor=0x80073748,
            modeled_calls=['configuration providers', '0x80072720'],
            limitation='Selected setup-copy path only; downstream runtime pointers, DMA and bootloader remain unresolved'))


def main():
    checks = []; fixture_checks(checks); helper_checks(checks); boundary_checks(checks); character_table_checks(checks)
    constructor_destination_checks(checks)
    report = dict(passed_groups=len(checks), results=checks, firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        physical_ownership_proven=False, limitations=[
            'Selected original routines execute with synthetic initialized RAM; no full boot or concurrency',
            'Table population, other allocators/derived consumers, bootloader, DMA/cache and physical aliases unresolved',
            'Static scan stops are limits, not proof no later use exists',
            'No firmware image, device access, allocation on the device or deployment'])
    OUT.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks), report=str(OUT))))


if __name__ == '__main__':
    main()
