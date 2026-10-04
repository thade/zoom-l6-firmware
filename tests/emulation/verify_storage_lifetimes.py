#!/usr/bin/env python3
"""Stock storage lifetime boundaries; no device I/O or replacement readiness flag."""
import hashlib,json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT,IMAGE,BIAS
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_storage_readiness import callees,word

BOX=0x801f9108;VOLUME=0x801f8f58;CALLBACK=0x21008000;ARG=0x21009000
MD=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);MD.skipdata=True

def instructions(start,end):return list(MD.disasm(IMAGE[start-BIAS:end-BIAS],start))
def stub_calls(m,start,end,events,keep=()):
    for fn in callees(start,end)-set(keep):
        m.hooks[fn]=lambda a,fn=fn:events.append((hex(fn),*a[:2])) or 0

def usb_request(selector,wait_result=1,signal_result=1,stop_request=False,m=None):
    m=m or Emulator();events=[]
    put32(m,BOX,0x7000);put32(m,BOX+12,0x7001)
    for fn in (0x80073ec8,0x80073f18,0x80077686):m.hooks[fn]=lambda a:0
    def signal(a):events.append(('signal',a[0],word(m,BOX+4),word(m,BOX+8)));return signal_result
    def wait(a):events.append(('wait',a[0],a[1]));return wait_result
    m.hooks.update({0x800763d8:signal,0x80076950:wait})
    result=m.invoke(0x8003b8a0 if stop_request else 0x8003b7e0,[] if stop_request else [selector,0x3456])
    return m,result,events

def usb_worker(command,start_result=1,stop_result=0):
    m=Emulator();events=[];delivered=False
    for base,n in ((0x401b0000,0x10000),(0x401f8000,0x1000),(0xe000e000,0x1000)):m.uc.mem_map(base,n)
    for offset,value in ((0,0x7000),(12,0x7001),(24,0x7002)):put32(m,BOX+offset,value)
    def wait(a):
        nonlocal delivered
        assert a[0]==0x7000
        if delivered:return stop(m)
        delivered=True;put32(m,BOX+4,command);put32(m,BOX+8,0)
        if command==0x800:m.uc.mem_write(0x80212e00,b'\x01')
        return 1
    def start(a):events.append(('start',struct.unpack('<H',m.uc.mem_read(a[0]+4,2))[0]));return start_result
    def stopped(a):events.append(('stop',));return stop_result
    def signal(a):
        if a[0]==0x7001:events.append(('ack',word(m,BOX+4),word(m,BOX+8)))
        return 1
    for fn in (0x8003b580,0x80073ec8,0x80073f18,0x80025f78,0x8001bcd8,
               0x8001bc98,0x800684b8,0x80026bf0,0x8001bc20,0x80036c98):m.hooks[fn]=lambda a:0
    m.hooks.update({0x80076950:wait,0x800763d8:signal,0x8003b5a8:start,
                   0x8003b558:stopped,0x8003b5d0:lambda a:events.append(('service',)) or 0})
    m.invoke(0x80045cf0,[])
    return m,events

def card_detach(active=0,callback=True,progress=True):
    m=Emulator();events=[]
    m.uc.mem_write(VOLUME,bytes([active,0,0,0])+bytes([0xa5])*0x30)
    if callback:put32(m,0x802350e4,CALLBACK|1)
    def notified(a):
        assert bytes(m.uc.mem_read(VOLUME+4,0x30))==bytes(0x30)
        events.append(('notify',*a[:2],int(m.uc.mem_read(VOLUME,1)[0])))
        return 0
    def delay(a):
        events.append(('wait_active',a[0]))
        if progress:m.uc.mem_write(VOLUME,b'\0')
        else:return stop(m)
        return 0
    m.hooks.update({CALLBACK:notified,0x80068508:lambda a:events.append(('driver_signal',a[0])) or 0,
                    0x80077686:delay})
    result=m.invoke(0x80062230,[0x41])
    return m,result,events

