#!/usr/bin/env python3
"""Audit candidate startup sites; original control flow, modeled drivers/RTOS.

Registration runs after stock idle creation on the boot CPU. This does not
approve placement/allocation budgets or authorize optional storage access.
"""
import hashlib
import json
import struct
from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_startup_order import StartupRig, SCHEDULER
from verify_extra_capture import ELF, STATE
from verify_native_worker import WORKER, CONFIG
from verify_session_manager import MAN
from verify_session_handover import DESC
from verify_control_transport import T
from verify_request_router import ROUTER
from verify_emulator_bridge import BR
from verify_block_exchange import P, SLOTS
from verify_extra_lifecycle import LIFE
from verify_native_audio import C
from verify_storage_readiness import mount, callees
from verify_native_scan import NativeScan, UID
from verify_read_ingress import DRIVER, UITASK
from verify_read_worker import CURRENT
from verify_work_ownership import F
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, IMAGE, RETURN, STACK
from verify_scheduling_boundaries import stop

POST_INIT=0x80067a84
POST_IDLE=0x800745e8
PORT=0x21038000


class Boot(StartupRig):
    def __init__(self,fail=None,optional_failure=False):
        super().__init__(fail,real_scheduler=True)
        self.observed_init=None;self.post_idle=None;self.optional_calls=0
        self.m.uc.mem_map(0x10010000,0x10000)
        self.m.uc.mem_map(STATE,0x20000)
        self.m.uc.mem_map(SLOTS,0x20000)
        with ELF.open('rb') as f:
            elf=ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type']=='PT_LOAD' and seg['p_filesz']:
                    self.m.uc.mem_write(seg['p_vaddr'],seg.data())
            self.syms={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        original=self.m.hooks[0x80076c60]
        def create(a):
            if a[0]!=self.syms['native_worker_entry']:return original(a)
            self.optional_calls+=1
            assert len(self.tasks)==36 and self.word(SCHEDULER)==0
            assert self.word(0x801f9060)!=0 # Native idle handle already exists.
            assert bytes(self.m.uc.mem_read(a[1],10))==b'L6Overdub\0'
            if optional_failure:return 0xffffffff
            put32(self.m,a[5],0x7f00);return 1
        self.m.hooks[0x80076c60]=create
        def after_init(uc,a,n,u):self.observed_init=uc.reg_read(A.UC_ARM_REG_R0)
        def after_idle(uc,a,n,u):
            self.post_idle=uc.context_save();stop(self.m)
        self.m.uc.hook_add(UC_HOOK_CODE,after_init,begin=POST_INIT,end=POST_INIT)
        self.pause=self.m.uc.hook_add(UC_HOOK_CODE,after_idle,begin=POST_IDLE,end=POST_IDLE)
    def register(self):
        # Host supplies permanent synthetic storage, but compiled boot/bind code
        # validates and initializes it. No active session is inserted by Python.
        assert self.post_idle and self.observed_init==0
        self.m.uc.mem_write(DESC,struct.pack('<10I',T,ROUTER,BR,P,LIFE,STATE,SLOTS,32,123,self.word(0x801f8f38)))
        self.m.uc.mem_write(CONFIG,struct.pack('<5I',4096,1,4,1,25))
        self.m.uc.mem_write(PORT,struct.pack('<5I',*[self.m.symbols[s] for s in
            ('na_prepare','na_arm','na_ready')],C,self.word(0x80446d78)))
        old=getattr(self.m,'stack',STACK);self.m.stack=0x20030000
        self.m.uc.mem_write(self.m.stack,struct.pack('<2I',0,1))
        try:
            result=self.m.invoke(self.syms['native_worker_register'],[WORKER,MAN,DESC,CONFIG])
            if result==0:result=self.m.invoke(self.syms['native_worker_bind_audio'],[WORKER,PORT])
            return result
        finally:self.m.stack=old
    def resume(self):
        self.m.uc.hook_del(self.pause);self.m.uc.context_restore(self.post_idle)
        self.m.reached_return=False;self.m.uc.emu_start(POST_IDLE|1,RETURN+2,count=10000000)


def ui(status=0,setup=0,send_result=0,mode=0):
    # Reuse the public-card fixture, then execute the actual UI startup prefix
    # and mode branches. Direct load-all and unrelated UI child bodies are
    # marked fixture calls; the separate native-adapter test runs load-all.
    m,_,events,messages=mount(status=status,setup=setup,send_result=send_result)
    events.clear();messages.clear();put32(m,0x807348cc,0)
    calls=[];card_returns=[];waits=[]
    for fn in callees(0x8002c1e8,0x8002c4c0)-{0x80009a40,0x8000ac80}:
        m.hooks[fn]=lambda a,fn=fn:calls.append(fn) or 0
    m.hooks[0x80006248]=lambda a:mode
    put32(m,0x80446850,0x7abc)
    def wait(a):
        if a[0]==0x7abc:waits.append(tuple(a[:2]));return 0 # Failure ignored by caller.
        return 1
    m.hooks[0x80076950]=wait
    def queued(a):calls.append(('event_wait',m.uc.reg_read(A.UC_ARM_REG_LR)));return stop(m)
    m.hooks[0x80020690]=queued
    m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:card_returns.append(uc.reg_read(A.UC_ARM_REG_R0)),
                  begin=0x8002c1f4,end=0x8002c1f4)
    m.invoke(0x8002c1e8,[])
    return m,calls,card_returns,waits,messages


