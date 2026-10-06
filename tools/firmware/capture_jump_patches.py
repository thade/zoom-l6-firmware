#!/usr/bin/env python3
"""Specify two candidate RAM-code jumps. Writes JSON only, never an image.

The placement ELF is for offline experiments. Its code is beyond the stock
MAIN payload length; application scatter-copy evidence cannot approve loading.
"""
import hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from build_deployment_probe import SOURCE,STOCK_SHA,validate

ROOT=Path(__file__).resolve().parents[2]
ELF=ROOT/'src/capture/capture-only-placement.elf'
BIAS=0x80000e00
SCATTER=(0x800a9408,0x20220000,0xd6dc,0x80079498)
SPECS=(dict(site=0x202269f8,adapter='placement_tap_hook',
            original='46f2202020580028',resume=0x20226a00,
            replay=['movw r0,#0x6220','ldr r0,[r4,r0]','cmp r0,#0']),
       dict(site=0x2022a776,adapter='placement_commit_hook',
            original='4bf8010048b0bdec108b',resume=0x2022a780,
            replay=['str.w r0,[r11,r1]','add sp,#0x120','vpop {d8-d15}']))

def symbols(path=ELF):
    with path.open('rb') as f:
        e=ELFFile(f)
        return {s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}

def make_patch(stock,spec,target):
    """Pure encoding with exact-byte/span checks; no writes or allocation."""
    if not (target&1) or not 0x800b6b00<=target<0x801f5400:
        raise ValueError('target must be Thumb code inside the candidate interval')
    site=spec['site'];old=bytes.fromhex(spec['original'])
    offset=SCATTER[0]-BIAS+site-SCATTER[1]
    if stock[offset:offset+len(old)]!=old:raise ValueError('stock instruction bytes differ')
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    instructions=list(md.disasm(old,site))
    if sum(i.size for i in instructions)!=len(old) or site+len(old)!=spec['resume']:
        raise ValueError('patch does not cover complete instructions')
    literal=(site+7)&~3;pc=(site+4)&~3;disp=literal-pc
    patch=struct.pack('<HH',0xf8df,0xf000|disp)
    patch+=b'\x00\xbf'*((literal-site-4)//2)+struct.pack('<I',target)
    if len(patch)!=len(old):raise ValueError('absolute jump exceeds selected span')
    return dict(**spec,source_file_offset=offset,bytes=len(old),target=target,
                literal_address=literal,patch=patch.hex(),
                decoded_original=[f'{i.mnemonic} {i.op_str}' for i in instructions])

def plan(elf_path=ELF):
    stock=SOURCE.read_bytes()
    if hashlib.sha256(stock).hexdigest()!=STOCK_SHA:raise ValueError('unsupported stock firmware')
    validate(stock)
    assert struct.unpack_from('<4I',stock,0x800a691c-BIAS)==SCATTER
    names=symbols(elf_path);patches=[make_patch(stock,s,names[s['adapter']]) for s in SPECS]
    start=names['placement_code_start'];end=names['placement_load_end']
    assert all(start<=p['target']<end for p in patches)
    assert stock[start-BIAS:end-BIAS]==b'\xff'*(end-start)
    with elf_path.open('rb') as f:
        e=ELFFile(f)
        segments=[dict(address=s['p_vaddr'],load_address=s['p_paddr'],
                       initialized_bytes=s['p_filesz'],memory_bytes=s['p_memsz'])
                  for s in e.iter_segments() if s['p_type']=='PT_LOAD']
    # A linear bounded disassembly can find direct branches, but cannot rule
    # out indirect entries, executable/data ambiguity or alternate callbacks.
    ram=stock[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]]
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True
    interiors=[]
    for a,size,mnemonic,ops in md.disasm_lite(ram,SCATTER[1]):
        if mnemonic.startswith('b') or mnemonic in ('cbz','cbnz'):
            try:target=int(ops.rsplit('#',1)[1],0)
            except (IndexError,ValueError):continue
            if any(p['site']<target<p['resume'] for p in patches):
                interiors.append(dict(site=a,target=target,instruction=f'{mnemonic} {ops}'))
    assert not interiors,'direct branch enters a displaced span'
    return dict(status='offline_placement_only_not_deployable',firmware_sha256=STOCK_SHA,
        placement_elf_sha256=hashlib.sha256(elf_path.read_bytes()).hexdigest(),
        segments=segments,patches=patches,direct_interior_branches=interiors,
        original_loaded_end=0x80001000+struct.unpack_from('<I',stock,0x2851f8)[0],
        candidate_code_start=start,candidate_load_end=end,
        globals_start=names['placement_globals_start'],globals_end=names['placement_globals_end'],
        limitations=['Only two RAM sites have byte-level patch specifications; other hooks use emulator interception',
            'Direct branch scan covers copied RAM only, is linear and cannot rule out indirect entries or other origins',
            'MAIN loader acceptance and code loading beyond original length remain unproved',
            'Global initialization, physical RAM ownership, startup admission and native I/O joins are unbound',
            'No firmware image construction, card transfer or device access'])

def main():
    report=plan();out=ROOT/'analysis/capture_jump_plan.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],patches=len(report['patches']),
        code_bytes=report['candidate_load_end']-report['candidate_code_start'],report=str(out))))

if __name__=='__main__':main()
