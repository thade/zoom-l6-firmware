#!/usr/bin/env python3
"""Build only offline SD fixtures, separate from every capture device profile."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
out=ROOT/'analysis/capture_io_probe.elf';out.parent.mkdir(exist_ok=True)
subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
 '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
 '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
 '-Wl,-T,tests/fixtures/capture_io_probe.ld','-Wl,-e,dependency_write','-Wl,--gc-sections',
 'tests/fixtures/sd_dependency_route.c','tests/fixtures/sd_transfer_probe.c',
 'tests/fixtures/sd_transfer_probe_hooks.S','tests/fixtures/sd_stop_probe.c',
 'tests/fixtures/sd_recovery_probe.c','tests/fixtures/sd_event_probe.c',
 'tests/fixtures/sd_admission_probe.c',
 'tests/fixtures/sd_cache_probe.c',
 '-o',str(out)],cwd=ROOT,env=env,check=True)
print(out)
