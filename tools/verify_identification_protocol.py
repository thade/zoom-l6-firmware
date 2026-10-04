#!/usr/bin/env python3
"""Check L6 service/version parsing offline using original firmware instructions.

Synthetic RAM only. RTOS event delivery, timers and MIDI output are intercepted.
Never opens MIDI/USB or calls any hardware interface. Does not execute service
actions such as entering test mode, resetting settings or storage tests.
"""
import json
from pathlib import Path
from verify_pad_protocol import Machine

ROOT = Path(__file__).resolve().parents[1]


def main():
    results = []

    def passed(name, **detail):
        results.append(dict(case=name, passed=True, **detail))

    # Verify parsing only: the queued event is intercepted before any action.
    m = Machine()
    packet = bytes.fromhex('f0 52 00 00 67 0b f7')
    assert m.parse(packet, state=1) == [[2, 2, 0x4d, 0, 0]]
    assert bytes(m.uc.mem_read(0x80629b60, 1)) == b'\x03'
    passed('service_mode_request_enqueues_event_only_in_emulator')

    for selector in range(5):
        m = Machine()
        m.hooks[0x800776d6] = lambda args: 0
        m.hooks[0x800776cc] = lambda args: 0
        packet = bytes([0xf0, 0x52, 0, 0, 0x10, selector, 0xf7])
        actual = m.parse(packet, state=3)
        assert actual == [[2, 2, 0x4e, 10, selector]], actual
        passed(f'version_query_selector_{selector}', event=actual[0])

    # Real getter, copying and reply construction, with synthetic version RAM.
    # These are firmware component strings, not processor identity registers.
    for selector, payload in enumerate([b'BOOT', b'VOIC', b'PANL']):
        m = Machine()
        m.uc.mem_write(0x2000f560 + 0x20 * selector, payload)
        m.hooks[0x80005e90] = lambda args: 1
        replies = []
        def capture(args):
            replies.append(bytes(m.uc.mem_read(args[0], args[1])))
            return 0
        m.hooks[0x80031648] = capture
        m.invoke(0x80006d00, [10, selector])
        expected = bytes([0xf0, 0x52, 0, 0, 0x11, selector]) + payload + b'\xf7'
        assert replies == [expected], replies
        passed(f'component_version_{selector}_uses_cached_string', reply_hex=expected.hex(' '))

    # A malformed/out-of-range selector gets zero bytes, not arbitrary memory.
    m = Machine()
    m.hooks[0x80005e90] = lambda args: 1
    replies = []
    m.hooks[0x80031648] = lambda a: replies.append(bytes(m.uc.mem_read(a[0], a[1])))
    m.invoke(0x80006d00, [10, 4])
    assert replies == [bytes.fromhex('f0 52 00 00 11 04 00 00 00 00 f7')]
    passed('out_of_range_version_selector_does_not_read_arbitrary_address')

    # Decode the other service commands without executing their queued actions.
    mapping = {0:(0, 2), 2:(1, 5), 4:(2, 0), 8:(3, 0), 13:(5, 2),
               17:(6, 0), 19:(8, 0), 21:(9, 0)}
    for sub in range(22):
        packet = bytes([0xf0, 0x52, 0, 0, 0x67, 0x0f, sub, 2, 1, 0xf7])
        actual = Machine().parse(packet, state=3)
        expected = [[2, 2, 0x4e, *mapping[sub]]] if sub in mapping else []
        assert actual == expected, (sub, actual, expected)
        passed(f'service_subcommand_{sub}_dispatch_only', events=actual)

    report = dict(
        source='Stock L6 v1.10; original Thumb instructions',
        limitations=['Synthetic version strings and session state',
                     'Timers, MIDI output and RTOS event delivery intercepted',
                     'No live chip ID, USB readback, service action or recovery tested'],
        count=len(results), results=results)
    path = ROOT / 'analysis/identification_protocol_verification.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(f'{len(results)} offline checks passed; {path}')


if __name__ == '__main__':
    main()
