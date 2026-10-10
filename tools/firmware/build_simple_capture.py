#!/usr/bin/env python3
"""Build the simplified capture ELF at the placement addresses. No image changes."""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'src/capture/simple/simple-capture.elf'
env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')

def build():
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7+fp_armv8d16sp','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
        '-ffunction-sections','-fdata-sections',
        '-Wl,-T,src/capture/placement.ld','-Wl,-e,sc_worker_entry','-Wl,--gc-sections',
        'src/capture/simple/simple_capture.c','src/capture/simple/simple_hooks.S',
        '-o',str(OUTPUT)],cwd=ROOT,env=env,check=True)
    return OUTPUT

if __name__=='__main__':print(build())
