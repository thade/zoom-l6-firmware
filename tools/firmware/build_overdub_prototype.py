#!/usr/bin/env python3
"""Build emulator-only ARM ELF. Never reads/writes an SD card or patches L6.BIN."""
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
env=dict(os.environ, ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local', ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabi',
    '-mcpu=cortex_m7','-mfloat-abi=soft','-Os','-g','-ffreestanding','-fno-builtin',
    '-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
    '-Wl,-T,src/overdub/emulator.ld','-Wl,-e,od_promote','-Wl,--no-gc-sections',
    'src/overdub/overdub.c','src/overdub/emulator_stop_bridge.c',
    'src/overdub/stock_pad_adapter.c',
    'src/overdub/admission_gate.c',
    'src/overdub/emulator_stream_bridge.c',
    'src/overdub/work_ownership.c',
    'src/overdub/emulator_stream_producer.c',
    'src/overdub/playback_session.c','src/overdub/playback_io.c',
    'src/overdub/native_scan.c','src/overdub/native_scan_hooks.S',
    'src/overdub/control_coordinator.c','tests/fixtures/control_fixture.c',
    'src/overdub/audio_completion.c','src/overdub/native_audio.c','src/overdub/native_audio_hooks.S',
    'src/overdub/playback_shutdown.c',
    'src/overdub/publication_lease.c',
    'src/overdub/reload_ownership.c',
    'src/overdub/reload_transport.c',
    'src/overdub/reload_read.c',
    'src/overdub/read_worker.c',
    'src/overdub/read_producer.c','src/overdub/read_producer_hooks.S',
    'src/overdub/pad_file.c','src/overdub/pad_file_hooks.S',
    'src/overdub/ordinary_io.c','src/overdub/ordinary_producer.c',
    'src/overdub/usb_ownership.c','src/overdub/reload_manager.c','src/overdub/publication_workflow.c',
    'src/overdub/reload_compact.c','src/overdub/reload_compact_hooks.S',
    '-o','src/overdub/overdub.elf'],cwd=ROOT,env=env,check=True)
print(ROOT/'src/overdub/overdub.elf')
