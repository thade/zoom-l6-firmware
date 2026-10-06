#!/usr/bin/env python3
"""Execute the added detour, compare USB output and audit candidate references.

Read-only device scope. Raw decoding intentionally over-includes non-code;
absence of references is not proof against all indirect uses.
"""
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_REG_PC
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_CPSR)

from verify_pad_protocol import Machine, IMAGE, ROOT, RETURN, STACK, REGS
from verify_code_probe import run, PROFILES
sys.path.insert(0, str(ROOT/'tools/firmware'))
from build_deployment_probe import digest, validate
from build_added_code_probe import OUT, BIAS, HOOK, ENTRY, RESUME, PAD_START, PAD_END, candidate

REGISTERS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
             UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
             UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
             UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_CPSR]


def initialized_regions():
    m = Machine()
    m.uc.mem_map(0x81000000, 0x1000000)
    regions = []
    for table in range(0x800a68dc, 0x800a695c, 16):
        source, dest, length, helper = struct.unpack_from('<4I', IMAGE, table-BIAS)
        if helper == 0x80001994:
            # Large repeated-data expansion needs a higher instruction budget.
            for reg, value in zip(REGS, [source, dest, length]):
                m.uc.reg_write(reg, value)
            m.uc.reg_write(UC_ARM_REG_SP, STACK)
            m.uc.reg_write(UC_ARM_REG_LR, RETURN | 1)
            m.reached_return = False
            m.uc.emu_start(helper | 1, RETURN+2, count=5000000)
            assert m.reached_return
            regions.append((dest, bytes(m.uc.mem_read(dest, length))))
        elif helper == 0x80079498:
            regions.append((dest, IMAGE[source-BIAS:source-BIAS+length]))
    return regions


def reference_audit():
    initialized = initialized_regions()
    main = (0x80001000, IMAGE[0x200:0xb5ce4])
    ram_code = next(r for r in initialized if r[0] == 0x20220000)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    md.detail = True
    hits, rejected_literal_example = [], []
    split_hits = []
    gap_hits = []
    nearby = set()
    decoded = 0
    for base, data in (main, ram_code):
        # Decode at every halfword so a mixed data block cannot hide subsequent
        # code merely by confusing one linear instruction stream.
        for offset in range(0, len(data)-1, 2):
            ins = next(md.disasm(data[offset:offset+4], base+offset, count=1), None)
            if ins is None:
                continue
            decoded += 1
            for op in ins.operands:
                if op.type == ARM_OP_IMM and PAD_START <= (op.imm & 0xffffffff) < PAD_END:
                    hits.append([hex(ins.address), ins.mnemonic, ins.op_str, 'immediate'])
                if op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC:
                    address = ((ins.address+4) & ~3) + op.mem.disp
                    # Conservative 16-byte span includes scalar/double loads.
                    if address < PAD_END and address+16 > PAD_START:
                        hits.append([hex(ins.address), ins.mnemonic, ins.op_str, 'PC memory'])
                    if address == 0x800530c0:
                        rejected_literal_example.append([hex(ins.address), ins.mnemonic, ins.op_str])
                if ins.mnemonic == 'adr' and op.type == ARM_OP_IMM:
                    address = ((ins.address+4) & ~3) + op.imm
                    if PAD_START <= address < PAD_END:
                        hits.append([hex(ins.address), ins.mnemonic, ins.op_str, 'ADR'])
            if ins.mnemonic != 'movw':
                continue
            reg, low = ins.operands[0].reg, ins.operands[1].imm
            # A bounded construction search, not a control-flow/value proof.
            # Retain pairs even across clobbers to avoid overstating filtering.
            for following in md.disasm(data[offset+ins.size:offset+ins.size+32], ins.address+ins.size):
                if following.mnemonic == 'movt' and following.operands[0].reg == reg:
                    address = (following.operands[1].imm << 16) | low
                    row = [hex(ins.address), hex(following.address), hex(address)]
                    if PAD_START <= address < PAD_END:
                        split_hits.append(row)
                    if 0x80960078 <= address < 0x80bb9400:
                        gap_hits.append(row)
                    if 0x8095ffd8 <= address < 0x80960100:
                        nearby.add(address)
                    break
    raw_hits = []
    # Include expanded initialized data, where pointer tables can be compressed
    # in the update image. Search at every byte offset, not just aligned words.
    for base, data in [main]+initialized:
        for pointer in range(PAD_START, PAD_END):
            offset = 0
            while True:
                found = data.find(struct.pack('<I', pointer), offset)
                if found < 0:
                    break
                raw_hits.append([hex(base+found), hex(pointer)])
                offset = found+1
    assert not hits and not split_hits and not raw_hits, (hits, split_hits, raw_hits)
    assert any(row[0] == '0x800530ac' for row in rejected_literal_example)
    return dict(halfword_decodes=decoded, direct_or_pc_references=hits,
                bounded_movw_movt_references=split_hits, raw_initialized_pointer_references=raw_hits,
                rejected_zero_region=dict(address='0x800530c0', references=rejected_literal_example),
                buffer_gap_bounded_constructions=gap_hits,
                nearby_constructed_addresses=[hex(a) for a in sorted(nearby)],
                limitations=['Not a whole-program reachability or computed-pointer proof',
                             'MOVW/MOVT search bounded to 32 bytes; pairs can include false positives',
                             'Firmware/bootloader runtime-created pointers and DMA not exhaustively covered'])


