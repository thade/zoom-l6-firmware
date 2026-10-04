#!/usr/bin/env python3
"""Offline firmware ABI evidence. No device, MIDI, SD or flash access.

Runs original v1.10 Thumb instructions with synthetic RAM and intercepted RTOS,
filesystem driver and SPI effects. Does not create a patched firmware image.
"""
import json
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from unicorn.arm_const import UC_ARM_REG_R10
from verify_pad_protocol import Machine, ROOT, INPUT, IMAGE, BIAS
from verify_record_catalogue import putstr, getstr

HANDLE = 0x20022000
VOLUME = 0x20024000
BUFFER = 0x20026000
TABLE = 0x800a0b28
RESULT = INPUT + 0x800


def put32(m, address, value):
    m.uc.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get32(m, address):
    return struct.unpack('<I', m.uc.mem_read(address, 4))[0]


def filesystem_machine(mode=2):
    m = Machine()
    m.uc.mem_write(HANDLE, bytes([0x40, mode]))
    put32(m, HANDLE + 0x230, VOLUME)
    m.uc.mem_write(VOLUME + 0x206, b'\x01')
    m.uc.mem_write(VOLUME + 0x20c, struct.pack('<H', 512))
    put32(m, VOLUME + 0x258, TABLE)
    # External locking, volume lookup, path validation and exception context.
    for fn in (0x8001bf88, 0x8002b130, 0x8002b110, 0x8002b100,
               0x80035180, 0x80035190, 0x800351b0, 0x80035168,
               0x80032810, 0x80001848, 0x8001d9b0):
        m.hooks[fn] = lambda a: 0
    m.hooks[0x800670b0] = lambda a: VOLUME
    return m


