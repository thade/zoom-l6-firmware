#!/usr/bin/env python3
"""Build the master-reference ELFs inside the consumed DSP source span.

The normal build is the reference only. The trial build adds the read-only
status query on the Editor parser and a worker stack measurement.
"""
import os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/'src/capture/master/master-ref.elf'
TRIAL=ROOT/'src/capture/master/master-ref-trial.elf'
QUERY=['src/capture/master/master_query.c','src/diagnostics/health_hooks.S',
       '-DHEALTH_QUERY_CALLBACK=mr_query','-Wl,-u,health_parser','-DMR_STACK_PAINT=0x5ca1ab1eu']
DIAG=['-DPANEL_DIAG']   # experiment 37's panel diagnostics (with the query)
FLASH=['-DFLASH_DIAG']  # experiment 39's flash reads and anchor status (with the query)
# The zig cache lives in the repository (ignored) unless the caller sets one.
env=dict(os.environ)
env.setdefault('ZIG_LOCAL_CACHE_DIR',str(ROOT/'.zig-cache/local'));env.setdefault('ZIG_GLOBAL_CACHE_DIR',str(ROOT/'.zig-cache/global'))

def build(trial=False,root=ROOT,stereo=False,diag=False,flash=False):
    """Build into root (a pinned build's temporary tree keeps its own ELF).
    stereo: link the stereo AUX hooks (an explicit choice, never implied)."""
    name=(TRIAL if trial else OUTPUT).stem+('-stereo' if stereo else '')+('-diag' if diag else '')+('-flash' if flash else '')+'.elf'
    output=Path(root)/OUTPUT.parent.relative_to(ROOT)/name
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7+fp_armv8d16sp','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
        '-ffunction-sections','-fdata-sections',
        '-Wl,-T,tests/fixtures/capture_source_reuse.ld','-Wl,-e,mr_worker_entry','-Wl,--gc-sections',
        'src/capture/master/master_ref.c','src/capture/master/master_hooks.S',
        *[s for s in ('src/capture/master/panel.c',) if (Path(root)/s).exists()],   # absent before experiment 35
        *(['src/capture/master/stereo_aux.c'] if stereo else []),
        *(QUERY if trial else []),*(DIAG if diag else []),*(FLASH if flash else []),
        '-o',str(output)],cwd=root,env=env,check=True)
    return output

if __name__=='__main__':print(build(),build(trial=True))
