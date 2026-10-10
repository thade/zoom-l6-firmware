#!/usr/bin/env python3
"""Compiled try-only executor and unchanged outer transition bodies, offline.

The test caller retains a whole request and supplies explicit retry scheduling.
This suite does not exercise Main's receive binding; verify_storage_main.py does.
Neither physical joining nor any device/update operation is enabled.
"""
import hashlib,json,struct
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from elftools.elf.elffile import ELFFile
from unicorn import arm_const as A
from verify_storage_lease import LeaseRig,LeaseBoot,Pending,IO_ERROR,scatter_startup
from verify_capture_transitions import Transitions
from verify_capture_integration import IntegrationRig,record
from verify_pad_dispatch import Dispatch,NORMAL,ALTERNATE,COMPLETE
from verify_native_worker import MAIN_SLOT,MAIN_HANDLE,SCHEDULER,HANDLE
from verify_control_transport import TASK
from verify_session_manager import RESET,PREPARE,STOPPED,BLOCKED
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,BIAS
from capture_jump_patches import symbols
from plan_capture_transitions import ELF,plan
from plan_capture_lease import plan as lease_plan
from plan_capture_packing import packing

PLAN=plan();PACK=packing(ELF);N=symbols(ELF)
GLOBALS=tuple(PLAN['packing']['globals'])
OUTPUT=0x20028000
ENTRIES=(0x8000c220,0x8000c288,0x8000c2d8,0x80009b18,0x80009a40)

def setup_model(model,m):
    """Same lower effects as the earlier ordering audit; execute selected body."""
    m.hooks.pop(model.entry,None)
    m.hooks.update(model.m.hooks)
    if model.entry==ENTRIES[4]:
        # Execute mount's outer native wrapper through its no-media branch.
        # Actual native mount/folder/SD chains are covered by separate suites.
        m.hooks[0x8005fc98]=lambda a:model.events.append((0x8005fc98,tuple(a[:2]))) or 2
        m.hooks[0x8000ac80]=lambda a:0
    put32(m,0x8045b620,0xa55a)

def baseline(op,argument,profile=0,mode=0,present=1,status=IO_ERROR):
    r=Transitions(ENTRIES[op],mode,profile,present,status)
    setup_model(r,r.m)
    native=r.invoke([argument,profile])
    return native,r.events,word(r.m,0x8045b620)

class TransitionRig(LeaseRig):
    elf_path=ELF;patch_plan=PLAN;packed=PACK;candidate_globals=GLOBALS
    def __init__(self):
        super().__init__();self.transition_events=[]
        put32(self.m,MAIN_SLOT,MAIN_HANDLE)
    def install(self,op,mode=0,profile=0,present=1,status=IO_ERROR):
        model=Transitions(ENTRIES[op],mode,profile,present,status)
        setup_model(model,self.m);self.transition_events=model.events
    def attempt(self,op,argument=0,profile=0,task=MAIN_HANDLE,gate=None):
        def call():
            self.m.uc.mem_write(OUTPUT,b'\xa5'*8)
            # ARM AAPCS aggregate result uses r0=sret; profile is stack arg 5.
            put32(self.m,self.m.stack,profile)
            self.m.invoke(N['storage_transition_try'],
                          [OUTPUT,self.lease() if gate is None else gate,op,argument])
            return struct.unpack('<2I',self.raw(OUTPUT,8))
        return self.other(call,task)

