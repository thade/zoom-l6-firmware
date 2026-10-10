#!/usr/bin/env python3
"""Prepare a local eight-byte detour trial; never access or stage a device."""
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from build_deployment_probe import SOURCE, STOCK_SHA, digest, validate, write_manifest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'deployment/03_added_code'
BIAS = 0x80000e00
HOOK = 0x800737f6
RESUME = HOOK + 4
ENTRY = 0x800360e4
PAD_START, PAD_END = 0x800360e2, 0x800360f0
ORIGINAL = bytes.fromhex('e8680c90')


def branch(source, target):
    """Encode Thumb-2 unconditional B.W, independently checked by Capstone."""
    delta = target - (source + 4)
    assert delta % 2 == 0 and -(1 << 24) <= delta < (1 << 24)
    bits = delta & ((1 << 25) - 1)
    s, i1, i2 = (bits >> 24) & 1, (bits >> 23) & 1, (bits >> 22) & 1
    j1, j2 = 1 ^ i1 ^ s, 1 ^ i2 ^ s
    raw = struct.pack('<HH', 0xf000 | s << 10 | ((bits >> 12) & 0x3ff),
                      0x9000 | j1 << 13 | j2 << 11 | ((bits >> 1) & 0x7ff))
    instructions = list(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(raw, source))
    assert len(instructions) == 1
    assert (instructions[0].mnemonic, instructions[0].op_str) == ('b.w', f'#{target:#x}')
    return raw


def candidate(stock):
    assert digest(stock) == STOCK_SHA
    validate(stock)
    assert stock[HOOK-BIAS:RESUME-BIAS] == ORIGINAL
    assert stock[PAD_START-BIAS:PAD_END-BIAS] == bytes(PAD_END-PAD_START)
    # The preceding function returns; the next function begins beyond this pad.
    assert stock[PAD_START-BIAS-4:PAD_START-BIAS] == bytes.fromhex('bde8f081')
    assert stock[PAD_END-BIAS:PAD_END-BIAS+4] == bytes.fromhex('074b1968')
    trial = bytearray(stock)
    trial[HOOK-BIAS:RESUME-BIAS] = branch(HOOK, ENTRY)
    # Select the existing full product label and perform the displaced store.
    # Unconditional branches preserve LR, SP and flags; no new RAM is required.
    routine = bytes.fromhex('e8690c90') + branch(ENTRY+4, RESUME)
    trial[ENTRY-BIAS:ENTRY-BIAS+len(routine)] = routine
    struct.pack_into('>I', trial, 0x1fc, sum(trial[0x200:]) & 0xffffffff)
    trial = bytes(trial)
    validate(trial)
    assert trial[0x2851f8:] == stock[0x2851f8:]
    allowed = set(range(0x1fc, 0x200)) | set(range(HOOK-BIAS, RESUME-BIAS)) | set(range(ENTRY-BIAS, ENTRY-BIAS+8))
    assert all(i in allowed for i, (a, b) in enumerate(zip(stock, trial)) if a != b)
    return trial


def build():
    stock = SOURCE.read_bytes()
    trial = candidate(stock)
    images = []
    for role, data in [('stock_restore', stock), ('trial_added_code_ZOOM_L6', trial)]:
        path = OUT/role/'L6.BIN'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            assert path.read_bytes() == data, 'Refusing to replace a different image'
        else:
            path.write_bytes(data)
        images.append(dict(role=role, path=str(path), sha256=digest(data), bytes=len(data)))
    manifest = dict(purpose='Execute an eight-byte added routine through an out-and-back branch',
                    source_sha256=STOCK_SHA, images=images,
                    hook=hex(HOOK), added_code=hex(ENTRY), resume=hex(RESUME),
                    changed_bytes=[dict(offset=hex(i), old=hex(a), new=hex(b))
                                   for i, (a, b) in enumerate(zip(stock, trial)) if a != b],
                    unchanged=['Payload length and all package/version fields',
                               'BOOT, panel and guide regions', 'Stored strings',
                               'All bytes outside the hook, added routine and checksum'],
                    deployment_status='Prepared locally; not staged or installed',
                    limitations=['Requires separate placement audit and emulator verification',
                                 'Indirect references cannot be exhaustively excluded by static scans',
                                 'No hardware execution or restoration of this trial yet',
                                 'Does not test appended payloads, large buffers or the overdub prototype',
                                 'Recovery from broken firmware remains unproven'])
    path = OUT/'manifest.json'
    if not path.exists():
        write_manifest(path, manifest)
    print(json.dumps(dict(images=images, changed_bytes=len(manifest['changed_bytes']))))


if __name__ == '__main__':
    build()
