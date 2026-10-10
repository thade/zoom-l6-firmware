#!/usr/bin/env python3
"""Build the capture-disabled, attributed storage-service probe locally only."""
import json,os,subprocess,sys
from elftools.elf.elffile import ELFFile
from build_health_probe import ROOT,END,SOURCE,candidate
OUT=ROOT/'deployment/07_service_probe'
ELF=ROOT/'src/diagnostics/service.elf'
ENTRY=0x800b2400
HOOKS={'health_parser':0x800301f0,'health_sd':0x80068378,
       'service_read':0x80060620,'service_write':0x800622b0,
       'service_take':0x800328f0,'service_give':0x80032890}
PROLOGUES={'service_read':'2de9f04f','service_write':'2de9f04f',
           'service_take':'4ff0ff31','service_give':'fff77abe'}
def compiled():
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
        '-DHEALTH_QUERY_CALLBACK=service_dispatch','-Wl,-T,src/diagnostics/service.ld',
        '-Wl,-e,health_parser','-Wl,-u,service_layout',
        *[f'-Wl,-u,{name}' for name in HOOKS],
        'src/diagnostics/timing_probe.c','src/diagnostics/service_probe.c',
        'src/diagnostics/health_hooks.S','src/diagnostics/timing_hooks.S',
        'src/diagnostics/service_hooks.S','-o',str(ELF)],cwd=ROOT,env=env,check=True)
    with ELF.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==ENTRY
        segment=segments[0];assert segment['p_memsz']==segment['p_filesz']
        symbols={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        return segment.data(),symbols
def trial(code,symbols):
    state=min(symbols['timing_stats'],symbols['service_stats'])
    end=max(symbols['timing_stats']+444,symbols['service_stats']+3832)
    assert code[state-ENTRY:end-ENTRY]==bytes(end-state)
    data,r=candidate(code,symbols,elf_path=ELF,hooks=HOOKS,
        state_name='timing_stats' if state==symbols['timing_stats'] else 'service_stats',
        state_bytes=end-state,prologues=PROLOGUES,probe_entry=ENTRY)
    r.update(experiment=7,timing_state=symbols['timing_stats'],service_state=symbols['service_stats'],
        service_state_bytes=3832,task_slots=8,lock_classes=['filesystem1','filesystem2','SD1','SD2'],
        protocol='77/76 kinds 1..41 observation only; legacy 7B/7A timing unchanged',
        capture_enabled=False,task_created=False,reservation_enabled=False,
        measurement='Native take call, successful-return-to-give-entry held-body lower bound, give call and public read/write elapsed; per stable TCB and file job.',
        extra_limits=['Token boundaries include scheduling; held body is a lower bound, not exact acquisition/release or physical completion.',
          'Eight permanent TCB slots; task deletion/TCB reuse and nested token acquisition are outside the bounded trial.',
          'No extra consumer, queue-delay measurement, card-busy attribution or stack high-water is supplied.'])
    return data,r
def build():
    code,symbols=compiled();data,r=trial(code,symbols)
    p=OUT/'trial_service_probe/L6.BIN';p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==data,'Refusing to replace a different prepared image'
    else:p.write_bytes(data)
    (OUT/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','code_start')}))
if __name__=='__main__':build()
