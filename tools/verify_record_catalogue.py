#!/usr/bin/env python3
"""Offline checks of stock L6 catalogue insertion and post-record assignment.

Executes original firmware instructions. No device access or patched image.
Synthetic RAM catalogues; RTOS, notifications, persistence and audio assignment
are intercepted. This does not emulate storage, audio or an entire recording.
"""
import json
import struct
from verify_pad_protocol import Machine, ROOT, INPUT

BASE = 0x8023e398
STRIDE = 0x80950


def putstr(m, address, value):
    m.uc.mem_write(address, (value + '\0').encode('utf-16le'))


def getstr(m, address):
    raw = bytes(m.uc.mem_read(address, 0x20a))
    end = next(i for i in range(0, len(raw), 2) if raw[i:i+2] == b'\0\0')
    return raw[:end].decode('utf-16le')


def main():
    results = []
    for pad in range(4):
        m = Machine()
        base = BASE + pad * STRIDE
        # Original clear/initialize routines, followed by a synthetic directory.
        for fn in (0x8002a2e0, 0x8002a428, 0x8002a2c8):
            m.invoke(fn, [base])
        directory = f'A:\\SOUND_PAD\\PAD{pad+1}'
        putstr(m, base+0x14, directory)
        notifications = []
        m.hooks[0x80008f00] = lambda a: notifications.append('catalogue_changed')
        for i, name in enumerate(('PASS_001.WAV', 'PASS_002.WAV')):
            putstr(m, INPUT, name)
            assert m.invoke(0x80008dd8, [pad, INPUT, 1]) == 0
            assert m.invoke(0x80008ee8, [pad]) == i+1
            index = m.invoke(0x80008ec0, [pad, INPUT])
            assert index == i
            ptr = m.invoke(0x80008e88, [pad, index])
            assert getstr(m, ptr) == directory+'\\'+name
        assert len(notifications) == 2

        assignments, persistence = [], []
        def assigned(args):
            assignments.append({'path': getstr(m, args[0]), 'pad': args[1],
                                'index': args[2], 'count': args[3], 'option': args[4]})
            return 0
        m.hooks.update({
            0x80076950: lambda a: 0,  # RTOS lock
            0x800763d8: lambda a: 0,  # RTOS unlock
            0x8004b760: assigned,    # audio/file validation and assignment
            0x8000ac90: lambda a: 0, # permit observed persistence branch
            0x80006b18: lambda a: persistence.append('save'),
        })
        putstr(m, INPUT, directory+'\\PASS_002.WAV')
        m.invoke(0x80008bd0, [pad, INPUT])
        assert assignments == [{'path': directory+'\\PASS_002.WAV', 'pad': pad,
                                'index': 1, 'count': 2, 'option': 0}]
        assert persistence == ['save']
        assert bytes(m.uc.mem_read(0x807348cc, 4)) == bytes(4)
        results.append({'case': f'insert_then_assign_pad_{pad+1}', 'passed': True,
                        'assignment': assignments[0]})

        putstr(m, INPUT, 'A:\\RECORDER\\SONG\\MISSING.WAV')
        m.invoke(0x80008bd0, [pad, INPUT])
        assert len(assignments) == 1
        results.append({'case': f'uncatalogued_name_not_assigned_pad_{pad+1}', 'passed': True})

        # This helper strips the incoming path and resolves only its basename.
        # A recorder pathname with an existing basename still selects the PAD file.
        putstr(m, INPUT, 'A:\\RECORDER\\SONG\\PASS_002.WAV')
        m.invoke(0x80008bd0, [pad, INPUT])
        assert assignments[-1]['path'] == directory+'\\PASS_002.WAV'
        assert len(assignments) == 2
        results.append({'case': f'recorder_path_resolves_to_pad_directory_{pad+1}', 'passed': True})

    # Confirm which logical recording stream produces the MASTER basename.
    m = Machine()
    m.uc.mem_write(INPUT, bytes(0x20a))
    m.invoke(0x80023258, [10, 1, INPUT])
    basename = getstr(m, INPUT)
    assert basename.startswith('MASTER'), basename
    results.append({'case': 'logical_stream_10_master_name', 'passed': True, 'name': basename})

    report = {
        'method': 'Unmodified stock Thumb instructions; synthetic RAM; intercepted external effects',
        'passed_cases': len(results), 'results': results,
        'limitations': [
            'No USB, MIDI, SD-card or firmware changes.',
            'Catalogue insertion is real code; its notification callback is intercepted.',
            'Post-record helper uses real catalogue lookup and path construction.',
            'Actual audio assignment, locks and settings persistence are intercepted.',
            'No full recording, filesystem rename/copy, reboot or timing verification.'
        ]}
    target = ROOT/'analysis/record_catalogue_verification.json'
    target.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'passed_cases': len(results), 'master_basename': basename, 'report': str(target)}))


if __name__ == '__main__':
    main()
