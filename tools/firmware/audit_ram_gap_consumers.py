#!/usr/bin/env python3
"""Bounded derived-address leads in stock initialized bytes; never a free-RAM proof.

Each candidate constant-producing instruction starts an independent straight-line
trace. Stop at control flow/IT, discard unknown register writes, and never read a
mutable global as a constant. Mixed code/data and unreachable starts remain leads.
"""
import hashlib
import json
import struct

from capstone import Cs, CsError, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS, CS_GRP_JUMP, CS_GRP_CALL, CS_GRP_RET
from capstone import arm as A
from build_deployment_probe import SOURCE, STOCK_SHA
from build_health_probe import ROOT, BIAS
from scatter_codec import expand

GAPS = ((0x80960078, 0x80bb9400), (0x81f26000, 0x82000000))
NEAR = tuple((a-0x100, b+0x100) for a, b in GAPS)
MAX_BYTES = 192
MAX_INSNS = 48
MASK = 0xffffffff
# Independently inspected stock ABIs: (destination register, length register,
# source register or None). The trace stops at the call after inspecting args.
COPY = {0x80001754: (A.ARM_REG_R0, A.ARM_REG_R2, A.ARM_REG_R1),
        0x80079498: (A.ARM_REG_R1, A.ARM_REG_R2, A.ARM_REG_R0)}
FILL = {0x8000177c: (A.ARM_REG_R0, A.ARM_REG_R1, None),
        0x8000178a: (A.ARM_REG_R0, A.ARM_REG_R1, None),
        0x8000178e: (A.ARM_REG_R0, A.ARM_REG_R2, None),
        0x800794a8: (A.ARM_REG_R1, A.ARM_REG_R2, None)}


def overlaps(start, size, intervals):
    return size > 0 and any(start < b and a < start+size for a, b in intervals)


def value(op, state):
    if op.type == A.ARM_OP_IMM:
        v = op.imm & MASK
    elif op.type == A.ARM_OP_REG:
        v = state.get(op.reg)
    else:
        return None
    if v is None:
        return None
    if op.shift.type == A.ARM_SFT_INVALID:
        return v
    if op.shift.type == A.ARM_SFT_LSL and op.shift.value < 32:
        return (v << op.shift.value) & MASK
    if op.shift.type == A.ARM_SFT_LSR and op.shift.value < 32:
        return v >> op.shift.value
    return None


def memory_width(ins):
    name = ins.mnemonic.split('.')[0]
    if name.startswith(('ldrb', 'strb', 'ldrsb')):
        return 1
    if name.startswith(('ldrh', 'strh', 'ldrsh')):
        return 2
    if name.startswith(('ldrd', 'strd')):
        return 8
    if name in ('vldr', 'vstr'):
        return 8 if ins.reg_name(ins.operands[0].reg).startswith('d') else 4
    if name in ('ldr', 'str', 'ldrex', 'strex'):
        return 4
    return None


