#!/usr/bin/env python3
"""Byte-checked patch plan for the simplified capture. JSON only, no image."""
import hashlib,json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from build_deployment_probe import SOURCE,STOCK_SHA,validate
from capture_jump_patches import ROOT,BIAS,SCATTER,symbols,plan as jump_plan
from capture_source_reuse_layout import CODE_INTERVAL,GLOBALS_START,GLOBALS_LIMIT
from plan_capture_hooks import make_patch as main_patch
from plan_capture_startup import SPECS as STARTUP_SPECS,make_patch as startup_patch
from plan_capture_transitions import RECEIVERS,receive_patch
from plan_capture_composed import SIZE_SITE
from plan_capture_packing import (TABLE_END_LITERAL,TABLE_END,TABLE_LIMIT,TABLE_TAIL,DECOMPRESS,ZERO,
    report as packing_report)
from scatter_codec import compress,expand

ELF=ROOT/'src/capture/simple/simple-capture.elf'
TRIAL_ELF=ROOT/'src/capture/simple/simple-capture-trial.elf'
TAKE_ELF=ROOT/'src/capture/simple/simple-capture-take.elf'
QUERY_SPEC=dict(site=0x800301f0,original='2de9f047',adapter='health_parser',resume=0x800301f4,
                replay='push.w {r4-r10,lr}',purpose='read-only status query on the Editor parser')
RECORDER_SPECS=(
    dict(site=0x8000b158,original='40f20120',adapter='sc_admit_hook',resume=0x8000b15c,
         replay='movw r0,#0x201',purpose='stock recorder admitted its seven streams'),
    dict(site=0x80006918,original='40f6c852',adapter='sc_stop_hook',resume=0x8000691c,
         replay='movw r2,#0xdc8',purpose='stock stop cursor setter, r0 = final cursor'))
SIZE_PATCH=dict(site=SIZE_SITE,original='4af68011',patch='46f28071',bytes=4,
    purpose='native ring capacity 223104 frames, freeing eight 67,584-byte lane tails')

def align4(n):return (n+3)&~3

def reuse_packing(elf_path):
    """Stock-decoder packing that places code and globals in consumed DSP input.

    Scatter order: patched DSP expands first from the start of its source span,
    then code expands over the consumed bytes, then globals are zeroed. Packed
    code sits beyond both destinations, so no expansion overwrites unread input.
    This is the interval experiment 16 executed from on hardware."""
    stock=SOURCE.read_bytes();jumps=jump_plan(elf_path,source_reuse=True);source,dest,length,_=SCATTER
    assert struct.unpack_from('<I',stock,TABLE_END_LITERAL-BIAS)[0]==TABLE_END
    assert stock[TABLE_END-BIAS:TABLE_LIMIT-BIAS]==bytes(TABLE_LIMIT-TABLE_END)
    dsp=bytearray(stock[source-BIAS:source-BIAS+length])
    for q in jumps['patches']:dsp[q['site']-dest:q['site']-dest+q['bytes']]=bytes.fromhex(q['patch'])
    with elf_path.open('rb') as f:
        segments=[g for g in ELFFile(f).iter_segments() if g['p_type']=='PT_LOAD' and g['p_filesz']]
        assert len(segments)==1 and segments[0]['p_vaddr']==CODE_INTERVAL[0];code=segments[0].data()
    dsp=bytes(dsp);packed_dsp=compress(dsp);packed_code=compress(code)
    assert expand(packed_dsp,len(dsp))==(dsp,len(packed_dsp))
    assert expand(packed_code,len(code))==(code,len(packed_code))
    code_end=CODE_INTERVAL[0]+len(code);g0,g1=jumps['globals_start'],jumps['globals_end']
    if not (code_end<=GLOBALS_START==g0 and g1<=GLOBALS_LIMIT):raise ValueError('reused destinations overflow')
    # The stock zero helper loops on 'subs #4; bne': any other length never ends.
    if g0%4 or (g1-g0)%4 or not g1>g0:raise ValueError('globals must be a nonzero multiple of 4 bytes')
    if TABLE_END+32>TABLE_LIMIT:raise ValueError('extended scatter table reaches the next record source')
    code_source=align4(max(source+len(packed_dsp),GLOBALS_LIMIT));packed_end=code_source+len(packed_code)
    if packed_end>source+length:raise ValueError('packed code exceeds the DSP source span')
    records=(struct.pack('<4I',source,dest,length,DECOMPRESS)+
             struct.pack('<4I',code_source,CODE_INTERVAL[0],len(code),DECOMPRESS)+
             struct.pack('<4I',0,g0,g1-g0,ZERO))
    old_tail=stock[TABLE_TAIL-BIAS:TABLE_END-BIAS]+bytes(32)
    new_tail=records+stock[TABLE_TAIL+16-BIAS:TABLE_END-BIAS]
    assert len(old_tail)==len(new_tail)==96 and old_tail[:12]==records[:12] # same span, now decompressed
    edits=[dict(address=TABLE_END_LITERAL,old=struct.pack('<I',TABLE_END).hex(),
                new=struct.pack('<I',TABLE_END+32).hex(),purpose='extend application scatter table'),
           dict(address=TABLE_TAIL,old=old_tail.hex(),new=new_tail.hex(),
                purpose='patched DSP, then capture code over its consumed input, then zeroed globals')]
    return dict(stock=stock,dsp=dsp,code=code,packed_dsp=packed_dsp,packed_code=packed_code,
                code_source=code_source,packed_end=packed_end,jumps=jumps,edits=edits,source_reuse=True)