def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=Boot();r.boot()
    assert r.post_idle and r.observed_init==0 and len(r.tasks)==36
    assert r.word(SCHEDULER)==0 and not r.kernel_entered
    assert r.register()==0 and r.optional_calls==1 and r.word(WORKER+8)==4
    assert r.word(r.syms['bridge_gateway_readers'])==0x80000000
    assert r.word(r.syms['ct_active'])==0 and r.word(r.syms['emulator_bridge_current'])==0
    r.resume();assert r.kernel_entered and r.word(SCHEDULER)==1
    assert r.word(WORKER+8)==4
    passed('post_idle_site_runs_compiled_registration_and_dormant_audio_binding_before_stock_kernel_entry',
           candidate=hex(POST_IDLE),initializer_observation=hex(POST_INIT))

    for fail in (('task',1),('mutex',1),('queue',1),('queue',7)):
        r=Boot(fail);r.boot()
        assert r.observed_init==0xffffffff and r.post_idle and len(r.tasks)==36
        # Do not register merely because idle creation later succeeded.
        assert not r.optional_calls;r.resume();assert r.kernel_entered
    passed('post_idle_success_does_not_replace_saved_first_initializer_failure_evidence')

    r=Boot(('idle',1));r.boot()
    assert r.idle_failed and not r.post_idle and not r.optional_calls
    r=Boot();original=r.m.hooks[0x80076c60]
    def idle_zero(a):return 0 if a[2]==90 and a[4]==0 else original(a)
    r.m.hooks[0x80076c60]=idle_zero;r.boot()
    assert not r.post_idle and not r.kernel_entered
    passed('idle_creation_failure_or_non_success_never_reaches_registration_candidate')

    r=Boot(optional_failure=True);r.boot();assert r.register()==13
    assert r.word(WORKER+8)==3 and r.optional_calls==1
    r.resume();assert r.kernel_entered and r.word(SCHEDULER)==1
    assert r.word(r.syms['emulator_bridge_current'])==0
    passed('optional_creation_failure_preserves_stock_scheduler_continuation_and_closed_capture')

    for status,setup,returned in ((1,0,0),(8,0,0xffffffff),(0,0xffffffff,0xffffffff)):
        m,calls,results,waits,messages=ui(status=status,setup=setup)
        assert results==[returned] and not messages
        assert 0x80009930 in calls and calls[-1][0]=='event_wait'
        assert waits==[(0x7abc,0xffffffff)]
    passed('normal_UI_startup_ignores_card_setup_and_semaphore_failure_then_loads_pads_and_enters_event_wait')

    for outcome in (0,0xffffffff):
        m,calls,results,_,messages=ui(send_result=outcome)
        assert results==[0] and len(messages)==1 and 0x80009930 in calls
        assert int.from_bytes(m.uc.mem_read(0x807348cc,4),'little')==1
        assert calls[-1]==('event_wait',0x8002c445)
    passed('normal_event_loop_is_reached_with_reload_pending_even_when_queue_send_failed')

    modes=[]
    for mode in range(6):
        _,calls,_,_,_=ui(mode=mode)
        assert calls[-1][0]=='event_wait'
        modes.append(dict(mode=mode,return_address=hex(calls[-1][1])))
    passed('startup_mode_branches_reach_distinct_wait_loops_so_one_loop_hook_is_not_global_admission',modes=modes)

    r=NativeScan().loaded();before=r.reads;observed=[]
    r.active=UITASK;put32(r.m,CURRENT,UID)
    r.m.hooks[DRIVER+0x80]=lambda a:stop(r.m)
    for name in ('pf_load','rt_open'):
        pc=r.m.symbols[name]&~1
        r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u,name=name:observed.append(name),begin=pc,end=pc)
    assert r.m.invoke(0x80009930,[])==0
    assert observed==['pf_load','rt_open']*4 and r.word(r.ledger)&F and r.reads==before
    assert r.paths()==['NO ASSIGN']*4
    assert not r.ordinary_packets and not r.parents
    passed('direct_startup_load_all_has_no_reload_scope_so_open_guard_faults_and_stock_loader_clears_all_assignments',
           limitation='Main driver fixture selected without injecting an ownership envelope; no new read reaches file worker')

    # The stock event receive supplies an infinite timeout. There is no periodic
    # return on which to rely for the new release API's BUSY -> retry handshake.
    from verify_reload_queue_audit import QueueRig, BUFFER
    q=QueueRig();wait=[]
    def receive(a):wait.append(tuple(a[:3]));return stop(q.m)
    q.m.hooks[0x80076710]=receive;q.m.invoke(0x80020690,[BUFFER])
    assert len(wait)==1 and wait[0][0]==q.ui and wait[0][2]==0xffffffff
    passed('original_Main_event_receive_blocks_indefinitely_so_release_retry_needs_explicit_wakeup_or_polling')

    out=ROOT/'analysis/startup_sites_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
        'Initializer evidence is observed and registration is invoked by harness at a suspended original instruction, not an installed trampoline',
        'Stock task creation, allocator backing, drivers and kernel scheduling remain fixtures',
        'Post-idle placement protects the already-created idle task but does not reserve later stock allocation capacity',
        'UI load-all is a marked stub in mode tests and executes separately with compiled read adapters in the negative control',
        'No valid production release site or complete startup ownership scope is claimed',
        'No device access, image staging or deployment']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