def trace_window(md, data, base, offset, intervals=NEAR):
    state = {}; forms = []; accesses = []; bulk = []; unknown = 0; stop = 'decode_end_or_byte_bound'
    start = base+offset

    def span(ins, address, size, mode, kind='scalar'):
        if address is not None and size is not None and address+size <= 1 << 32 and overlaps(address, size, intervals):
            accesses.append(dict(at=ins.address, start=address, end=address+size,
                                 bytes=size, mode=mode, kind=kind))

    for n, ins in enumerate(md.disasm(data[offset:offset+MAX_BYTES], start)):
        if n >= MAX_INSNS:
            stop = 'instruction_bound'; break
        ops = ins.operands; name = ins.mnemonic.split('.')[0]
        if name == 'it' or name.startswith('it') and all(c in 'te' for c in name[1:]):
            stop = 'IT'; break
        if ins.cc not in (A.ARM_CC_AL, A.ARM_CC_INVALID):
            stop = 'conditional'; break
        if ins.group(CS_GRP_CALL):
            target = ops[0].imm & MASK if ops and ops[0].type == A.ARM_OP_IMM else None
            abi = COPY.get(target) or FILL.get(target)
            if abi:
                dst, length, src = abi; count = state.get(length)
                before = len(accesses)
                span(ins, state.get(dst), count, 'write', 'bulk')
                if src is not None:
                    span(ins, state.get(src), count, 'read', 'bulk')
                if len(accesses) != before:
                    bulk.append(dict(at=ins.address, helper=target, destination=state.get(dst),
                                     source=state.get(src), bytes=count))
            stop = 'call'; break
        if ins.group(CS_GRP_JUMP) or ins.group(CS_GRP_RET) or name in ('cbz', 'cbnz', 'tbb', 'tbh', 'svc', 'bkpt'):
            stop = 'control_flow'; break
        updates = {}
        # Inspect known effective addresses before killing load destinations.
        for op in ops:
            if op.type != A.ARM_OP_MEM:
                continue
            mem = op.mem; b = state.get(mem.base)
            if mem.base == A.ARM_REG_PC:
                b = (ins.address+4) & ~3
            ix = 0 if not mem.index else state.get(mem.index)
            if ix is not None and op.shift.type != A.ARM_SFT_INVALID:
                if op.shift.type == A.ARM_SFT_LSL and op.shift.value < 32:
                    ix = (ix << op.shift.value) & MASK
                else:
                    ix = None
            if op.subtracted and ix is not None:
                ix = -ix
            address = None if b is None or ix is None else (b+mem.disp+ix*mem.scale) & MASK
            width = memory_width(ins)
            span(ins, address, width, 'write' if name.startswith(('str', 'vstr', 'strex')) else 'read')
            if address is None:
                unknown += 1
            if name == 'ldr' and mem.base == A.ARM_REG_PC and width == 4 and address is not None and base <= address <= base+len(data)-4:
                updates[ops[0].reg] = struct.unpack_from('<I', data, address-base)[0]
            if ins.writeback and address is not None:
                # Post-index forms use the old base for the access; the trailing
                # displacement advances it afterward.
                advance = value(ops[-1], state) if ops[-1].type in (A.ARM_OP_IMM, A.ARM_OP_REG) else None
                updates[mem.base] = (address+advance) & MASK if advance is not None else address
        if name in ('ldm', 'stm', 'ldmia', 'stmia', 'ldmdb', 'stmdb') and ops and ops[0].type == A.ARM_OP_REG:
            b = state.get(ops[0].reg); width = 4*(len(ops)-1)
            address = b-width if b is not None and name.endswith('db') else b
            span(ins, address, width, 'write' if name.startswith('stm') else 'read', 'multiple')
            if ins.writeback and b is not None:
                updates[ops[0].reg] = (b-width if name.endswith('db') else b+width) & MASK
        if ops and ops[0].type == A.ARM_OP_REG:
            dest = ops[0].reg; result = None
            if name in ('mov', 'movs', 'movw') and len(ops) == 2:
                result = value(ops[1], state)
            elif name == 'movt' and len(ops) == 2 and dest in state:
                result = (state[dest] & 0xffff) | (ops[1].imm << 16)
            elif name == 'adr' and len(ops) == 2:
                result = value(ops[1], state)
            elif name in ('add', 'adds', 'sub', 'subs', 'and', 'ands', 'orr', 'orrs', 'bic', 'bics', 'lsl', 'lsls', 'lsr', 'lsrs') and len(ops) in (2, 3):
                left = state.get(dest) if len(ops) == 2 else value(ops[1], state)
                right = value(ops[-1], state)
                if left is not None and right is not None:
                    if name.startswith('add'): result = left+right
                    elif name.startswith('sub'): result = left-right
                    elif name.startswith('and'): result = left & right
                    elif name.startswith('orr'): result = left | right
                    elif name.startswith('bic'): result = left & ~right
                    elif right < 32: result = left << right if name.startswith('lsl') else left >> right
            if result is not None:
                updates[dest] = result & MASK
        # Register access information also catches implicit writes/multi-loads.
        try:
            _, written = ins.regs_access()
        except CsError:
            state.clear(); written = []
        for reg in written:
            state.pop(reg, None)
        for reg, v in updates.items():
            state[reg] = v
            if overlaps(v, 1, intervals):
                forms.append(dict(at=ins.address, register=ins.reg_name(reg), value=v))
        if A.ARM_REG_PC in written:
            stop = 'pc_write'; break
    return dict(forms=forms, accesses=accesses, bulk_calls=bulk, unknown_memory_operands=unknown, stop=stop)


