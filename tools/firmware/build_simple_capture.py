#!/usr/bin/env python3
"""Build the simplified capture ELFs inside the consumed DSP source span.

The normal build is capture only. The trial build adds the read-only status
query on the Editor parser. Neither changes a stock image.
"""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'src/capture/simple/simple-capture.elf'
TRIAL=ROOT/'src/capture/simple/simple-capture-trial.elf'
TAKE=ROOT/'src/capture/simple/simple-capture-take.elf'
QUERY=['src/capture/simple/simple_query.c','src/diagnostics/health_hooks.S',
       '-DHEALTH_QUERY_CALLBACK=sc_query','-Wl,-u,health_parser']
env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')

def build(trial=False,root=ROOT):
    """trial: False (capture only), 'tap' or True (experiment 19: capture code
    plus query), 'take' (experiment 20: plus the worker stack measurement)."""
    output={False:OUTPUT,True:TRIAL,'tap':TRIAL,'take':TAKE}[trial]
    extra=QUERY+['-DSC_STACK_PAINT=0x5ca1ab1eu'] if trial=='take' else QUERY if trial else []
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7+fp_armv8d16sp','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
        '-ffunction-sections','-fdata-sections',
        # Same reused interval as the hardware-verified source-reuse diagnostic.
        '-Wl,-T,tests/fixtures/capture_source_reuse.ld','-Wl,-e,sc_worker_entry','-Wl,--gc-sections',
        'src/capture/simple/simple_capture.c','src/capture/simple/simple_hooks.S',*extra,
        '-o',str(output)],cwd=root,env=env,check=True)
    return output

if __name__=='__main__':print(build(),build(trial='tap'),build(trial='take'))
