#!/usr/bin/env python3
"""Build experiment 08 locally; no staging or device access."""
import os,struct,subprocess,sys,json
from elftools.elf.elffile import ELFFile
from build_health_probe import ROOT,END,BIAS,SCATTER,DSP_SOURCE,SOURCE,candidate
from build_deployment_probe import validate,digest,write_manifest
OUT=ROOT/'deployment/08_ring_probe'
ELF=ROOT/'src/diagnostics/ring.elf'
ENTRY=0x800b2400
CAP=223104
SIZE_SITE=0x800121ce
HOOKS={'health_parser':0x800301f0,'ring_sd':0x80068378,
       'ring_read':0x80060620,'ring_write':0x800622b0}
PROLOGUES={k:'2de9f04f' for k in HOOKS if k!='health_parser'}
PROLOGUES['ring_sd']='2de9f047'
STATE_SIZES={'timing_stats':444,'ring_guards':116,'ring_spans':36}
def compiled():
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
        '-DHEALTH_QUERY_CALLBACK=ring_dispatch','-Wl,-T,src/diagnostics/ring.ld',
        '-Wl,-e,health_parser','-Wl,-u,ring_layout',*[f'-Wl,-u,{name}' for name in HOOKS],
        'src/diagnostics/timing_probe.c','src/diagnostics/ring_probe.c',
        'src/diagnostics/health_hooks.S','src/diagnostics/timing_hooks.S','-o',str(ELF)],
        cwd=ROOT,env=env,check=True)
    with ELF.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==ENTRY
        seg=segments[0];assert seg['p_memsz']==seg['p_filesz']
        symbols={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        return seg.data(),symbols
def trial(code,symbols):
    first=min(STATE_SIZES,key=lambda name:symbols[name]);state=symbols[first]
    end=max(symbols[name]+size for name,size in STATE_SIZES.items())
    assert code[state-ENTRY:end-ENTRY]==bytes(end-state)
    image,r=candidate(code,symbols,elf_path=ELF,hooks=HOOKS,state_name=first,
        state_bytes=end-state,prologues=PROLOGUES,probe_entry=ENTRY)
    stock=SOURCE.read_bytes();old=stock[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]
    assert old==bytes.fromhex('4af68011')
    # MOVW r1,#6780; existing MOVT r1,#3 supplies the upper half.
    new=bytes.fromhex('46f28071');data=bytearray(image)
    data[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]=new
    struct.pack_into('>I',data,0x1fc,sum(data[0x200:])&0xffffffff)
    data=bytes(data);validate(data)
    allowed=[(0x1fc,0x200),(SCATTER-BIAS+12,SCATTER-BIAS+16),(DSP_SOURCE-BIAS,END-BIAS)]
    allowed.extend((p-BIAS,p-BIAS+4) for p in (*HOOKS.values(),SIZE_SITE))
    assert len(stock)==len(data) and all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(stock,data)) if x!=y)
    assert data[0x2851f8:]==stock[0x2851f8:]
    r['patches'].append(dict(symbol='native_startup_capacity',site=SIZE_SITE,old=old.hex(),new=new.hex()))
    r.update(experiment=8,trial_sha256=digest(data),native_capacity_frames=CAP,
        ordinary_history_seconds=CAP/48000,tail_bytes_per_lane=(240000-CAP)*4,
        tail_lanes=12,guard_chunk_bytes=2048,guard_chunks_per_sweep=396,
        prospective_history_slots=1024,prospective_history_seconds=1024*64/48000,
        states={name:dict(address=symbols[name],bytes=size) for name,size in STATE_SIZES.items()},
        capture_enabled=False,task_created=False,allocation_enabled=False,
        protocol='75/74 kinds 1..5; kind 2 explicitly writes guard chunks, kind 3 checks; legacy timing unchanged',
        limitations=['Local diagnostic only; 223104 frames is test geometry, not a selected service budget.',
          'Writes detect sampled guard corruption, not reads, aliases, physical DMA/cache lifetime or complete ownership.',
          'Initialization writes fixed native tails after coherent idle setup; there is no live resizing or capacity repair.',
          'Sampled modulo native backlog cannot detect missed whole laps or unsampled peaks.',
          'IO span observations report requested CPU addresses, not physical completion; generic effect destinations remain uncertain.',
          'No extra audio, worker, allocation or SD/file request; guard/query timing and stack need hardware validation.',
          'DSP bytes and ordinary sectors are verified offline with driver/scheduling fixtures, not on this device with this image.'])
    return data,r
def build():
    code,symbols=compiled();data,r=trial(code,symbols)
    p=OUT/'trial_ring_probe/L6.BIN';p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==data,'Refusing to replace a different prepared image'
    else:p.write_bytes(data)
    write_manifest(OUT/'manifest.json',r)
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','native_capacity_frames')}))
if __name__=='__main__':build()
