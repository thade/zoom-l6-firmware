#!/usr/bin/env python3
"""Compiled 32-byte queue envelopes through original RecPlayCtl dispatch.

No Python request-identity sidecar. Kernel delivery/task changes and deep file
registration are fixtures; original task getter and critical sections execute.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_request_router import RequestRig,ROUTER
from verify_record_scheduler import request_setup,word
from verify_scheduling_boundaries import stop
from verify_history_capture import payload
from verify_extra_capture import ELF
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32

T=0x2201b000
QHANDLE=0x21032000
TASK=0x808e291c
PRODUCER=0x21033000
WORKER=0x21033100
OTHER=0x21033200
DEPTH=0x801f6090

def assert_fifo_send(args):
    # Only the common stock sender's queue contract, not every kernel API.
    assert args[2:4]==[0xffffffff,0],('unexpected stock queue timeout/mode',args[2:4])

class TransportRig(RequestRig):
    def __init__(self):
        super().__init__();m=self.m
        m.uc.mem_map(0xe000e000,0x1000)
        put32(m,TASK,PRODUCER);put32(m,0x801f8f38,QHANDLE)
        self.original_header_state=self.raw(0x801f8edc,128)
        self.wire=[];self.sent=[];self.callback_args=[];self.deep_args=[]
        self.tlayout=struct.unpack('<4I',self.raw(self.syms['ct_layout'],16))
        assert m.invoke(self.syms['ct_init'],[T,ROUTER,QHANDLE])==0
        del m.hooks[0x800483f8]
        m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,s,u:uc.reg_write(UC_ARM_REG_PC,self.syms['ct_queue_send']),begin=0x800483f8,end=0x800483f8)
        m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,s,u:uc.reg_write(UC_ARM_REG_PC,self.syms['ct_emulator_admit']),begin=0x8000b650,end=0x8000b650)
        from verify_pad_protocol import REGS
        def args(uc,a,s,u):
            assert word(self.m,DEPTH)==0,'Original callback under critical section'
            self.callback_args.append((a,bytes(uc.mem_read(uc.reg_read(REGS[0]),28))))
        # Start does not use r0 as arguments, but dispatcher gives it the buffer.
        for a in (0x8004b9a0,0x8004ba40):m.uc.hook_add(UC_HOOK_CODE,args,begin=a,end=a)
        self.install_stock_stubs()
    def install_stock_stubs(self):
        for fn in (0x80008a60,0x8001e4d8,0x80007c20,0x80008a70,0x8000b320,0x8000b330,
          0x8000b698,0x8000acf0,0x8000b9b8,0x80008a80,0x80008880,0x80008890,0x800068c8,
          0x8000bab8,0x8000bbe8,0x80020360,0x80006968,0x80006740,0x8000ac00):
            self.m.hooks[fn]=lambda a:0
        self.m.hooks[0x80076950]=lambda a:1
        self.m.hooks[0x800763d8]=self.kernel_send
        self.m.hooks[0x800483a8]=self.receive
    def scope(self,q,callback=0):
        assert not callback,'Callback scope must come from compiled queue dispatch'
        return self.m.invoke(self.syms['ct_scope'],[T,q])
    def rr(self,name,q,*args):
        if name in ('begin','finish_request','ignore'):
            return self.m.invoke(self.syms['ct_request_op'],[T,q,('begin','finish_request','ignore').index(name)])
        return super().rr(name,q,*args)
    def kernel_send(self,a):
        if a[0]!=QHANDLE:return 1
        assert_fifo_send(a)
        assert word(self.m,DEPTH)==0,'Blocking send under critical section'
        msg=bytes(self.m.uc.mem_read(a[1],32));self.sent.append(msg)
        if self.send_result==0:self.wire.append(msg);return 1
        return 0
    def receive(self,a):
        assert a[0]==QHANDLE
        if not self.wire:return stop(self.m)
        self.m.uc.mem_write(a[1],self.wire.pop(0));return 0
    def request(self,ui=0,busy=0,reject=False):
        q=self.begin();assert self.scope(q)==0
        request_setup(self.m,ui,busy)
        self.m.hooks[0x800763d8]=self.kernel_send
        if reject:self.m.hooks[0x80006290]=lambda a:1
        self.m.invoke(0x80034f40,[0xffffffff])
        assert self.scope(0)==0;self.rr('finish_request',q)
        assert word(self.m,DEPTH)==0
        return q
    def dispatch_all(self):
        put32(self.m,TASK,WORKER);self.install_stock_stubs()
        self.m.invoke(0x80034bc8,[])
        assert word(self.m,DEPTH)==0
        put32(self.m,TASK,PRODUCER)
    def finish(self):self.request(1);self.dispatch_all();assert self.pump()==0

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=TransportRig();m=r.m
    for task in (0,PRODUCER,OTHER):
        put32(m,TASK,task);before=r.raw(task+0x74,4) if task else b''
        assert m.invoke(0x800770e8,[])==task
        if task:assert r.raw(task+0x74,4)==before
    put32(m,TASK,PRODUCER)
    m.invoke(0x80073ec8,[]);m.invoke(0x80073ec8,[]);assert word(m,DEPTH)==2
    m.invoke(0x80073f18,[]);m.invoke(0x80073f18,[]);assert word(m,DEPTH)==0
    passed('original_current_task_getter_and_nested_critical_sections_execute',
           current_task_getter='0x800770e8',current_task_word='0x808e291c')

    r=TransportRig();r.block();q=r.request();assert not r.released(q)
    wire=r.sent[-1];fields=struct.unpack('<8I',wire)
    assert fields[0]==r.syms['ct_dispatch'] and fields[1]==T and fields[4]==123
    r.dispatch_all();assert r.released(q)
    for _ in range(5):r.block();assert r.pump()==11
    r.finish();r.validate(payload(64,384))
    assert [a for a,_ in r.callback_args]==[0x8004b9a0,0x8004ba40]
    passed('compiled_envelopes_pass_through_original_control_worker_to_start_stop_and_exact_WAV',frames=320)

    # Original callback argument words survive copied queue message and changed
    # producer stack. Callback only interprets its defined first stop argument.
    r=TransportRig();r.block();r.request();r.dispatch_all();r.block()
    q=r.begin();r.scope(q)
    source=0x21034000;words=[0x8004ba41,0,0x11111111,0x22222222,0x33333333,0x44444444,0x55555555,0x66666666]
    r.m.uc.mem_write(source,struct.pack('<8I',*words))
    assert r.m.invoke(0x800483f8,[QHANDLE,source])==0
    r.scope(0);r.rr('finish_request',q)
    r.m.uc.mem_write(source,b'\xaa'*32);r.dispatch_all()
    assert r.callback_args[-1][1]==struct.pack('<7I',*words[1:])
    assert r.pump()==0;r.validate(payload(64,128))
    passed('all_seven_original_argument_words_survive_producer_buffer_mutation')

    # Inline stop producer bypasses 4b718 and is still tagged at common sender.
    r=TransportRig();r.block();r.request();r.dispatch_all();r.block()
    q=r.begin();r.scope(q);r.m.invoke(0x80034d18,[]);r.scope(0);r.rr('finish_request',q)
    assert struct.unpack('<I',r.sent[-1][:4])[0]==r.syms['ct_dispatch']
    r.dispatch_all();assert r.pump()==0;r.validate(payload(64,128))
    passed('inline_stop_producer_is_attributed_at_common_queue_boundary')

    # Explicit bindings remain isolated when the actual current-task word changes.
    r=TransportRig();r.block();q1=r.begin();r.scope(q1)
    put32(r.m,TASK,OTHER);q2=r.begin();assert r.scope(q2)==0
    r.start();r.scope(0);r.rr('ignore',q2)
    put32(r.m,TASK,PRODUCER);r.start()
    request_setup(r.m,0);r.m.hooks[0x800763d8]=r.kernel_send
    r.m.invoke(0x80034f40,[0xffffffff]);r.scope(0);r.rr('finish_request',q1)
    r.dispatch_all();r.block();r.finish();r.validate(payload(64,128))
    assert r.released(q1) and r.released(q2)
    passed('task_identity_separates_overlapping_request_scopes')

    r=TransportRig();r.block();q=r.request();saved=r.sent[-1];r.dispatch_all()
    # Replayed completed, bad request id and old session do not run stock callback.
    bad=list(struct.unpack('<8I',saved));bad[3]+=1
    old=list(struct.unpack('<8I',saved));old[4]=122
    count=len(r.callback_args)
    r.wire.extend([saved,struct.pack('<8I',*bad),struct.pack('<8I',*old)])
    r.dispatch_all();assert len(r.callback_args)==count
    r.block();r.finish();r.validate(payload(64,128))
    passed('replayed_and_mismatched_wire_tokens_do_not_execute_original_callbacks')

    r=TransportRig();r.block();r.request();r.dispatch_all();r.block()
    # Producer coverage is incomplete: detect the bypass rather than borrow another task's scope.
    put32(r.m,TASK,OTHER);r.m.invoke(0x8004b718,[0])
    assert struct.unpack('<I',r.sent[-1][:4])[0]==0x8004ba41
    r.assert_failed()
    passed('unguarded_stop_cancels_optional_capture_and_preserves_stock_queue_message')

    r=TransportRig();r.block();r.send_result=0xffffffff;q=r.request()
    assert not r.released(q) and not r.wire;r.assert_failed()
    passed('queue_failure_keeps_uncertain_request_owned_after_compiled_transport_returns')

    r=TransportRig();r.block();r.request();r.dispatch_all();r.block()
    # Force capacity exhausted rather than allocating/reusing any live envelope.
    put32(r.m,T+12,8);q=r.request(1)
    assert struct.unpack('<I',r.sent[-1][:4])[0]==0x8004ba41
    assert not r.released(q);r.assert_failed()
    passed('fixed_envelope_capacity_exhaustion_cancels_without_reusing_live_storage')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      transport_bytes=r.tlayout[0],job_bytes=r.tlayout[1],
      limitations=['Request entry allocation/binding and all-producer coverage remain explicit/unproved',
        'Original task getter and critical instructions execute; task switches and kernel queue delivery are modeled',
        'Eight non-reused envelopes and eight task bindings; no teardown/rearm or live task-handle reuse',
        'Original callbacks execute with deep recorder/file/UI callees stubbed; admission checkpoint body is compiled fixture',
        'No firmware patch, hardware RAM/cache/timing, SD or recovery validation'])
    path=ROOT/'analysis/control_transport_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))

if __name__=='__main__':main()
