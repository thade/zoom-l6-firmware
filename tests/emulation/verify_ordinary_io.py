#!/usr/bin/env python3
"""Compiled ordinary read/seek lifetime core; native dispatch remains unbound."""
import json
import struct
from verify_pad_file import Native, CTX, LEDGER
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT
from verify_firmware_workflow import put32
from verify_work_ownership import OK, BUSY, CONFLICT, STALE
from verify_reload_prefetch import READ_SEM
from verify_scheduling_boundaries import BASE

IO=0x2102c000
REQ=IO+0x900
TABLE=REQ+0x40
TASK=TABLE+0x40
PACKET=TASK+0x40
OUT=PACKET+0x40
BUFFER=0x21030000


class Rig(Native):
    def oi(self,name,*args):return self.m.invoke(self.m.symbols['oi_'+name],list(args))
    def own(self,name,*args):return self.m.invoke(self.m.symbols['od_own_'+name],[LEDGER,*args])
    def begin(self,slot=0,kind=0,pad=0,first=BUFFER,second=64,parent=0):
        self.m.uc.mem_write(REQ,struct.pack('<6I',kind,pad,first,second,slot+2,parent))
        put32(self.m,TABLE+4*slot,IO+0x100*slot)
        return self.oi('begin',CTX,IO+0x100*slot,REQ)
    def queue(self,slot=0):
        o=IO+0x100*slot
        assert self.oi('prepare',o)==OK
        assert self.oi('packet',o,slot,PACKET)==OK
        return bytes(self.m.uc.mem_read(PACKET,16))
    def decode(self,packet=None):
        if packet is not None:self.m.uc.mem_write(PACKET,packet)
        return self.oi('decode',TABLE,TASK,PACKET,OUT)
    def complete(self,slot=0,status=0,actual=64):
        assert self.oi('observe',TASK,status,actual)==OK
        assert self.oi('return',TASK)==OK
        assert self.oi('finish',IO+0x100*slot)==OK
    def blocked(self,slot=0,pad=0):
        handle=self.word(IO+0x100*slot+60)
        assert self.pf('change_begin',pad,0x7999)==BUSY
        assert self.pf('close_begin',handle,0x7999,OUT)==BUSY
        assert self.own('promote',OUT)==BUSY


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))

    # Normal short reads/EOF are not reload failures. Completion is lifetime
    # evidence only; statuses and counts here are explicit harness observations.
    for kind,first,second,status,actual in (
        (0,BUFFER,64,0,64),(0,BUFFER,64,0,17),(0,BUFFER,64,0,0),
        (0,BUFFER,64,0xffffd825,0),(0,BUFFER,0,0,0),
        (1,1234,0,0,0),(1,0xfffffffc,2,0xffffd825,0)):
        r=Rig();assert r.begin(kind=kind,first=first,second=second)==OK
        r.queue();r.blocked();assert r.decode()==OK
        assert struct.unpack('<4I',r.m.uc.mem_read(OUT,16))==(kind,0,first,second)
        handle=r.word(IO+60)
        assert r.oi('check',TASK,handle,first,second)==OK
        assert r.oi('finish',IO)==BUSY and r.oi('return',TASK)==BUSY
        assert r.oi('observe',TASK,status,actual)==OK
        assert r.oi('finish',IO)==BUSY
        r.blocked() # Signal wake alone cannot release a pin.
        assert r.oi('return',TASK)==OK and r.oi('finish',IO)==OK
        assert r.oi('result',IO,OUT)==OK
        assert struct.unpack('<2I',r.m.uc.mem_read(OUT,8))==(status,actual)
        assert r.word(LEDGER)==0
        assert r.pf('change_begin',0,0x7999)==OK
    passed('read_short_eof_zero_length_error_and_seek_preserve_results_and_wait_for_return')

    # Run the decoded words through the original worker in the fixture CPU.
    # Explicit copies/observations below are harness plumbing, not native hooks.
    for kind in (0,1):
        r=Rig();first,second=(BUFFER,64) if kind==0 else (1234,0)
        assert r.begin(kind=kind,first=first,second=second)==OK
        r.queue();assert r.decode()==OK
        raw=bytes(r.m.uc.mem_read(OUT,16));handle=r.word(IO+60)
        assert r.oi('check',TASK,handle,first,second)==OK
        r.io_cpu.uc.mem_write(BASE,bytes(r.m.uc.mem_read(BASE,0x9f0)))
        r.io_cpu.uc.mem_write(BUFFER,b'\xa5'*64)
        path,_=r.handles[handle];r.handles[handle][1]=len(r.files[path])-17
        put32(r.io_cpu,0x80446800,0x7111)
        seeks=[]
        def seek(a):seeks.append(tuple(a[:3]));return 0
        r.io_cpu.hooks[0x8005f168]=seek
        r.io_queue=[raw];r.signals=[]
        r.io_cpu.invoke(0x80036118,[])
        assert not r.io_queue
        assert r.signals==[READ_SEM if kind==0 else 0x7111]
        if kind==0:
            assert bytes(r.io_cpu.uc.mem_read(BUFFER,64))==bytes(r.files[path][-17:])+b'\x00'*47
        else:assert seeks==[(handle,first,second)]
        r.blocked();r.complete(actual=17 if kind==0 else 0)
    passed('decoded_read_and_seek_execute_original_worker_with_eof_zero_fill_and_distinct_signals')

    r=Rig();assert r.begin()==OK;r.queue();r.blocked()
    assert r.oi('finish',IO)==BUSY and r.oi('result',IO,OUT)==BUSY
    assert r.oi('packet',IO,0,OUT)==CONFLICT
    assert r.begin()==BUSY
    passed('missing_delivery_retains_root_and_pin_without_republish_or_context_reuse')

    r=Rig();assert r.begin()==OK;old=r.queue();assert r.decode()==OK
    assert r.decode()==BUSY
    handle=r.word(IO+60)
    for h,a,b in ((handle+4,BUFFER,64),(handle,BUFFER+4,64),(handle,BUFFER,65)):
        assert r.oi('check',TASK,h,a,b)==CONFLICT
    assert r.oi('observe',TASK,0,64)==OK
    assert r.oi('observe',TASK,0,64)==CONFLICT
    assert r.oi('return',TASK)==OK and r.oi('return',TASK)==STALE
    assert r.oi('finish',IO)==OK and r.oi('finish',IO)==OK
    assert r.begin()==OK;new=r.queue();assert old!=new
    assert r.decode(old)==STALE;r.blocked();assert r.decode(new)==OK;r.complete()
    passed('wrong_arguments_duplicates_and_stale_packets_cannot_release_reused_context')

    r=Rig();assert r.begin()==OK
    put32(r.m,LEDGER+4,1)
    assert r.oi('prepare',IO)==BUSY and r.word(IO+4)==1 and r.word(LEDGER)==0
    put32(r.m,LEDGER+4,0)
    latch=r.m.symbols['pad_files']+8;put32(r.m,latch,1)
    assert r.oi('prepare',IO)==BUSY and r.word(IO+4)==2 and r.word(LEDGER)==1
    ticket=r.word(IO+8);assert r.own('promote',OUT)==BUSY
    put32(r.m,latch,0);r.queue();assert r.word(IO+8)==ticket and r.word(LEDGER)==1
    assert r.decode()==OK;r.complete()
    passed('prepare_contention_retains_single_root_before_pin_admission')

    r=Rig();assert r.begin()==OK;r.queue()
    for latch in (IO,TASK):
        put32(r.m,latch,1);assert r.decode()==BUSY;put32(r.m,latch,0)
    assert r.decode()==OK
    for name,args in (('observe',(TASK,0,32)),('return',(TASK,))):
        for latch in (IO,TASK):
            put32(r.m,latch,1);assert r.oi(name,*args)==BUSY;put32(r.m,latch,0)
        assert r.oi(name,*args)==OK
    latch=r.m.symbols['pad_files']+8;put32(r.m,latch,1)
    assert r.oi('finish',IO)==BUSY and r.word(IO+4)==10
    put32(r.m,latch,0);put32(r.m,LEDGER+4,1)
    assert r.oi('finish',IO)==BUSY and r.word(IO+4)==11
    # A second pin drop would now be stale: the retry must only retire ledger.
    assert r.pf('drop',2,r.word(IO+64))==STALE
    put32(r.m,LEDGER+4,0)
    assert r.oi('finish',IO)==OK and r.word(LEDGER)==0
    passed('decode_observe_return_and_retirement_contention_retry_metadata_only')

    r=Rig();packets=[]
    for slot in range(8):
        assert r.begin(slot=slot)==OK;packets.append(r.queue(slot))
    assert r.word(LEDGER)==8
    for slot,packet in enumerate(packets):
        r.blocked(slot);assert r.decode(packet)==OK;r.complete(slot)
    assert r.word(LEDGER)==0 and r.pf('change_begin',0,0x7999)==OK
    passed('all_eight_ordinary_pin_slots_protect_shared_handle_until_last_completion')

    r=Rig();r.m.uc.mem_write(REQ,struct.pack('<5I',7,0,0,0,0))
    assert r.own('reserve',REQ,OUT)==OK;parent=r.word(OUT)
    assert r.own('offer',parent)==OK and r.own('submitted',parent,1)==OK
    assert r.own('claim',parent,REQ)==OK
    assert r.begin(parent=parent)==OK;r.queue()
    assert r.word(LEDGER)==1 and r.own('finish_session',parent)==BUSY
    assert r.decode()==OK;r.complete()
    assert r.word(LEDGER)==1 and r.own('finish_session',parent)==OK
    passed('explicit_parent_stays_live_until_ordinary_child_finishes')

    r=Rig();assert r.own('promote',OUT)==OK
    assert r.begin()==OK and r.oi('prepare',IO)==BUSY
    assert r.word(IO+4)==1 and r.word(IO+8)==0
    passed('exclusive_promotion_blocks_new_ordinary_root')

    r=Rig()
    for args in (dict(kind=2),dict(pad=4),dict(first=0),dict(first=0xfffffff0),dict(slot=8)):
        assert r.begin(**args)==CONFLICT
    assert r.word(LEDGER)==0
    m=Emulator();m.uc.mem_write(REQ,struct.pack('<6I',0,0,BUFFER,64,2,0))
    assert m.invoke(m.symbols['oi_begin'],[CTX,IO,REQ])==CONFLICT
    passed('invalid_requests_and_unbound_pad_guard_rejected_before_reservation')

    out=ROOT/'analysis/ordinary_io_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Compiled lifetime core uses loaded native pad handles; dispatch and IO observations are harness calls',
        'Native callback/file-worker routing, unique context binding and explicit stream-parent attribution remain uninstalled',
        'A completed operation is not a completed playback session or proof of successful IO',
        'Card teardown, lower-level close bypasses, lock ordering and physical scheduling remain unaudited',
        'No device access or firmware installation']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
