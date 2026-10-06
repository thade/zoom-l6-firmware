#!/usr/bin/env python3
"""Size a capture-only binding proposal; never build or write a firmware image.

Candidate addresses are arithmetic inside previously audited intervals, not
approved device allocations. Physical ownership, loader acceptance and stack
headroom are prerequisites that this report deliberately cannot satisfy.
"""
import hashlib,json,struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from build_deployment_probe import SOURCE,STOCK_SHA,validate
from capture_jump_patches import plan as jump_plan

ROOT=Path(__file__).resolve().parents[2]
ELF=ROOT/'src/capture/capture-only.elf'
GAP=(0x80960078,0x80bb9400)
CODE_LIMIT=0x801f5400 # first later scatter destination, not unused-memory proof
CONFIG=dict(stack_words=4096,priority=1,steps_per_pass=4,poll_ticks=1,idle_ticks=25)
LAYOUTS=(('transport','ct_layout'),('router','rr_layout'),('bridge','bridge_layout'),
    ('exchange','exchange_layout'),('lifecycle','life_layout'),('staging','extra_layout'),
    ('manager','manager_layout'),('worker','native_worker_layout'))

def align(n,a=32):return (n+a-1)&-a

def plan():
    stock=SOURCE.read_bytes();assert hashlib.sha256(stock).hexdigest()==STOCK_SHA;validate(stock)
    jumps=jump_plan()
    with ELF.open('rb') as f:
        elf=ELFFile(f)
        symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
        def constant(name,index=0):
            symbol=symbols[name];section=elf.get_section(symbol['st_shndx'])
            offset=symbol['st_value']-section['sh_addr']+4*index
            return struct.unpack_from('<I',section.data(),offset)[0]
        sections=[dict(name=s.name,address=s['sh_addr'],bytes=s['sh_size'],
            alignment=s['sh_addralign'],writable=bool(s['sh_flags']&1),zero_fill=s['sh_type']=='SHT_NOBITS')
            for s in elf.iter_sections() if s['sh_flags']&2 and s['sh_size']]
        # Text/rodata, unwind data and initial values all need a loadable image.
        load_bytes=globals_bytes=0
        for section in sections:
            if not section['zero_fill']:
                load_bytes=align(load_bytes,max(1,section['alignment']))+section['bytes']
            if section['writable']:
                globals_bytes=align(globals_bytes,max(1,section['alignment']))+section['bytes']
        sizes={name:constant(layout) for name,layout in LAYOUTS}
        slot_bytes=constant('exchange_layout',1)
    assert sizes['lifecycle']==1072 and sizes['staging']==4160 and slot_bytes==528
    assert not any(n.startswith(('audio_fixture_','history_','na_','backing_','bn_','sdp_')) for n in symbols)
    cursor=align(GAP[0]);arenas=[]
    for name,size in [('permanent_globals',globals_bytes),*sizes.items(),
                      ('descriptor',40),('worker_config',20),('history_slots',4096*slot_bytes)]:
        cursor=align(cursor);arenas.append(dict(name=name,start=cursor,end=cursor+size,bytes=size));cursor+=size
    end=align(cursor);assert end<=GAP[1]
    loaded_end=0x80001000+struct.unpack_from('<I',stock,0x2851f8)[0]
    code_start=jumps['candidate_code_start'];code_end=align(jumps['candidate_load_end'])
    assert code_start==align(loaded_end)
    assert jumps['globals_end']-jumps['globals_start']==globals_bytes
    assert code_end<CODE_LIMIT
    offset=code_start-0x80000e00
    reserved=stock[offset:offset+code_end-code_start]
    padding_ff=reserved==b'\xff'*(code_end-code_start)
    patches={p['site']:p for p in jumps['patches']}
    hooks=[dict(site=hex(a),adapter=patches[a]['adapter'] if a in patches else n,
        encoding='inline_absolute_jump' if a in patches else 'unencoded_candidate',
        patch_bytes=patches[a]['bytes'] if a in patches else None,
        original_instructions_replayed=patches[a]['replay'] if a in patches else None,
        branch_range_requires_absolute_jump=not (-(1<<24)<=code_start-(a+4)<(1<<24))) for a,n in (
        (0x8001078a,'emulator_audio_outer_hook'),(0x8001078e,'emulator_audio_return_hook'),
        (0x202269f8,'emulator_tap_hook'),(0x2022a776,'emulator_commit_hook'),
        (0x80006908,'emulator_start_hook'),(0x80006918,'emulator_stop_hook'),
        (0x8000b158,'emulator_admit_hook'),(0x80034fc0,'emulator_reject_hook'),
        (0x800483f8,'ct_queue_send'),(0x80034f40,'ct_record_request'),
        (0x80034d18,'ct_stop_request'),(0x80034e58,'ct_play_request'),
        (0x80035038,'ct_stop_argument'),(0x800350d8,'ct_stop_other'),
        (0x8000b78c,'emulator_recorder_drained_hook'))]
    return dict(status='proposal_only_not_deployable',firmware_sha256=STOCK_SHA,
        capture_only_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),compiled_sections=sections,
        placement_elf_sha256=jumps['placement_elf_sha256'],
        code=dict(candidate_start=code_start,candidate_end=code_end,
            initialized_bytes=jumps['candidate_load_end']-code_start,
            normal_emulator_initialized_bytes=load_bytes,
            original_loaded_end=loaded_end,reserved_bytes_all_ff=padding_ff,
            requires='Approve runtime ownership and a loading route: tested offline packed scatter proposal or separately verified MAIN extension',
            packed_loading_proposal='plan_capture_packing.py uses original MAIN length and stock startup decoder; physical loading remains unverified',
            hook_encoding='Two copied RAM sites use tested 8/10-byte inline absolute jumps and complete replay; remaining hooks are unencoded',
            encoded_hooks_proposal='plan_capture_hooks.py adds a separate byte-checked MAIN/startup fixture; storage authorization and physical I/O remain unbound',
            excludes='Remaining hook encodings, startup/global initialization and device-specific integration'),
        ram=dict(candidate_interval=list(GAP),arenas=arenas,used_including_alignment=end-GAP[0],
            remaining=GAP[1]-end,history_frames=4096*64,history_seconds_at_48k=4096*64/48000,
            requires='Approve whole interval ownership, physical extent and cache/DMA behavior; bounded scans are insufficient'),
        worker=dict(experimental_config=CONFIG,stack_bytes=CONFIG['stack_words']*4,task_object_bytes=0x94,
            minimum_heap_payload_bytes=CONFIG['stack_words']*4+0x94,
            allocation='Stock task creator allocates stack/object from the bounded stock heap; account separately from the gap',
            requires='Measure call-chain/interrupt stack headroom, priority and throughput; reserve later stock allocations and include allocator overhead'),
        hooks=hooks,
        startup=dict(initializer_result_site='0x80067a84',registration_candidate='0x800745e8',
            sequence=['Remember successful original task/queue initialization, then successful idle creation',
                'Zero permanent added globals/manager/worker before optional hook entry; register while scheduler stopped',
                'Preserve stock continuation on optional failure; core boot closes audio/control gateways',
                'Install complete whole-callback/control coverage, including copied RAM-code hooks after stock scatter loading',
                'Main authorizes release only after established storage/USB/card-mode admission and joined startup users',
                'Worker prepares a unique TMP; strict whole-callback adoption and first successful block precede live control admission'],
            release_site=None,requires='No stock release site/storage admission provider has been approved'),
        failures=['Extra creation/write/readback failure withholds result and retains TMP; ordinary behavior continues',
            'Uncertain close or native I/O lifetime retains ownership and forbids reset/rearm',
            'A physical join must precede native error-stack unwind; public return alone is insufficient',
            'Missing history, unsupported callback/copy mode, incomplete control coverage or uncertain queue delivery cancels extra capture'],
        acceptance='One exact verified TMP plus byte-identical ordinary input/master files; no pad/seal/settings mutation',
        limitations=['Offline candidate ELF relocation and two jump specifications only; no image construction, installation or device access',
            'Candidate physical addresses are not approved device allocations; startup initialization remains unbound',
            'Full DSP/compression/effects, physical timing, power loss and sustained SD behavior remain unverified'])

def main():
    report=plan();out=ROOT/'analysis/capture_binding_plan.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],report=str(out),
        lifecycle_bytes=next(a['bytes'] for a in report['ram']['arenas'] if a['name']=='lifecycle'),
        proposed_ram_bytes=report['ram']['used_including_alignment'],remaining_ram_bytes=report['ram']['remaining'])))

if __name__=='__main__':main()
