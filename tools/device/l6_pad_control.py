#!/usr/bin/env python3
"""Restricted adapter for catalogue queries and existing-file assignments.

Uses the already connected official editor session. No playback, recording,
file deletion, gain, firmware, or arbitrary-command interface.
"""
import ctypes as C
import time
from l6_pad_fixture_test import Session as FixtureSession, pack7
from decode_l6_sysex import decode
import l6_midi_probe as midi


class PadSession(FixtureSession):
    def __init__(self, path):
        try:
            super().__init__(path)
            # CoreMIDI connects input ports asynchronously.
            time.sleep(1)
        except Exception:
            if getattr(self, 'client', None) and self.client.value:
                midi.client_free(self.client)
            if getattr(self, 'log', None):
                self.log.close()
            raise

    def send(self, data):
        message = decode(data)
        if message.get('pad_index') not in range(4):
            raise ValueError('Invalid pad')
        allowed = {'request_file_count', 'request_listed_filename',
                   'request_assigned_filename', 'select_existing_file'}
        if message['interpretation'] not in allowed:
            raise ValueError('Command is outside the overdub workflow')
        if message['interpretation'] == 'select_existing_file':
            if not message['filename'].startswith('OD_') or not message['filename'].endswith('.WAV'):
                raise ValueError('Only workflow-owned filenames can be selected')
        storage = C.create_string_buffer(2048)
        raw = C.create_string_buffer(data)
        first = midi.packet_init(storage)
        if not midi.packet_add(storage, len(storage), first, 0, len(data), raw):
            raise RuntimeError('Cannot build MIDI packet')
        sent_at = time.time()
        midi.check(midi.send(self.output, self.destination, storage))
        self.write({'direction': 'workflow_to_device', 'timestamp': sent_at,
                    'hex': data.hex(' '), 'decoded': message})
        return sent_at

    def query(self, pad, sub, index=None):
        extra = [] if index is None else [index >> 7, index & 127]
        at = self.send(bytes([0xf0, 0x52, 0, 0, 0x46, sub, pad, *extra, 0xf7]))
        return self.wait(lambda d: d.get('command') == '0x45'
                         and d.get('subcommand') == sub and d.get('pad_index') == pad
                         and (index is None or d.get('file_index') == index), at)

    def catalogue(self, pad):
        count = self.query(pad, 0)['count']
        if not 0 <= count <= 1000:
            raise RuntimeError('Unexpected catalogue size')
        return [self.query(pad, 1, index) for index in range(count)]

    def assign(self, pad, index, name):
        payload = pack7(name.encode('utf-16le'))
        self.send(bytes([0xf0, 0x52, 0, 0, 0x31, 5, pad, index >> 7, index & 127,
                         len(payload) & 127, len(payload) >> 7]) + payload + b'\xf7')
        for _ in range(12):
            time.sleep(0.25)
            result = self.query(pad, 2)
            if result.get('filename') == name:
                return result
        raise RuntimeError(f'Pad {pad + 1} did not confirm {name}')
