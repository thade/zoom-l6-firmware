#!/usr/bin/env python3
"""Original USB driver lifecycle audit. Hardware/RTOS effects are fixtures.
No changes to prototype readiness ports and no physical USB or SD access.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from verify_overdub_prototype import Emulator,ELF
from verify_pad_protocol import ROOT,IMAGE,BIAS
from verify_firmware_workflow import put32
from verify_storage_readiness import callees,word
from verify_storage_lifetimes import instructions
from verify_scheduling_boundaries import stop
UP=0x802142b5;MID=0x802142b8;LOW=0x808e0d44
CORE=0x21008000;DEV=0x8095ffe0;DESC=0x21009000
MSC=0x8023d120;LUN=0x801f8e5c;CALLBACK=0x2100a000;PARAM=0x2100b000

def stubs(m,start,end,events,results=None,keep=()):
    results=results or {}
    for fn in callees(start,end)-set(keep):
        def called(a,fn=fn):events.append((hex(fn),*a[:2]));return results.get(fn,0)
        m.hooks[fn]=called

def initialized():
    m=Emulator();m.uc.mem_write(UP,b'\x01\x01\x01');m.uc.mem_write(MID,b'\x01\x01')
    m.uc.mem_write(LOW,struct.pack('<3I',0x101,CORE,DEV))
    m.uc.mem_write(CORE,struct.pack('<2I',1,1))
    m.uc.mem_write(DEV,b'\x01\x01');put32(m,DEV+0x28,0x800718a1)
    put32(m,0x80960028,DESC)
    return m

def outer_stop(fail_core=False,fail_device=False):
    m=initialized();events=[]
    def core(a):events.append(('core_stop',a[0]));return 0xffff1234 if fail_core else 0
    def device(a):events.append(('device_stop',));return 0 if fail_device else 1
    m.hooks[0x800451f8]=core;m.hooks[0x800718a0]=device
    # Execute original stop wrappers/teardown and their state mutations. Only
    # the final class-specific cleanup effects are intercepted here.
    for fn in (0x80044f98,0x80044fd8):m.hooks[fn]=lambda a,fn=fn:events.append((hex(fn),)) or 0xffff1234
    result=m.invoke(0x8003b558,[])
    return m,result,events

def start(failure=None,valid=True):
    m=Emulator();events=[];m.uc.mem_write(UP,b'\x01\0\0');m.uc.mem_write(MID+0x9c,b'\x01')
    for offset in (0x2c,0x30,0x34,0x60,0x64):put32(m,PARAM+4+offset,1)
    if not valid:put32(m,PARAM+4+0x30,0)
    for fn in callees(0x8003aeb8,0x8003af90)-{0x80001754}:
        def called(a,fn=fn):
            events.append(hex(fn))
            if fn==0x80053b68:return DESC
            return int(fn!=failure)
        m.hooks[fn]=called
    result=m.invoke(0x8003b5a8,[PARAM]);return m,result,events

def core_stop(failure=0,current=0x1111):
    m=Emulator();events=[]
    for a,v in ((0x80213d60,0x1111),(0x80213884,0x2222),(0x80213d5c,0x3333),
                (0x80213894,0x4444),(0x80213898,0x5555)):put32(m,a,v)
    stubs(m,0x800412c8,0x80041388,events)
    m.hooks[0x80044bd8]=lambda a:events.append(('endpoint_stop',)) or failure
    def task(a):put32(m,a[0],current);return 0
    m.hooks[0x80032810]=task
    # All modeled cleanup calls fail; result should still be only endpoint result.
    for fn in (0x800328b8,0x80032240,0x80032210,0x80032228,0x80032230,0x80032260):
        m.hooks[fn]=lambda a,fn=fn:events.append((hex(fn),a[0])) or 0xffff1234
    result=m.invoke(0x800412c8,[]);return m,result,events

def endpoint_stop(progress=True):
    m=Emulator();events=[];m.uc.mem_map(0x402e0000,0x1000)
    base=0x808e0814
    for i in range(16):m.uc.mem_write(base+0xec+i*64+8,b'\xff')
    ep=base+0xec+6*64 # endpoint 3 OUT: not a special skipped endpoint
    m.uc.mem_write(ep+8,b'\x02');put32(m,ep+0x10,8)
    put32(m,ep+0x20,DESC);put32(m,ep+0x24,PARAM)
    m.uc.mem_write(PARAM,b'\xa5'*32)
    stubs(m,0x80044bd8,0x80044d90,events,keep=(0x8000178e,))
    reads=[]
    def poll(uc,a,n,u):
        reads.append(a)
        if progress and len(reads)==3:put32(m,0x402e01b4,0)
        if not progress and len(reads)==5:stop(m)
    m.uc.hook_add(UC_HOOK_CODE,poll,begin=0x80044c40,end=0x80044c40)
    m.hooks[0x80072f08]=lambda a:0
    result=m.invoke(0x80044bd8,[])
    return m,result,events,reads,ep

def mass_stop(wait_result=1,pending=False):
    m=Emulator();events=[]
    for off,val in ((0x5c,0x1001),(0x60,0x1002),(0x64,0x1003),(0x68,0x1004)):put32(m,MSC+off,val)
    stubs(m,0x80066dd8,0x80066e42,events,keep=(0x800328f0,))
    m.hooks[0x800328a8]=lambda a:0
    def wait(a):
        events.append(('wait',*a[:2]))
        if pending:return stop(m)
        return wait_result
    m.hooks[0x80076950]=wait
    result=m.invoke(0x80066dd8,[]);return m,result,events

def mass_worker(callback_result=0,luns=1,native=False):
    m=Emulator();events=[]
    put32(m,MSC+0x5c,0x1001);put32(m,MSC+0x64,0x1003)
    m.uc.mem_write(MSC+0x57,bytes([luns]))
    put32(m,LUN,DESC);put32(m,LUN+4,0x9876);m.uc.mem_write(LUN+0x13,b'\x02')
    put32(m,DESC,CALLBACK|1);m.uc.mem_write(DESC+0x10,b'\x03')
    m.hooks[0x800328d8]=lambda a:0
    def flags(a):
        if a[1]==0xfffffdff:put32(m,a[3],0x400);return 0
        assert a[1]==0x30
        return 0xffffffce # no unrelated reset event
    m.hooks[0x80032848]=flags
    def cb(a):
        p=bytes(m.uc.mem_read(a[0],20));events.append(('storage_callback',p.hex()))
        assert p[0]==6 and p[1]==3 and int.from_bytes(p[4:8],'little')==0x9876 and p[8]==4
        return callback_result
    m.hooks[CALLBACK]=cb
    if native:
        m.uc.mem_map(0x400fc000,0x1000)
        put32(m,DESC,0x80068379);m.uc.mem_write(DESC+0x10,b'\x01')
        m.uc.mem_write(0x801f5fbc,b'\x01');put32(m,0x801f5fc0,0x1005)
        m.hooks[0x80076950]=lambda a:events.append(('unit_lock',*a[:2])) or 1
        def forbidden(a):raise AssertionError('operation6/mode4 unexpectedly entered SD backend')
        for fn in (0x80068fa0,0x80068da8,0x800688d0,0x80069488,0x80068db0,0x80068e40,0x800685a8,0x800687a0):
            m.hooks[fn]=forbidden
    m.hooks[0x800763d8]=lambda a:events.append(('unit_unlock' if a[0]==0x1005 else 'ack',a[0])) or 1
    m.hooks[0x80032898]=lambda a:events.append(('park',)) or stop(m)
    m.invoke(0x80065a60,[]);return m,events

def mass_cleanup(error=0):
    m=Emulator();events=[];m.uc.mem_write(MSC+0x57,b'\x01')
    put32(m,LUN,DESC);put32(m,LUN+4,0x9876);m.uc.mem_write(LUN+0x13,b'\x02')
    put32(m,DESC,CALLBACK|1);m.uc.mem_write(DESC+0x10,b'\x03')
    def cb(a):events.append(bytes(m.uc.mem_read(a[0],20)).hex());return error
    m.hooks[CALLBACK]=cb
    result=m.invoke(0x80065568,[]);return m,result,events

def storage_request(operation=6,mode=4,wait_result=1,backend_error=0):
    m=Emulator();m.uc.mem_map(0x400fc000,0x1000);events=[]
    m.uc.mem_write(0x801f5fbc,b'\x01');put32(m,0x801f5fc0,0x1005)
    p=bytearray(20);p[0]=operation;p[1]=1;p[8]=mode
    m.uc.mem_write(PARAM,bytes(p))
    m.hooks[0x80076950]=lambda a:events.append(('lock',*a[:2])) or wait_result
    m.hooks[0x800763d8]=lambda a:events.append(('unlock',a[0])) or 1
    for fn in (0x80068fa0,0x80068da8,0x800688d0,0x80069488,0x80068db0,0x80068e40,0x800685a8,0x800687a0):
        m.hooks[fn]=lambda a,fn=fn:events.append((hex(fn),*a[:2])) or backend_error
    result=m.invoke(0x80068378,[PARAM]);return m,result,events

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    for failed in (None,0x80053178,0x8006c500,0x800727b8,0x800727e8,0x80072998):
        m,r,e=start(failed)
        assert r==int(failed is None) and m.uc.mem_read(UP+1,2)==b'\x01\x01'
        assert m.uc.mem_read(MID+1,1)==bytes([int(failed is None)])
        if failed==0x80072998:assert e[-1]=='0x80072490'
    passed('outer_start_sets_active_even_when_original_lower_start_returns_failure_at_five_stages')
    m,r,e=start(valid=False);assert r==0 and not e and m.uc.mem_read(UP+1,1)==b'\x01'
    passed('invalid_start_configuration_can_leave_outer_active_without_any_lower_setup')
    m=Emulator();m.uc.mem_write(UP,b'\x01\x01\x01');calls=[]
    m.hooks[0x8003aeb8]=lambda a:calls.append(a) or 1
    assert m.invoke(0x8003b5a8,[PARAM])==0 and not calls
    passed('active_outer_start_refuses_retry_without_reinitializing_state')

    for core,dev in ((False,False),(True,False),(False,True),(True,True)):
        m,r,e=outer_stop(core,dev)
        assert r==1 and m.uc.mem_read(UP+1,1)==b'\0' and m.uc.mem_read(MID,2)==b'\0\0'
        assert word(m,LOW)==0 and word(m,LOW+4)==0 and word(m,LOW+8)==0
        assert word(m,CORE)==0
        assert bool(word(m,CORE+4))==core
        assert bool(m.uc.mem_read(DEV+1,1)[0])==dev
    passed('native_stop_chain_returns_one_and_clears_outer_handles_despite_failed_core_or_device_stop',
           limitation='Injected lower-call failures; not a reproduced physical-device failure')
    m=initialized();m.uc.mem_write(UP+1,b'\0');calls=[]
    m.hooks[0x8003acc0]=lambda a:calls.append(a) or 1
    assert m.invoke(0x8003b558,[])==0 and not calls and word(m,LOW)
    passed('inactive_outer_stop_skips_lower_live_fixture_state_return_zero_is_not_universal_success')

    for current in (0x1111,0x3333):
        for error in (0,0xffff1234):
            m,r,e=core_stop(error,current)
            assert r==error
            assert all(word(m,a)==0 for a in (0x80213d60,0x80213884,0x80213d5c,0x80213894,0x80213898))
            assert ('0x80032260',0) in e if current==0x3333 else ('0x80032240',0x3333) in e
    passed('core_stop_returns_endpoint_result_only_and_discards_task_event_cleanup_failures_in_both_context_branches')

    m,r,e,p,ep=endpoint_stop();assert r==0 and len(p)==3 and word(m,ep+0x24)==0
    assert bytes(m.uc.mem_read(PARAM,32))==bytes(32) and word(m,DESC+8)==1
    passed('original_endpoint_shutdown_polls_hardware_flush_before_discarding_transfer_descriptor',
           limitation='Register clears are fixture events; no physical DMA completion is proven')
    m,r,e,p,ep=endpoint_stop(False);assert len(p)==5 and word(m,ep+0x24)==PARAM
    assert bytes(m.uc.mem_read(PARAM,32))==b'\xa5'*32
    passed('uncleared_hardware_flush_stays_in_poll_and_does_not_reach_descriptor_cleanup',
           observation='Stopped emulator after five reads; loop has no software timeout in this range')

    for wait in (0,1):
        m,r,e=mass_stop(wait);assert r==0
        assert ('0x80032888',0x1001,0x400) in e and ('wait',0x1003,0xffffffff) in e
        assert all(word(m,MSC+off)==0 for off in (0x5c,0x60,0x64,0x68))
        assert any(x[0]=='0x80065568' for x in e)
    passed('mass_storage_stop_sends_0x400_waits_on_completion_then_clears_resources_even_after_failed_wait')
    m,r,e=mass_stop(pending=True)
    assert e[-1]==('wait',0x1003,0xffffffff) and word(m,MSC+0x60)==0x1002
    assert not any(x[0]=='0x80065568' for x in e)
    passed('pending_mass_storage_worker_reply_prevents_caller_teardown_in_modeled_scheduler')

    for error in (0,0xffff1234):
        m,e=mass_worker(error)
        assert [x[0] for x in e]==['storage_callback','ack','park'] and e[1]==('ack',0x1003)
    passed('original_mass_storage_worker_calls_operation6_mode4_then_acknowledges_and_parks_even_after_callback_error')
    m,e=mass_worker(luns=0);assert e==[('ack',0x1003),('park',)]
    passed('mass_storage_worker_without_registered_units_acknowledges_without_storage_callback')

    for error in (0,0xffff1234):
        m,r,e=mass_cleanup(error)
        assert r==error and [bytes.fromhex(x)[0] for x in e]==[5,1]
        assert m.uc.mem_read(MSC+0x57,1)==b'\0' and m.uc.mem_read(LUN+0x13,1)==b'\0'
    passed('post_worker_cleanup_calls_storage_operations5_and1_and_clears_registration_despite_callback_errors')

    # The configured low-level device stop callback only toggles one byte.
    m=Emulator();m.uc.mem_write(0x808e2eb4,b'\x01')
    assert m.invoke(0x800718a0,[])==1 and m.uc.mem_read(0x808e2eb4,1)==b'\0'
    assert m.invoke(0x800718a0,[])==0
    passed('default_device_stop_callback_only_clears_software_state_not_a_transfer_join')

    m,e=mass_worker(native=True)
    assert e==[('unit_lock',0x1005,0xffffffff),('unit_unlock',0x1005),('ack',0x1003),('park',)]
    passed('worker_stop_through_actual_registered_storage_dispatcher_mode4_only_locks_unlocks_then_acknowledges_no_SD_backend_call')
    m,r,e=storage_request();assert r==0 and e==[('lock',0x1005,0xffffffff),('unlock',0x1005)]
    assert word(m,0x400fc080)==0
    m,r,e=storage_request(wait_result=0);assert r==0xffffd8ef and e==[('lock',0x1005,0xffffffff)]
    passed('actual_mode4_callback_is_serialization_only_and_propagates_unit_lock_failure')
    for operation,target in ((1,'0x80068da8'),(5,'0x80069488')):
        m,r,e=storage_request(operation=operation)
        assert target in [x[0] for x in e] and r==0
    m,r,e=storage_request(mode=6);assert r==0 and '0x800687a0' in [x[0] for x in e]
    passed('storage_dispatch_positive_controls_reach_distinct_backend_calls_for_other_cleanup_and_mode_operations')

    windows=[(0x8003acc0,0x8003ace4),(0x8003aeb8,0x8003afac),(0x8003b558,0x8003b5e8),
      (0x80072440,0x800724d4),(0x80072998,0x80072a34),(0x80073b78,0x80073bbc),
      (0x800735d0,0x80073698),(0x800412c8,0x80041390),(0x80044bd8,0x80044d90),
      (0x80066dd8,0x80066e42),(0x80065a60,0x80065c4c),(0x800654b0,0x80065608),
      (0x80071df2,0x80071e68),(0x800718a0,0x800718ba),(0x800327c8,0x80032808),
      (0x800328f0,0x800328f8),(0x800682d8,0x80068318),(0x80068378,0x800684b8)]
    lines=[]
    for a,b in windows:
        lines.append(f'\n# {a:08x}..{b:08x}')
        lines.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(a,b))
    (ROOT/'analysis/usb_driver_lifetime_disassembly.txt').write_text('\n'.join(lines)+'\n')
    table=struct.unpack_from('<24I',IMAGE[0x800a1298-BIAS:0x800a12f8-BIAS])
    out=ROOT/'analysis/usb_driver_lifetime_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      storage_registration_table=[hex(x) for x in table],limitations=[
      'Original routine control flow executes with synthetic RAM; RTOS scheduling/waits, class cleanup effects and hardware flush register updates are modeled',
      'Failures are injected negative controls, not reproduced hardware bugs; register polling is not proof of physical DMA completion',
      'Actual registered storage callback operation6/mode4 takes/releases the unit semaphore but performs no SD backend call; outstanding asynchronous SD work is not proven joined',
      'No replacement native checked worker, positive publication readiness, firmware patch, hardware access or SD writes']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
