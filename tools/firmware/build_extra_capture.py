#!/usr/bin/env python3
"""Build separate emulator-only additional-capture ELF; no stock image changes."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
 '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
 '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
 '-Wl,-T,src/capture/emulator.ld','-Wl,-e,extra_capture','-Wl,--gc-sections',
 'src/capture/capture.c','src/capture/lifecycle.c',
 'src/capture/history.c','src/capture/block_exchange.c',
 'src/capture/emulator_bridge.c','src/capture/request_router.c',
 'src/capture/control_transport.c',
 'tests/fixtures/audio_fixture.c',
 'src/capture/session_manager.c',
 'src/capture/pad_publisher.c','src/overdub/overdub.c',
 'src/capture/emulator_hooks.S',
 '-o','src/capture/capture.elf'],
 cwd=ROOT,env=env,check=True)
print(ROOT/'src/capture/capture.elf')
