#!/usr/bin/env python3
"""Audit original card setup and recorder stop. Synthetic lower-level effects.
No hardware access; weak stock status values are negative controls, not readiness.
"""
import hashlib,json
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT,IMAGE,BIAS
from verify_firmware_workflow import put32

MD=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
def callees(start,end):
    return {int(i.op_str[1:],16) for i in MD.disasm(IMAGE[start-BIAS:end-BIAS],start) if i.mnemonic=='bl'}
def word(m,a):return int.from_bytes(m.uc.mem_read(a,4),'little')

def mount(status=0,mount_result=0,setup=0,send_result=0):
    m=Emulator();events=[];messages=[]
    for fn in callees(0x80009a40,0x80009b18):m.hooks[fn]=lambda a:0
    # Run actual volume-bit getters and original deferred reload producer.
    for fn in (0x8000ac70,0x8000ac80,0x80008d68):del m.hooks[fn]
    m.hooks[0x8005ec00]=lambda a:status
    m.hooks[0x8005fc98]=lambda a:events.append(('mount',mount_result)) or mount_result
    m.hooks[0x80002d80]=lambda a:setup
    m.hooks[0x8000bad0]=lambda a:0x21008000
    m.hooks[0x80076950]=lambda a:1
    m.hooks[0x800763d8]=lambda a:0
    put32(m,0x801f8f3c,0x6543)
    def send(a):
        assert a[0]==0x6543
        messages.append(bytes(m.uc.mem_read(a[1],32)))
        events.append(('reload_submit',word(m,0x807348cc)))
        return send_result
    m.hooks[0x800483f8]=send
    result=m.invoke(0x80009a40,[2])
    return m,result,events,messages

def recorder(close_error=0,final_error=0,enabled=1,delayed=False):
    m=Emulator();events=[];state=0x801f8c48;c=0x8077ca30
    m.uc.mem_write(state+0x2c,bytes([enabled]));m.uc.mem_write(state+8,bytes([2,0,1,1,0]))
    for fn in callees(0x8000b698,0x8000b9b4):m.hooks[fn]=lambda a:0
    for fn in (0x80037dc0,0x80037d68,0x80037df0,0x800380d0):del m.hooks[fn]
    m.hooks[0x80002360]=lambda a:1
    m.hooks[0x80037e98]=lambda a:0x1000+a[0]
    m.hooks[0x80037e58]=lambda a:8192
    put32(m,c+8,0xfff)
    if delayed:
        m.uc.mem_write(c+0x1ea4,b'\x01');m.uc.mem_write(c+0xe8,b'\x01');put32(m,c+0x440,1)
    def delay(a):
        if m.uc.mem_read(c+0x1ea4,1)!=b'\0':
            events.append(('join','file'));m.uc.mem_write(c+0x1ea4,b'\0')
        elif m.uc.mem_read(c+0xe8,1)!=b'\0':
            events.append(('join','producer'));m.uc.mem_write(c+0xe8,b'\0')
        elif word(m,c+0x440):events.append(('join','flush'));put32(m,c+0x440,0)
        else:raise AssertionError('unexpected wait')
        return 0
    m.hooks[0x80077686]=delay
    def finalize(a):
        events.append(('finalize',a[0]-0x1000));return final_error if a[0]==0x100a else 0
    def close(a):
        events.append(('close',a[0]-0x1000));return close_error if a[0]==0x100a else 0
    m.hooks[0x8000ea08]=finalize;m.hooks[0x8005c1f8]=close
    m.hooks[0x800032b0]=lambda a:events.append(('postprocess',word(m,c+8))) or 0
    result=m.invoke(0x8000b698,[0xffffffff])
    return m,result,events

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    m=Emulator()
    for status in (0,1,8,9,0xffffffff):
        m.hooks[0x8005ec00]=lambda a,status=status:status
        assert m.invoke(0x8000ac80,[])==1-(status&1)
        assert m.invoke(0x8000ac70,[])==(status>>3)&1
    passed('actual_volume_getters_decode_status_bit_zero_inverted_and_bit_three')

    for error in (0,0xffffd825):
        m,r,e,q=mount(status=1,mount_result=error)
        assert r==0 and not q and word(m,0x807348cc)==0
        assert e==[('mount',error)]
    passed('mount_backend_zero_return_can_mean_unavailable_volume_and_no_reload_even_after_mount_error')

    for status,setup in ((8,0),(0,0xffffffff)):
        m,r,e,q=mount(status=status,setup=setup)
        assert r==0xffffffff and not q
    passed('volume_bit_three_or_directory_setup_failure_aborts_before_reload')

    for send_result in (0,0xffffffff):
        m,r,e,q=mount(send_result=send_result)
        assert r==0 and len(q)==1 and int.from_bytes(q[0][:4],'little')==0x80049da1
        assert word(m,0x807348cc)==1 and e==[('mount',0),('reload_submit',1)]
    passed('mount_success_returns_with_reload_queued_and_masks_reload_send_failure',
           callback='0x80049da0',pending='0x807348cc',queue_slot='0x801f8f3c',
           limitation='Captured 32-byte messages; reload worker not executed here')

    for close_error,final_error in ((0,0),(0xffffd825,0),(0,0xffffd825),(0xffffd825,0xffffd825)):
        m,r,e=recorder(close_error,final_error)
        assert e==[(op,i) for i in range(12) for op in ('finalize','close')]+[('postprocess',0)]
        assert m.uc.mem_read(0x801f8c50,1)==b'\0' and word(m,0x8077ca38)==0
    passed('stop_ignores_master_finalize_and_close_errors_then_clears_stream_mask_and_reports_idle',
           finalize_call='0x8000b8e2',close_call='0x8000b8e8',state_clear='0x8000b9aa')

    m,r,e=recorder(delayed=True)
    assert e[:3]==[('join','file'),('join','producer'),('join','flush')]
    assert e[3]==('finalize',0) and e[-1]==('postprocess',0)
    passed('actual_stop_predicates_wait_for_modeled_file_producer_and_flush_completion_before_finalizers',
           limitation='Flags advanced by scheduled fixture; no proof that unknown asynchronous users retain no references')

    m,r,e=recorder(enabled=0)
    assert not e and word(m,0x8077ca38)==0xfff
    passed('disabled_stop_returns_without_finalizing_or_clearing_existing_synthetic_stream_state')

    out=ROOT/'analysis/storage_readiness_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
      'Original mount, queued reload producer, status getters, stop backend and drain predicates execute with synthetic RAM',
      'Filesystem mount, status query, directory setup, queue/RTOS and finalizer/close bodies are modeled',
      'Reload callback, actual recorder I/O lifecycle and USB session ownership not installed or fully joined',
      'Zero result, idle flag and cleared enabled mask are explicitly insufficient readiness evidence',
      'No card or device access; no automatic publication authorization']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