def main():
    results = []
    def passed(case, **evidence):
        results.append({'case': case, 'passed': True, **evidence})

    # Public open wrapper: actual slot selection and driver dispatch.
    for flags in (0, 1, 2, 0x101, 0x501):
        m = filesystem_machine()
        m.uc.mem_write(0x801f9270, b'\xff')
        putstr(m, INPUT, 'A:\\SOUND_PAD\\PAD1\\OD_TEST.WAV')
        calls = []
        m.hooks[0x800604e8] = lambda a: calls.append(a[:4]) or 0
        assert m.invoke(0x8005ffe8, [RESULT, INPUT, flags, 0x80]) == 0
        assert calls == [[0x801f9270, INPUT, flags, 0x80]], calls
        assert get32(m, RESULT) == 0x801f9270
        passed(f'open_wrapper_flags_{flags:#x}', driver_args=calls[0], output_handle=get32(m, RESULT))
    m = filesystem_machine()
    m.uc.mem_write(0x801f9270, b'\xff')
    putstr(m, INPUT, 'A:\\MISSING.WAV')
    m.hooks[0x800604e8] = lambda a: 0xffffd75a
    put32(m, RESULT, 0xdeadbeef)
    assert m.invoke(0x8005ffe8, [RESULT, INPUT, 0, 0x100]) == 0xffffd75a
    assert get32(m, RESULT) == 0
    passed('failed_open_clears_handle_and_propagates_status')

    for fn, driver, name in ((0x80060620, 0x80060818, 'read'),
                              (0x800622b0, 0x800624a8, 'write')):
        for status, actual in ((0, 512), (0, 31), (0xffffd825, 0)):
            m = filesystem_machine()
            calls = []
            def operation(a):
                calls.append(a[:4])
                put32(m, a[3], actual)
                return status
            m.hooks[driver] = operation
            assert m.invoke(fn, [HANDLE, BUFFER, 512, RESULT]) == status
            assert calls == [[HANDLE, BUFFER, 512, RESULT]]
            assert get32(m, RESULT) == actual
            passed(f'{name}_status_{status:#x}_actual_{actual}', result=status, transferred=actual)

    for mode, fn, driver in ((1, 0x80060620, 0x80060818), (0, 0x800622b0, 0x800624a8)):
        m = filesystem_machine(mode)
        calls = []
        m.hooks[driver] = lambda a: calls.append(a) or 0
        result = m.invoke(fn, [HANDLE, BUFFER, 512, RESULT])
        assert result != 0 and not calls
        passed(f'access_mode_{mode}_rejects_{fn:#x}', result=result)

    # Original driver at EOF, including its real request-initialization helper.
    m = filesystem_machine()
    put32(m, HANDLE + 0x21c, 4096)
    put32(m, HANDLE + 0x22c, 4096)
    put32(m, RESULT, 0xdeadbeef)
    result = m.invoke(0x80060818, [HANDLE, BUFFER, 512, RESULT])
    assert result == 0xffffd759 and get32(m, RESULT) == 0
    passed('stock_read_driver_at_eof', result_hex=hex(result), signed_status=result - 2**32,
           transferred=get32(m, RESULT), hardware_intercepted=False)

    for status in (0, 0xffffd825):
        m = filesystem_machine()
        seen = []
        m.hooks[0x8005c388] = lambda a: seen.append(a[0]) or status
        assert m.invoke(0x8005c1f8, [HANDLE]) == status and seen == [HANDLE]
        passed(f'close_wrapper_propagates_{status:#x}')

    # Follow creation flags into the real driver and create helper. Only directory
    # lookup, temporary handle allocation/free are intercepted. Existing target
    # must fail before the directory creation/truncation routine is reached.
    for flags, expected_allow in ((0x101, 1), (0x501, 0)):
        m = filesystem_machine()
        temp = HANDLE + 0x400
        putstr(m, INPUT, 'A:\\SOUND_PAD\\PAD1\\OD_TEST.WAV')
        m.hooks[0x80067150] = lambda a: temp
        m.hooks[0x8006e168] = lambda a: 0
        seen = []
        def create(a):
            seen.append(a[:6])
            return 0xffffd75b
        m.hooks[0x80067ef8] = create
        assert m.invoke(0x800604e8, [HANDLE, INPUT, flags, 0x80]) == 0xffffd75b
        assert seen[0][1] == expected_allow
        passed(f'creation_flag_{flags:#x}', existing_target_allowed=bool(expected_allow), helper_args=seen[0])
    m = filesystem_machine()
    putstr(m, INPUT, 'A:\\SOUND_PAD\\PAD1\\OD_TEST.WAV')
    def existing(a):
        put32(m, a[2], BUFFER)
        return 0
    m.hooks[0x800676a0] = existing
    forbidden = []
    m.hooks[0x8006bd30] = lambda a: forbidden.append(a) or 1
    result = m.invoke(0x80067ef8, [HANDLE, 0, 0x20, INPUT, RESULT, 0])
    assert result == 0xffffd75b and not forbidden
    passed('exclusive_create_existing_target_rejected_before_modification', result_hex=hex(result))

    # Verify public path/name builders independently, including split filenames.
    m = Machine()
    directory = 'A:\\RECORDER\\261002_181142'
    putstr(m, 0x8060ff80, directory)
    paths = []
    for part in (1, 2, 3):
        address = m.invoke(0x80022c80, [10, part])
        paths.append(getstr(m, address))
    assert paths[0] == directory + '\\MASTER.WAV'
    assert len(set(paths)) == 3 and all(x.startswith(directory + '\\MASTER') for x in paths)
    passed('master_paths_and_segment_names', paths=paths, shared_buffer=hex(address))
    m.invoke(0x80022c80, [0, 1])
    assert getstr(m, address) != paths[-1]
    passed('master_path_buffer_is_overwritten_by_next_path_request')

    # Execute real stream-shutdown control flow. External audio/RTOS work,
    # file I/O and post-processing are replaced with tracing stubs.
    disassembler = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    callees = {int(ins.op_str[1:], 16) for ins in disassembler.disasm(
        IMAGE[0x8000b698 - BIAS:0x8000b9b4 - BIAS], 0x8000b698) if ins.mnemonic == 'bl'}
    for enabled, post_enabled, close_status in ((1, 1, 0), (1, 1, 0xffffd825), (1, 0, 0), (0, 1, 0)):
        m = Machine()
        events = []
        state = 0x801f8c48
        m.uc.mem_write(state + 0x2c, bytes([enabled]))
        m.uc.mem_write(state + 8, bytes([2, 0, 1, post_enabled, 0]))
        for fn in callees:
            m.hooks[fn] = lambda a: 0
        for fn in (0x80037dc0, 0x80037d68, 0x80002360, 0x80037df0):
            m.hooks[fn] = lambda a: 1
        m.hooks[0x80037e98] = lambda a: 0x1000 + a[0]
        m.hooks[0x80037e58] = lambda a: 8192
        def finalize(a):
            events.append(['finalize', a[0] - 0x1000])
            return 0
        def close(a):
            events.append(['close', a[0] - 0x1000])
            return close_status if a[0] == 0x100a else 0
        m.hooks[0x8000ea08] = finalize
        m.hooks[0x8005c1f8] = close
        m.hooks[0x800032b0] = lambda a: events.append(['postprocess', a[0]]) or 0
        m.invoke(0x8000b698, [0xffffffff])
        expected = [[action, stream] for stream in range(12) for action in ('finalize', 'close')] if enabled else []
        if enabled and post_enabled:
            expected.append(['postprocess', 0xffffffff])
        assert events == expected, events
        passed(f'stop_enabled_{enabled}_post_{post_enabled}_master_close_{close_status:#x}',
               events=events, note='Stock ordering only; close errors do not prevent the observed post-processing call.')

    startup_start, startup_end = struct.unpack_from('<II', IMAGE, 0x8000198c - BIAS)
    startup = []
    helpers = {0x80001994: 'decompress', 0x80079498: 'copy', 0x800794a8: 'zero'}
    for address in range(startup_start, startup_end, 16):
        source, destination, length, helper = struct.unpack_from('<IIII', IMAGE, address - BIAS)
        assert helper in helpers
        startup.append({'entry': hex(address), 'source': hex(source), 'destination': hex(destination),
                        'length': hex(length), 'end_exclusive': hex(destination + length),
                        'operation': helpers[helper]})
    assert len(startup) == 8
    passed('startup_initialization_table', entries=startup,
           note='Parsed from the startup loop; does not establish a free executable code region.')

    # Trace the initial read of each named factory checksum range. Capture the
    # original loop's remaining-length register without running the byte sum.
    class Captured(Exception):
        pass
    regions = []
    for selector, label in ((1, 'BOOT'), (0, 'MAIN'), (2, 'PANEL'), (3, 'AUDIOGUIDE')):
        m = Machine()
        def capture(a):
            regions.append({'name': label, 'offset': a[0], 'length': m.uc.reg_read(UC_ARM_REG_R10),
                            'first_read_bytes': a[2]})
            raise Captured()
        m.hooks[0x8001aee8] = capture
        try:
            m.invoke(0x80023ac8, [selector])
        except Captured:
            pass
        else:
            raise AssertionError('Did not reach flash read')
    assert [(r['offset'], r['length']) for r in regions] == [
        (0, 0x65000), (0x65000, 0x285000), (0x2ea000, 0x10000), (0x2fa000, 0x100000)]
    passed('stock_factory_checksum_region_selection', regions=regions)

    m = Machine()
    spi = []
    m.hooks[0x800760a8] = lambda a: 0
    def transfer(a):
        spi.append({'tx': bytes(m.uc.mem_read(a[0], a[2])).hex() if a[0] else None,
                    'rx': a[1], 'length': a[2], 'bits': a[3], 'keep_selected': a[4]})
        return 0
    m.hooks[0x80032e60] = transfer
    assert m.invoke(0x8001aee8, [0x65000, BUFFER, 16]) == 0
    assert spi[0]['tx'] == '0b06500000' and spi[1]['rx'] == BUFFER and spi[1]['length'] == 16
    passed('flash_read_sends_command_and_address', spi=spi)
    spi.clear()
    assert m.invoke(0x8001aee8, [0x400000, BUFFER, 1]) == 0xffffffff and not spi
    passed('flash_read_rejects_access_beyond_4MiB')

    report = {'firmware': 'stock 1.10', 'passed_cases': len(results), 'results': results,
              'limitations': ['Synthetic RAM, mocked filesystem driver/RTOS/SPI effects except where stated.',
                              'Not a complete file-copy, SD durability, audio or bootloader emulation.',
                              'No modified firmware, device commands, hardware dump or recovery test.',
                              'Flash map is derived from the application, not measured from a physical chip.']}
    target = ROOT / 'analysis/firmware_workflow_verification.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed_cases': len(results), 'master_paths': paths, 'flash_regions': regions,
                      'report': str(target)}, indent=2))


if __name__ == '__main__':
    main()
