#!/usr/bin/env python3
"""Execute stock USB-mode and sampler scheduling code offline.

Queue/semaphore scheduling, device drivers and hardware registers are modeled.
Separate Unicorn instances represent producer and worker contexts; this is not
full RTOS emulation. No device communication or firmware patching is present.
"""
import hashlib
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_LR
from verify_overdub_prototype import Emulator, ELF
from verify_admission_gate import gate, word, GATE
from verify_pad_protocol import ROOT, IMAGE
from verify_firmware_workflow import put32

BASE=0x80735180
BUFFER=0x21006000
CALLBACK=0x21000100
MODE=0x80440dc8+0x2340


def stop(m):
    m.reached_return=True
    m.uc.emu_stop()
    return 0


def sampler(kind=0,error=0,short=False,handle=0x1234,prior_error=0):
    producer,worker,control=Emulator(),Emulator(),Emulator()
    events=[];queued=[];signals=[]
    assert gate(control,'work_begin')==0
    def busy(label):
        assert gate(control,'promote_begin')==1
        events.append(label)
    slot=BASE+0x9a0
    put32(worker,slot+4,handle);put32(worker,slot+12,CALLBACK)
    put32(worker,slot+16,prior_error)
    worker.uc.mem_write(BUFFER,b'?'*16)
    put32(producer,0x801f8f30,0x6000)
    for m in (producer,worker):
        put32(m,0x804467fc,0x6001);put32(m,0x80446800,0x6002)
    def enqueue(a):
        busy('queued');assert a[0]==0x6000
        queued.append(bytes(producer.uc.mem_read(a[1],16)))
        return 0
    def dequeue(a):
        if not queued:return stop(worker)
        worker.uc.mem_write(a[1],queued.pop(0));return 0
    def read(a):
        busy('read');assert a[:3]==[handle,BUFFER,16]
        n=7 if short else 16
        worker.uc.mem_write(BUFFER,b'R'*n);put32(worker,a[3],n)
        return error
    def seek(a):
        busy('seek');assert a[:3]==[handle,123,2]
        return error
    def callback(a):
        busy('error_callback');assert a[0]==error
        return 0
    def signal(a):
        busy('worker_signal');signals.append(a[0]);return 0
    def wait(a):
        busy('producer_wait')
        worker.invoke(0x80036118,[])
        assert signals==[0x6001+kind]
        assert a[:2]==[0x6001+kind,0xffffffff]
        busy('wait_resumes');return 1
    producer.hooks.update({0x800483f8:enqueue,0x80076950:wait})
    worker.hooks.update({0x800483a8:dequeue,0x80060620:read,
        0x8005f168:seek,0x800763d8:signal,CALLBACK:callback})
    result=producer.invoke(0x80036208 if kind==0 else 0x80036250,
        [0,BUFFER if kind==0 else 123,16 if kind==0 else 2])
    busy('producer_returned')
    assert gate(control,'work_end')==0
    assert gate(control,'promote_begin')==0
    assert result==1  # semaphore success, NOT the file-operation result
    if handle:
        assert ('seek' if kind else 'read') in events
        assert word(worker,slot+16)==(prior_error or error)
        assert ('error_callback' in events)==bool(error and not prior_error)
        if short and not error and not prior_error:
            assert bytes(worker.uc.mem_read(BUFFER,16))==b'R'*7+bytes(9)
    else:assert not ({'read','seek','error_callback'}&set(events))
    return dict(events=events,file_error=word(worker,slot+16),producer_return=result)


def usb_worker(selector,success=True):
    m=Emulator();events=[];requests=[];delivered=False
    # These are private emulated memory pages, not host/hardware register access.
    for address,size in ((0x401b0000,0x10000),(0x401f8000,0x1000),(0xe000e000,0x1000)):
        m.uc.mem_map(address,size)
    for offset,value in ((0,0x7000),(12,0x7001),(24,0x7002)):
        put32(m,0x801f9108+offset,value)
    flags={5:0x20,6:0x40,7:0x80,8:0x100,9:0x200,10:0x400}
    def wait(a):
        nonlocal delivered
        assert a[0]==0x7000
        if delivered:return stop(m)
        delivered=True;put32(m,0x801f910c,flags[selector]);put32(m,0x801f9110,0)
        return 0
    def start(a):
        requests.append(struct.unpack('<H',m.uc.mem_read(a[0]+4,2))[0])
        events.append('usb_start_attempt');return int(success)
    def signal(a):
        if a[0]==0x7001:events.append('transition_acknowledged')
        return 0
    for fn in (0x8003b580,0x80073ec8,0x80073f18,0x80025f78,
        0x8001bcd8,0x8001bc98,0x800684b8,0x80026bf0,
        0x8001bc20,0x8003b5d0):m.hooks[fn]=lambda a:0
    m.hooks.update({0x80076950:wait,0x800763d8:signal,0x8003b5a8:start})
    m.invoke(0x80045cf0,[])
    assert events==['usb_start_attempt','transition_acknowledged'],events
    assert m.uc.mem_read(0x80212e00,1)==bytes([int(success)])
    return dict(selector=selector,configuration=requests[0],events=events,
                start_success=success)