def release_card():
    m=Emulator();events=[]
    stub_calls(m,0x80009b18,0x80009b44,events,(0x80062230,0x8000b2a8))
    stub_calls(m,0x8000b2a8,0x8000b2fc,events)
    m.hooks[0x800088d0]=lambda a:events.append(('catalogue_tail',)) or 0
    # Zero-active filesystem path still executes its real pointer clearing.
    m.uc.mem_write(VOLUME+4,bytes([0xa5])*0x30)
    m.uc.mem_write(0x801f8c48+0x2c,b'\x01')
    def stop_backend(a):
        assert bytes(m.uc.mem_read(VOLUME+4,0x30))==bytes(0x30)
        events.append(('recorder_stop_after_detach',a[0]));return 0xffffd825
    m.hooks[0x8000b698]=stop_backend
    result=m.invoke(0x80009b18,[])
    return m,result,events

def recorder_producer(address,send_result):
    m=Emulator();packets=[]
    put32(m,0x801f8f38,0x6000);put32(m,0x80446894,0x6001)
    m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:0x42
    def send(a):packets.append(bytes(m.uc.mem_read(a[1],32)));return send_result
    m.hooks[0x800483f8]=send
    result=m.invoke(address,[7])
    return result,packets

def alternate_start():
    m=Emulator();events=[]
    stub_calls(m,0x8004b890,0x8004b8f4,events)
    m.hooks[0x8000b650]=lambda a:events.append(('backend_start',a[0])) or 0xffffd825
    m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:0
    m.invoke(0x8004b890,[ARG])
    return m,events

def postprocess(enabled,classification=0,error=0):
    m=Emulator();events=[]
    stub_calls(m,0x800032b0,0x800035d0,events,(0x8000178e,))
    m.hooks[0x80022cc8]=m.hooks[0x80022cd8]=lambda a:0
    m.hooks[0x80006c20]=lambda a:0
    m.hooks[0x80022c78]=lambda a:int(a[0] in enabled)
    m.hooks[0x80022bd0]=lambda a:1
    m.hooks[0x80022b80]=lambda a:classification
    m.hooks[0x80004868]=lambda a:events.append(('file_postprocess',*a[:3])) or error
    m.hooks[0x80022938]=lambda a:events.append(('stream_cleanup',a[0])) or 0
    m.hooks[0x80022958]=lambda a:events.append(('final_cleanup',)) or 0
    m.hooks[0x800035d0]=lambda a:events.append(('postprocess_tail',)) or 0
    m.invoke(0x800032b0,[0xffffffff])
    return events

def postprocess_tail(open_error=0,close_error=0):
    m=Emulator();events=[]
    stub_calls(m,0x800035d0,0x8000384e,events)
    m.hooks[0x80022960]=lambda a:int(a[0]==10)
    m.hooks[0x80022c80]=lambda a:ARG
    def opened(a):
        events.append(('reopen',a[2],a[3]));put32(m,a[0],0x1234);return open_error
    m.hooks[0x8005ffe8]=opened
    m.hooks[0x8000f0b0]=lambda a:events.append(('parse_rejected',a[0])) or 1
    m.hooks[0x8005c1f8]=lambda a:events.append(('close',a[0])) or close_error
    m.hooks[0x80022930]=lambda a:events.append(('cleanup_after_attempt',a[0])) or 0
    m.hooks[0x800047a0]=lambda a:events.append(('tail_final_update',)) or 0
    m.invoke(0x800035d0,[])
    return events

