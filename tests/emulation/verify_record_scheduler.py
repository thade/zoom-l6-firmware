#!/usr/bin/env python3
"""Original recorder scheduling boundaries; offline deterministic fixtures only.

Includes a negative control for the provisional bridge's early start hook.
No firmware patch, hardware IO, real RTOS scheduling or reclamation fence.
"""
import hashlib,json,struct
from unicorn.arm_const import UC_ARM_REG_R4,UC_ARM_REG_R9
from verify_overdub_prototype import Emulator
from verify_emulator_bridge import BridgeRig,BR
from verify_recording_writer import C,WriterRig
from verify_record_events import UI,REC,START_SAVED
from verify_uncompressed_tap import B,TapRig
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT,IMAGE,BIAS

BUSY=UI+4
QUEUE=0x801f8f38
TOKEN=0x804467f8

def word(m,a):return struct.unpack('<I',m.uc.mem_read(a,4))[0]
def byte(m,a,v):m.uc.mem_write(a,bytes([v]))
def base():
    m=Emulator()
    m.hooks.update({0x80076950:lambda a:1,0x800763d8:lambda a:1})
    return m

def request_setup(m,ui,busy=0):
    byte(m,UI,ui);put32(m,BUSY,busy)
    for fn,value in ((0x80006290,0),(0x8000ac80,1),(0x8000ac70,0),
                     (0x8000ac90,0),(0x80008990,1),(0x80006b48,3),
                     (0x8000ad30,2),(0x80002df8,0),(0x80005fd0,0),
                     (0x80006968,0),(0x80006740,0),(0x80007c20,0)):
        m.hooks[fn]=lambda a,v=value:v
    m.hooks[0x80076950]=lambda a:1
    m.hooks[0x800763d8]=lambda a:1

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))

    # Original setup, with allocation/task creation modeled.
    m=base();alloc=[]
    m.hooks[0x80076c60]=lambda a:1
    m.hooks[0x80076318]=lambda a:0x1111
    def allocate(a):
        handle=0x4000+len(alloc)*16;alloc.append((handle,a[:3]));return handle
    m.hooks[0x80076348]=allocate
    assert m.invoke(0x80048248,[])==0
    assert dict(alloc)[word(m,QUEUE)]==[512,32,0]
    assert dict(alloc)[word(m,0x801f8f2c)]==[1,16,0]
    descriptors=[]
    for a in range(0x800a1bd4,0x800a1bd4+35*24,24):
        row=struct.unpack_from('<6I',IMAGE,a-BIAS)
        if row[0] in (0x80034bc9,0x80037381,0x80039341):
            name=IMAGE[row[1]-BIAS:].split(b'\0',1)[0].decode()
            descriptors.append(dict(address=hex(a),entry=hex(row[0]),name=name,raw_size=row[2]))
    assert len(descriptors)==3
    passed('original_queue_setup_and_distinct_recorder_tasks',descriptors=descriptors,
           control_queue=dict(capacity=512,message_bytes=32),file_queue=dict(capacity=1,message_bytes=16))

    # Failure from queue-send is overwritten by the producer's mutex release.
    for status in (0,0xffffffff):
        for fn,arg,callback in ((0x8004b6d8,0,0x8004b9a1),(0x8004b718,7,0x8004ba41)):
            m=base();messages=[]
            m.hooks[0x800483f8]=lambda a:messages.append(bytes(m.uc.mem_read(a[1],32))) or status
            assert m.invoke(fn,[arg])==1
            assert struct.unpack_from('<I',messages[0])[0]==callback
            if arg:assert struct.unpack_from('<I',messages[0],4)[0]==arg
    passed('producer_return_does_not_report_control_queue_send_failure')

    # Busy describes callback execution, not pending messages. A marker orders
    # earlier callbacks only; a later callback can already be queued behind it.
    m=base();pending=[0x21000201,0x21000211,0x21000221];seen=[];idle_pending=[]
    def receive(a):
        idle_pending.append((word(m,BUSY),len(pending)))
        if not pending:return stop(m)
        m.uc.mem_write(a[1],struct.pack('<8I',pending.pop(0),0,0,0,0,0,0,0));return 0
    m.hooks[0x800483a8]=receive
    for addr,label in ((0x21000200,'old_stop'),(0x21000210,'marker'),(0x21000220,'later_start')):
        m.hooks[addr]=lambda a,label=label:seen.append((label,word(m,BUSY),len(pending))) or 0
    m.invoke(0x80034bc8,[])
    assert seen==[('old_stop',1,2),('marker',1,1),('later_start',1,0)]
    assert idle_pending==[(0,3),(0,2),(0,1),(0,0)]
    passed('busy_zero_and_FIFO_marker_do_not_exclude_pending_or_future_callbacks',
           callbacks=seen,idle_before_receives=idle_pending,
           limitation='FIFO delivery is modeled; no producer admission gate or actual marker installed')

    # The high-level request selects/stores START even for ignored and stop paths.
    outcomes=[]
    for ui,busy,wanted in ((0,0,0x8004b9a1),(0,1,None),(1,0,0x8004ba41),(2,0,None)):
        m=base();request_setup(m,ui,busy);messages=[]
        m.hooks[0x80002478]=lambda a:12345
        m.hooks[0x800483f8]=lambda a:messages.append(word(m,a[1])) or 0
        m.invoke(0x80034f40,[0xffffffff])
        assert word(m,START_SAVED)==12345
        assert messages==([] if wanted is None else [wanted]),(ui,busy,messages)
        outcomes.append(dict(ui=ui,busy=busy,callbacks=[hex(v) for v in messages]))
    passed('start_cursor_setter_is_reached_before_start_stop_or_ignore_classification',outcomes=outcomes)

    # Execute the current compiled bridge with that genuine stop-toggle path.
    r=BridgeRig();r.block();r.start();r.admit();r.block();assert r.pump()==11
    request_setup(r.m,1);messages=[]
    r.m.hooks[0x800483f8]=lambda a:messages.append(word(r.m,a[1])) or 0
    r.m.invoke(0x80034f40,[0xffffffff])
    assert messages==[0x8004ba41]
    assert r.pump()==12 and not r.eligible() and not r.opened
    r.assert_ordinary()
    passed('negative_control_current_early_hook_cancels_on_stock_stop_toggle',
           defect='Current bridge publishes duplicate START before original request queues STOP; hook must be reattributed')

    # These are active state-changing stop helpers, not passive idle getters.
    m=base();byte(m,C+0x10,2);byte(m,C+0xe8,1)
    assert m.invoke(0x80037d68,[])==0 and bytes(m.uc.mem_read(C+0x10,1))==b'\0'
    assert bytes(m.uc.mem_read(0x8077ca26,2))==b'\x01\x02'
    byte(m,C+0xe8,0);assert m.invoke(0x80037d68,[])==1
    m.invoke(0x80037d98,[]);assert bytes(m.uc.mem_read(C+0x10,1))==b'\x02'
    put32(m,C+0x440,1);assert m.invoke(0x80037df0,[])==0
    put32(m,C+0x440,0);byte(m,C+0xe8,1);assert m.invoke(0x80037df0,[])==0
    byte(m,C+0xe8,0);byte(m,C+0x1e88,0);byte(m,C,2)
    assert m.invoke(0x80037df0,[])==1 and bytes(m.uc.mem_read(C,1))==b'\0'
    # No filesystem status is read here.
    put32(m,C+0x1e48,0xffffd825);assert m.invoke(0x80037df0,[])==1
    passed('stock_stop_helpers_disable_production_and_check_activity_but_not_IO_success')

    # 02360's apparent predicate unconditionally clears recording state.
    r=TapRig();m=r.m;put32(m,B+0x53d0,9);byte(m,B+0x53d4,1)
    assert m.invoke(0x80002360,[])==1
    assert word(m,B+0x53d0)==0 and bytes(m.uc.mem_read(B+0x53d4,1))==b'\0'
    passed('audio_stop_helper_returns_one_after_clearing_state_without_waiting_for_callback_return')

    # Actual selection/signal suffix and worker's wait/call loop.
    r=TapRig();m=r.m;signals=[]
    put32(m,0x80446940,0x1234);put32(m,C+0xb8+10*4,64)
    m.hooks[0x800763d8]=lambda a:signals.append(tuple(a[:4])) or 1
    m.uc.reg_write(UC_ARM_REG_R9,C)
    from verify_pad_protocol import REGS
    m.uc.reg_write(REGS[0],10);m.uc.reg_write(REGS[1],11)
    r.window(0x80037b20,0x80037b56)
    assert word(m,C+0xec)==10 and word(m,C+0xf0)==64
    assert bytes(m.uc.mem_read(C+0xe8,1))==b'\x01' and signals==[(0x1234,0,0,0)]
    for wait_status in (0,1):
        m=base();events=[];put32(m,0x80446940,0x1234)
        def wait(a):
            events.append(('wait',a[0],a[1]))
            if len(events)>1:return stop(m)
            return wait_status
        m.hooks[0x80076950]=wait
        m.hooks[0x80038e60]=lambda a:events.append(('producer',)) or 0
        m.invoke(0x80039340,[])
        assert events==[('wait',0x1234,0xffffffff),('producer',),('wait',0x1234,0xffffffff)]
    passed('record_stream_signal_and_separate_worker_wait_call_route_execute',
           limitation='Signal delivery modeled; worker does not branch on wait return')

    # Final write rendezvous: wait/take then give the same token. It ignores a
    # failed wait, so success attribution must not just mean this helper returned.
    for wait_status in (0,1):
        m=base();events=[];put32(m,TOKEN,0x5678)
        m.hooks[0x80076950]=lambda a:events.append(('wait',a[0],a[1])) or wait_status
        m.hooks[0x800763d8]=lambda a:events.append(('give',*a[:4])) or 1
        m.invoke(0x80037358,[])
        assert events==[('wait',0x5678,0xffffffff),('give',0x5678,0,0,0)]
    # Verify normal initialization installs this helper in the producer slot.
    r=TapRig();r.m.uc.reg_write(UC_ARM_REG_R4,C)
    r.window(0x80037f0a,0x80037f42)
    assert word(r.m,C+0x1e20)==0x80037359
    passed('registered_final_write_rendezvous_ignores_wait_failure',
           installed_callback='0x80037359',callback_slot=hex(C+0x1e20))

    # Last-stream completion invokes that rendezvous BEFORE clearing active mask.
    for wait_status in (0,1):
        r=TapRig();m=r.m;events=[]
        m.uc.reg_write(UC_ARM_REG_R4,C);put32(m,C+0x440,1<<10)
        m.uc.reg_write(REGS[0],10)
        put32(m,C+0x1e20,0x80037359);put32(m,TOKEN,0x5678)
        m.uc.mem_write(m.stack+0x30,struct.pack('<I',10))
        m.hooks[0x80076950]=lambda a:events.append(('wait',word(m,C+0x440))) or wait_status
        m.hooks[0x800763d8]=lambda a:events.append(('give',word(m,C+0x440))) or 1
        r.window(0x80039304,0x8003933a)
        assert events==[('wait',1024),('give',1024)] and word(m,C+0x440)==0
    passed('last_stream_active_bit_clears_after_rendezvous_even_if_wait_failed')

    # The file worker gives that same token after a write attempt, including
    # failed/short writes. Completion and successful data storage are distinct.
    for failure,expected in ((None,0),((0,128),0xffffd826),((0xffffd825,0),0xffffd825)):
        r=WriterRig();r.header();r.master_block([0]*64,[0]*64);r.produce()
        m=r.m;put32(m,TOKEN,0x5678);r.fail_write=failure;signals=[]
        m.hooks[0x800763d8]=lambda a:signals.append((a[0],len(r.write_calls),word(m,C+0x1e48))) or 1
        before=len(r.write_calls);r.drain()
        assert signals==[(0x5678,before+1,expected)]
    passed('file_worker_completion_token_follows_write_attempt_including_short_and_failed_writes')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        prototype_sha256=hashlib.sha256((ROOT/'src/capture/capture.elf').read_bytes()).hexdigest(),
        limitations=['Original instruction windows with explicit state, queue and wait fixtures',
          'Includes confirmed negative control against provisional bridge; passing tests do not mean device-ready',
          'No full stop/backend/filesystem execution or arbitrary RTOS preemption',
          'No new worker installed, no producer exclusion, no retirement or audio-reader fence'])
    path=ROOT/'analysis/record_scheduler_verification.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))

if __name__=='__main__':main()