def initialized(stock):
    length = struct.unpack_from('<I', stock, 0x2851f8)[0]
    regions = [('main', 0x80001000, stock[0x200:0x200+length])]
    for table in range(0x800a68dc, 0x800a695c, 16):
        src, dst, length, helper = struct.unpack_from('<4I', stock, table-BIAS)
        if helper == 0x80001994:
            regions.append(('decompressed', dst, expand(stock[src-BIAS:], length)[0]))
        elif helper == 0x80079498:
            regions.append(('copied', dst, stock[src-BIAS:src-BIAS+length]))
        else:
            assert helper == 0x800794a8
    return regions


def audit():
    stock = SOURCE.read_bytes(); assert hashlib.sha256(stock).hexdigest() == STOCK_SHA
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS); md.detail = True
    raw = []; leads = []; summaries = []
    for kind, base, data in initialized(stock):
        count = seeds = 0; stops = {}; unknown = 0
        for offset in range(len(data)-3):
            v = struct.unpack_from('<I', data, offset)[0]
            if overlaps(v, 1, GAPS):
                raw.append(dict(region=kind, location=base+offset, value=v, aligned=(base+offset)%4 == 0))
        for offset in range(0, len(data)-1, 2):
            ins = next(md.disasm(data[offset:offset+4], base+offset, count=1), None)
            if ins is None:
                continue
            count += 1; name = ins.mnemonic.split('.')[0]; ops = ins.operands
            seed = name in ('movw', 'adr') or name in ('mov', 'movs') and len(ops) == 2 and ops[1].type == A.ARM_OP_IMM
            seed |= name == 'ldr' and len(ops) == 2 and ops[1].type == A.ARM_OP_MEM and ops[1].mem.base == A.ARM_REG_PC
            if not seed:
                continue
            seeds += 1; result = trace_window(md, data, base, offset)
            unknown += result['unknown_memory_operands']; stops[result['stop']] = stops.get(result['stop'], 0)+1
            if result['forms'] or result['accesses']:
                leads.append(dict(region=kind, seed=base+offset, **result))
        summaries.append(dict(region=kind, start=base, bytes=len(data), halfword_decodes=count,
                              trace_seeds=seeds, stops=stops, unknown_memory_operands_in_traces=unknown))
    # Keep candidates and deduplicate observations without treating them as live.
    accesses = {tuple(sorted(row.items())) for lead in leads for row in lead['accesses']}
    accesses = [dict(r) for r in sorted(accesses)]
    forms = {tuple(sorted(row.items())) for lead in leads for row in lead['forms']}
    forms = [dict(r) for r in sorted(forms)]
    return dict(status='ownership_unresolved', firmware_sha256=STOCK_SHA,
        gaps=[dict(start=a, end=b, bytes=b-a) for a, b in GAPS],
        trace_bounds=dict(bytes=MAX_BYTES, instructions=MAX_INSNS), scanned_regions=summaries,
        raw_gap_candidates=raw, derived_leads=leads, unique_nearby_forms=forms, unique_nearby_accesses=accesses,
        unique_gap_accesses=[r for r in accesses if overlaps(r['start'], r['bytes'], GAPS)],
        unique_gap_forms=[r for r in forms if overlaps(r['value'], 1, GAPS)],
        limitations=[
            'Each halfword is a candidate start in mixed code/data, not a recovered reachable code map',
            'Traces are bounded, stop on calls/branches/IT, and do not merge paths or trace runtime input',
            'A seed inside a conditional block may produce a false lead; no lead is dismissed as harmless',
            'Only supported constant arithmetic, literal loads, scalar/multiple accesses and six inspected bulk helpers',
            'Mutable global loads are unknown; register clobbers discard values; unresolved operands remain unproved',
            'DMA, cache effects, other instructions/allocators/images, bootloader and physical aliasing remain unresolved',
            'Zero findings cannot establish ownership; no firmware or device modification'])


def main():
    result = audit(); path = ROOT/'analysis/ram_gap_consumers_audit.json'
    path.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(status=result['status'], raw_candidates=len(result['raw_gap_candidates']),
        gap_forms=len(result['unique_gap_forms']), gap_accesses=len(result['unique_gap_accesses']),
        nearby_accesses=len(result['unique_nearby_accesses']), report=str(path))))


if __name__ == '__main__':
    main()
