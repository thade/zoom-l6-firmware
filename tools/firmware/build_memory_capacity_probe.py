#!/usr/bin/env python3
"""Prepare fixed passive RAM-controller queries locally; never stage firmware."""
import json,os,subprocess,sys
from elftools.elf.elffile import ELFFile
import build_sd_command_probe as command
from build_health_probe import ROOT
from build_deployment_probe import digest,write_manifest

ENTRY=command.ENTRY
ELF=ROOT/'src/diagnostics/memory-capacity.elf'
OUT=ROOT/'deployment/12_memory_capacity'
STATES=command.STATES

def compiled(*,elf_path=ELF,query_callback='memory_capacity_dispatch',extra_sources=(),extra_roots=(),extra_flags=(),linker_script='src/diagnostics/sd_command.ld'):
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    roots=['health_sd','completion_wait','raw_irq_hook','command_probe']+[v[0] for v in command.PROGRAM_SITES.values()]+list(extra_roots)
    sources=['health_probe.c','sd_completion_probe.c','sd_raw_probe.c','sd_command_probe.c',
             'memory_capacity_probe.c','health_hooks.S','sd_raw_hooks.S','sd_command_hooks.S',*extra_sources]
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
      '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
      '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
      '-DHEALTH_QUERY_CALLBACK='+query_callback,'-DSD_COMPLETION_DETAIL=1',
      '-DSD_COMMAND_OBSERVER=1','-Wl,-T,'+linker_script,'-Wl,-e,health_parser',
      *extra_flags,*['-Wl,-u,'+n for n in roots],*['src/diagnostics/'+n for n in sources],'-o',str(elf_path)],
      cwd=ROOT,env=env,check=True)
    with elf_path.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==ENTRY
        assert segments[0]['p_filesz']==segments[0]['p_memsz']
        return segments[0].data(),{s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}

def trial(code,syms,*,elf_path=ELF):
    previous=command.ELF
    try:
        command.ELF=elf_path
        data,r=command.trial(code,syms)
    finally:command.ELF=previous
    r.update(experiment=12,elf_sha256=digest(elf_path.read_bytes()),
      protocol='6F/6E kind1 fixed RAM-controller/core registers; all experiment11 queries retained',
      memory_query_persistent_state_bytes=0,physical_capacity_confirmed=False,
      limitations=r['limitations']+[
       'No register writes, RAM patterns, alias tests, allocation, worker or capture are added',
       'SEMC sizes are configured decode windows, not physical chip-density detection or free-space proof',
       'Core/silicon IDs do not by themselves identify the precise fitted RT104x derivative',
       'Two agreeing register snapshots are sequential consistency evidence, not an atomic snapshot',
       'Candidate-family register layouts are compared with official headers; fitted silicon remains unconfirmed'])
    return data,r

def build():
    code,syms=compiled();data,r=trial(code,syms)
    path=OUT/'trial_memory_capacity/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to replace a different prepared image'
    else:path.write_bytes(data)
    write_manifest(OUT/'manifest.json',r)
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','native_capacity_frames')}))
if __name__=='__main__':build()
