#!/usr/bin/env python3
"""Compact compiled transport through stock worker/UI and guarded cleanup.
Native entry redirection, kernel queues and task switching remain fixtures.
"""
from collections import deque
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_R4,UC_CPU_ARM_CORTEX_M7
from verify_reload_transport import Transport,RUNTIME,PORTS,PRODUCER,WORK,UITASK,DRIVER,CTX,LEDGER,OK,BUSY,STALE,CONFLICT,FAULT,F
from verify_pad_protocol import ROOT,IMAGE,REGS,STACK
from verify_overdub_prototype import ELF,Emulator
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_reload_queue_audit import packed,REDUCE,PLAIN
BIND=0x21026000;WQ=0x808ff000;UQ=0x808ff080;CURRENT=0x808e291c
WID=0x7001;UID=0x7002;SCRATCH=0x21027000

class Compact(Transport):
    emulator_factory=staticmethod(lambda:Emulator(cpu_model=UC_CPU_ARM_CORTEX_M7,mclass=True))
    def __init__(self):
        super().__init__();self.q={WQ:deque(),UQ:deque()};self.yields=0;self.timeouts=[]
        assert self.word(self.m.symbols['rc_layout'])==44
        sym=lambda s:self.m.symbols[s]|1
        self.m.uc.mem_write(BIND,packed((RUNTIME,WORK,UITASK,WID,UID,WQ,UQ,DRIVER+0x51,DRIVER+0x61,0,0)))
        assert self.rc('bind',BIND)==OK
        put32(self.m,PORTS+8,sym('rc_stock_ui'))
        put32(self.m,PORTS+12,sym('rc_send_worker'))
        put32(self.m,PORTS+16,sym('rc_send_ui'))
        put32(self.m,0x801f8f3c,WQ);put32(self.m,0x801f8f28,UQ)
        self.m.hooks[DRIVER+0x50]=self.native_receive
        self.m.hooks[DRIVER+0x60]=self.yield_task
        self.m.hooks[0x800763d8]=self.kernel_send
        self.m.hooks[0x80076710]=self.kernel_receive
        self.m.hooks[0x8003bd58]=lambda a:0
        for fn in (0x80073ec8,0x80073f18):self.m.hooks[fn]=lambda a:0
        for addr,name in ((0x800483a8,'next'),(0x8002d568,'ui'),(0x8001fd08,'filter'),(0x80020438,'clear'),(0x80020548,'delete')):
            self.m.hooks.pop(addr,None)
            def redir(uc,a,n,u,name=name):uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rc_'+name]|1)
            self.m.uc.hook_add(UC_HOOK_CODE,redir,begin=addr,end=addr)
    def rc(self,name,*args):return self.m.invoke(self.m.symbols['rc_'+name],list(args))
    def redirect(self,uc,address,size,user):
        if address==0x800483f8:
            q=uc.reg_read(REGS[0])
            if q==WQ:
                args=[RUNTIME,self.producer,uc.reg_read(REGS[1])]
                for reg,v in zip(REGS,args):uc.reg_write(reg,v)
                uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rt_queue']|1)
            else:uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rc_queue']|1)
            return
        return super().redirect(uc,address,size,user)
    def qsync(self,q):put32(self.m,q+0x38,len(self.q[q]))
    def kernel_send(self,a):
        q=a[0]
        if q not in self.q:return 1
        self.timeouts.append((q,a[2]))
        if len(self.q[q]) >= (512 if q==WQ else 4096):return 0
        self.q[q].append(bytes(self.m.uc.mem_read(a[1],32 if q==WQ else 20)));self.qsync(q);return 1
    def kernel_receive(self,a):
        q=a[0]
        if not self.q[q]:return 0
        self.m.uc.mem_write(a[1],self.q[q].popleft());self.qsync(q);return 1
    def native_receive(self,a):
        if not self.q[a[0]]:return stop(self.m)
        return 0 if self.kernel_receive(a) else 0xffffffff
    def yield_task(self,a):self.yields+=1;return 0
    def submit(self,p=PRODUCER):
        put32(self.m,CURRENT,0x7003)
        return super().submit(p)
    def worker(self):
        self.active=WORK;put32(self.m,CURRENT,WID)
        try:return self.m.invoke(0x80036290,[])
        finally:self.active=None
    def consume(self):
        self.active=UITASK;put32(self.m,CURRENT,UID)
        self.m.uc.reg_write(UC_ARM_REG_R4,STACK+4)
        try:return self.m.invoke(0x8002c43e,[])
        finally:self.active=None
    def ui_events(self):return [struct.unpack('<5I',p) for p in self.q[UQ]]
    def seed(self,events):self.q[UQ]=deque(packed(e) for e in events);self.qsync(UQ)
    def run(self):
        status,owner=self.submit();assert status==OK
        self.worker();self.consume();return owner

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    r=Compact();_,o=r.submit();w=r.q[WQ][0]
    assert len(w)==32 and struct.unpack('<I',w[:4])[0]==r.m.symbols['rc_worker']|1
    r.worker();assert len(r.q[UQ])==1 and len(r.q[UQ][0])==20
    assert r.ui_events()[0][3]==o and r.retire()==BUSY
    r.consume();assert r.verify(o) and r.retire()==OK and r.word(LEDGER)==0
    assert len(r.prefetch)==8 and r.counts['settings_write']==2
    assert all(timeout==0 for q,timeout in r.timeouts if q==UQ)
    passed('compiled_32_20_byte_messages_execute_original_worker_Main_UI_reload_and_settings_save')

    r=Compact();_,o=r.submit();r.worker();events=r.ui_events()
    assert r.rc('clear')==BUSY and r.ui_events()==events
    assert r.rc('delete',1,4,26)==BUSY and r.ui_events()==events
    r.m.uc.mem_write(REDUCE,b''.join(packed(e) for e in events+[(2,3,26,0,0)]))
    assert r.rc('filter',2)==2 and bytes(r.m.uc.mem_read(REDUCE,40))==b''.join(packed(e) for e in events+[(2,3,26,0,0)])
    assert r.word(BIND+36)==7
    r.consume();assert r.verify(o) and r.retire()==OK
    r.seed([PLAIN,PLAIN]);r.m.invoke(0x80020360,[]);assert r.ui_events()==[PLAIN]
    assert r.rc('delete',1,4,26)==OK and not r.ui_events()
    r.seed([PLAIN]);assert r.rc('clear')==OK and not r.ui_events()
    passed('all_three_cleanup_operations_preserve_live_reload_then_execute_original_behavior_after_retirement')

    r=Compact();_,o=r.submit()
    r.seed([PLAIN]);assert r.rc('clear')==BUSY and r.ui_events()==[PLAIN]
    assert r.word(CTX+392)==0
    passed('cleanup_is_deferred_even_before_worker_publishes_its_UI_continuation')

    r=Compact();assert r.rl('cleanup_begin')==OK
    status,o=r.submit();assert status==BUSY and o==0 and not r.q[WQ]
    assert r.rl('cleanup_begin')==BUSY and r.rl('cleanup_end')==OK
    assert r.rl('cleanup_end')==CONFLICT
    assert r.submit()[0]==OK
    passed('cleanup_lease_closes_admission_without_holding_metadata_lock_and_reopens_only_after_end')

    r=Compact();_,o=r.submit();r.worker();r.fail=('settings_write',2,'short');r.consume()
    assert r.verify(o) and r.retire()==FAULT and r.word(LEDGER)&F
    assert r.rc('clear')==BUSY
    passed('compact_route_retains_original_saver_short_write_error_and_defers_cleanup_of_faulted_job')

    r=Compact();_,o=r.submit();w=r.q[WQ].popleft();r.qsync(WQ)
    put32(r.m,CURRENT,WID);r.m.uc.mem_write(SCRATCH,w[4:]);put32(r.m,CTX+4,1)
    assert r.rc('worker',SCRATCH)==BUSY and r.word(WORK+4)==1
    r.q[WQ].append(w);r.qsync(WQ)
    assert r.rc('next',WQ,SCRATCH+0x100)==0xffffffff and r.yields==1 and len(r.q[WQ])==1
    put32(r.m,CTX+4,0);r.worker()
    assert len(r.prefetch)==4 and len(r.q[UQ])==1 # duplicate rejects after resume
    r.consume();assert r.verify(o) and r.retire()==OK
    passed('worker_receive_retries_retained_claim_before_dequeuing_next_message_and_does_not_reexecute_duplicate')

    r=Compact();_,o=r.submit();r.worker();u=r.q[UQ].popleft();r.qsync(UQ)
    put32(r.m,CURRENT,UID);r.m.uc.mem_write(SCRATCH,u);put32(r.m,CTX+4,1)
    assert r.rc('ui',SCRATCH)==BUSY
    r.q[UQ].append(u);r.qsync(UQ)
    assert r.rc('next',UQ,SCRATCH+0x100)==0xffffffff and r.yields==1
    put32(r.m,CTX+4,0);r.consume()
    assert len(r.prefetch)==8 and r.verify(o) and r.retire()==OK
    passed('Main_receive_retries_retained_UI_work_before_next_event')

    for ident in (0,UID,0x8888):
        r=Compact();_,o=r.submit();w=r.q[WQ][0];r.m.uc.mem_write(SCRATCH,w[4:]);put32(r.m,CURRENT,ident)
        assert r.rc('worker',SCRATCH)==FAULT and not r.prefetch and r.word(LEDGER)&F
    passed('original_current_task_getter_rejects_null_unknown_and_wrong_task_binding')

    r=Compact();assert r.rc('bind',BIND)==CONFLICT
    _,o=r.submit();w=r.q[WQ][0];r.worker();r.consume();assert r.verify(o) and r.retire()==OK
    _,new=r.submit();r.q[WQ].appendleft(w);r.qsync(WQ);r.worker();r.consume()
    assert len(r.prefetch)==16 and r.verify(new) and r.retire()==OK
    passed('binding_cannot_be_replaced_and_old_ticket_cannot_claim_reused_producer')

    r=Compact();_,a=r.submit();_,b=r.submit(PRODUCER+0x20);r.worker()
    assert [e[3] for e in r.ui_events()]==[a,b]
    r.q[UQ].reverse();r.consume()
    assert r.verify(b) and r.retire(PRODUCER+0x20)==OK and r.word(LEDGER)==1
    assert r.verify(a) and r.retire()==OK
    passed('two_live_jobs_survive_reversed_UI_order_through_original_dispatch')

    r=Compact();_,o=r.submit();r.seed([PLAIN]*4096);r.worker()
    assert len(r.q[UQ])==4096 and r.retire()==BUSY and r.word(BIND+36)&1
    assert all(timeout==0 for q,timeout in r.timeouts if q==UQ)
    assert r.word(LEDGER)==1
    passed('full_UI_queue_preserves_existing_events_and_returns_without_blocking_or_releasing_missing_continuation',limitation='At this checkpoint Main has not run retry ingress; the owner remains held. Recovery is tested separately in verify_reload_recovery.py')

    # Verify native entry hooks, not just direct adapter calls, defer all clears.
    r=Compact();_,o=r.submit();r.worker();events=r.ui_events()
    r.m.invoke(0x80020438,[]);r.m.invoke(0x80020548,[1,4,26,0]);r.m.invoke(0x80020360,[])
    assert r.ui_events()==events and r.retire()==BUSY
    r.consume();assert r.verify(o) and r.retire()==OK
    passed('original_clear_delete_and_backlog_cleanup_entry_redirection_preserves_pending_ticket')

    for task,ident in ((WORK,WID),(UITASK,UID)):
        r=Compact();_,o=r.submit()
        if task==UITASK:r.worker()
        addr=r.m.symbols['rl_complete']&~1;fired=[]
        def contend(uc,a,n,u):
            if not fired:fired.append(True);put32(r.m,CTX+4,1)
        hook=r.m.uc.hook_add(UC_HOOK_CODE,contend,begin=addr,end=addr)
        r.m.hooks[DRIVER+0x60]=lambda a:stop(r.m)
        (r.worker if task==WORK else r.consume)()
        assert r.word(task+4)==4
        count=len(r.prefetch)
        r.m.uc.hook_del(hook);put32(r.m,CTX+4,0)
        r.m.hooks[DRIVER+0x60]=r.yield_task
        (r.worker if task==WORK else r.consume)()
        assert len(r.prefetch)==count
        if task==WORK:r.consume()
        assert r.verify(o) and r.retire()==OK
    passed('both_native_receive_paths_resume_contended_return_completion_without_replaying_stock_IO')

    r=Compact();r.seed([PLAIN]);observed=[]
    original=r.m.hooks[0x80076710]
    def during_clear(a):
        observed.append((r.word(CTX+392),r.word(CTX+4)))
        return original(a)
    r.m.hooks[0x80076710]=during_clear
    r.rc('clear')
    assert observed and all(x==(1,0) for x in observed) and r.word(CTX+392)==0
    assert r.submit()[0]==OK
    passed('actual_clear_body_holds_admission_lease_but_not_metadata_latch_until_original_return')

    out=ROOT/'analysis/reload_compact_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Entry hooks are emulator PC redirects; no native patch, memory placement or live task lifecycle verified',
      'Current task getter executes original code; task identities and switching are fixture values; interrupt guard is compiled but not a hardware interrupt test',
      'C codec, pending-work ingress, cleanup lease and assembly forwarders execute with original worker, Main loop, UI body and file control flow',
      'Kernel FIFO/mutex/yield, filesystem driver, RIFF parser, prefetch and producer/file task attribution retain explicit fixtures',
      'This suite does not install the mode-5 entry adapter; transition draining and retained delivery recovery are tested separately in verify_reload_recovery.py',
      'Global nonblocking UI send changes saturation behavior; all unrelated send callers and UI scheduling require native integration audit',
      'No device access, flashing or SD writes']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
