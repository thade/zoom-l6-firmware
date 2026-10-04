#!/usr/bin/env python3
"""Build separate emulator-only additional-capture ELF; no stock image changes."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
 '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
 '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
 '-Wl,-T,prototype/extra_capture/emulator.ld','-Wl,-e,extra_capture','-Wl,--gc-sections',
 'prototype/extra_capture/capture.c','prototype/extra_capture/lifecycle.c',
 'prototype/extra_capture/history.c','prototype/extra_capture/block_exchange.c',
 'prototype/extra_capture/emulator_bridge.c','prototype/extra_capture/request_router.c',
 'prototype/extra_capture/control_transport.c',
 'prototype/extra_capture/audio_fixture.c',
 'prototype/extra_capture/session_manager.c',
 'prototype/extra_capture/pad_publisher.c','prototype/overdub/overdub.c',
 'prototype/extra_capture/emulator_hooks.S',
 '-o','prototype/extra_capture/capture.elf'],
 cwd=ROOT,env=env,check=True)
print(ROOT/'prototype/extra_capture/capture.elf')