def inventory():
    targets=[0x8000c220,0x8000c288,0x8000c2d8,0x80009a40,0x80009b18,
             0x80009938,0x80062230,0x8003b7e0,0x8003b8a0,0x8000b650,0x8000b698,0x800032b0]
    found={hex(t):[] for t in targets}
    for i in MD.disasm(IMAGE[0x600:0xa0000],BIAS+0x600):
        if i.mnemonic in ('bl','b','b.w') and i.op_str.startswith('#'):
            target=i.op_str[1:]
            if target in found:found[target].append(hex(i.address))
    return found

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    flags=[]
    for selector in range(11):
        m,r,e=usb_request(selector)
        assert e[0][0:2]==('signal',0x7000) and e[0][3]==0x3456
        assert e[1]==('wait',0x7001,0xffffffff) and r==1
        flags.append(e[0][2]);assert word(m,BOX+4)==flags[-1]
    assert flags==[1,4,2,8,16,32,64,128,256,512,1024],flags
    passed('all_eleven_USB_selectors_store_single_command_parameter_pair_before_shared_ack_wait',flags=flags)

    for selector in (11,0xffffffff):
        m,r,e=usb_request(selector);assert not e and word(m,BOX+4)==0
    passed('out_of_range_USB_selector_does_not_signal_or_write_command_slot')

    for signal in (0,1):
        m,r,e=usb_request(6,wait_result=0,signal_result=signal)
        assert r==0 and e[-1][0]=='wait' and word(m,BOX+4)==0x40
    passed('failed_request_signal_still_waits_and_failed_wait_returns_with_command_pending')

    m,r,e=usb_request(6,wait_result=0)
    m,r,e=usb_request(0,stop_request=True,m=m)
    assert e[0]==('signal',0x7000,0x800,0) and r==1
    assert word(m,BOX+4)==0x800 and word(m,BOX+8)==0
    passed('later_stop_replaces_unconsumed_request_pair_after_injected_wait_failure',
           limitation='Failure/preemption fixture; not evidence of a reproduced user-visible device race')

    for command in (0x20,0x40,0x80,0x100,0x200,0x400):
        for result in (0,1):
            m,e=usb_worker(command,start_result=result)
            assert e[0][0]=='start' and e[1]==('ack',0,0)
            assert bool(m.uc.mem_read(0x80212e00,1)[0])==bool(result)
            if result:assert e[2][0]=='service'
            else:assert len(e)==2
    passed('worker_consumes_pair_and_acknowledges_both_failed_and_successful_start_before_later_USB_service')

    for error in (0,0xffffd825):
        m,e=usb_worker(0x800,stop_result=error)
        assert e==[('stop',),('ack',0,0)] and m.uc.mem_read(0x80212e00,1)==b'\0'
    passed('USB_stop_worker_clears_active_and_acknowledges_even_if_modeled_stop_callee_reports_error')

    m,r,e=card_detach();assert r==1 and not e
    assert bytes(m.uc.mem_read(VOLUME+4,0x30))==bytes(0x30) and m.uc.mem_read(VOLUME+2,1)==b'\x01'
    passed('inactive_volume_detach_clears_registration_and_sets_detached_byte_without_notification')

    m,r,e=card_detach(active=2)
    assert r==1 and e==[('driver_signal',0),('notify',1,0,2),('wait_active',100)]
    assert m.uc.mem_read(VOLUME+2,1)==b'\x01'
    passed('active_detach_clears_pointers_then_notifies_registered_callback_then_waits_for_status_zero')

    m,r,e=card_detach(active=2,callback=False,progress=False)
    assert e==[('wait_active',100)] and m.uc.mem_read(VOLUME+2,1)==b'\0'
    passed('missing_detach_callback_does_not_supply_completion_while_active_status_stays_nonzero')

    m=Emulator()
    for volume,offset in ((1,0),(2,0x38)):
        for status in (0,1,2):
            m.uc.mem_write(VOLUME+offset,bytes([9,7]))
            m.invoke(0x8004bd98,[volume,5,status])
            assert m.uc.mem_read(VOLUME+offset,1)==bytes([status])
            assert m.uc.mem_read(VOLUME+offset+1,1)==bytes([5 if status==2 else 7])
    passed('stock_status_callback_writes_volume_status_and_only_updates_auxiliary_byte_for_status_two')

    m,r,e=release_card()
    ops=[x[0] for x in e]
    assert ops.index('0x80002ce8')<ops.index('recorder_stop_after_detach')<ops.index('catalogue_tail')
    assert m.uc.mem_read(0x801f8c48+0x2c,1)==b'\0'
    passed('card_release_detaches_before_pad_stop_and_forced_recorder_stop_then_disables_backend_despite_injected_error')

    for addr,callback in ((0x8004b698,0x8004b891),(0x8004b6d8,0x8004b9a1),(0x8004b718,0x8004ba41)):
        for result in (0,0xffffffff):
            returned,packets=recorder_producer(addr,result)
            assert returned==0x42 and len(packets)==1 and struct.unpack_from('<I',packets[0])[0]==callback
    passed('transport_has_alternate_start_callback_in_same_control_queue_and_all_three_producers_mask_send_result')

    m,e=alternate_start()
    assert ('backend_start',1) in e and m.uc.mem_read(0x80578ebc,1)==b'\x02'
    passed('alternate_start_passes_different_backend_argument_and_sets_distinct_UI_state_despite_injected_failure')

    for enabled in ([10],list(range(12))):
        for error in (0,0xffffd825):
            e=postprocess(enabled,error=error)
            calls=[x for x in e if x[0]=='file_postprocess']
            assert [x[1] for x in calls]==enabled
            assert all(x[2]==0xffffffff and x[3]==0x8060e504+x[1]*522 for x in calls)
            assert [x[1] for x in e if x[0]=='stream_cleanup']==enabled and e[-2:]==[('final_cleanup',),('postprocess_tail',)]
    passed('ordinary_postprocess_walks_enabled_streams_and_continues_cleanup_after_injected_per_file_error')

    e=postprocess([10],classification=2)
    assert not any(x[0]=='file_postprocess' for x in e) and ('stream_cleanup',10) in e
    passed('postprocess_skips_file_work_for_classifier_above_one_but_still_cleans_stream')

    for error in (0,0xffffd825):
        e=postprocess_tail(close_error=error)
        narrow=[x for x in e if x[0] in ('reopen','parse_rejected','close','cleanup_after_attempt','tail_final_update')]
        assert narrow==[('reopen',2,0x180),('parse_rejected',0x1234),('close',0x1234),
                        ('cleanup_after_attempt',0xffffffff),('tail_final_update',)]
    passed('postprocessing_tail_reopens_stream_file_and_continues_metadata_update_after_parse_and_close_failure')

    e=postprocess_tail(open_error=0xffffd825)
    assert ('reopen',2,0x180) in e and not any(x[0] in ('close','parse_rejected') for x in e)
    assert e[-1]==('tail_final_update',)
    passed('postprocessing_tail_handles_failed_open_without_close_but_final_update_is_not_success_evidence')

    refs=inventory()
    assert len(refs['0x80062230'])>=6 and len(refs['0x80009a40'])>=5
    assert '0x8000c3bc' in refs['0x8003b7e0'] and '0x8004b934' in refs['0x8000b698']
    passed('bounded_direct_call_inventory_exposes_mount_detach_alternate_USB_and_alternate_recorder_ingress',references=refs)

    windows=[(0x8003b7e0,0x8003b8d8),(0x80062230,0x800622b0),(0x80036c98,0x80036ce0),
             (0x8004bd98,0x8004bdd0),(0x80009b18,0x80009b44),(0x8000b2a8,0x8000b2fc),
             (0x8000c2d8,0x8000c3d0),(0x8004b698,0x8004b760),(0x8004b890,0x8004b8f4),
             (0x800032b0,0x80003850),(0x80004868,0x80004970),(0x80005d74,0x80005d98)]
    listing=[]
    for lo,hi in windows:
        listing.append(f'\nBOUND {lo:08x}..{hi:08x}')
        listing.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(lo,hi))
    (ROOT/'analysis/storage_lifetime_disassembly.txt').write_text('\n'.join(listing)+'\n')
    out=ROOT/'analysis/storage_lifetimes_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
      'Original instruction paths under synthetic state; RTOS waits/signals, USB engine, card callback progress and per-file postprocessing bodies are fixtures',
      'Injected callee errors and command replacement test weak evidence, not proven naturally occurring device failures',
      'Direct-call scan is bounded main-code linear disassembly; indirect calls, branch-table decoding and copied RAM code require separate coverage',
      'No complete admission/ownership binding or positive external_held implementation is claimed',
      'No device access, SD writes, prototype ELF rebuild or firmware patch']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
