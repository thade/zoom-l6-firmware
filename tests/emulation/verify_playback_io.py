#!/usr/bin/env python3
"""Compiled playback ownership provider through original seek/refill/file paths."""
import json
import struct
from collections import deque
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_LR
from verify_ordinary_routing import Ordinary, CONFIG, OUT, BUFFER
from verify_read_ingress import UID, FID, CTX, LEDGER, DRIVER
from verify_read_worker import CURRENT
from verify_scheduling_boundaries import BASE, stop
from verify_firmware_workflow import put32
from verify_work_ownership import OK, BUSY, CONFLICT
from verify_pad_protocol import ROOT, IMAGE, BIAS, STACK

SESSION=0x2102e000
PORT=SESSION+0x40
BIND=PORT+0x40
SQ=0x808ff200
SID=0x7020
AUDIO=0x20015e4c


class Playback(Ordinary):
    def __init__(self,bind=True):
        super().__init__(bind=False)
        self.parents=[];self.refills=0;self.after_refill=None
        self.fence_ready=False
        self.q[SQ]=deque();put32(self.m,0x801f8f34,SQ);put32(self.m,0x80446dcc,SID)
        put32(self.m,CONFIG+12,SID);put32(self.m,CONFIG+44,0x80446dcc)
        sym=lambda name:self.m.symbols[name]|1
        put32(self.m,CONFIG+92,sym('pi_parent'))
        put32(self.m,SESSION,LEDGER);put32(self.m,SESSION+4,PORT)
        self.m.uc.mem_write(PORT,struct.pack('<7I',sym('od_emulator_session_loaded'),sym('pi_start'),
            sym('od_emulator_session_stop'),DRIVER+0xb1,sym('od_emulator_session_quiet'),
            DRIVER+0xc1,sym('od_emulator_stream_scan')))
        self.m.uc.mem_write(BIND,struct.pack('<8I',SESSION,UID,SID,SQ,sym('rc_stock_receive'),
            sym('od_emulator_session_start'),0x800369a9,DRIVER+0x81))
        self.m.hooks[DRIVER+0xb0]=self.fence
        self.m.hooks[DRIVER+0xc0]=lambda a:0
        self.m.hooks[0x80005eb0]=lambda a:0
        for address,name in ((0x80036c70,'next'),(0x80036c7c,'refill')):
            def redirect(uc,a,n,u,name=name):
                uc.reg_write(UC_ARM_REG_LR,(a+4)|1);uc.reg_write(UC_ARM_REG_PC,sym('pi_'+name))
            self.m.uc.hook_add(UC_HOOK_CODE,redirect,begin=address,end=address)
        def publish(uc,a,n,u):uc.reg_write(UC_ARM_REG_PC,sym(getattr(self,'publication_symbol','od_emulator_stream_publish_trampoline')))
        self.m.uc.hook_add(UC_HOOK_CODE,publish,begin=0x8003664a,end=0x8003664a)
        def entering(uc,a,n,u):
            if self.word(CURRENT)==SID:self.refills+=1
        self.m.uc.hook_add(UC_HOOK_CODE,entering,begin=0x800369a8,end=0x800369a8)
        if bind:
            assert self.pi('bind',BIND)==OK
            assert self.op('bind',CONFIG)==OK
    def pi(self,name,*args):return self.m.invoke(self.m.symbols['pi_'+name],list(args))
    def loaded(self):
        super().loaded()
        # Audio stop/fade and rendering are deliberately fixture effects.
        self.m.hooks[0x80018350]=lambda a:put32(self.m,AUDIO+0x3c*a[0],0) or 0
        put32(self.m,0x20010a48,48000)
        return self
    def owner(self):return self.word(SESSION+12)
    def session(self,name,*args):
        return self.scheduled(self.m.symbols['od_session_'+name],[SESSION,*args],None,UID)
    def kernel_send(self,a):
        if a[0]==SQ:
            self.q[SQ].append(bytes(self.m.uc.mem_read(a[1],16)));return 1
        return super().kernel_send(a)
    def read_wait(self,a):
        # Observe the real compiled ordinary child, not a supplied parent value.
        for index in (1,2):
            o=self.operation(index)
            if self.word(o+4)==7:
                self.parents.append((index,self.word(o+36),self.word(o+8)))
        return super().read_wait(a)
    def convert(self,a):
        if self.word(CURRENT)!=SID:return super().convert(a)
        assert self.word(self.operation(2)+4)==12
        self.converted.append((a[3],bytes(self.m.uc.mem_read(a[0],a[1]*a[4]*a[5]))))
        return a[1]*a[4]*a[5]
    def seed_scan(self):
        # Model the next refill window after restart; the synthetic initial
        # preload consumed the whole short fixture file. This is buffer state,
        # not ownership evidence or a renderer simulation.
        put32(self.m,BASE+0x11c,0);put32(self.m,BASE+0x328,0)
        self.m.uc.mem_write(BASE,b'\x01')
        for offset,value in ((4,0),(0x14,32),(0x18,8),(0x20,0),(0x24,16)):
            put32(self.m,BASE+offset,value)
    def stream(self):return self.scheduled(0x80036c60,[],None,SID)
    def fence(self,a):
        if not self.fence_ready:return BUSY
        for pad in range(4):self.m.uc.mem_write(BASE+pad*0x44,b'\x00')
        put32(self.m,a[1],a[0]);return OK


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    row=struct.unpack_from('<6I',IMAGE,0x800a1d3c-BIAS)
    assert row[0]==0x80036c61 and row[5]==0x80446dcc
    assert IMAGE[row[1]-BIAS:].split(b'\0',1)[0]==b'SamplerUpdatePlyStream'
    passed('stock_task_descriptor_identifies_stream_worker_and_native_identity_word')

    r=Playback().loaded();assert r.session('start',0)==OK
    owner=r.owner();assert owner and r.parents==[(1,owner,r.parents[0][2])]
    assert len(r.seeks)==1 and r.word(LEDGER)==1
    r.seed_scan();assert r.session('scan')==OK and len(r.q[SQ])==1
    refill=struct.unpack_from('<I',r.q[SQ][0])[0]
    assert r.stream() is None # Worker waits on its next empty queue.
    assert r.refills==1 and r.parents[-1][0:2]==(2,refill)
    assert r.word(LEDGER)==1 and r.owner()==owner and not r.q[SQ]
    assert r.session('stop',0)==OK and r.session('quiesce')==BUSY
    r.fence_ready=True;assert r.session('quiesce')==OK and r.word(LEDGER)==0
    passed('real_restart_seek_and_queued_refill_reads_inherit_distinct_compiled_owners_then_wait_for_renderer_fence')

    r=Playback().loaded();assert r.session('start',0)==OK;owner=r.owner()
    assert r.session('start',0)==OK and r.owner()==owner and len(r.seeks)==2
    assert all(p[1]==owner for p in r.parents)
    passed('retrigger_seeks_keep_the_same_playback_session')

    r=Playback().loaded();original_receive=r.kernel_receive
    def sleeping_receive(a):
        if a[0]==SQ:
            assert not r.q[SQ]
            return stop(r.m) # Suspend inside native receive, before it returns.
        return original_receive(a)
    r.m.hooks[0x80076710]=sleeping_receive
    put32(r.m,CURRENT,SID);r.m.stack=0x20028000
    r.m.invoke(0x80036c60,[])
    r.m.stack=STACK
    assert r.session('start',0)==OK and r.parents[-1][0:2]==(1,r.owner())
    assert len(r.seeks)==1 and r.word(LEDGER)==1
    passed('stream_worker_blocked_in_empty_native_receive_does_not_lock_out_main_restart_seek')

    r=Playback().loaded();assert r.session('start',0)==OK
    r.seed_scan();assert r.session('scan')==OK;packet=r.q[SQ][0]
    r.stream();assert r.refills==1
    r.q[SQ].append(packet);r.stream();assert r.refills==1 and r.word(LEDGER)==1
    passed('stale_refill_packet_does_not_read_again_or_borrow_the_current_session')

    r=Playback().loaded();assert r.session('start',0)==OK;old_owner=r.owner()
    r.seed_scan();assert r.session('scan')==OK;old_packet=r.q[SQ][0];r.stream()
    assert r.session('stop',0)==OK;r.fence_ready=True
    assert r.session('quiesce')==OK and r.session('start',0)==OK
    assert r.owner()!=old_owner
    r.q[SQ].append(old_packet);r.stream()
    assert r.refills==1 and r.parents[-1][0:2]==(1,r.owner()) and r.word(LEDGER)==1
    passed('old_generation_refill_cannot_attach_to_replacement_playback_session')

    r=Playback().loaded();assert r.session('start',0)==OK
    r.seed_scan();assert r.session('scan')==OK
    r.delivery=False;r.schedule=False
    before=r.reads;r.stream()
    assert r.refills==1 and r.reads==before and len(r.ordinary_packets)==2
    refill_parent=r.parents[-1][1]
    entries=[struct.unpack('<12I',r.m.uc.mem_read(LEDGER+12+48*i,48)) for i in range(16)]
    refill=next(e for e in entries if e[0]==refill_parent)
    assert refill[2]==1 and refill[3]==4 and r.word(LEDGER)==1
    assert r.pf('change_begin',0,UID)==BUSY
    passed('undelivered_file_read_keeps_claimed_refill_ancestors_and_file_pin_live')

    r=Playback().loaded();assert r.session('start',0)==OK
    r.seed_scan();assert r.session('scan')==OK
    original_receive=r.kernel_receive;deliveries=[]
    def hold_decode(a):
        result=original_receive(a)
        if a[0]==SQ and result:
            deliveries.append(1);put32(r.m,LEDGER+4,1)
        return result
    r.m.hooks[0x80076710]=hold_decode
    r.stream();assert deliveries==[1] and r.refills==0 and not r.q[SQ]
    put32(r.m,LEDGER+4,0);r.stream()
    assert deliveries==[1] and r.refills==1 and r.word(LEDGER)==1
    passed('busy_stream_decode_keeps_the_dequeued_packet_until_ledger_is_available')

    r=Playback().loaded();assert r.session('start',0)==OK
    r.seed_scan();assert r.session('scan')==OK
    completions=[];pauses=[];original_pause=r.pause_read
    def complete(uc,a,n,u):
        if r.word(CURRENT)==SID:
            completions.append(1)
            if len(completions)==1:put32(r.m,LEDGER+4,1)
    at=r.m.symbols['od_own_complete']&~1
    r.m.uc.hook_add(UC_HOOK_CODE,complete,begin=at,end=at)
    def resume(a):
        if r.word(LEDGER+4):
            pauses.append(1)
            if len(pauses)==2:put32(r.m,LEDGER+4,0)
        return original_pause(a)
    r.m.hooks[DRIVER+0x80]=resume;r.stream()
    assert len(pauses)==2 and r.refills==1 and r.reads==9 and r.word(LEDGER)==1
    passed('busy_refill_retirement_retries_completion_without_repeating_original_refill_or_read')

    for ident in (UID,SID,FID):
        r=Playback().loaded();assert r.session('start',0)==OK
        put32(r.m,CURRENT,ident)
        assert r.pi('parent',ident,OUT)==CONFLICT
        assert r.word(LEDGER)==1
    passed('session_presence_alone_does_not_authorize_unscoped_main_worker_or_file_task_IO')

    for address in (BIND+4,BIND+8,BIND+12):
        r=Playback(bind=False);old=r.word(address);put32(r.m,address,old+4)
        assert r.pi('bind',BIND)==CONFLICT
        put32(r.m,address,old);assert r.pi('bind',BIND)==OK
        assert r.pi('bind',BIND)==CONFLICT
    passed('native_main_stream_and_queue_identity_mismatch_rejected_before_binding')

    r=Playback(bind=False)
    assert r.op('bind',CONFIG)==CONFLICT
    assert r.pi('bind',BIND)==OK
    put32(r.m,SESSION,LEDGER+0x1000)
    assert r.op('bind',CONFIG)==CONFLICT
    put32(r.m,SESSION,LEDGER)
    put32(r.m,CONFIG+12,0);put32(r.m,CONFIG+44,0)
    assert r.op('bind',CONFIG)==CONFLICT
    put32(r.m,CONFIG+12,SID);put32(r.m,CONFIG+44,0x80446dcc)
    assert r.op('bind',CONFIG)==OK
    passed('ordinary_binding_requires_ready_provider_same_ledger_and_both_native_callers')

    r=Playback(bind=False);assert r.pi('bind',BIND)==OK
    put32(r.m,CURRENT,SID);r.pi('next',SQ,OUT)
    assert r.op('bind',CONFIG)==BUSY
    passed('even_empty_stream_worker_activity_closes_provider_binding_window')

    for address,value in ((0x80446dcc,SID+1),(0x801f8f34,SQ+4)):
        r=Playback().loaded();assert r.session('start',0)==OK
        r.seed_scan();assert r.session('scan')==OK;put32(r.m,address,value)
        put32(r.m,CURRENT,SID)
        assert r.pi('next',SQ,OUT)==0xffffffff and len(r.q[SQ])==1 and not r.refills
        assert r.pi('parent',SID,OUT)==CONFLICT
    passed('changed_stream_identity_or_queue_cannot_consume_or_borrow_ownership')

    r=Playback().loaded();assert r.session('start',0)==OK
    r.q[SQ].append(struct.pack('<4I',0,8,32,0));r.stream()
    assert r.refills==0 and r.word(LEDGER)==0x40000001
    passed('raw_stock_stream_message_cannot_bypass_ticket_attribution')

    out=ROOT/'analysis/playback_io_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Compiled parent provider supplies ownership; original start/seek/refill/file-worker instructions execute',
        'Stream producer still uses existing emulator scan context and fixed ledger address',
        'Audio stop/fade, conversion, renderer fence, kernel queues and scheduling remain fixtures',
        'Only Main start/restart and claimed stream refills are attributed; other direct callers fail closed',
        'No physical hook installation, device access or playback timing proof']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
