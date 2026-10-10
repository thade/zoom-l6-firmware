#!/usr/bin/env python3
"""Build an in-place instruction probe. Local files only; no device access."""
import json
import struct
from pathlib import Path
from build_deployment_probe import SOURCE, STOCK_SHA, validate, digest, write_manifest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'deployment/02_code_marker'
BIAS = 0x80000e00
PATCH_ADDRESS = 0x800737f6
PATCH_OFFSET = PATCH_ADDRESS - BIAS
OLD = bytes.fromhex('e8 68')  # ldr r0, [r5, #12]
NEW = bytes.fromhex('e8 69')  # ldr r0, [r5, #28]


def build():
    stock = SOURCE.read_bytes()
    assert digest(stock) == STOCK_SHA
    validate(stock)
    assert stock[PATCH_OFFSET:PATCH_OFFSET+2] == OLD
    trial = bytearray(stock)
    trial[PATCH_OFFSET:PATCH_OFFSET+2] = NEW
    struct.pack_into('>I', trial, 0x1fc, sum(trial[0x200:]) & 0xffffffff)
    trial = bytes(trial)
    validate(trial)
    diffs = [i for i, (a, b) in enumerate(zip(stock, trial)) if a != b]
    assert diffs == [0x1ff, PATCH_OFFSET+1]
    assert trial[0xa1d50:0xa1d58] == stock[0xa1d50:0xa1d58] == b'ZOOM L6\0'
    assert trial[0x285200:] == stock[0x285200:]
    images = []
    for role, data in [('stock_restore', stock), ('trial_code_name_ZOOM_L6', trial)]:
        path = OUT / role / 'L6.BIN'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            assert path.read_bytes() == data, 'Refusing to overwrite a different image'
        else:
            path.write_bytes(data)
        images.append(dict(role=role, path=str(path), bytes=len(data), sha256=digest(data)))
    manifest = dict(
        purpose='Execute a changed USB configuration load instruction: L6 -> ZOOM L6',
        source_sha256=STOCK_SHA, images=images,
        instruction=dict(runtime_address=hex(PATCH_ADDRESS), file_offset=hex(PATCH_OFFSET),
                         old_bytes=OLD.hex(), new_bytes=NEW.hex(),
                         before='ldr r0, [r5, #0xc]', after='ldr r0, [r5, #0x1c]'),
        changed_bytes=[dict(file_offset=hex(i), old=hex(stock[i]), new=hex(trial[i])) for i in diffs],
        unchanged=['All stored strings and initialized tables', 'Image length and version fields',
                   'BOOT descriptor (empty)', 'Panel and voice-guide regions',
                   'All bytes except one instruction byte and one checksum byte'],
        deployment_status='Prepared locally; not copied to card or installed',
        limitations=['No hardware execution of this code probe yet',
                     'Does not test new code storage, hooks or overdub integration',
                     'Recovery from broken firmware remains unproven'])
    path = OUT / 'manifest.json'
    if not path.exists():
        write_manifest(path, manifest)
    print(json.dumps(dict(images=images, changed_bytes=manifest['changed_bytes']), indent=2))


if __name__ == '__main__':
    build()
