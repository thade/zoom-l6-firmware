#!/usr/bin/env python3
"""Actual compact reload ingress establishes scopes used by native read routing.
No fixture writes task phases/envelopes. Kernel scheduling and files are models.
"""
import json
import struct
from collections import deque
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_R4
from verify_reload_compact import Compact, WQ, UQ, WID, UID, CURRENT
from verify_reload_transport import WORK, UITASK, CTX, DRIVER, PRODUCER, LEDGER
from verify_reload_prefetch import PrefetchRig
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT, STACK, RETURN, REGS
from verify_work_ownership import OK, BUSY, CONFLICT, FAULT

PCONFIG=0x2102a000
WCONFIG=0x2102a100
SLOTS=(0x2102a200,0x2102a300)
FQ=0x808ff100
FSEM=0x7011
FID=0x7012


class Ingress(Compact,PrefetchRig):
    def __init__(self,bind=True):
        super().__init__()
        self.q[FQ]=deque();self.io_cpu=self.m
        self.reads=0;self.waits=0;self.wire=[];self.scopes=[];self.suspended=False
        self.schedule=True;self.delivery=True;self.delay=3
        put32(self.m,0x80446dc8,WID);put32(self.m,0x80446da4,UID)
        put32(self.m,0x80446dc4,FID);put32(self.m,0x801f8f30,FQ)
        put32(self.m,0x804467fc,FSEM)
        sym=lambda name:self.m.symbols[name]|1
        self.m.uc.mem_write(PCONFIG,struct.pack('<14I',CTX,WORK,UITASK,WID,UID,FQ,FSEM,
            *SLOTS,0,1,sym('rc_stock_send'),0x80076951,DRIVER+0x81))
        self.m.uc.mem_write(WCONFIG,struct.pack('<14I',CTX,*SLOTS,*([0]*6),FID,FQ,
            sym('rc_stock_receive'),0x80060621,DRIVER+0x71))
        self.m.hooks[0x80076950]=self.read_wait
        self.m.hooks[0x80060620]=self.read_public
        self.m.hooks[DRIVER+0x70]=lambda a:stop(self.m)
        self.m.hooks[DRIVER+0x80]=self.pause_read
        self.m.hooks[0x8005f168]=lambda a:0
        self.m.uc.hook_add(UC_HOOK_CODE,self.redirect,begin=0x80036208,end=0x80036208)
        for address,name in ((0x80036152,'next'),(0x80036184,'read')):
            def file_boundary(uc,addr,n,u,name=name):
                uc.reg_write(UC_ARM_REG_LR,(addr+4)|1)
                uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rw_'+name]|1)
            self.m.uc.hook_add(UC_HOOK_CODE,file_boundary,begin=address,end=address)
        if bind:assert self.rc('bind_reads',PCONFIG,WCONFIG)==OK
    def redirect(self,uc,address,size,user):
        if address==0x80036208:
            uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rp_read_entry']|1)
            return
        return super().redirect(uc,address,size,user)
    def kernel_send(self,a):
        if a[0]!=FQ:return super().kernel_send(a)
        raw=bytes(self.m.uc.mem_read(a[1],16));self.wire.append(raw)
        magic,slot,ticket,_=struct.unpack('<4I',raw);assert magic==0x52525131
        task=WORK if slot==0 else UITASK
        assert self.word(task)==1 and self.word(task+4)==2
        tag=bytes(self.m.uc.mem_read(task+8,16))
        assert bytes(self.m.uc.mem_read(SLOTS[slot]+12,16))==tag
        self.scopes.append((*struct.unpack('<4I',tag)[1:],ticket))
        if self.delivery:self.q[FQ].append(raw)
        return 1 if self.delivery else 0
    def read_wait(self,a):
        if a[0]==FSEM:self.waits+=1
        return 1 # Early wake deliberately precedes file-worker completion.
    def pause_read(self,a):self.suspended=True;return stop(self.m)
    def read_public(self,a):
        self.reads+=1
        self.read_pad=next(i for i in range(4) if self.word(0x80735b24+20*i)==a[0])
        return PrefetchRig.read_samples(self,a)
    def convert(self,a):
        buf,frames,dest,pad,channels,width=a[:6]
        slot=0 if self.word(CURRENT)==WID else 1
        assert self.word(SLOTS[slot]+4)==7
        data=bytes(self.m.uc.mem_read(buf,frames*channels*width))
        self.converted.append((pad,data));return len(data)
    def scheduled(self,address,args,task,ident):
        self.active=task;put32(self.m,CURRENT,ident);self.suspended=False
        try:
            result=self.m.invoke(address,args)
            for _ in range(200):
                if not self.suspended:return result
                context=self.m.uc.context_save()
                if self.schedule and self.waits>self.reads:
                    if self.delay:self.delay-=1
                    else:
                        put32(self.m,CURRENT,FID);self.m.stack=0x20030000
                        self.m.invoke(0x80036118,[]);self.m.stack=STACK
                self.m.uc.context_restore(context);put32(self.m,CURRENT,ident)
                self.suspended=False;self.m.reached_return=False
                self.m.uc.emu_start(self.m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=10000000)
                assert self.m.reached_return
                result=self.m.uc.reg_read(REGS[0])
            return None
        finally:self.active=None
    def worker(self):return self.scheduled(0x80036290,[],WORK,WID)
    def consume(self):
        self.m.uc.reg_write(UC_ARM_REG_R4,STACK+4)
        return self.scheduled(0x8002c43e,[],UITASK,UID)


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))
    r=Ingress();owner=r.run()
    assert r.verify(owner) and r.retire()==OK and r.word(LEDGER)==0
    assert r.word(WORK+4)==r.word(UITASK+4)==5 and r.reads==r.waits==8
    assert [x[2] for x in r.scopes]==[1]*4+[2]*4
    assert all(x[0]==owner for x in r.scopes) and len({x[3] for x in r.scopes})==8
    for pad,data in r.converted:
        raw=r.files[r.expected[pad]];assert data==bytes(raw[raw.find(b'data')+8:])
    passed('compact_ingress_creates_real_RUNNING_scopes_for_eight_reads_and_completes_both_branches')

    for phase in ('worker','ui'):
        for mode in ('short','error'):
            r=Ingress();_,owner=r.submit()
            if phase=='worker':r.read_mode=mode
            r.worker()
            if phase=='ui':r.read_mode=mode
            r.consume();assert r.verify(owner) and r.retire()==FAULT
    passed('read_failures_from_either_actual_reload_branch_prevent_root_retirement')

    r=Ingress();r.delivery=False;r.schedule=False;_,owner=r.submit();r.worker()
    assert r.word(WORK)==1 and r.word(WORK+4)==2 and not r.q[UQ]
    assert not r.converted and len(r.wire)==r.waits==1 and r.retire()==BUSY
    passed('lost_read_keeps_actual_rt_run_stack_and_root_live_without_UI_publication')

    r=Ingress();_,first=r.submit();_,second=r.submit(PRODUCER+0x20)
    r.worker();r.q[UQ].reverse();r.consume()
    assert r.verify(first) and r.retire()==OK
    assert r.verify(second) and r.retire(PRODUCER+0x20)==OK
    assert r.reads==16 and len({x[3] for x in r.scopes})==16
    assert [x[0] for x in r.scopes[8:]]==[second]*4+[first]*4
    passed('shared_task_contexts_keep_correct_root_across_two_jobs_and_reversed_UI_delivery')

    for address,value in ((PCONFIG,CTX+4),(PCONFIG+4,UITASK),(PCONFIG+12,UID),
                          (WCONFIG,CTX+4),(WCONFIG+4,SLOTS[1]),(WCONFIG+40,WQ)):
        r=Ingress(bind=False);old=r.word(address);put32(r.m,address,value)
        assert r.rc('bind_reads',PCONFIG,WCONFIG)==CONFLICT
        put32(r.m,address,old)
        assert r.rc('bind_reads',PCONFIG,WCONFIG)==OK
        assert r.rc('bind_reads',PCONFIG,WCONFIG)==CONFLICT
    passed('mismatched_shared_bindings_are_rejected_without_consuming_either_one_time_binding')

    r=Ingress(bind=False);r.submit()
    assert r.rc('bind_reads',PCONFIG,WCONFIG)==BUSY
    passed('binding_after_reload_admission_is_rejected_before_read_hooks_can_be_activated')

    for address in (CTX+4,LEDGER+4,WORK,UITASK+4,SLOTS[0],SLOTS[1]+4,SLOTS[0]+8):
        r=Ingress(bind=False);put32(r.m,address,1)
        assert r.rc('bind_reads',PCONFIG,WCONFIG)==BUSY
        put32(r.m,address,0)
        assert r.rc('bind_reads',PCONFIG,WCONFIG)==OK
    passed('busy_metadata_task_or_read_slot_rejects_initialization_without_partial_binding')

    for first,config,other,remaining in (('rw_bind',WCONFIG,'rp_can_bind',PCONFIG),
                                        ('rp_bind',PCONFIG,'rw_can_bind',WCONFIG)):
        r=Ingress(bind=False)
        assert r.m.invoke(r.m.symbols[first],[config])==OK
        assert r.rc('bind_reads',PCONFIG,WCONFIG)==CONFLICT
        assert r.m.invoke(r.m.symbols[other],[remaining])==OK
    passed('already_bound_endpoint_is_detected_before_consuming_the_other_endpoint')

    out=ROOT/'analysis/read_ingress_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Compiled compact transport and rt_run create task envelopes/phases; fixture does not write these states',
        'Original reload/UI/prefetch/file-worker instructions and compiled read adapters execute on one CPU',
        'Native handles, hook redirection, queue copies, scheduling, public file effects and conversion remain fixtures',
        'Single cold binder preflights both endpoints; no concurrent initialization or live cutover supported',
        'Physical placement, storage lifetime, failure isolation and startup release remain unfinished; no device access']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
