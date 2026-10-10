#!/usr/bin/env python3
"""Compile the alternative scatter-loader experiment; no firmware image."""
import json,os,subprocess,sys
from elftools.elf.elffile import ELFFile
from build_health_probe import ROOT
ELF=ROOT/'analysis/scatter_lz4.elf'

def compiled(*,source_reuse=False):
    output=ELF.with_name('scatter_lz4_source_reuse.elf') if source_reuse else ELF
    ELF.parent.mkdir(exist_ok=True)
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7','-Os','-g','-ffreestanding','-fno-builtin','-fno-stack-protector',
        '-nostdlib','-Wall','-Wextra','-Werror','-Wl,-T,tests/fixtures/scatter_lz4.ld','-Wl,-e,scatter_lz4',
        *(['-DL6_LZ4_SOURCE_REUSE'] if source_reuse else []),
        'tests/fixtures/scatter_lz4.c','-o',str(output)],cwd=ROOT,env=env,check=True)
    with output.open('rb') as f:
        elf=ELFFile(f);segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==0x800a9408
        assert segments[0]['p_filesz']==segments[0]['p_memsz']
        symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        return segments[0].data(),symbols

if __name__=='__main__':
    code,names=compiled();print(json.dumps(dict(elf=str(ELF),bytes=len(code),entry=names['scatter_lz4'])))