class TransitionPending(Pending,TransitionRig):pass
class TransitionBoot(LeaseBoot):
    names=N;packed=PACK;patch_plan=PLAN;global_range=GLOBALS

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    base=lease_plan()
    assert GLOBALS==(0x80960080,0x809600e8) and PLAN['packing']['spare_bytes']>=0
    assert [p for p in PLAN['patches'] if p.get('adapter')!='storage_main_receive']==base['patches']
    assert PLAN['DSP_patches']==base['DSP_patches']
    assert PLAN['heap_requested_bytes']==base['heap_requested_bytes']==9887
    assert not any(n.startswith(('pc_','sdp_','backing_','bn_')) for n in N)
    hashes,helpers=scatter_startup(True,pack=PACK)
    assert len(hashes)==8 and helpers[4][3]==104
    b=TransitionBoot();b.boot();b.guard()
    arena=b.arena();gate=arena+word(b.m,N['native_arena_layout']+24)
    assert word(b.m,arena+4)==9887 and word(b.m,gate)==b.manager
    assert bytes(b.m.uc.mem_read(gate+4,12))==bytes(12)
    assert word(b.m,b.worker+8)==4 and b.optional_calls==1
    passed('executor_and_Main_binding_fit_without_new_heap_globals_or_input_queue',
           raw_code_bytes=len(PACK['code']),packed_code_bytes=len(PACK['packed_code']),
           spare_bytes=PLAN['packing']['spare_bytes'],globals_bytes=104,
           original_scatter_and_startup_verified=True)

    for op,argument,profile in ((0,2,0),(0,1,3),(1,2,0),(1,1,1),(2,2,0),
                                (3,1,0),(3,0,1),(4,3,0),(4,1,1),(5,0,0),
                                (0xffffffff,0,0)):
        r=TransitionRig();assert r.boot(release=True)==0;r.install(0)
        assert r.attempt(op,argument,profile)==(12,0)
        assert r.lstate()==1 and not r.transition_events and not r.calls
    r=TransitionRig();assert r.boot(release=True)==0;r.install(0)
    for task in (0,HANDLE,0x21039000):
        assert r.attempt(0,1,task=task)==(12,0) and r.lstate()==1
    put32(r.m,MAIN_SLOT,0);assert r.attempt(0,1)==(12,0)
    put32(r.m,MAIN_SLOT,MAIN_HANDLE);put32(r.m,SCHEDULER,0)
    assert r.attempt(0,1)==(12,0);put32(r.m,SCHEDULER,1)
    r.m.uc.reg_write(A.UC_ARM_REG_IPSR,3)
    try:assert r.attempt(0,1)==(12,0)
    finally:r.m.uc.reg_write(A.UC_ARM_REG_IPSR,0)
    assert r.attempt(0,1,gate=0)==(12,0)
    assert r.lstate()==1 and not r.transition_events and not r.calls
    passed('invalid_parameters_task_scheduler_ISR_and_unbound_gate_never_revoke_or_mutate')

    comparisons=0
    for op in range(5):
        arguments=range(3 if op==4 else 1 if op==3 else 2)
        for argument in arguments:
            for profile in (range(3) if op==0 else (0,)):
                for mode in ((0,1) if op in (2,4) else (0,)):
                    for present in ((0,1) if op in (1,2) else (1,)):
                        for status in (0,IO_ERROR):
                            expected,events,state=baseline(op,argument,profile,mode,present,status)
                            r=TransitionRig();assert r.boot()==0
                            r.install(op,mode,profile,present,status)
                            assert r.attempt(op,argument,profile)==(0,expected)
                            assert r.lstate()==3 and r.transition_events==events
                            assert word(r.m,0x8045b620)==state and not r.calls
                            assert r.admit(2)==12 and r.resume()==12
                            comparisons+=1
    passed('all_five_unchanged_outer_bodies_preserve_arguments_effect_order_and_native_returns',
           comparisons=comparisons)

    # Native outer success is deliberately not a trusted mount observation.
    r=TransitionRig();assert r.boot()==0;r.install(4,mode=0)
    assert r.attempt(4,0)==(0,0) and r.lstate()==3
    assert r.transition_events[0][0]==0x8005fc98
    assert r.admit(2,mount=0)==12
    passed('apparent_native_setup_success_does_not_reopen_capture_or_authorize_mount_generation')

    for op in range(5):
        for phase in ('create','initial_header','audio','final_header','read_header','read_audio',
                      'close_write','close_read'):
            r=TransitionPending();assert r.boot(release=True)==0
            if phase in ('create','initial_header'):
                r.pause=phase;r.wait_pending()
            else:
                r.ready();r.begin_recording()
                for _ in range(5):r.audio_call();r.tick()
                if phase=='audio':r.pause=phase;r.wait_pending(audio=True)
                else:
                    r.pause=phase;r.audio_call();r.stop_recording();r.wait_pending(audio=True)
            frame=r.frame();native_calls=list(r.calls);pending=r.pending
            r.install(op)
            request=(op,1 if op in (0,1,2) else 0,2 if op==0 else 0)
            for _ in range(3):
                assert r.attempt(*request)==(11,0)
                assert r.lstate()&3==2 and r.frame()==frame and r.pending==pending
                assert r.calls==native_calls and not r.transition_events
            # The caller keeps the request. Guard attempts neither wait nor
            # consume packets, and independent audio/control work can progress.
            r.other(r.audio_call,MAIN_HANDLE)
            if r.wire:r.other(r.dispatch_all,MAIN_HANDLE)
            assert r.frame()==frame and r.pending==pending and not r.transition_events
            r.complete();r.retire()
            expected,events,state=baseline(*request)
            assert r.attempt(*request)==(0,expected)
            assert r.transition_events==events and word(r.m,0x8045b620)==state
            assert r.lstate()==3 and not r.opened
    passed('pending_create_headers_audio_readback_and_closes_defer_every_native_body_before_first_effect',
           pending_combinations=40,
           scheduling='explicit separate-stack caller retries; not native Main retention/wakeup')

    r=TransitionPending();assert r.boot(release=True)==0;r.ready();r.begin_recording()
    for _ in range(5):r.audio_call();r.tick()
    r.pause='audio';r.wait_pending(audio=True);r.install(0)
    assert r.attempt(0,1,2)==(11,0)
    r.complete(IO_ERROR);r.retire()
    assert r.attempt(0,1,2)[0]==0 and r.transition_events and not r.opened
    assert r.lstate()==3 and r.result()==12
    passed('physically_joined_write_failure_can_finish_cancellation_then_run_pending_transition')

    ordinary=record(IntegrationRig(enabled=False),delay=2,blocks=23)
    r=TransitionRig();assert r.boot(release=True)==0;r.ready();r.sequence=0;r.install(0)
    r.audio_call();r.begin_recording(2)
    for block in range(23):
        r.audio_call()
        if block==4:assert r.attempt(0,1,2)==(11,0)
        r.tick()
        if r.wire:r.dispatch_all()
    assert r.recording and r.queued_record and not r.transition_events
    r.stop_recording();r.assert_ordinary();r.retire()
    assert {h:bytes(r.files[h]) for h in range(1,8)}==ordinary
    assert r.attempt(0,1,2)[0]==0 and r.transition_events
    passed('transition_request_cancels_only_extra_capture_while_seven_ordinary_files_remain_exact')

    r=TransitionPending();assert r.boot(release=True)==0;r.ready();r.install(3)
    r.pause='close_write';assert r.attempt(3)==(11,0)
    r.wait_pending();assert r.pending[0]=='close_write'
    r.complete(IO_ERROR);r.drive(lambda:r.mstate()==BLOCKED,with_audio=False)
    calls=list(r.calls)
    for _ in range(6):
        assert r.attempt(3)==(11,0) and r.tick()==13 and not r.transition_events
        assert r.calls==calls and r.opened and r.lstate()==2
    passed('uncertain_close_never_releases_native_transition_or_retries_file_close')

    # Deliberately unsafe raw callee binding: execute ORIGINAL Main receive,
    # card/USB handler and following calls. BUSY is ignored and packet consumed.
    for start in (NORMAL,ALTERNATE):
        for code,callee,tail in ((0x32,ENTRIES[3],0x800350d8),(0x33,ENTRIES[2],None)):
            r=Dispatch();seen=[]
            r.m.hooks[0x8001e4d8]=lambda a:0
            r.m.hooks[callee]=lambda a:seen.append(('busy',callee)) or 11
            r.m.hooks[0x800350d8]=lambda a:seen.append(('stop_after_busy',)) or 0
            r.m.hooks[0x8000a5d8]=lambda a:seen.append(('card_tail_after_busy',)) or 0
            r.seed([(0,9 if code==0x32 else 0,code,0,0),COMPLETE]);r.loop(start)
            assert seen[0]==('busy',callee) and not r.events()
            assert ('reload',) in r.effects
            if tail:assert ('stop_after_busy',) in seen
            if start==NORMAL and tail:assert ('card_tail_after_busy',) in seen
    passed('negative_control_raw_callee_BUSY_is_ignored_by_both_real_Main_loops_and_loses_request',
           negative_control=True,native_receiver_dispatch=True)

    # Decode the actual switch tables, rather than relying on a linear scan
    # through inline data being mistaken for code.
    routes={}
    for table,count in ((0x8002c9f2,54),(0x8002d0c2,53)):
        routes[hex(table)]={hex(code):hex(table+2*struct.unpack_from('<H',IMAGE,table-BIAS+2*code)[0])
                            for code in range(count) if code in (0x32,0x33,0x34,0x35)}
    assert routes['0x8002c9f2']['0x32']=='0x8002cdc8'
    assert routes['0x8002c9f2']['0x33']=='0x8002cde8'
    assert routes['0x8002d0c2']['0x32']=='0x8002d49c'
    assert routes['0x8002d0c2']['0x33']=='0x8002d470'
    references={hex(t):[] for t in ENTRIES}
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True
    for addr,size,mnemonic,operands in md.disasm_lite(IMAGE[0x200:0xb5ce4],0x80001000):
        if mnemonic in ('bl','b','b.w') and operands.startswith('#'):
            target=int(operands[1:],0)
            if target in ENTRIES:references[hex(target)].append(hex(addr))
    assert '0x8002ce36' in references[hex(ENTRIES[3])]
    assert '0x8000ab8e' in references[hex(ENTRIES[1])]
    assert '0x8002c48c' in references[hex(ENTRIES[0])]
    assert sum(map(len,references.values()))==20
    pointers={hex(t):IMAGE.count(struct.pack('<I',t|1)) for t in ENTRIES}
    assert not any(pointers.values())
    passed('branch_tables_and_bounded_direct_calls_expose_startup_helper_and_card_USB_parents',
           routes=routes,direct_references=references,literal_Thumb_pointer_matches=pointers,
           exhaustive_indirect_coverage=False)

    with ELF.open('rb') as f:
        e=ELFFile(f);sym=next(s for s in e.get_section_by_name('.symtab').iter_symbols()
                            if s.name=='storage_transition_try')
        section=e.get_section(sym['st_shndx']);offset=(sym['st_value']&~1)-section['sh_addr']
        code=section.data()[offset:offset+sym['st_size']]
        instructions=list(Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS).disasm(code,sym['st_value']&~1))
        assert not any(i.mnemonic.startswith('v') for i in instructions)
    passed('executor_is_integer_only_and_has_no_added_wait_or_retry_loop')

    report=dict(passed=True,device_access=False,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        fixture_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        test_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limitations=[
            'Actual compiled executor, lease/manager and selected unchanged outer native instructions execute.',
            'Lower transition effects, RTOS progress, file bytes and physical I/O joins remain models.',
            'Whole-request ownership/retry is a test caller, not installed native Main control flow.',
            'No safe stock caller hooks, ordered overlap/backpressure, retry wakeup or exhaustive ingress coverage.',
            'Software retirement is not physical completion or trustworthy native mount/USB success.',
            'No source/IRQ/cache ownership provider, image, transfer or device operation.'])
    (ROOT/'analysis/storage_transitions_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),results=cases),indent=2))
if __name__=='__main__':main()
