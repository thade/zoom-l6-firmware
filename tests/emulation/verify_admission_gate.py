#!/usr/bin/env python3
"""Offline ARM admission protocol and selected original scheduling paths.

No firmware patch, USB, MIDI or SD access. Stock queues/RTOS are models.
Activity counts are supplied by this harness, not discovered device hooks.
"""
import hashlib
import itertools
import json
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
from verify_overdub_prototype import Emulator, PORT, ELF
from verify_stock_pad_adapter import StockRig, CONFIG, TEMP
from verify_pad_protocol import ROOT, IMAGE, STACK
from verify_firmware_workflow import put32
from verify_record_catalogue import putstr, getstr

GATE=0x21003800
PROMOTING=0x80000000
FAILED=0x40000000
COUNT=0x3fffffff


def word(m, addr=GATE):
    return struct.unpack('<I', m.uc.mem_read(addr,4))[0]


def gate(m, name, *args):
    return m.invoke(m.symbols['od_gate_'+name], [GATE,*args])


class GatedRig(StockRig):
    def __init__(self):
        super().__init__()
        for index,name in ((7,'enter'),(8,'leave'),(14,'checkpoint')):
            put32(self.m, PORT+index*4, self.m.symbols['od_emulator_gate_'+name]|1)

    def checkpoint(self,a):
        assert word(self.m)==PROMOTING
        assert word(self.m,GATE+4)==1  # competing compiled admission returned BUSY
        return super().checkpoint(a)


