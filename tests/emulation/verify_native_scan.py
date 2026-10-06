#!/usr/bin/env python3
"""Native AudioSubProcess dispatcher -> session scan -> attributed refill IO."""
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_playback_io import Playback, SESSION, PORT, BIND, SQ, SID, CONFIG, OUT
from verify_read_ingress import UID, LEDGER, CTX, DRIVER
from verify_read_worker import CURRENT
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import BASE, stop
from verify_work_ownership import OK, BUSY, CONFLICT
from verify_pad_protocol import ROOT, IMAGE, BIAS, STACK, RETURN

NSCONFIG=SESSION+0x100
ASID=0x7030
ASEM=0x7031
LEGACY=0x21003900


class NativeScan(Playback):
    publication_symbol='ns_publish_entry'
    def __init__(self,bind=True,ledger=LEDGER):
        super().__init__(bind=False)
        self.ledger=ledger;put32(self.m,SESSION,ledger);put32(self.m,CTX,ledger)
        self.scans=0;self.scan_events=[];self.wakes=0;self.send_mode='normal'
        self.after_send=None
        put32(self.m,0x80446d7c,ASID);put32(self.m,0x80446930,ASEM)
        sym=lambda s:self.m.symbols[s]|1
        put32(self.m,PORT+24,sym('ns_scan'))
        self.m.uc.mem_write(NSCONFIG,struct.pack('<5I',SESSION,ASID,SQ,sym('ns_stock_send'),DRIVER+0xd1))
        self.m.hooks[DRIVER+0xd0]=self.pause_read
        self.m.hooks[DRIVER+0xe0]=lambda a:2 # Positive no-send fixture.
        source,dest,length,helper=struct.unpack_from('<4I',IMAGE,0x800a691c-BIAS)
        assert (source,dest,length,helper)==(0x800a9408,0x20220000,0xd6dc,0x80079498)
        self.m.uc.mem_map(dest,0x10000);self.m.uc.mem_write(dest,IMAGE[source-BIAS:source-BIAS+length])
        def scan_entry(uc,a,n,u):self.scans+=1
        self.m.uc.hook_add(UC_HOOK_CODE,scan_entry,begin=0x80036508,end=0x80036508)
        def callback_entry(uc,a,n,u):uc.reg_write(UC_ARM_REG_PC,sym('ns_callback'))
        self.m.uc.hook_add(UC_HOOK_CODE,callback_entry,begin=0x800366f0,end=0x800366f0)
        self.m.uc.mem_write(LEGACY,b'\xa5'*16)
        if bind:self.bind()
    def ns(self,name,*args):return self.m.invoke(self.m.symbols['ns_'+name],list(args))
    def bind(self):
        assert self.pi('bind',BIND)==OK
        assert self.ns('bind',NSCONFIG)==OK
        assert self.op('bind',CONFIG)==OK
    def entries(self):
        es=[struct.unpack('<12I',self.m.uc.mem_read(self.ledger+12+48*i,48)) for i in range(16)]
        return [e for e in es if e[0]]
    def kernel_send(self,a):
        if a[0]==SQ:
            raw=bytes(self.m.uc.mem_read(a[1],16));ticket=struct.unpack_from('<I',raw)[0]
            e=next(e for e in self.entries() if e[0]==ticket)
            self.scan_events.append((ticket,e[1],tuple(e[8:12])))
            if self.send_mode!='lost':self.q[SQ].append(raw)
            if self.after_send:self.after_send(self)
            return int(self.send_mode=='normal')
        return super().kernel_send(a)
    def read_wait(self,a):
        if a[0]!=ASEM:return super().read_wait(a)
        self.wakes+=1
        return 1 if self.wakes==1 else stop(self.m)
    def dispatch(self,register=True):
        if register:self.m.invoke(0x80002870,[0x800366f1])
        self.wakes=0
        return self.scheduled(0x2022a7a8,[],None,ASID)
    def legacy_untouched(self):assert bytes(self.m.uc.mem_read(LEGACY,16))==b'\xa5'*16


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    row=struct.unpack_from('<6I',IMAGE,0x800a1c04-BIAS)
    assert row[0]==0x2022a7a9 and row[5]==0x80446d7c
    assert IMAGE[row[1]-BIAS:].split(b'\0',1)[0]==b'AudioSubProcess'
    passed('native_audio_background_task_descriptor_and_copied_dispatcher_verified')

    for ledger in (LEDGER,0x21032000):
        r=NativeScan(ledger=ledger).loaded();assert r.session('start',0)==OK
        r.seed_scan();r.dispatch()
        assert r.scans==1 and len(r.scan_events)==1 and len(r.q[SQ])==1
        refill,scan,args=r.scan_events[0]
        es={e[0]:e for e in r.entries()}
        assert es[scan][1]==r.owner() and es[scan][3]==5 and es[scan][5]==1
        assert es[refill][1]==scan and args==(0,8,32,0)
        r.stream()
        assert r.refills==1 and r.parents[-1][:2]==(2,refill)
        assert len(r.entries())==1 and r.entries()[0][0]==r.owner()
        assert r.word(ledger)==1;r.legacy_untouched()
    passed('actual_dispatcher_uses_bound_session_and_relocated_ledger_through_scan_refill_and_read')

    r=NativeScan().loaded();r.seed_scan();before=bytes(r.m.uc.mem_read(BASE,0x44))
    r.dispatch();assert r.scans==0 and not r.scan_events
    assert bytes(r.m.uc.mem_read(BASE,0x44))==before and r.word(LEDGER)==0
    assert r.session('start',0)==OK
    for field in (SESSION+8,SESSION+20):
        put32(r.m,field,1);r.dispatch();assert r.scans==0 and not r.scan_events
        put32(r.m,field,0)
    passed('no_session_busy_session_and_closing_session_skip_scan_before_stock_mutations')

    for mode in ('uncertain','lost'):
        r=NativeScan().loaded();assert r.session('start',0)==OK;r.seed_scan();r.send_mode=mode
        r.dispatch();assert len(r.scan_events)==1 and len(r.entries())==3 and r.word(LEDGER)==1
        if mode=='uncertain':
            r.stream();assert len(r.entries())==1
        else:
            assert r.session('stop',0)==OK;r.fence_ready=True
            r.m.uc.mem_write(BASE+0x1c,b'\x00') # Idle flags cannot release unknown delivery.
            assert r.session('quiesce')==BUSY and len(r.entries())==3
        r.legacy_untouched()
    passed('uncertain_queue_result_retains_scan_and_refill_until_actual_delivery')

    r=NativeScan(bind=False);put32(r.m,NSCONFIG+12,DRIVER+0xe1);r.bind();r.loaded()
    assert r.session('start',0)==OK;r.seed_scan();before=r.word(BASE+0x20)
    r.dispatch()
    assert r.scans==1 and not r.scan_events and not r.q[SQ] and len(r.entries())==1
    assert r.word(BASE+0x20)==before and bytes(r.m.uc.mem_read(BASE+0x1c,1))==b'\x00'
    passed('positive_nonpublication_evidence_restores_pending_state_and_retires_only_attempted_work')

    r=NativeScan().loaded();assert r.session('start',0)==OK;r.seed_scan()
    r.after_send=lambda r:put32(r.m,LEDGER+4,1)
    pauses=[];original=r.pause_read
    def release(a):
        if r.word(LEDGER+4):
            pauses.append(1)
            if len(pauses)==3:put32(r.m,LEDGER+4,0)
        return original(a)
    r.m.hooks[DRIVER+0xd0]=release
    r.dispatch();assert len(pauses)==3 and r.scans==1 and len(r.scan_events)==1
    r.stream();assert len(r.entries())==1 and r.refills==1
    passed('busy_submission_acknowledgment_retries_metadata_without_resending_or_rescanning')

    r=NativeScan().loaded();assert r.session('start',0)==OK;r.seed_scan()
    r.after_send=lambda r:stop(r.m)
    put32(r.m,CURRENT,ASID)
    r.m.invoke(r.m.symbols['ns_callback'],[])
    producer=r.m.uc.context_save()
    ticket,scan,_=r.scan_events[0]
    assert next(e for e in r.entries() if e[0]==ticket)[4]==0
    r.m.stack=0x20028000;r.stream()
    entry=next(e for e in r.entries() if e[0]==ticket)
    assert entry[3]==5 and entry[4]==0 and entry[5]==0
    assert r.refills==1 and r.word(SESSION+8)==1 and len(r.entries())==3
    r.m.uc.context_restore(producer);put32(r.m,CURRENT,ASID);r.m.reached_return=False
    r.m.uc.emu_start(r.m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=10000000)
    r.m.stack=STACK
    assert r.m.reached_return and len(r.entries())==1 and r.word(SESSION+8)==0
    assert len(r.scan_events)==1 and r.refills==1;r.legacy_untouched()
    passed('refill_and_file_IO_can_finish_before_scan_sender_returns_without_releasing_its_active_scope')

    r=NativeScan().loaded();assert r.session('start',0)==OK;r.seed_scan()
    completions=[];pauses=[];original=r.pause_read
    def complete(uc,a,n,u):
        if r.word(CURRENT)==ASID:
            completions.append(1)
            if len(completions)==1:put32(r.m,LEDGER+4,1)
    at=r.m.symbols['od_own_complete']&~1
    r.m.uc.hook_add(UC_HOOK_CODE,complete,begin=at,end=at)
    def release_completion(a):
        if r.word(LEDGER+4):
            pauses.append(1)
            if len(pauses)==2:put32(r.m,LEDGER+4,0)
        return original(a)
    r.m.hooks[DRIVER+0xd0]=release_completion;r.dispatch()
    assert len(pauses)==2 and r.scans==1 and len(r.scan_events)==1
    assert r.word(SESSION+8)==0;r.stream();assert len(r.entries())==1
    passed('scan_return_contention_retries_only_completion_without_reentering_original_scan')

    r=NativeScan().loaded();assert r.session('start',0)==OK;r.seed_scan()
    r.m.uc.mem_write(OUT,struct.pack('<5I',7,0,0,0,0))
    for _ in range(15):assert r.own('reserve',OUT,OUT+32)==OK
    before=bytes(r.m.uc.mem_read(BASE,0x44));r.dispatch()
    assert not r.scans and not r.scan_events and len(r.entries())==16
    assert bytes(r.m.uc.mem_read(BASE,0x44))==before and r.word(SESSION+8)==0
    passed('full_ledger_before_scan_admission_skips_native_mutations_and_releases_session_latch')

    for address in (0x80446d7c,0x80446dcc,0x801f8f34):
        r=NativeScan().loaded();assert r.session('start',0)==OK;r.seed_scan()
        put32(r.m,address,r.word(address)+4)
        r.dispatch();assert not r.scans and not r.scan_events and r.word(LEDGER)&0x40000000
    passed('changed_task_worker_or_queue_binding_faults_before_original_scan')

    r=NativeScan().loaded();assert r.session('start',0)==OK
    put32(r.m,CURRENT,UID)
    assert r.ns('scan',r.owner())==CONFLICT and not r.scans
    put32(r.m,CURRENT,ASID)
    assert r.ns('scan',r.owner())==CONFLICT and not r.scans
    passed('native_task_identity_alone_cannot_bypass_session_operation_admission')

    r=NativeScan(bind=False);assert r.ns('bind',NSCONFIG)==CONFLICT
    assert r.pi('bind',BIND)==OK
    for offset in (0,4,8):
        old=r.word(NSCONFIG+offset);put32(r.m,NSCONFIG+offset,old+4)
        assert r.ns('bind',NSCONFIG)==CONFLICT;put32(r.m,NSCONFIG+offset,old)
    assert r.ns('bind',NSCONFIG)==OK and r.ns('bind',NSCONFIG)==CONFLICT
    passed('shared_session_task_queue_and_one_time_cold_binding_validated')

    out=ROOT/'analysis/native_scan_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Original copied AudioSubProcess dispatcher, scan, refill, seek and file-worker instructions execute',
        'Kernel queues/scheduling, valid refill buffer window, file effects, audio stop and renderer fence are fixtures',
        'A relocated ledger and poisoned legacy context verify no fixed ownership fixture addresses are used',
        'Original registered callback entry and publication call site are redirected by the emulator; firmware patches remain uninstalled',
        'Other direct callers, renderer lifetime fence, full lock audit and recovery remain open; no device access']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
