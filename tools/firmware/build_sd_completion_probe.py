#!/usr/bin/env python3
"""Prepare passive chunk-completion experiment 09 locally; never stage it."""
import argparse,json,os,struct,subprocess,sys
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from build_health_probe import ROOT,BIAS,SCATTER,DSP_SOURCE,END,SOURCE,candidate
from build_deployment_probe import validate,digest
from build_added_code_probe import branch
OUT=ROOT/'deployment/09_sd_completion';ELF=ROOT/'src/diagnostics/sd-completion.elf'
DETAIL_OUT=OUT/'detail';DETAIL_ELF=ROOT/'src/diagnostics/sd-completion-detail.elf'
ENTRY=0x800b2400;CAP=223104;SIZE_SITE=0x800121ce
WAIT_SITES=(0x8006a06a,0x8006a1f4,0x8006ac6e,0x8006ae10)
HOOKS={'health_parser':0x800301f0,'health_sd':0x80068378}
STATES={'health_sd_stats':56,'completion_trace':124}
DETAIL_STATES={'health_sd_stats':56,'completion_trace':380}
def bl(site,target):
    raw=bytearray(branch(site,target));raw[3]|=0x40
    decoded=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB).disasm(raw,site))
    assert len(decoded)==1 and (decoded[0].mnemonic,decoded[0].op_str)==('bl',f'#{target:#x}')
    return bytes(raw)
def compiled(detail=False):
    elf=DETAIL_ELF if detail else ELF
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
        '-DHEALTH_QUERY_CALLBACK=completion_dispatch',
        *(['-DSD_COMPLETION_DETAIL=1'] if detail else []),
        '-Wl,-T,src/diagnostics/sd_completion.ld',
        '-Wl,-e,health_parser','-Wl,-u,health_sd','-Wl,-u,completion_wait',
        'src/diagnostics/health_probe.c','src/diagnostics/sd_completion_probe.c',
        'src/diagnostics/health_hooks.S','-o',str(elf)],cwd=ROOT,env=env,check=True)
    with elf.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==ENTRY
        s=segments[0];assert s['p_filesz']==s['p_memsz']
        names={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        return s.data(),names
def trial(code,names,detail=False):
    states=DETAIL_STATES if detail else STATES
    first=min(states,key=lambda n:names[n]);start=names[first]
    end=max(names[n]+size for n,size in states.items())
    assert code[start-ENTRY:end-ENTRY]==bytes(end-start)
    image,r=candidate(code,names,elf_path=DETAIL_ELF if detail else ELF,hooks=HOOKS,state_name=first,
                      state_bytes=end-start,probe_entry=ENTRY)
    data=bytearray(image);stock=SOURCE.read_bytes()
    for site in WAIT_SITES:
        old=stock[site-BIAS:site-BIAS+4];assert old==bl(site,0x800328c0)
        new=bl(site,names['completion_wait']&~1)
        data[site-BIAS:site-BIAS+4]=new
        r['patches'].append(dict(symbol='completion_wait',site=site,old=old.hex(),new=new.hex()))
    old=stock[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4];assert old==bytes.fromhex('4af68011')
    new=bytes.fromhex('46f28071');data[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]=new
    r['patches'].append(dict(symbol='native_startup_capacity',site=SIZE_SITE,old=old.hex(),new=new.hex()))
    struct.pack_into('>I',data,0x1fc,sum(data[0x200:])&0xffffffff);data=bytes(data);validate(data)
    allowed=[(0x1fc,0x200),(SCATTER-BIAS+12,SCATTER-BIAS+16),(DSP_SOURCE-BIAS,END-BIAS)]
    allowed.extend((s-BIAS,s-BIAS+4) for s in (*HOOKS.values(),*WAIT_SITES,SIZE_SITE))
    assert len(data)==len(stock) and data[0x2851f8:]==stock[0x2851f8:]
    assert all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(stock,data)) if x!=y)
    r.update(experiment=9,trial_sha256=digest(data),native_capacity_frames=CAP,
        states={n:dict(address=names[n],bytes=size) for n,size in states.items()},
        capture_enabled=False,task_created=False,allocation_enabled=False,
        detail_enabled=detail,
        protocol='73/72 kinds 1 latest / 2 first anomaly'+
            (' / 3 per-site counters and reason unions / 4..7 latest anomaly per site' if detail else '')+
            '; legacy health 7D/7C retained',
        limitations=r['limitations']+[
            'Four fixed native data-wait sites observed, including reached non-DMA error-path reads; general PIO paths, command exits, raw IRQ identity and admission are not covered',
            'Sequential MMIO samples are observations, not permission for physical completion or cache reuse',
            'The DMA address sample may already have advanced; it is not the originally submitted address',
            'No buffer retention, reset, recovery, extra capture or pad assignment is enabled',
            'Observer omissions and busy snapshots invalidate complete interval coverage; timing/stack require a device trial'])
    return data,r
def build(detail=False):
    out=DETAIL_OUT if detail else OUT
    code,names=compiled(detail);data,r=trial(code,names,detail)
    p=out/'trial_sd_completion/L6.BIN';p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==data,'Refusing to replace a different prepared image'
    else:p.write_bytes(data)
    (out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','native_capacity_frames')}))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--detail',action='store_true',help='Prepare per-site counters/latest anomalies in a separate output directory')
    build(p.parse_args().detail)
