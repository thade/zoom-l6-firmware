#!/usr/bin/env python3
"""Build a separate passive raw-IRQ diagnostic locally; never stage it."""
import json,os,struct,subprocess,sys
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from build_sd_completion_probe import ENTRY,CAP,SIZE_SITE,WAIT_SITES,HOOKS,bl
from build_health_probe import ROOT,BIAS,SCATTER,DSP_SOURCE,END,SOURCE,candidate
from build_deployment_probe import validate,digest
from build_added_code_probe import branch
ELF=ROOT/'src/diagnostics/sd-raw.elf';OUT=ROOT/'deployment/10_sd_raw'
IRQ_SITE=0x8006eab6;IRQ_BYTES=6
STATES={'health_sd_stats':56,'completion_trace':380,'raw_trace':188}

def compiled():
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
      '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
      '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
      '-DHEALTH_QUERY_CALLBACK=raw_completion_dispatch','-DSD_COMPLETION_DETAIL=1',
      '-Wl,-T,src/diagnostics/sd_raw.ld','-Wl,-e,health_parser',
      '-Wl,-u,health_sd','-Wl,-u,completion_wait','-Wl,-u,raw_irq_hook',
      'src/diagnostics/health_probe.c','src/diagnostics/sd_completion_probe.c',
      'src/diagnostics/sd_raw_probe.c','src/diagnostics/health_hooks.S',
      'src/diagnostics/sd_raw_hooks.S','-o',str(ELF)],cwd=ROOT,env=env,check=True)
    with ELF.open('rb') as f:
        e=ELFFile(f);segs=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segs)==1 and segs[0]['p_vaddr']==ENTRY and segs[0]['p_filesz']==segs[0]['p_memsz']
        names={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        return segs[0].data(),names

def trial(code,names):
    first=min(STATES,key=lambda n:names[n]);start=names[first]
    end=max(names[n]+size for n,size in STATES.items())
    assert code[start-ENTRY:end-ENTRY]==bytes(end-start)
    image,r=candidate(code,names,elf_path=ELF,hooks=HOOKS,state_name=first,
                      state_bytes=end-start,probe_entry=ENTRY)
    data=bytearray(image);stock=SOURCE.read_bytes()
    for site in WAIT_SITES:
        old=stock[site-BIAS:site-BIAS+4];assert old==bl(site,0x800328c0)
        new=bl(site,names['completion_wait']&~1);data[site-BIAS:site-BIAS+4]=new
        r['patches'].append(dict(symbol='completion_wait',site=site,old=old.hex(),new=new.hex()))
    assert stock[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]==bytes.fromhex('4af68011')
    data[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]=bytes.fromhex('46f28071')
    r['patches'].append(dict(symbol='native_startup_capacity',site=SIZE_SITE,
                             old='4af68011',new='46f28071'))
    old=stock[IRQ_SITE-BIAS:IRQ_SITE-BIAS+IRQ_BYTES]
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    assert [(i.mnemonic,i.op_str) for i in md.disasm(old,IRQ_SITE)]==[
        ('lsls','r4, r1, #0x17'),('and.w','r3, r3, r2')]
    new=branch(IRQ_SITE,names['raw_irq_hook']&~1)+bytes.fromhex('00bf')
    data[IRQ_SITE-BIAS:IRQ_SITE-BIAS+IRQ_BYTES]=new
    r['patches'].append(dict(symbol='raw_irq_hook',site=IRQ_SITE,old=old.hex(),new=new.hex()))
    struct.pack_into('>I',data,0x1fc,sum(data[0x200:])&0xffffffff);data=bytes(data);validate(data)
    allowed=[(0x1fc,0x200),(SCATTER-BIAS+12,SCATTER-BIAS+16),(DSP_SOURCE-BIAS,END-BIAS),
             (IRQ_SITE-BIAS,IRQ_SITE-BIAS+IRQ_BYTES)]
    allowed.extend((s-BIAS,s-BIAS+4) for s in (*HOOKS.values(),*WAIT_SITES,SIZE_SITE))
    assert len(data)==len(stock) and data[0x2851f8:]==stock[0x2851f8:]
    assert all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(stock,data)) if x!=y)
    r.update(experiment=10,trial_sha256=digest(data),native_capacity_frames=CAP,
      states={n:dict(address=names[n],bytes=size) for n,size in STATES.items()},
      capture_enabled=False,task_created=False,allocation_enabled=False,
      protocol='75/74 raw kinds 1 latest TC / 2 first TC / 3 latest raw error / 4 counters; detail 73/72 and health 7D/7C retained',
      limitations=r['limitations']+[
        'Raw IRQ snapshots are sequential, not transfer-generation, owner or physical completion proofs',
        'Task is the interrupted task; sampled DS_ADDR may have advanced',
        'Only native common IRQ ingress and four fixed data waits are observed; polling/no-IRQ paths are not exhausted',
        'The observer never changes native event mapping, interrupt masks, cache state or error handling',
        'Core cache/TCM registers are read and stored on a TC/error IRQ, never written',
        'Omitted IRQ samples and busy query epochs invalidate complete coverage; stack/timing require hardware validation'])
    return data,r

def build():
    code,names=compiled();data,r=trial(code,names)
    p=OUT/'trial_sd_raw/L6.BIN';p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==data,'Refusing to replace a different prepared image'
    else:p.write_bytes(data)
    (OUT/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','native_capacity_frames')}))
if __name__=='__main__':build()