def observer(trace):
    def install(m):
        def code(uc, address, size, data):
            trace.append((address, [uc.reg_read(r) for r in REGISTERS]))
        for address in (HOOK, ENTRY, ENTRY+2, ENTRY+4, RESUME):
            m.uc.hook_add(UC_HOOK_CODE, code, begin=address, end=address)
        def read(uc, access, address, size, value, data):
            assert not (address < PAD_END and address+size > PAD_START), 'Candidate used as data'
        m.uc.hook_add(UC_HOOK_MEM_READ, read)
    return install


def flag_cases(trial):
    # Check the local detour contract independently of USB configuration.
    for flags in range(16):
        m = Machine()
        m.uc.mem_write(0x80001000, trial[0x200:0xb5ce4])
        profile = 0x20022000
        value = 0x12345678 ^ flags
        m.uc.mem_write(profile+28, struct.pack('<I', value))
        for index, reg in enumerate(REGISTERS[:-1]):
            m.uc.reg_write(reg, 0x10203040+index*4)
        m.uc.reg_write(UC_ARM_REG_R5, profile)
        m.uc.reg_write(UC_ARM_REG_SP, STACK)
        # emu_start(address|1) selects Thumb. Seed that same mode before taking
        # the snapshot so the harness's mode selection is not counted as a
        # firmware side effect.
        m.uc.reg_write(UC_ARM_REG_CPSR, (m.uc.reg_read(UC_ARM_REG_CPSR) & 0x0fffffff) | (flags << 28) | 0x20)
        before = [m.uc.reg_read(r) for r in REGISTERS]
        stopped = []
        writes = []
        m.uc.hook_add(UC_HOOK_MEM_WRITE,
                     lambda uc, access, address, size, value, data: writes.append((address, size, value)))
        def stop(uc, address, size, data):
            stopped.append(address)
            uc.emu_stop()
        m.uc.hook_add(UC_HOOK_CODE, stop, begin=RESUME, end=RESUME)
        m.uc.emu_start(HOOK | 1, RESUME+2, count=20)
        after = [m.uc.reg_read(r) for r in REGISTERS]
        assert stopped == [RESUME]
        assert after[0] == value and after[1:] == before[1:], (flags, [(i, hex(a), hex(b)) for i, (a, b) in enumerate(zip(before, after)) if a != b])
        assert writes == [(STACK+0x30, 4, value)]
        assert bytes(m.uc.mem_read(STACK+0x30, 4)) == struct.pack('<I', value)
    return 16


def main():
    trial = (OUT/'trial_added_code_ZOOM_L6/L6.BIN').read_bytes()
    assert trial == candidate(IMAGE)
    validate(trial)
    audit = reference_audit()
    rows = []
    for profile in PROFILES:
        for power in (0, 1):
            stock_trace, trial_trace = [], []
            original, a = run(IMAGE, profile, power, observer(stock_trace))
            changed, b = run(trial, profile, power, observer(trial_trace))
            assert [t[0] for t in stock_trace] == [HOOK, RESUME]
            assert [t[0] for t in trial_trace] == [HOOK, ENTRY, ENTRY+2, ENTRY+4, RESUME]
            assert stock_trace[-1][1][1:] == trial_trace[-1][1][1:]
            assert a['product'] == 'L6' and b['product'] == 'ZOOM L6'
            assert original[:0x18] == changed[:0x18] and original[0x1c:] == changed[0x1c:]
            rows.append(dict(stock=a, trial=b, exact_detour_path=True,
                             other_registers_flags_and_configuration_unchanged=True))
    cases = flag_cases(trial)
    report = dict(passed=True, stock_sha256=digest(IMAGE), trial_sha256=digest(trial),
                  placement_audit=audit, paired_usb_cases=len(rows), flag_cases=cases, results=rows,
                  limits=['Synthetic USB profiles and power flags; no full boot or physical USB',
                          'MPU/cache and real scheduling not simulated',
                          'Static reference audit cannot exclude every indirect use',
                          'Not staged or installed; no hardware result for this trial'])
    (OUT/'offline_verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, paired_usb_cases=len(rows), flag_cases=cases,
                          candidate_references=0, buffer_gap_constructions=audit['buffer_gap_bounded_constructions'])))


if __name__ == '__main__':
    main()
