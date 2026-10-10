#!/usr/bin/env python3
"""Prepare the fixed candidate reservation trial locally; no device access."""
import hashlib,json,os,struct,subprocess,sys
from elftools.elf.elffile import ELFFile
from build_health_probe import ROOT,ENTRY,END,SOURCE,candidate
from build_timing_probe import HOOKS,PROLOGUES

OUT=ROOT/'deployment/06_reservation_probe'
ELF=ROOT/'src/diagnostics/reservation.elf'
HEAP_ELF=ROOT/'src/capture/capture-only-heap.elf'
SLOTS=128

def budget():
    with HEAP_ELF.open('rb') as f:
        e=ELFFile(f);syms={s.name:s for s in e.get_section_by_name('.symtab').iter_symbols()}
        def words(name):
            s=syms[name];section=e.get_section(s['st_shndx']);offset=s['st_value']-section['sh_addr']
            return struct.unpack('<'+'I'*(s['st_size']//4),section.data()[offset:offset+s['st_size']])
        align=lambda n:(n+31)&~31
        arena=align(words('native_arena_layout')[0])
        for name in ('ct_layout','rr_layout','bridge_layout','exchange_layout','life_layout','extra_layout'):
            arena+=align(words(name)[0])
        slot=words('exchange_layout')[1]
        arena+=align(slot*SLOTS)+align(words('manager_layout')[0])+align(words('native_worker_layout')[0])+31
        assert arena==77279 and slot==528
        sizes=[arena,16384,148]
        charge=sum((n&~7)+16 for n in sizes)
        return dict(slots=SLOTS,arena_request_bytes=arena,worker_stack_request_bytes=sizes[1],
                    worker_task_request_bytes=sizes[2],expected_split_charge_bytes=charge,
                    minimum_free_floor_bytes=65536,preflight_required_free_bytes=charge+48+65536,
                    capture_abi_elf_sha256=hashlib.sha256(HEAP_ELF.read_bytes()).hexdigest())

def compiled():
    subprocess.run([sys.executable,str(ROOT/'tools/firmware/build_extra_capture.py'),'--heap-fixture'],cwd=ROOT,check=True)
    b=budget()
    env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
    subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
        '-mcpu=cortex_m7','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
        '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
        '-DHEALTH_QUERY_CALLBACK=reservation_dispatch',f'-DRESERVATION_ARENA_BYTES={b["arena_request_bytes"]}',
        '-Wl,-T,src/diagnostics/timing.ld','-Wl,-e,health_parser',
        '-Wl,-u,health_sd','-Wl,-u,timing_read','-Wl,-u,timing_write',
        'src/diagnostics/timing_probe.c','src/diagnostics/reservation_probe.c',
        'src/diagnostics/health_hooks.S','src/diagnostics/timing_hooks.S','-o',str(ELF)],cwd=ROOT,env=env,check=True)
    with ELF.open('rb') as f:
        e=ELFFile(f);segments=[s for s in e.iter_segments() if s['p_type']=='PT_LOAD']
        assert len(segments)==1 and segments[0]['p_vaddr']==ENTRY
        seg=segments[0];assert seg['p_memsz']==seg['p_filesz'] and ENTRY+seg['p_memsz']<=END
        syms={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols()}
        return seg.data(),syms,b

def trial(code,syms,b):
    state=syms['timing_stats'];last=syms['reservation_stats']+32
    assert state%32==syms['reservation_stats']%32==0 and state+444<=syms['reservation_stats']
    data,r=candidate(code,syms,elf_path=ELF,hooks=HOOKS,state_name='timing_stats',
                     state_bytes=last-state,prologues=PROLOGUES)
    r.update(experiment=6,budget=b,protocol='79/78 kinds 1 status (read-only), 2 reserve (explicit mutation); 7B/7A timing unchanged',
        timing_state=state,reservation_state=syms['reservation_stats'],reservation_state_bytes=32,
        capture_enabled=False,task_created=False,
        limitations=['Successful reservation holds three unused native allocations until reboot; no worker is created.',
          '64-KiB remaining-heap floor is an experimental admission rule, not proven later stock reserve.',
          'Native allocation instructions and nested scheduling exclusion need device verification.',
          'No audio tap, file operation, extra SD request, pad change, completion or recovery provider is added.',
          'Code/state use the same diagnostic MAIN/DSP-tail placement; arbitrary computed consumers remain uncertain.',
          'Physical timing, stack, contiguous future allocations and extra-capture throughput remain unmeasured.'])
    return data,r

def build():
    code,syms,b=compiled();data,r=trial(code,syms,b)
    for role,payload in (('stock_restore',SOURCE.read_bytes()),('trial_reservation_probe',data)):
        p=OUT/role/'L6.BIN';p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists():assert p.read_bytes()==payload,'Refusing to replace a different prepared image'
        else:p.write_bytes(payload)
    (OUT/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps({k:r[k] for k in ('trial_sha256','code_bytes','state_bytes','budget')}))
if __name__=='__main__':build()
