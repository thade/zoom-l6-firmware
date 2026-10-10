#!/usr/bin/env python3
"""Prepare passive command/buffer journal 11 locally; never access a device."""
import json,os,struct,subprocess,sys
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
import build_sd_raw_probe as raw
from build_health_probe import ROOT,BIAS,SOURCE,SCATTER,DSP_SOURCE,END
from build_deployment_probe import validate,digest,write_manifest
from build_added_code_probe import branch
ENTRY=raw.ENTRY
ELF=ROOT/'src/diagnostics/sd-command.elf'
OUT=ROOT/'deployment/11_sd_command'
STATES={**raw.STATES,'command_trace':412}
PROGRAM_SITES={0x80069fec:('command_direct_read',4,[('str','fp, [sl, #-0x20]')]),
 0x8006a180:('command_bounce_read',4,[('str','r7, [r6]'),('lsrs','r1, r0, #9')]),
 0x8006abf0:('command_direct_write',4,[('str','r4, [r8, #-0x20]')]),
 0x8006adac:('command_bounce_write',6,[('str','r7, [r6]'),('cmp.w','fp, #1')])}
COMMAND_SITE=0x8006a348

def compiled():
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    roots=['health_sd','completion_wait','raw_irq_hook','command_probe']+[v[0] for v in PROGRAM_SITES.values()]
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
      '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
      '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
      '-DHEALTH_QUERY_CALLBACK=command_completion_dispatch','-DSD_COMPLETION_DETAIL=1',
      '-DSD_COMMAND_OBSERVER=1','-Wl,-T,src/diagnostics/sd_command.ld','-Wl,-e,health_parser',
      *['-Wl,-u,'+n for n in roots],
      'src/diagnostics/health_probe.c','src/diagnostics/sd_completion_probe.c',
      'src/diagnostics/sd_raw_probe.c','src/diagnostics/sd_command_probe.c',
      'src/diagnostics/health_hooks.S','src/diagnostics/sd_raw_hooks.S',
      'src/diagnostics/sd_command_hooks.S','-o',str(ELF)],cwd=ROOT,env=env,check=True)
    with ELF.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==ENTRY
        assert segments[0]['p_filesz']==segments[0]['p_memsz']
        syms={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        return segments[0].data(),syms

def trial(code,syms):
    old_elf,old_states=raw.ELF,raw.STATES
    try:
        raw.ELF,raw.STATES=ELF,STATES
        image,r=raw.trial(code,syms)
    finally:raw.ELF,raw.STATES=old_elf,old_states
    data=bytearray(image);stock=SOURCE.read_bytes();md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    sites={**PROGRAM_SITES,COMMAND_SITE:('command_probe',4,[('push.w','{r4, r5, r6, r7, r8, sb, sl, fp, lr}')])}
    for site,(name,span,expected) in sites.items():
        old=stock[site-BIAS:site-BIAS+span]
        assert [(i.mnemonic,i.op_str) for i in md.disasm(old,site)]==expected,(hex(site),old.hex())
        new=branch(site,syms[name]&~1)+bytes.fromhex('00bf')*((span-4)//2)
        data[site-BIAS:site-BIAS+span]=new
        r['patches'].append(dict(symbol=name,site=site,old=old.hex(),new=new.hex()))
    struct.pack_into('>I',data,0x1fc,sum(data[0x200:])&0xffffffff);data=bytes(data);validate(data)
    allowed=[(0x1fc,0x200),(SCATTER-BIAS+12,SCATTER-BIAS+16),(DSP_SOURCE-BIAS,END-BIAS)]
    allowed += [(p['site']-BIAS,p['site']-BIAS+len(bytes.fromhex(p['new']))) for p in r['patches']]
    assert len(data)==len(stock) and data[0x2851f8:]==stock[0x2851f8:]
    assert all(any(a<=i<b for a,b in allowed) for i,(x,y) in enumerate(zip(stock,data)) if x!=y)
    r.update(experiment=11,trial_sha256=digest(data),
      protocol='71/70 kinds 1 latest completed block packet / 2 latest condition / 3 counters; raw, detail and health retained',
      program_hook_sites=sorted(PROGRAM_SITES),command_hook_site=COMMAND_SITE,
      completion_guard_enabled=False,
      limitations=r['limitations']+[
       'Command-entry task is observed in native Thread context, not a proven physical transfer owner',
       'Per-command raw latch is temporal association only; stale physical sources are not excluded or joined',
       'The four pre-DS_ADDR stores and native packet codes22/23 (read) and32/33 (write) are the bounded observed path',
       'No observer lock is held across command/data waiting; overlap, omissions and changed epochs make observations incomplete',
       'No cache/controller policy, reset, retention, storage gate or extra capture is enabled'])
    return data,r

def build():
    code,syms=compiled();data,r=trial(code,syms)
    path=OUT/'trial_sd_command/L6.BIN';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==data,'Refusing to replace a different prepared image'
    else:path.write_bytes(data)
    write_manifest(OUT/'manifest.json',r)
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','native_capacity_frames')}))
if __name__=='__main__':build()
