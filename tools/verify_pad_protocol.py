#!/usr/bin/env python3
"""Run selected original L6 v1.10 instructions in an isolated ARM emulator.

No USB/MIDI access, app modification, firmware patching or flash output. External
event delivery, filesystem lookups and audio validation are intercepted. This
verifies parser/encoding behavior, not hardware operation or recovery.
Requires capstone==5.0.9 and unicorn==2.1.4 in the analysis environment.
"""
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[1]
BIAS = 0x80000e00
IMAGE = (ROOT/'Reference/L6_v1.10_E/L6.BIN').read_bytes()
assert hashlib.sha256(IMAGE).hexdigest() == '64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
REGS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
INPUT = 0x20020000
RETURN = 0x20000000
STACK = 0x20010000

def pack7(raw):
    out = bytearray()
    for i in range(0, len(raw), 7):
        chunk = raw[i:i+7]
        out.append(sum(((v >> 7) & 1) << (6-j) for j,v in enumerate(chunk)))
        out.extend(v & 127 for v in chunk)
    return bytes(out)

def request(subcommand, pad, index=None):
    data = [0xf0, 0x52, 0, 0, 0x46, subcommand, pad]
    if index is not None:
        data += [index >> 7, index & 127]
    return bytes(data + [0xf7])

def assignment(pad, index, name):
    data = pack7(name.encode('utf-16le'))
    return bytes([0xf0, 0x52, 0, 0, 0x31, 5, pad, index >> 7, index & 127,
                  len(data) & 127, len(data) >> 7]) + data + b'\xf7'

