#!/usr/bin/env python3
"""Compiled replacement reload endpoints, original stock bodies, modeled queues.
No native queue allocation/trampoline or hardware execution is claimed.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_LR
from verify_pad_reload import ReloadRig,BUSY_WORD
from verify_pad_protocol import REGS,ROOT,IMAGE
from verify_firmware_workflow import put32
from verify_overdub_prototype import ELF
from verify_reload_ownership import CTX,WORKER,UI
from verify_work_ownership import LEDGER,OK,BUSY,STALE,CONFLICT,FAULT,F

RUNTIME=0x21025000;PORTS=RUNTIME+0x20;PRODUCER=RUNTIME+0x80
WORK=RUNTIME+0x100;UITASK=RUNTIME+0x180;PACKET=RUNTIME+0x200
ARGS=RUNTIME+0x300;OUT=RUNTIME+0x380;DRIVER=0x21024000

class Transport(ReloadRig):
    def __init__(self):
        super().__init__();self.worker_packets=[];self.ui_packets=[];self.active=None
        self.producer=PRODUCER;self.deliver_ui=True;self.observed=[];self.after_io=None
        self.open_sites={}
        self.layout=struct.unpack('<6I',self.m.uc.mem_read(self.m.symbols['rt_layout'],24))
        assert self.layout==(8,32,64,16,48,36),self.layout
        put32(self.m,CTX,LEDGER);self.m.uc.mem_write(RUNTIME,struct.pack('<2I',CTX,PORTS))
        ports=[0x80008d69,0x80049da1,0x8002d569,DRIVER+1,DRIVER+0x11,
               DRIVER+0x21,DRIVER+0x31,DRIVER+0x41]
        self.m.uc.mem_write(PORTS,struct.pack('<8I',*ports))
        self.m.hooks.update({DRIVER:self.send_worker,DRIVER+0x10:self.send_ui,
                            DRIVER+0x20:lambda a:self.driver('close',a),
                            DRIVER+0x30:lambda a:self.driver('open',a),
                            DRIVER+0x40:lambda a:self.driver('write',a)})
        # Boundary trampolines modeled by PC/register redirection. The compiled
        # adapter and original body run on the SAME CPU/stack. Python only copies
        # complete transport packets and selects a scheduler task context.
        for address in (0x800483f8,0x8006e4b8,0x8005c388,0x800604e8,0x800624a8):
            self.m.hooks.pop(address,None)
            self.m.uc.hook_add(UC_HOOK_CODE,self.redirect,begin=address,end=address)
        def open_entry(uc,a,n,u):self.open_sites[self.active]=uc.reg_read(UC_ARM_REG_LR)
        self.m.uc.hook_add(UC_HOOK_CODE,open_entry,begin=0x8005ffe8,end=0x8005ffe8)
        self.m.hooks[0x8001e4d8]=lambda a:0
        self.m.hooks[0x80018350]=lambda a:0
        self.m.hooks[0x8000ac90]=lambda a:0
        self.m.hooks[0x8000a5d8]=lambda a:0
        # Real stock settings save is deliberately enabled (not inherited UI stub).

    def call(self,name,*args):return self.m.invoke(self.m.symbols['rt_'+name],list(args))
    def rl(self,name,*args):return self.m.invoke(self.m.symbols['rl_'+name],[CTX,*args])
    def redirect(self,uc,address,size,user):
        a=[uc.reg_read(reg) for reg in REGS]
        if address==0x800483f8:
            assert a[0]==0x6543
            fn='queue';args=[RUNTIME,self.producer,a[1]]
        elif address==0x8006e4b8:
            fn='event';args=[RUNTIME,self.active,a[0]]
        elif address==0x8005c388:
            fn='close';args=[RUNTIME,self.active,a[0]]
        else:
            fn='open' if address==0x800604e8 else 'write'
            scratch=ARGS+(self.active-WORK)
            uc.mem_write(scratch,struct.pack('<5I',*a,self.open_sites.get(self.active,0)));args=[RUNTIME,self.active,scratch]
        assert all(x is not None for x in args)
        for reg,value in zip(REGS,args):uc.reg_write(reg,value)
        uc.reg_write(UC_ARM_REG_PC,self.m.symbols['rt_'+fn]|1)
    def driver(self,op,a):
        assert self.active in (WORK,UITASK)
        assert self.word(LEDGER)&0x3fffffff
        assert self.word(self.active+4)==2 # RT_RUNNING
        result=getattr(super(),op)(a)
        self.observed.append((op,self.active,result))
        if self.after_io:self.after_io(self,op,result)
        return result
    def send_worker(self,a):
        packet=bytes(self.m.uc.mem_read(a[0],48))
        if self.deliver:self.worker_packets.append(packet)
        return self.queue_result
    def send_ui(self,a):
        packet=bytes(self.m.uc.mem_read(a[0],36))
        assert struct.unpack('<5I',packet[16:])==(1,4,26,0,0)
        if self.deliver_ui:self.ui_packets.append(packet)
        return self.event_result
    def submit(self,p=PRODUCER):
        self.producer=p
        result=self.call('produce',RUNTIME,p,0)
        return result,self.word(p+4)
    def receive(self,task,packet,role):
        self.m.uc.mem_write(PACKET,bytes(packet))
        return self.call('receive',task,PACKET,role)
    def execute(self,task):
        self.active=task
        try:return self.call('run',RUNTIME,task)
        finally:self.active=None
    def worker(self):
        packet=self.worker_packets.pop(0)
        assert self.receive(WORK,packet,WORKER)==OK
        return self.execute(WORK)
    def consume(self):
        packet=self.ui_packets.pop(0)
        assert self.receive(UITASK,packet,UI)==OK
        return self.execute(UITASK)
    def verify(self,owner):
        good=self.paths()==self.expected and all(self.snapshot(p)[0]==0 for p in range(4))
        assert self.rl('verify',owner,1 if good else 2)==OK
        return good
    def retire(self,p=PRODUCER):return self.call('retire',RUNTIME,p)
    def run(self):
        status,owner=self.submit();assert status==OK
        assert self.worker()==OK and self.consume()==OK
        return owner

def main():
    results=[]
    def passed(case,**kw):results.append(dict(case=case,passed=True,**kw))
    r=Transport();status,owner=r.submit();assert status==OK and r.word(BUSY_WORD)==1
    w=r.worker_packets[0]
    assert r.worker()==OK and r.retire()==BUSY
    u=r.ui_packets[0]
    assert struct.unpack('<4I',w[:16])[1]==struct.unpack('<4I',u[:16])[1]==owner
    assert r.consume()==OK and r.word(BUSY_WORD)==0 and len(r.prefetch)==8
    assert r.retire()==BUSY and r.verify(owner) and r.retire()==OK
    assert r.word(LEDGER)==0 and r.counts['settings_write']>0
    passed('compiled_packets_run_original_worker_UI_and_settings_save_on_one_CPU_then_require_verification',observed_io=len(r.observed))

    for stage in ('worker','UI'):
        r=Transport();_,owner=r.submit()
        if stage=='worker':r.fail=('close',1,'error')
        assert r.worker()==OK
        if stage=='UI':r.fail=('close',r.counts['close']+1,'error')
        assert r.consume()==OK and r.verify(owner)
        assert r.retire()==FAULT and r.word(LEDGER)&F
        assert r.word((WORK if stage=='worker' else UITASK)+24)==0xffffd825
    passed('compiled_close_observer_retains_ignored_failure_in_either_original_body')

    for failure in (('settings_write',2,'short'),('settings_write',2,'error'),('settings_close',1,'error')):
        r=Transport();_,owner=r.submit();assert r.worker()==OK;r.fail=failure
        assert r.consume()==OK and r.verify(owner)
        assert r.word(UITASK+24)!=0 and r.retire()==FAULT
    passed('original_settings_writer_short_write_write_error_and_close_error_are_retained_by_compiled_observers')

    for nth in (1,2):
        r=Transport();_,owner=r.submit();assert r.worker()==OK
        r.fail=('settings_open',nth,'error')
        assert r.consume()==OK and r.verify(owner) and r.retire()==FAULT
    passed('settings_probe_IO_error_and_creation_failure_are_not_mistaken_for_expected_absence')

    r=Transport();r.fail=('open',2,'error');_,owner=r.submit()
    assert r.worker()==OK and r.consume()==OK and r.word(WORK+24)==0xffffd825
    assert r.retire()==FAULT
    passed('compiled_open_observer_captures_failure_before_original_caller_masks_result')

    r=Transport();_,owner=r.submit();w=r.worker_packets.pop(0)
    assert r.receive(WORK,w,WORKER)==OK
    r.m.uc.mem_write(PACKET,bytes(48)) # copied task message independent of queue buffer
    put32(r.m,CTX+4,1)
    assert r.execute(WORK)==BUSY and not r.prefetch and r.word(WORK+4)==1
    assert r.receive(WORK,w,WORKER)==BUSY
    put32(r.m,CTX+4,0)
    assert r.execute(WORK)==OK and len(r.prefetch)==4 and r.consume()==OK
    assert r.verify(owner) and r.retire()==OK
    passed('busy_claim_retains_copied_packet_without_running_or_overwriting_it')

    for inject_error in (False,True):
        r=Transport();_,owner=r.submit()
        if inject_error:r.fail=('close',1,'error')
        # Contend completion metadata after the stock worker returned, not its
        # event publication; direct instruction entry is an explicit schedule.
        addr=r.m.symbols['rl_io_error' if inject_error else 'rl_complete']&~1
        fired=[]
        def contend(uc,a,n,u):
            if not fired:fired.append(True);put32(r.m,CTX+4,1)
        hook=r.m.uc.hook_add(UC_HOOK_CODE,contend,begin=addr,end=addr)
        assert r.worker()==BUSY
        count=len(r.prefetch);events=len(r.ui_packets)
        r.m.uc.hook_del(hook);put32(r.m,CTX+4,0)
        assert r.execute(WORK)==OK and len(r.prefetch)==count and len(r.ui_packets)==events
        assert r.consume()==OK and r.verify(owner)
        assert r.retire()==(FAULT if inject_error else OK)
    passed('contended_error_commit_or_completion_retries_without_reexecuting_stock_body')

    for role in (WORKER,UI):
        r=Transport();r.queue_result=0xffffffff if role==WORKER else 0
        r.event_result=0xffffffff if role==UI else 0
        owner=r.run();assert r.verify(owner) and r.retire()==OK
    passed('delivered_ambiguous_send_is_resolved_by_both_compiled_consumer_returns')

    for role in (WORKER,UI):
        r=Transport();r.queue_result=0xffffffff if role==WORKER else 0
        r.event_result=0xffffffff if role==UI else 0
        r.deliver=role!=WORKER;r.deliver_ui=role!=UI
        _,owner=r.submit()
        if role==UI:assert r.worker()==OK
        assert r.retire()==BUSY and r.word(LEDGER)==1
    passed('undelivered_ambiguous_packet_retains_storage_owner')

    r=Transport();_,owner=r.submit();w=r.worker_packets[0]
    assert r.worker()==OK and r.consume()==OK and r.verify(owner) and r.retire()==OK
    _,new=r.submit();assert new>owner
    assert r.receive(WORK,w,WORKER)==OK and r.execute(WORK)==STALE
    assert r.retire()==BUSY and r.word(LEDGER)==1
    assert r.worker()==OK and r.consume()==OK and r.verify(new) and r.retire()==OK
    passed('late_packet_cannot_claim_new_job_after_producer_reuse')

    r=Transport();_,a=r.submit();_,b=r.submit(PRODUCER+0x20)
    assert a!=b and r.word(LEDGER)==2
    assert r.worker()==OK and r.worker()==OK
    # Reverse UI order proves matching uses tags rather than FIFO pairing lists.
    r.ui_packets.reverse();assert r.consume()==OK and r.consume()==OK
    assert r.verify(b) and r.retire(PRODUCER+0x20)==OK and r.word(LEDGER)==1
    assert r.verify(a) and r.retire()==OK and r.word(LEDGER)==0
    passed('two_reload_jobs_and_reversed_UI_delivery_preserve_packet_identity')

    r=Transport();_,owner=r.submit();w=r.worker_packets[0]
    for offset in (0,12,16):
        bad=bytearray(w);bad[offset]^=1
        assert r.receive(WORK,bad,WORKER)==CONFLICT and not r.prefetch
    assert r.receive(WORK,w,UI)==CONFLICT
    assert r.worker()==OK and r.execute(WORK)==STALE
    assert r.consume()==OK and r.verify(owner) and r.retire()==OK
    passed('malformed_role_or_callback_packets_and_duplicate_run_never_execute_wrong_body')

    r=Transport();owner=r.run();assert r.verify(owner)
    assert r.call('close',RUNTIME,UITASK,0x1234)==0xffff0001
    assert r.word(LEDGER)&F and r.retire()==FAULT
    passed('unattributed_file_operation_fails_closed_without_entering_driver')

    r=Transport();_,owner=r.submit()
    def lock_at_event(uc,a,n,u):put32(r.m,CTX+4,1)
    addr=r.m.symbols['rt_event']&~1
    hook=r.m.uc.hook_add(UC_HOOK_CODE,lock_at_event,begin=addr,end=addr)
    assert r.worker()==BUSY and not r.ui_packets and r.word(LEDGER)&F
    r.m.uc.hook_del(hook);put32(r.m,CTX+4,0)
    assert r.retire()==BUSY and r.word(LEDGER)&F
    passed('UI_reservation_contention_does_not_publish_unowned_event_or_repeat_worker')

    out=ROOT/'analysis/reload_transport_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      layout=r.layout,limitations=[
       '48-byte worker and 36-byte UI replacement packets require different native queue allocation and both endpoint changes; not an installed patch',
       'Python models boundary trampolines, task-context selection, queue copies and scheduling; C executes producer, transport, claim, bodies, error and return protocol',
       'Original producer, worker callback, UI reload and settings save execute on one ARM CPU; RTOS, filesystem driver, RIFF parser and prefetch remain fixtures',
       'Compiled open/close/write observers cover modeled lower-driver boundaries only; earlier public-wrapper errors and context-specific read/EOF policy remain unaudited',
       'Producer context is retained until final verification/retirement; no fault recovery/reset; metadata publication contention faults closed',
       'Containing USB/card/recorder roots and asynchronous descendants are not newly bound; task scheduler integration and hardware placement remain unverified',
       'No mixer communication, SD writes or firmware installation']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