def main():
    results=[]
    def passed(case,**data): results.append(dict(case=case,passed=True,**data))

    m=Emulator()
    # Inspect emitted instructions as well as executing them below.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    start=m.symbols['od_gate_work_begin']&~1
    end=m.symbols['od_gate_work_end']&~1
    mnemonics={i.mnemonic for i in md.disasm(bytes(m.uc.mem_read(start,end-start)),start)}
    assert {'ldrex','strex','dmb'}<=mnemonics, mnemonics
    passed('compiled_arm_exclusive_access_and_memory_barriers')

    assert gate(m,'promote_begin')==0
    assert gate(m,'work_begin')==1 and gate(m,'promote_begin')==1
    assert word(m)==PROMOTING
    assert gate(m,'promote_end',0)==0 and word(m)==0
    assert gate(m,'work_begin')==0 and gate(m,'work_end')==0
    passed('exclusive_promotion_blocks_new_work_and_releases')

    # Queue residency, active execution and pending completion all own a count.
    # Labels document intended integration coverage; firmware bindings absent.
    domains=['recording','pad_playback','assignment','catalogue_scan',
             'usb_file_transfer','sampler_file_read','sampler_stream_update']
    for domain in domains:
        m=Emulator()
        assert gate(m,'work_begin')==0
        for phase in ('queued','running','awaiting_completion'):
            assert gate(m,'promote_begin')==1 and word(m)==1, (domain,phase)
        assert gate(m,'work_end')==0 and gate(m,'promote_begin')==0
        assert gate(m,'promote_end',0)==0
    passed('modeled_activity_lifetimes_exclude_promotion',domains=domains)

    # Every API-level ordering of two complete activities and a promotion.
    schedules=0
    for order in itertools.permutations(('a+','a-','b+','b-','p+','p-')):
        if any(order.index(x+'+')>order.index(x+'-') for x in 'abp'):continue
        m=Emulator();active=set();promoting=False;accepted={}
        for op in order:
            name,action=op
            if action=='+':
                expected=not promoting and (not active if name=='p' else True)
                value=gate(m,'promote_begin' if name=='p' else 'work_begin')
                assert value==(0 if expected else 1),(order,op,value)
                accepted[name]=expected
                if expected:
                    if name=='p':promoting=True
                    else:active.add(name)
            elif accepted[name]:
                assert gate(m,'promote_end',0)==0 if name=='p' else gate(m,'work_end')==0
                if name=='p':promoting=False
                else:active.remove(name)
            assert word(m)==(PROMOTING if promoting else len(active))
        assert word(m)==0;schedules+=1
    assert schedules==90
    passed('all_90_api_boundary_orderings',schedules=schedules,
           scope='Not instruction-level preemption or a real RTOS timing test')

    m=Emulator();assert gate(m,'work_begin')==0
    assert gate(m,'promote_begin')==1  # would wait for its own recording
    assert gate(m,'upgrade')==0 and word(m)==PROMOTING
    assert gate(m,'promote_end',0)==0
    assert gate(m,'work_begin')==0 and gate(m,'work_begin')==0
    assert gate(m,'upgrade')==1 and word(m)==2
    assert gate(m,'work_end')==0 and gate(m,'upgrade')==0
    assert gate(m,'promote_end',0)==0
    passed('owned_stop_activity_upgrade_avoids_self_wait',
           caveat='Caller ownership and recording completion are harness assumptions')

    for fn,args in (('work_end',()),('promote_end',(0,))):
        m=Emulator();assert gate(m,fn,*args)==3
        assert word(m)==FAILED and gate(m,'work_begin')==2
    m=Emulator();put32(m,GATE,COUNT)
    assert gate(m,'work_begin')==2 and word(m)==FAILED|COUNT
    passed('underflow_invalid_release_and_overflow_fail_closed')

    m=Emulator();assert gate(m,'work_begin')==0
    gate(m,'fail');assert gate(m,'work_end')==0 and word(m)==FAILED
    assert gate(m,'promote_begin')==2
    m=Emulator();assert gate(m,'promote_begin')==0
    gate(m,'fail');assert gate(m,'promote_end',0)==0 and word(m)==FAILED
    passed('asynchronous_fault_survives_activity_and_promotion_cleanup')

    r=GatedRig()
    for n in range(1,7):assert r.promote(r.take(n))=='ok' and word(r.m)==0
    attempts=word(r.m,GATE+8);assert attempts>100
    passed('six_passes_stock_assignment_with_competing_checkpoint_requests',
           rejected_requests=attempts,pads=r.paths())

    r=GatedRig();path=r.take(1);assert gate(r.m,'work_begin')==0
    assert r.promote(path)=='busy' and r.history()==[]
    assert not any(p.startswith('A:\\SOUND_PAD') for p in r.files)
    assert gate(r.m,'work_end')==0 and r.promote(path)=='ok'
    passed('busy_promotion_does_no_file_work_then_explicit_retry_succeeds')

    r=GatedRig();r.fail=('checkpoint',1,'cancel')
    assert r.promote(r.take(1))=='cancelled' and word(r.m)==0
    r=GatedRig();r.fail=('close',1,'error')
    assert r.promote(r.take(1))=='fault' and word(r.m)==FAILED
    assert gate(r.m,'work_begin')==2
    passed('cancellation_releases_gate_but_uncertain_close_latches_fault')

    # Original producer code: queue send intercepted, not patched/gated.
    r=StockRig();m=r.m;messages=[]
    m.hooks[0x800483f8]=lambda a: messages.append(bytes(m.uc.mem_read(a[1],32))) or 0
    put32(m,0x80578ec0,1)
    m.invoke(0x8004b6d8,[])
    assert struct.unpack_from('<I',messages[0])[0]==0x8004b9a1
    passed('stock_record_start_producer_still_queues_while_worker_busy')

    messages.clear();putstr(m,TEMP,'A:\\SOUND_PAD\\PAD1\\FIRST.WAV')
    m.uc.mem_write(STACK,struct.pack('<II',1,1))
    m.invoke(0x80008c68,[0,TEMP,0,0])
    assert len(messages)==1
    fields=struct.unpack('<8I',messages[0])
    assert fields[:5]==(0x80049d61,0,TEMP,0,0),fields
    assert word(m,0x807348cc)==1
    putstr(m,TEMP,'A:\\SOUND_PAD\\PAD1\\SECOND.WAV')
    assert getstr(m,fields[2]).endswith('SECOND.WAV')
    passed('stock_assignment_queue_retains_path_pointer_not_path_copy')

    # Negative control: a new gate is powerless without stock admission hooks.
    messages.clear();assert gate(m,'promote_begin')==0
    putstr(m,CONFIG+0x798,'A:\\SOUND_PAD\\PAD1\\OLD.WAV')
    m.uc.mem_write(STACK,bytes(8));m.invoke(0x80008c68,[2,0,0,0])
    assert messages==[] and getstr(m,CONFIG+0x798)==getstr(m,0x800a32ea)
    assert word(m)==PROMOTING and word(m,0x807348cc)==0
    passed('negative_control_ungated_stock_clear_bypasses_proposed_gate')

    # Original worker loop serializes callbacks and exposes busy throughout.
    r=StockRig();m=r.m;seen=[];pending=[0x8004ba41,0x8004b9a1]
    def receive(args):
        if not pending:
            m.reached_return=True;m.uc.emu_stop();return 1
        m.uc.mem_write(args[1],struct.pack('<8I',pending.pop(0),0,0,0,0,0,0,0));return 0
    m.hooks[0x800483a8]=receive
    for address,label in ((0x8004ba40,'stop'),(0x8004b9a0,'start')):
        m.hooks[address]=lambda a,label=label: seen.append((label,word(m,0x80578ec0))) or 0
    m.invoke(0x80034bc8,[])
    assert seen==[('stop',1),('start',1)] and word(m,0x80578ec0)==0
    passed('original_record_worker_serializes_callbacks',observed=seen)

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['Offline only; stock firmware unmodified',
          'Gate requires participation at ALL ingress and real completion points',
          'No complete stock activity ledger or USB mode-transition binding',
          'RTOS, SD drivers, audio and asynchronous completion effects modeled',
          '90 schedules cover API boundaries, not arbitrary machine-instruction interleavings',
          'No automatic retry scheduler, busy UI or verified real-time latency'])
    path=ROOT/'analysis/admission_gate_verification.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))


if __name__=='__main__':main()