class Machine:
    def __init__(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        self.uc.mem_map(0x80000000, 0x1000000)
        self.uc.mem_map(0x20000000, 0x40000)
        self.uc.mem_write(0x80001000, IMAGE[0x200:0xb5ce4])
        self.calls = []
        self.hooks = {}
        self.reached_return = False
        self.uc.hook_add(UC_HOOK_CODE, self._hook)

    def _hook(self, uc, address, size, _):
        if address == RETURN:
            self.reached_return = True
            uc.emu_stop()
        elif address in self.hooks:
            args = [uc.reg_read(r) for r in REGS]
            sp = uc.reg_read(UC_ARM_REG_SP)
            args += list(struct.unpack('<II', uc.mem_read(sp, 8)))
            result = self.hooks[address](args)
            if result is not None:
                uc.reg_write(UC_ARM_REG_R0, result)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def invoke(self, address, args):
        self.uc.reg_write(UC_ARM_REG_SP, STACK)
        self.uc.reg_write(UC_ARM_REG_LR, RETURN | 1)
        for reg, value in zip(REGS, args):
            self.uc.reg_write(reg, value)
        for i,value in enumerate(args[4:]):
            self.uc.mem_write(STACK+4*i, struct.pack('<I', value))
        self.reached_return = False
        self.uc.emu_start(address | 1, RETURN+2, count=100000)
        assert self.reached_return, 'Function did not return within the instruction limit'
        return self.uc.reg_read(UC_ARM_REG_R0)

    def parse(self, packet, state=2):
        self.uc.mem_write(INPUT, struct.pack('<I', len(packet))+packet)
        self.uc.mem_write(0x80629b60, bytes([state]))
        self.hooks[0x80020ca0] = lambda args: self.calls.append(args[:5])
        self.invoke(0x800301f0, [INPUT])
        return self.calls

def main():
    results = []
    def record(name, **data):
        results.append({'case': name, 'passed': True, **data})

    for sub, base in [(0, 0x38), (1, 0x3c), (2, 0x40), (3, 0x44)]:
        for pad in range(4):
            packet = request(sub, pad, 130 if sub == 1 else None)
            actual = Machine().parse(packet)
            assert actual == [[2, 2, base+pad, 130 if sub == 1 else 0, 0]], actual
            record(f'request_{sub}_pad_{pad}', packet_hex=packet.hex(' '), queued_event=actual[0])
    assert Machine().parse(request(0,4)) == []
    record('out_of_range_pad_rejected')
    assert Machine().parse(request(2,0), state=0) == []
    record('filename_query_rejected_in_initial_session_state')

    # Execute the stock encoder independently against our inferred 7-bit packing.
    raw_cases = [bytes(range(n)) for n in range(33)] + [bytes(range(256)), 'Café_日本.WAV'.encode('utf-16le')]
    for raw in raw_cases:
        m = Machine()
        m.uc.mem_write(INPUT, raw + bytes(16))
        length = m.invoke(0x8006e658, [INPUT, len(raw)])
        actual = bytes(m.uc.mem_read(0x8062990e, length))
        assert actual == pack7(raw), (raw.hex(), actual.hex(), pack7(raw).hex())
    record('stock_encoder_matches_packing', input_cases=len(raw_cases))

    for pad, index, name in [(0,0,'TAKE_A.WAV'), (3,130,'Café_日本.WAV')]:
        m = Machine()
        packet = assignment(pad,index,name)
        actual = m.parse(packet)
        assert actual == [[2,0,5+pad,index,len(pack7(name.encode('utf-16le')))]], actual
        decoded = bytes(m.uc.mem_read(0x80629474,len(name.encode('utf-16le'))+2))
        assert decoded == name.encode('utf-16le') + b'\0\0'
        record('assignment_decodes_'+name, packet_hex=packet.hex(' '), queued_event=actual[0], decoded_filename=name)

    # Run the real filename comparison and branch logic with a synthetic file list.
    # Mocked audio validation returns 0; this does NOT establish WAV compatibility.
    for name, should_assign in [('TAKE_A.WAV',True), ('TAKE_B.WAV',False), ('A:\\RECORDER\\TAKE_A.WAV',False)]:
        m = Machine()
        event = m.parse(assignment(0,0,name))[0]
        candidate = 0x20021000
        fullpath = 0x20022000
        m.uc.mem_write(candidate, 'TAKE_A.WAV\0'.encode('utf-16le'))
        m.uc.mem_write(fullpath, 'A:\\SOUND_PAD\\PAD1\\TAKE_A.WAV\0'.encode('utf-16le'))
        assigned = []
        m.hooks.update({
            0x80034da8: lambda args: 0xff,
            0x80008e00: lambda args: 0,
            0x80008e70: lambda args: candidate,
            0x80008ee8: lambda args: 1,
            0x80008e88: lambda args: fullpath,
            0x80009568: lambda args: 0,
            0x80002440: lambda args: 0,
            0x80008c68: lambda args: assigned.append(args),
        })
        m.invoke(0x80009ba0, [event[2]-5,event[3],event[4]])
        assert bool(assigned) == should_assign, (name, assigned)
        if assigned:
            assert assigned[0] == [0,fullpath,0,0,1,1], assigned
        record('synthetic_catalog_'+name, assignment_queued=bool(assigned), mocked_dependencies=True)

    # Capture replies by intercepting the outgoing queue, not by opening MIDI.
    for address, args, expected in [
        (0x80030990,[2,130],bytes.fromhex('f0 52 00 00 45 00 02 01 02 f7')),
        (0x80030778,[1,0,0,0],bytes.fromhex('f0 52 00 00 45 02 01 7f 7f 00 00 f7')),
    ]:
        m = Machine()
        sent = []
        m.hooks[0x80031648] = lambda a: sent.append(bytes(m.uc.mem_read(a[0],a[1])))
        m.invoke(address,args)
        assert sent == [expected], sent
        record('reply_'+hex(address), packet_hex=sent[0].hex(' '))

    report = {'method':'Original stock Thumb instructions in Unicorn; intercepted external effects; no hardware',
              'limitations':['Session state seeded for ordinary requests; connection handshake not verified on hardware.',
                             'Synthetic file catalog; filesystem/audio/RTOS behavior is not emulated.',
                             'Installed editor AOT method bodies have not been independently decoded.',
                             'No malformed-message fuzzing or device probing.'],
              'passed_cases':len(results),'results':results}
    (ROOT/'analysis/pad_protocol_verification.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'passed_cases':len(results),'report':'analysis/pad_protocol_verification.json'}))

if __name__ == '__main__':
    main()