def interior_branches(stock,patches):
    """Direct branches into any displaced span, over the final patch list."""
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True;found=[]
    spans=[(p['site'],p['site']+len(bytes.fromhex(p['patch']))) for p in patches]
    regions=[(stock[0x200:0xb5ce4],0x80001000),
             (stock[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]],SCATTER[1])]
    for code,base in regions:
        for address,size,mnemonic,ops in md.disasm_lite(code,base):
            if mnemonic.startswith('b') or mnemonic in ('cbz','cbnz'):
                try:target=int(ops.rsplit('#',1)[1],0)
                except (IndexError,ValueError):continue
                if any(a<target<b for a,b in spans):found.append(dict(site=address,target=target))
    return found

def plan(elf_path=None,trial=False):
    """Capture plan (trial=False); the tap-only trial (True or 'tap': startup,
    ring size, DSP tap/commit and the status query, no recorder or storage
    hooks); or the take trial ('take': every capture site plus the query)."""
    if trial is True:trial='tap'
    elf_path=elf_path or {False:ELF,'tap':TRIAL_ELF,'take':TAKE_ELF}[trial]
    stock=SOURCE.read_bytes()
    if hashlib.sha256(stock).hexdigest()!=STOCK_SHA:raise ValueError('unsupported stock firmware')
    validate(stock);names=symbols(elf_path)
    p=reuse_packing(elf_path);p['names']=names;at=dict(code_interval=CODE_INTERVAL)
    patches=[startup_patch(stock,s,names[s['adapter']],**at) for s in STARTUP_SPECS]
    if stock[SIZE_SITE-BIAS:SIZE_SITE-BIAS+4]!=bytes.fromhex(SIZE_PATCH['original']):
        raise ValueError('stock ring capacity instruction differs')
    patches.append(dict(SIZE_PATCH))
    if trial:patches.append(main_patch(stock,QUERY_SPEC,names['health_parser'],**at))
    if trial!='tap':
        patches+=[main_patch(stock,s,names[s['adapter']],**at) for s in RECORDER_SPECS]
        patches+=[receive_patch(stock,site,old,names['sc_main_receive'],adapter='sc_main_receive',**at)
                  for site,old in RECEIVERS]
    ordered=sorted(patches,key=lambda x:x['site'])
    for a,b in zip(ordered,ordered[1:]):
        if a['site']+len(bytes.fromhex(a['patch']))>b['site']:raise ValueError('MAIN patches overlap')
    # Replayed instructions are re-executed at a new address: none may read PC.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.detail=True
    for q in patches+p['jumps']['patches']:
        if 'adapter' not in q or q['adapter'].startswith('startup_') or q['adapter']=='sc_main_receive':continue
        for i in md.disasm(bytes.fromhex(q['original']),q['site']):
            if 'pc' in i.op_str:raise ValueError(f"displaced PC-relative instruction at {q['site']:#x}")
    interiors=interior_branches(stock,patches+p['jumps']['patches'])
    if interiors:raise ValueError('direct branch enters a displaced span: '+str(interiors))
    pack=packing_report(p)
    return dict(status=f'offline_simple_capture_{trial}_trial_plan' if trial else 'offline_simple_capture_plan_not_deployable',
        firmware_sha256=STOCK_SHA,pack=p,
        elf_sha256=hashlib.sha256(elf_path.read_bytes()).hexdigest(),
        patches=ordered,DSP_patches=p['jumps']['patches'],packing=pack,
        code_bytes=len(p['code']),globals_bytes=p['jumps']['globals_end']-p['jumps']['globals_start'],
        patch_sites=len(patches)+len(p['jumps']['patches']),
        history=dict(blocks=1024,frames=65536,seconds=65536/48000,bytes=1024*512),
        limitations=['JSON only; no container, checksum, staging or installation',
            'Code/globals reuse the consumed DSP source span executed from in experiment 16; lane-tail ownership is unchanged',
            'Worker stack (16 KiB) and SD service under the extra 384,000 B/s are unmeasured on hardware',
            'Linear direct-branch scan cannot exclude indirect entries into displaced spans'])

def main():
    r=plan();r.pop('pack');out=ROOT/'analysis/simple_capture_plan.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(patch_sites=r['patch_sites'],code_bytes=r['code_bytes'],
        globals_bytes=r['globals_bytes'],spare_bytes=r['packing']['spare_bytes'],report=str(out))))
if __name__=='__main__':main()
