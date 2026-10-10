#!/usr/bin/env python3
"""Build a local heap/SD-observation trial. Never stage or access a device."""
import hashlib,json,os,struct,subprocess,sys
from pathlib import Path
from elftools.elf.elffile import ELFFile
from build_deployment_probe import SOURCE,STOCK_SHA,validate,digest,write_manifest
from build_added_code_probe import branch
from scatter_codec import compress,expand
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'deployment/04_health_probe';ELF=ROOT/'src/diagnostics/health.elf'
BIAS=0x80000e00
SCATTER=0x800a691c
DSP_SOURCE,DSP_DEST,DSP_BYTES=0x800a9408,0x20220000,0xd6dc
ENTRY=0x800b6000;END=0x800b6ae4
HOOKS={'health_parser':0x800301f0,'health_sd':0x80068378}

def compiled():
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-fstack-usage','-nostdlib','-Wall','-Wextra','-Werror',
        '-Wl,-T,src/diagnostics/health.ld','-Wl,-e,health_parser','-Wl,-u,health_sd',
        'src/diagnostics/health_probe.c','src/diagnostics/health_hooks.S','-o',str(ELF)],
        cwd=ROOT,env=env,check=True)
    with ELF.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==ENTRY
        seg=segments[0];assert seg['p_memsz']==seg['p_filesz']
        symbols={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        return seg.data(),symbols

def candidate(code,symbols,*,elf_path=ELF,hooks=HOOKS,state_name='health_sd_stats',state_bytes=56,prologues=None,probe_entry=ENTRY):
    stock=SOURCE.read_bytes();assert digest(stock)==STOCK_SHA;validate(stock)
    assert struct.unpack_from('<4I',stock,SCATTER-BIAS)==(DSP_SOURCE,DSP_DEST,DSP_BYTES,0x80079498)
    dsp=stock[DSP_SOURCE-BIAS:DSP_SOURCE-BIAS+DSP_BYTES];packed=compress(dsp)
    assert expand(packed,DSP_BYTES)==(dsp,len(packed))
    assert DSP_SOURCE+len(packed)<=probe_entry and probe_entry+len(code)<=END
    trial=bytearray(stock)
    trial[DSP_SOURCE-BIAS:END-BIAS]=bytes(END-DSP_SOURCE)
    trial[DSP_SOURCE-BIAS:DSP_SOURCE-BIAS+len(packed)]=packed
    trial[probe_entry-BIAS:probe_entry-BIAS+len(code)]=code
    struct.pack_into('<I',trial,SCATTER-BIAS+12,0x80001994)
    patches=[]
    for name,site in hooks.items():
        old=stock[site-BIAS:site-BIAS+4]
        expected=(prologues or {}).get(name,'2de9f047')
        assert old==bytes.fromhex(expected),(name,old.hex())
        new=branch(site,symbols[name]&~1)
        trial[site-BIAS:site-BIAS+4]=new
        patches.append(dict(symbol=name,site=site,target=symbols[name]&~1,old=old.hex(),new=new.hex()))
    struct.pack_into('>I',trial,0x1fc,sum(trial[0x200:])&0xffffffff)
    trial=bytes(trial);validate(trial)
    allowed=[(0x1fc,0x200),(SCATTER-BIAS+12,SCATTER-BIAS+16),(DSP_SOURCE-BIAS,END-BIAS)]
    allowed += [(site-BIAS,site-BIAS+4) for site in hooks.values()]
    assert len(stock)==len(trial) and all(any(a<=i<b for a,b in allowed) for i,(s,t) in enumerate(zip(stock,trial)) if s!=t)
    assert trial[0x2851f8:]==stock[0x2851f8:]
    return trial,dict(stock_sha256=STOCK_SHA,trial_sha256=digest(trial),elf_sha256=digest(elf_path.read_bytes()),
        dsp_source=DSP_SOURCE,dsp_destination=DSP_DEST,dsp_bytes=DSP_BYTES,packed_bytes=len(packed),
        code_start=probe_entry,code_bytes=len(code),state=symbols[state_name],state_bytes=state_bytes,patches=patches,
        deployment_status='Prepared locally only; verification required before staging',
        limitations=['Code/global placement reuses an audited stock DSP source span; arbitrary computed consumers remain uncertain.',
            'Original decoder and exact DSP output are verified offline, not on this device with this image.',
            'Counters are observations only; native return and measured duration are not physical completion.',
            'No capture, allocation, task, card write, reset, retry, extra command or join permission is added.',
            'Probe stack and timing require hardware validation; recovery from broken firmware remains unproven.'])

def build():
    code,symbols=compiled();trial,report=candidate(code,symbols)
    for role,data in (('stock_restore',SOURCE.read_bytes()),('trial_health_probe',trial)):
        p=OUT/role/'L6.BIN';p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists():assert p.read_bytes()==data,'Refusing to replace a different prepared image'
        else:p.write_bytes(data)
    write_manifest(OUT/'manifest.json',report)
    print(json.dumps({k:report[k] for k in ('trial_sha256','code_bytes','packed_bytes','state_bytes')}))
if __name__=='__main__':build()
