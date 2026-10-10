#!/usr/bin/env python3
"""Prepare the observation-only read/write timing trial locally; no device access."""
import json,os,subprocess,sys
from elftools.elf.elffile import ELFFile
from build_health_probe import ROOT,ENTRY,END,SOURCE,candidate
OUT=ROOT/'deployment/05_timing_probe';ELF=ROOT/'src/diagnostics/timing.elf'
HOOKS={'health_parser':0x800301f0,'health_sd':0x80068378,
       'timing_read':0x80060620,'timing_write':0x800622b0}
PROLOGUES={'timing_read':'2de9f04f','timing_write':'2de9f04f'}
STATE_BYTES=444
def compiled():
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    # Deliberately retain integer-only compilation for these hot observers.
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
        '-Wl,-T,src/diagnostics/timing.ld','-Wl,-e,health_parser',
        '-Wl,-u,health_sd','-Wl,-u,timing_read','-Wl,-u,timing_write',
        'src/diagnostics/timing_probe.c','src/diagnostics/health_hooks.S',
        'src/diagnostics/timing_hooks.S','-o',str(ELF)],cwd=ROOT,env=env,check=True)
    with ELF.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==ENTRY
        seg=segments[0];assert seg['p_memsz']==seg['p_filesz'] and ENTRY+seg['p_memsz']<=END
        symbols={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        return seg.data(),symbols
def trial(code,symbols):
    return candidate(code,symbols,elf_path=ELF,hooks=HOOKS,state_name='timing_stats',
                     state_bytes=STATE_BYTES,prologues=PROLOGUES)
def build():
    code,symbols=compiled();data,report=trial(code,symbols)
    report.update(experiment=5,protocol='fixed 7B requests / 7A replies, kinds 1..7',
        measures=['Per-operation SD and public file calls, errors and first error',
          'Per-operation elapsed maxima, peak request identity/size and eight tick bins',
          'Separate busy-observer and missed-weak-claim counts; unchanged heap counters'],
        unmeasured=['Largest contiguous heap block and stock/task stack high-water',
          'Extra-capture load, ring occupancy, catch-up and worker scheduling',
          'Physical completion/cache/source exclusion'])
    for role,payload in (('stock_restore',SOURCE.read_bytes()),('trial_timing_probe',data)):
        p=OUT/role/'L6.BIN';p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists():assert p.read_bytes()==payload,'Refusing to replace a different prepared image'
        else:p.write_bytes(payload)
    (OUT/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('trial_sha256','code_bytes','packed_bytes','state_bytes')}))
if __name__=='__main__':build()