def usb_transition(enter,profile=1,card=True,mount_result=0):
    m=Emulator();events=[]
    put32(m,MODE,0 if enter else 1)
    def event(name,result=0):
        def fn(a):events.append(dict(op=name,args=a[:2],mode=word(m,MODE)));return result
        return fn
    m.hooks.update({0x800345f8:lambda a:0,
        0x80009b18:event('release_card'),0x80061f60:event('storage_prepare'),
        0x80077686:event('delay'),0x8003b7e0:event('usb_mode_request'),
        0x8003b8a0:event('usb_stop'),0x8005f0d0:event('filesystem_reset'),
        0x8001fca0:event('card_detect',int(card)),
        0x80009a40:event('mount_scan_reload',mount_result)})
    m.invoke(0x8000c220 if enter else 0x8000c288,[1,profile])
    assert word(m,MODE)==(1 if enter else 0)
    if enter:
        assert [e['op'] for e in events]==['release_card','storage_prepare','delay','usb_mode_request']
        assert events[-1]['args'][0]==6+2*profile
        assert all(e['mode']==0 for e in events)
    else:
        assert [e['op'] for e in events]==['usb_stop','filesystem_reset','card_detect',
            'mount_scan_reload' if card else 'release_card']
        assert all(e['mode']==1 for e in events)
    return dict(events=events,final_mode=word(m,MODE),mount_result=mount_result)


