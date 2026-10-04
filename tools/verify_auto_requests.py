#!/usr/bin/env python3
"""Automatic owned entry/exit around five original request functions.

Request allocation/binding is compiled; kernel delivery, file registration and
selected callee effects remain explicit fixtures. No device access.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_control_transport import TransportRig,T,TASK,PRODUCER,OTHER,DEPTH
from verify_record_scheduler import request_setup,word
from verify_history_capture import payload
from verify_extra_capture import ELF
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32

ENTRIES={0x80034f40:'ct_record_request',0x80034d18:'ct_stop_request',0x80034e58:'ct_play_request',
         0x80035038:'ct_stop_argument',0x800350d8:'ct_stop_other'}

class AutoRig(TransportRig):
    def __init__(self):
        super().__init__();m=self.m
        self.alayout=struct.unpack('<3I',self.raw(self.syms['ct_auto_layout'],12))
        self.entries_enabled=True
        for address,name in ENTRIES.items():
            def redirect(uc,a,s,u,name=name):
                if self.entries_enabled:uc.reg_write(A.UC_ARM_REG_PC,self.syms[name])
            m.uc.hook_add(UC_HOOK_CODE,redirect,begin=address,end=address)
        m.hooks[0x80007ad0]=lambda a:0
        m.hooks[0x80006958]=lambda a:0
        m.hooks[0x8000ad10]=lambda a:1
        m.hooks[0x8004b890]=lambda a:0
    def slots(self):return [T+self.alayout[1]+i*self.alayout[0] for i in range(self.alayout[2])]
    def newest(self):return max(self.slots(),key=lambda q:word(self.m,q+8))
    def request(self,ui=0,busy=0,reject=False,entry=0x80034f40):
        request_setup(self.m,ui,busy);self.m.hooks[0x800763d8]=self.kernel_send
        if reject:self.m.hooks[0x80006290]=lambda a:1
        self.m.invoke(entry,[0xffffffff])
        assert word(self.m,DEPTH)==0
        return self.newest() # observe only; does not allocate/bind/complete
    def idle_scopes(self):
        for i in range(8):assert word(self.m,T+20+12*i+4)==0
        for q in self.slots():assert word(self.m,q+64)==0

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))

    for endpoint in ENTRIES:
        r=AutoRig();r.block();q=r.request();r.idle_scopes();assert not r.released(q)
        r.dispatch_all();assert r.released(q)
        for _ in range(4):r.block();assert r.pump()==11
        stopq=r.request(1,entry=endpoint);r.idle_scopes();assert stopq!=q and not r.released(stopq)
        r.dispatch_all();assert r.released(stopq) and r.pump()==0
        if endpoint==0x80035038:assert struct.unpack_from('<I',r.callback_args[-1][1])[0]==0xffffffff
        r.validate(payload(64,320))
    passed('automatic_start_and_all_five_stop_paths_keep_exact_extra_audio',frames=256)

    for ui,busy,reject in ((0,1,False),(2,0,False),(1,0,True)):
        r=AutoRig();r.block();start=r.request();r.dispatch_all();r.block();assert r.pump()==11
        q=r.request(ui,busy,reject);r.idle_scopes();assert r.released(q) and not r.wire
        assert q!=start
        r.block();r.finish();r.validate(payload(64,192))
    passed('ignored_busy_playback_and_rejected_returns_automatically_release_their_own_scope')

    r=AutoRig();r.block();ids=[];addresses=[]
    for _ in range(80):
        q=r.request(0,1);addresses.append(q);ids.append(word(r.m,q+8));r.idle_scopes()
        assert r.released(q) and not r.wire
    assert len(set(addresses))==1 and ids==list(range(1,81))
    r.request();r.dispatch_all();r.block();r.finish();r.validate(payload(64,128))
    passed('ignored_never_submitted_storage_can_be_reused_without_exhausting_pool',requests=80)

    r=AutoRig();r.block();q=r.request();oldid=word(r.m,q+8)
    for _ in range(20):r.request(0,1)
    assert word(r.m,q+8)==oldid and not r.released(q)
    r.dispatch_all();r.block();r.finish();r.validate(payload(64,128))
    passed('queued_request_storage_is_not_recycled_during_later_ignored_requests')

    r=AutoRig();r.block();r.send_result=0xffffffff;q=r.request();r.idle_scopes()
    assert not r.released(q) and not r.wire;r.assert_failed()
    # No request pool reset is performed merely because the caller returned.
    assert word(r.m,q+8)!=0 and word(r.m,q+36)==1
    passed('failed_send_retains_request_after_automatic_caller_exit')

    r=AutoRig();r.block();q=r.request(0,entry=0x80034e58);r.idle_scopes()
    assert r.released(q) and struct.unpack_from('<I',r.sent[-1])[0]==0x8004b891
    r.dispatch_all();assert word(r.m,T+16)==0
    r.request();r.dispatch_all();r.block();r.finish();r.validate(payload(64,128))
    passed('play_start_message_remains_stock_and_provisional_capture_request_is_released')

    for alias in (0x8002d7b8,0x80008a20):
        r=AutoRig();r.block();r.request();r.dispatch_all();r.block()
        r.request(1,entry=alias);r.dispatch_all();assert r.pump()==0
        r.validate(payload(64,128));r.idle_scopes()
    passed('verified_tail_call_aliases_reach_automatic_entry_wrappers')

    # Mimic a same-task nested entry while an outer request scope is live.
    r=AutoRig();r.block();outer=r.begin();assert r.scope(outer)==0
    r.request(0,1)
    assert word(r.m,T+24)==outer and word(r.m,T+16)==28
    r.scope(0);r.rr('ignore',outer);r.assert_failed()
    passed('unsupported_same_task_nesting_cannot_borrow_parent_request_and_restores_scope')

    r=AutoRig();r.block();r.request();r.dispatch_all();r.block()
    for q in r.slots():put32(r.m,q+64,1)
    r.request(1)
    assert struct.unpack_from('<I',r.sent[-1])[0]==0x8004ba41
    assert word(r.m,T+16)==26;r.assert_failed()
    passed('pool_exhaustion_preserves_ordinary_request_and_cancels_optional_capture')

    snapshots=[]
    for enabled in (False,True):
        r=AutoRig();r.entries_enabled=enabled;m=r.m;request_setup(m,0,1)
        m.hooks[0x800763d8]=r.kernel_send
        regs=[getattr(A,'UC_ARM_REG_R'+str(i)) for i in range(4,12)]
        values=[0x12340000+i*0x101 for i in range(len(regs))]
        for reg,v in zip(regs,values):m.uc.reg_write(reg,v)
        result=m.invoke(0x80034f40,[0xffffffff])
        snapshots.append((result,[m.uc.reg_read(reg) for reg in regs],m.uc.reg_read(A.UC_ARM_REG_SP)))
        assert snapshots[-1][1]==values and snapshots[-1][2]==m.stack
    assert snapshots[0]==snapshots[1]
    passed('wrapper_preserves_stock_return_callee_saved_integer_registers_and_stack')

    # Different original task identities can independently enter these wrappers.
    r=AutoRig();r.block();q=r.request();put32(r.m,TASK,OTHER)
    ignored=r.request(0,1);assert r.released(ignored) and not r.released(q)
    put32(r.m,TASK,PRODUCER);r.dispatch_all();r.block();r.finish()
    r.validate(payload(64,128));r.idle_scopes()
    passed('automatic_requests_remain_separate_across_task_identities')

    r=AutoRig();r.block();request_setup(r.m,0,1);r.m.hooks[0x800763d8]=r.kernel_send
    def unexpected_task(a):put32(r.m,TASK,OTHER);return 0
    r.m.hooks[0x8000ac70]=unexpected_task
    r.m.invoke(0x80034f40,[0xffffffff]);q=r.newest()
    assert word(r.m,T+16)==29 and word(r.m,T+24)==q
    assert word(r.m,q+64)==1 and not r.released(q)
    put32(r.m,TASK,PRODUCER);r.assert_failed()
    passed('unexpected_task_identity_on_return_retains_scope_and_storage_instead_of_freeing')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      entry_sites={hex(k):v for k,v in ENTRIES.items()},transport_bytes=r.tlayout[0],entry_slot_bytes=r.alayout[0],entry_slots=r.alayout[2],
      limitations=['Five verified high-level entry paths plus two tested aliases; not exhaustive producer coverage',
        'Kernel delivery/task changes and deep file/UI effects remain fixtures',
        'Only never-submitted ignored slots are reused; queued requests/jobs have no session rearm',
        'No hardware placement, timing, bootloader recovery or installed hooks'])
    path=ROOT/'analysis/auto_requests_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))

if __name__=='__main__':main()
