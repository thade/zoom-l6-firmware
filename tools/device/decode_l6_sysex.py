#!/usr/bin/env python3
"""Decode a single captured L6 pad SysEx message offline. Never opens MIDI/USB.

Derived from stock v1.10 firmware instructions, verified in an isolated emulator;
not yet compared with a real editor/device capture. Input includes F0 and F7.
"""
import argparse
import json

def unpack7(payload):
    out = bytearray()
    for start in range(0, len(payload), 8):
        block = payload[start:start+8]
        if len(block) < 2:
            raise ValueError('An encoded group needs a prefix and at least one data byte')
        for n, value in enumerate(block[1:]):
            out.append(value | (((block[0] >> (6-n)) & 1) << 7))
    return bytes(out)

def decode(packet):
    if len(packet) < 6 or packet[0] != 0xf0 or packet[-1] != 0xf7:
        raise ValueError('Expected one complete F0 ... F7 message')
    if any(v > 127 for v in packet[1:-1]):
        raise ValueError('SysEx data bytes must be 7-bit')
    if packet[1] != 0x52:
        raise ValueError('Not the manufacturer byte used by this firmware')
    command = packet[4]
    result = {'hex': packet.hex(' '), 'command': hex(command), 'interpretation': 'unknown',
              'header_bytes_2_3': packet[2:4].hex(' ')}
    if len(packet) < 8:
        return result
    sub, pad = packet[5:7]
    result.update(subcommand=sub, pad_index=pad, pad_number=pad+1)
    names = {0:'file_count',1:'listed_filename',2:'assigned_filename',3:'pad_state'}
    if command == 0x46 and sub in names:
        expected = 10 if sub == 1 else 8
        if len(packet) != expected:
            raise ValueError(f'Expected {expected} bytes for this request')
        result['interpretation'] = 'request_'+names[sub]
        if sub == 1:
            result['file_index'] = (packet[7] << 7) | packet[8]
    elif command == 0x45 and sub == 0:
        if len(packet) != 10:
            raise ValueError('Expected 10 bytes for a file-count reply')
        result.update(interpretation='file_count_reply', count=(packet[7]<<7)|packet[8])
    elif (command == 0x45 and sub in (1,2)) or (command == 0x31 and sub == 5):
        if len(packet) < 12:
            raise ValueError('Filename message is too short')
        index = (packet[7]<<7)|packet[8]
        length = packet[9] | (packet[10]<<7)
        if len(packet) != length+12:
            raise ValueError('Encoded filename length does not match message length')
        raw = unpack7(packet[11:-1])
        if len(raw)%2:
            raise ValueError('Decoded filename has an odd UTF-16 byte count')
        name = raw.decode('utf-16le').rstrip('\0')
        result.update(file_index=index, encoded_length=length, filename=name)
        if command == 0x31:
            result['interpretation'] = 'clear_assignment' if length == 0 else 'select_existing_file'
        else:
            result['interpretation'] = names[sub]+'_reply'
            if sub == 2 and index == 0x3fff and length == 0:
                result['interpretation'] = 'no_file_assigned_reply'
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hex', required=True, help='Space-separated hexadecimal bytes including F0 and F7')
    args = p.parse_args()
    try:
        result = decode(bytes.fromhex(args.hex))
    except (ValueError, UnicodeError) as e:
        p.error(str(e))
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