def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    for kind in (0,1):
        name='seek' if kind else 'read'
        for error in (0,0xffffd825):
            passed(name+('_error' if error else '_success')+'_waits_for_worker',
                   **sampler(kind,error))
        passed(name+'_missing_handle_still_completes',**sampler(kind,handle=0))
        passed(name+'_existing_error_suppresses_callback',
               **sampler(kind,0xffffd825,prior_error=0xffffd759))
    passed('successful_short_read_zero_fills_remainder',**sampler(short=True))

    m=Emulator();calls=[]
    m.hooks[0x800483f8]=lambda a:calls.append('queue') or 0
    m.hooks[0x80076950]=lambda a:calls.append('wait') or 0
    for args in ([4,BUFFER,16],[0,0,16]):m.invoke(0x80036208,args)
    m.invoke(0x80036250,[4,123,2]);assert calls==[]
    passed('invalid_sampler_requests_do_not_queue_or_wait')

    for producer_address in (0x80036208,0x80036250):
        m=Emulator();events=[]
        def enqueue_failed(a):events.append('queue_failed');return 0xffffffff
        def unexpected_wait(a):events.append('wait_attempted');return 0
        m.hooks.update({0x800483f8:enqueue_failed,0x80076950:unexpected_wait})
        assert m.invoke(producer_address,[0,BUFFER,16])==0
        assert events==['queue_failed','wait_attempted']
    passed('sampler_producers_wait_even_if_queue_send_fails')

    m=Emulator();queued=[]
    m.hooks[0x800483f8]=lambda a:queued.append(bytes(m.uc.mem_read(a[1],16))) or 0
    m.hooks[0x80076950]=lambda a:0
    assert m.invoke(0x80036208,[0,BUFFER,16])==0 and len(queued)==1
    passed('failed_wait_can_return_with_sampler_job_still_queued',
           implication='Producer return alone cannot release admission after a failed wait')

    # Actual stream-completion routine and its early-cancel path.
    for cancelled in (False,True):
        m=Emulator();m.hooks[0x8001aaa0]=lambda a:0;m.hooks[0x8001aab8]=lambda a:0
        m.uc.mem_write(BASE+0x1c,b'\x01');m.uc.mem_write(BASE+0x330,bytes([cancelled]))
        m.invoke(0x800369a8,[0,0,0,0])
        assert m.uc.mem_read(BASE+0x1c,1)==bytes([cancelled])
        passed('stream_'+('early_cancel_retains_pending_flag' if cancelled else 'zero_work_clears_pending_flag'))

    # Connect a compiled completion bridge to the ORIGINAL worker's call site.
    # Producer admission and ownership of these two messages are test fixtures.
    for owned in (True,False):
        m=Emulator();pending=[(0,0,0,0),(1,0,0,0)];counts=[]
        m.uc.mem_write(BASE+0x330,b'\x01')  # first message cancels immediately
        for pad in (0,1):m.uc.mem_write(BASE+pad*0x44+0x1c,b'\x01')
        if owned:
            assert gate(m,'work_begin')==0 and gate(m,'work_begin')==0
        def receive(a):
            counts.append(word(m))
            if not pending:return stop(m)
            m.uc.mem_write(a[1],struct.pack('<4I',*pending.pop(0)));return 0
        def redirect(uc,address,size,unused):
            uc.reg_write(UC_ARM_REG_LR,0x80036c81)
            uc.reg_write(UC_ARM_REG_PC,m.symbols['od_emulator_stream_callback'])
        m.hooks[0x800483a8]=receive
        m.hooks[0x8001aaa0]=lambda a:0;m.hooks[0x8001aab8]=lambda a:0
        m.uc.hook_add(UC_HOOK_CODE,redirect,begin=0x80036c7c,end=0x80036c7c)
        m.invoke(0x80036c60,[])
        if owned:
            assert counts==[2,1,0] and word(m,GATE+12)==0
            assert gate(m,'promote_begin')==0
        else:
            assert counts==[0,0x40000000,0x40000000] and word(m,GATE+12)==3
            assert gate(m,'promote_begin')==2
        assert m.uc.mem_read(BASE+0x1c,1)==b'\x01'
        assert m.uc.mem_read(BASE+0x44+0x1c,1)==b'\x00'
        passed('compiled_stream_bridge_'+('releases_each_owned_message' if owned else 'missing_ownership_latches_fault'),
               observed_counts=counts)

    # Nonempty refill: original stream loop, with file input and conversion
    # callbacks modeled. Admission must survive both callbacks and completion.
    m=Emulator();pending=[(0,2,16,0)];events=[];counts=[]
    assert gate(m,'work_begin')==0
    for offset,value in ((0x14,64),(0x24,64),(0x110,1),(0x114,1),
                         (0x120,16),(0x124,CALLBACK),(0x32c,0x80036209)):
        put32(m,BASE+offset,value)
    m.uc.mem_write(BASE+0x118,b'\x20');m.uc.mem_write(BASE+0x1c,b'\x01')
    def receive_refill(a):
        counts.append(word(m))
        if not pending:return stop(m)
        m.uc.mem_write(a[1],struct.pack('<4I',*pending.pop(0)));return 0
    def read_refill(a):
        assert word(m)==1 and a[:3]==[0,0x80735b80,128]
        m.uc.mem_write(a[1],bytes(128));events.append('file_input');return 0
    def convert_refill(a):
        assert word(m)==1 and a[1]==2
        events.append('audio_conversion');return 16
    m.hooks.update({0x800483a8:receive_refill,0x80036208:read_refill,CALLBACK:convert_refill})
    for fn in (0x80076950,0x800763d8,0x8001aaa0,0x8001aab8):m.hooks[fn]=lambda a:0
    m.uc.hook_add(UC_HOOK_CODE,redirect,begin=0x80036c7c,end=0x80036c7c)
    m.invoke(0x80036c60,[])
    assert events==['file_input','audio_conversion'] and counts==[1,0]
    assert word(m,BASE+0x11c)==2 and m.uc.mem_read(BASE+0x1c,1)==b'\x00'
    passed('compiled_stream_bridge_retains_ownership_through_nonempty_refill',events=events)

    # Execute the stock mode worker for all three normal/storage profile pairs.
    expected=[0x89f,0x88f,0x89e,0x88e,0x89d,0x88d]
    for selector,configuration in zip(range(5,11),expected):
        data=usb_worker(selector);assert data['configuration']==configuration
        passed('usb_mode_selector_'+str(selector),**data)
    passed('usb_acknowledges_even_failed_start',**usb_worker(8,False))

    # Link transfer configuration values to the original storage backend selector.
    for configuration,index in ((0x88f,0),(0x88e,1),(0x88d,2)):
        m=Emulator();calls=[]
        m.uc.mem_write(0x8023d174,b'\x01\x00')
        m.hooks[0x80068378]=lambda a:calls.append(bytes(m.uc.mem_read(a[0],20))) or 0
        assert m.invoke(0x800654b0,[configuration])==0
        assert word(m,0x801f8e5c)==0x800a129c+24*index and len(calls)==1
    passed('three_transfer_configurations_select_mass_storage_backend')

    for profile in range(3):passed('enter_transfer_profile_'+str(profile),**usb_transition(True,profile))
    passed('return_to_card_requests_scan_reload',**usb_transition(False))
    passed('failed_mount_still_clears_stock_transfer_mode',
           **usb_transition(False,mount_result=0xffffffff))
    passed('missing_card_exit_still_clears_stock_transfer_mode',
           **usb_transition(False,card=False))

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['No hardware or firmware patch',
          'Original producer, worker and transition instructions run with modeled queues/semaphores',
          'USB hardware initialization and actual SD/USB transfers are intercepted',
          'Sampler file read/seek results are injected at filesystem wrapper boundaries',
          'Compiled stream-completion bridge intercepts one emulator call site; producer ownership is supplied by the harness',
          'Stream tests cover zero-work, early-cancel and one nonempty refill with modeled file/conversion callbacks; no audible output'])
    path=ROOT/'analysis/scheduling_boundaries_verification.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))


if __name__=='__main__':main()
