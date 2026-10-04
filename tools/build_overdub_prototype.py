#!/usr/bin/env python3
"""Build emulator-only ARM ELF. Never reads/writes an SD card or patches L6.BIN."""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
env=dict(os.environ, ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local', ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabi',
    '-mcpu=cortex_m7','-mfloat-abi=soft','-Os','-g','-ffreestanding','-fno-builtin',
    '-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
    '-Wl,-T,prototype/overdub/emulator.ld','-Wl,-e,od_promote','-Wl,--no-gc-sections',
    'prototype/overdub/overdub.c','prototype/overdub/emulator_stop_bridge.c',
    'prototype/overdub/stock_pad_adapter.c',
    'prototype/overdub/admission_gate.c',
    'prototype/overdub/emulator_stream_bridge.c',
    'prototype/overdub/work_ownership.c',
    'prototype/overdub/emulator_stream_producer.c',
    'prototype/overdub/playback_session.c',
    'prototype/overdub/control_coordinator.c','prototype/overdub/control_fixture.c',
    'prototype/overdub/audio_completion.c',
    'prototype/overdub/playback_shutdown.c',
    'prototype/overdub/publication_lease.c',
    'prototype/overdub/reload_ownership.c',
    'prototype/overdub/reload_transport.c',
    'prototype/overdub/usb_ownership.c','prototype/overdub/reload_manager.c','prototype/overdub/publication_workflow.c',
    'prototype/overdub/reload_compact.c','prototype/overdub/reload_compact_hooks.S',
    '-o','prototype/overdub/overdub.elf'],cwd=ROOT,env=env,check=True)
print(ROOT/'prototype/overdub/overdub.elf')
