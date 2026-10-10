#!/usr/bin/env python3
"""Build a separate emulator-only IRQ delivery helper, never a device image."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
 '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
 '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
 '-Wl,-T,tests/fixtures/capture_io_probe.ld','-Wl,-e,command_delivery',
 'tests/fixtures/sd_command_delivery.c','-o',str(ROOT/'analysis/sd-command-delivery.elf')],cwd=ROOT,env=env,check=True)
