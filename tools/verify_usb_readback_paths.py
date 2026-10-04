#!/usr/bin/env python3
"""Offline checks of stock L6 USB dispatch; never opens a USB/MIDI device.

Runs original Thumb instructions with synthetic USB setup packets and class
registration. Hardware setup retrieval, USB transfer and endpoint stall are
intercepted. SCSI checks select handlers; they never execute read/write commands.
"""
import hashlib
import json
import struct
from verify_pad_protocol import Machine, INPUT, IMAGE, ROOT


def main():
    results = []
    m = Machine()
    setup = bytes(8)
    stalls, transfers = [], []

    def get_setup(args):
        m.uc.mem_write(args[0], setup)
        return 0

    def stall(args):
        stalls.append(args[:2])
        return 0

    def transfer(args):
        transfers.append(bytes(m.uc.mem_read(args[1], args[2])).hex())
        return 0

    def unexpected_flash_read(args):
        raise AssertionError('A USB case unexpectedly reached the flash reader')

    m.hooks.update({0x80042730: get_setup, 0x80044868: stall,
                    0x80072930: transfer, 0x8001aee8: unexpected_flash_read})
    # Synthetic registrations exercise each real class callback through the real
    # setup dispatcher and recipient resolver, independent of current USB mode.
    m.uc.mem_write(0x808e07d8, bytes(7 * 4))
    m.uc.mem_write(0x80214b6c, bytes(32 * 4))
    classes = {'midi': 0x800a1f50, 'audio': 0x800a0768,
               'auxiliary': 0x800a0774, 'mass_storage': 0x800a0c14}
    for name, table in classes.items():
        m.uc.mem_write(0x80213dbc, struct.pack('<I', table))
        count = 0
        for recipient in (0, 1, 2):
            for direction in (0, 0x80):
                for value, length in ((0, 0), (0xffff, 64)):
                    for request in range(256):
                        setup = struct.pack('<BBHHH', 0x40 | direction | recipient,
                                            request, value, 0, length)
                        stalls.clear()
                        transfers.clear()
                        m.invoke(0x80041008, [])
                        assert len(stalls) == 1 and stalls[0][1] == 1, (name, setup.hex(), stalls)
                        assert transfers == [], (name, setup.hex(), transfers)
                        count += 1
        results.append({'case': 'vendor_requests_' + name, 'passed': True,
                        'synthetic_setup_cases': count, 'outcome': 'endpoint_stall'})

    # Positive control: prove the synthetic routing can reach and successfully
    # execute a supported class request, rather than rejecting every packet.
    m.uc.mem_write(0x8023d120 + 0x57, b'\x01')
    setup = struct.pack('<BBHHH', 0xa1, 0xfe, 0, 0, 1)
    stalls.clear()
    transfers.clear()
    assert m.invoke(0x80041008, []) == 0
    assert stalls == [] and transfers == ['00'], (stalls, transfers)
    results.append({'case': 'mass_storage_get_max_lun_positive_control', 'passed': True})

    expected = {0x00: 0x80064ca9, 0x03: 0x80064ae9, 0x04: 0x80064011,
                0x08: 0x80064851, 0x0a: 0x800650e1, 0x12: 0x80064091,
                0x1a: 0x80064639, 0x1b: 0x80064c21, 0x1d: 0x80064b89,
                0x1e: 0x80064751, 0x25: 0x80064899, 0x28: 0x800647e1,
                0x2a: 0x80065071, 0x2f: 0x80064d19, 0x5a: 0x80064561,
                0xa0: 0x80064ad1, 0xa8: 0x80064819, 0xaa: 0x800650a9,
                0xaf: 0x80064d71}
    for opcode in range(256):
        cbw = bytearray(31)
        cbw[14], cbw[15] = 16, opcode
        m.uc.mem_write(INPUT, bytes(cbw))
        actual = m.invoke(0x80065650, [INPUT])
        assert actual == expected.get(opcode, 0x80064d01), (hex(opcode), hex(actual))
    results.append({'case': 'all_scsi_opcode_selections', 'passed': True,
                    'synthetic_cdb_cases': 256,
                    'accepted_handlers': {f'{k:02x}': f'{v:08x}' for k, v in expected.items()},
                    'read_buffer_3c': 'unsupported', 'vendor_c0_ff': 'unsupported'})

    m.uc.mem_write(INPUT, bytes(0x80))
    m.uc.mem_write(INPUT + 0x50, struct.pack('<I', INPUT + 0x100))
    m.uc.mem_write(INPUT + 0x100, bytes(0x40))
    assert m.invoke(0x80064d00, [INPUT]) == 0
    assert bytes(m.uc.mem_read(INPUT + 0x2c, 1)) == b'\x01'
    assert bytes(m.uc.mem_read(INPUT + 0x110, 3)) == b'\x00\x20\x05'
    results.append({'case': 'unsupported_scsi_sets_error_state', 'passed': True,
                    'internal_sense_bytes_at_10': '00 20 05'})

    report = {'firmware_sha256': hashlib.sha256(IMAGE).hexdigest(),
              'scope': 'Offline original-code dispatch checks with synthetic state; no hardware I/O',
              'limitations': 'Does not test bootloader/ROM modes or prove absence of alternate/indirect paths.',
              'results': results}
    output = ROOT / 'analysis/usb_readback_verification.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'{len(results)} check groups passed; report: {output}')


if __name__ == '__main__':
    main()
