#!/usr/bin/env python3
"""Compiled playback session + original start/stop/callback/stream routines.

Offline only. Renderer fence acknowledgement is explicitly simulated. Default
unbound adapter is tested to retain ownership, never inferred from idle flags.
"""
import hashlib
import json
import struct
from verify_playback_lifetime import PlaybackRig,AUDIO,REGISTRY
from verify_work_ownership import LEDGER,OK,BUSY,FAULT,P,F,STALE,CONFLICT,FULL
from verify_scheduling_boundaries import BASE
from verify_firmware_workflow import put32
from verify_overdub_prototype import ELF
from verify_pad_protocol import ROOT,IMAGE

SESSION=0x21003a00
PORT=0x21003b00
FENCE=0x21000300
REARM=0x21000310
ERROR=0x21000320


class SessionRig(PlaybackRig):
    def __init__(self,pads=(0,)):
        super().__init__(pads)
        m=self.m;self.fence_ready=True;self.fence_ack=None;self.fence_calls=[]
        self.rearms=[];self.rearm_result=0;self.observed=[]
        assert struct.unpack('<2I',m.uc.mem_read(m.symbols['od_session_layout'],8))==(32,28)
        put32(m,SESSION,LEDGER);put32(m,SESSION+4,PORT)
        fns=[m.symbols['od_emulator_session_'+n] for n in ('loaded','start','stop')]
        fns += [FENCE|1,m.symbols['od_emulator_session_quiet'],REARM|1,
                m.symbols['od_emulator_stream_scan']]
        m.uc.mem_write(PORT,struct.pack('<7I',*fns))
        m.hooks[FENCE]=self.fence;m.hooks[REARM]=self.rearm
        m.hooks[ERROR]=lambda a:1
        m.hooks[0x80036750]=lambda a:0 # file-seek completion is modeled
        for pad in pads:
            self.seed_audio(pad);put32(m,AUDIO+pad*0x3c,0)
            put32(m,0x807348d0+pad*0x22c,1)
            put32(m,0x807348d0+pad*0x22c+0x18,128)
        def progress(a):
            self.observed.append((self.owner(),self.word(),self.mask()))
            # Model audio fade and independently execute queued workers.
            for pad in range(4):put32(m,AUDIO+pad*0x3c+0x24,0)
            if self.queue:self.run_worker()
            return 0
        m.hooks[0x80077686]=progress

    def field(self,i):return self.u32(SESSION+i*4)
    def owner(self):return self.field(3)
    def mask(self):return self.field(4)
    def invoke(self,name,*args):
        result=self.m.invoke(self.m.symbols['od_session_'+name],[SESSION,*args])
        self.invariant();assert self.field(2)==0
        return result

    def fence(self,a):
        epoch,out=a[:2];self.fence_calls.append(epoch)
        assert epoch==self.owner() and self.field(5)==1 and self.mask()==0
        if not self.fence_ready:return BUSY
        # This is synthetic renderer join/disable evidence, not recovered code.
        for pad in range(4):self.m.uc.mem_write(BASE+pad*0x44,b'\x00')
        put32(self.m,out,epoch if self.fence_ack is None else self.fence_ack)
        return OK

    def rearm(self,a):
        previous,new=a[:2];self.rearms.append((previous,new))
        assert previous==self.field(6) and new==self.owner() and previous!=new
        assert self.word()==1 and self.mask()
        return self.rearm_result

    def probe_during_operation(self,name):
        # Independent CPU to preserve the running stock caller's registers.
        p=SessionRig(())
        for address,size in ((LEDGER,self.size),(SESSION,32),(PORT,28)):
            p.m.uc.mem_write(address,bytes(self.m.uc.mem_read(address,size)))
        return p.m.invoke(p.m.symbols['od_session_'+name],[SESSION,0])


def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))

    r=SessionRig();assert r.invoke('start',0)==OK
    owner=r.owner();assert owner and r.mask()==1 and r.word()==1
    r.register(r.m.symbols['od_emulator_session_callback'])
    r.dispatch();assert len(r.queue)==1 and r.word()==1
    assert all(e[1] for e in r.entries() if e[0]!=owner)
    r.run_worker();assert r.word()==1 and r.owner()==owner
    assert r.promotion()[0]==BUSY
    passed('compiled_no_argument_callback_and_session_block_gap_between_refills')

    r=SessionRig();assert r.invoke('start',0)==OK
    owner=r.owner();assert r.invoke('scan')==OK and r.queue
    assert r.invoke('start',0)==OK
    assert r.owner()==owner and r.word()==1 and r.mask()==1
    assert r.observed and all(o==owner and count==1 for o,count,mask in r.observed)
    assert not r.queue and r.pending(0)==0
    passed('stock_retrigger_keeps_same_session_through_fade_and_pending_drain')

    r=SessionRig((0,1));assert r.invoke('start',0)==OK and r.invoke('start',1)==OK
    owner=r.owner();assert r.mask()==3 and r.word()==1
    assert r.invoke('stop',0)==OK and r.mask()==2
    assert r.invoke('quiesce')==BUSY and not r.fence_calls
    assert r.invoke('stop',1)==OK and r.owner()==owner and r.word()==1
    assert r.invoke('quiesce')==OK and r.word()==0
    passed('two_pads_share_session_until_both_stopped_and_fenced')

    r=SessionRig();assert r.invoke('start',0)==OK and r.invoke('stop',0)==OK
    put32(r.m,PORT+12,r.m.symbols['od_emulator_session_unbound_fence'])
    assert r.invoke('quiesce')==BUSY and r.word()==1
    assert r.invoke('start',0)==BUSY and r.invoke('scan')==BUSY
    assert r.promotion()[0]==BUSY
    passed('default_unbound_renderer_fence_never_releases_session')

    r=SessionRig();assert r.invoke('start',0)==OK and r.invoke('stop',0)==OK
    r.fence_ready=False
    assert r.invoke('quiesce')==BUSY and r.field(5)==1
    assert r.invoke('start',0)==BUSY and r.invoke('scan')==BUSY
    r.fence_ready=True;assert r.invoke('quiesce')==OK
    assert r.owner()==0 and r.field(6) and r.word()==0
    assert r.promotion()[0]==OK
    passed('quiesce_retries_keep_admission_closed_until_epoch_acknowledged')

    r=SessionRig();assert r.invoke('start',0)==OK and r.invoke('scan')==OK
    assert r.invoke('stop',0)==OK
    # stop's modeled fade may finish worker; create a new owned refill afterward.
    r.seed(0);assert r.invoke('scan')==OK and r.queue
    r.m.uc.mem_write(BASE+0x1c,b'\x00') # deliberately misleading idle flag
    assert r.invoke('quiesce')==BUSY and r.word()==1
    r.run_worker();assert r.invoke('quiesce')==OK and r.word()==0
    passed('idle_pending_flag_cannot_override_outstanding_child_ticket')

    r=SessionRig();assert r.invoke('start',0)==OK and r.invoke('stop',0)==OK
    r.m.uc.mem_write(BASE+0x1c,b'\x01') # unattributed preexisting work
    assert r.invoke('quiesce')==BUSY and r.word()==1
    passed('pending_flag_without_child_still_prevents_release')

    r=SessionRig();assert r.invoke('start',0)==OK and r.invoke('stop',0)==OK
    r.fence_ack=0
    assert r.invoke('quiesce')==FAULT and r.word()&F and r.owner()
    passed('missing_or_stale_fence_acknowledgement_faults_and_retains_owner')

    r=SessionRig();assert r.invoke('start',0)==OK
    old=r.owner();assert r.invoke('stop',0)==OK and r.invoke('quiesce')==OK
    assert r.invoke('start',0)==OK and r.owner()!=old
    assert r.rearms==[(old,r.owner())] and r.field(6)==0 and r.word()==1
    assert r.invoke('stop',0)==OK
    r.fence_ack=old;assert r.invoke('quiesce')==FAULT and r.owner()
    passed('fresh_session_rearms_under_new_owner_and_rejects_previous_epoch')

    r=SessionRig();assert r.invoke('start',0)==OK
    assert r.invoke('stop',0)==OK and r.invoke('quiesce')==OK
    r.rearm_result=BUSY
    assert r.invoke('start',0)==FAULT and r.owner() and r.mask()==1 and r.word()&F
    passed('uncertain_rearm_retains_new_owner_and_latches_fault')

    for operation,index in (('start',1),('stop',2)):
        r=SessionRig()
        if operation=='stop':assert r.invoke('start',0)==OK
        put32(r.m,PORT+index*4,ERROR|1)
        assert r.invoke(operation,0)==FAULT and r.owner() and r.mask()==1
        assert r.word()&F and r.invoke('quiesce')==FAULT
    passed('failed_start_or_stop_keeps_session_and_blocks_release')

    r=SessionRig();status,p=r.promotion();assert status==OK
    before=r.state(0)
    assert r.invoke('start',0)==BUSY and r.owner()==0 and r.state(0)==before
    assert r.u32(AUDIO)==0 and r.word()==P
    passed('promotion_blocks_session_before_original_restart_mutations')

    r=SessionRig();assert r.invoke('start',4)==CONFLICT
    assert r.invoke('start',1)==STALE and r.word()==0 and not r.owner()
    assert r.invoke('scan')==BUSY and r.invoke('stop',0)==OK and r.invoke('quiesce')==OK
    passed('invalid_unloaded_and_idle_operations_create_no_reservations')

    r=SessionRig();assert r.invoke('start',0)==OK
    seen=[]
    original=r.m.hooks[0x80077686]
    def contended(a):
        seen.extend(r.probe_during_operation(n) for n in ('start','stop','scan','quiesce'))
        return original(a)
    r.m.hooks[0x80077686]=contended
    assert r.invoke('stop',0)==OK and seen==[BUSY]*4
    assert r.word()==1
    passed('concurrent_operations_return_busy_without_reentering_stock_stop')

    r=SessionRig();assert r.invoke('start',0)==OK and r.invoke('stop',0)==OK
    put32(r.m,AUDIO,1) # unexpected renderer reactivation contradicts stopped mask
    assert r.invoke('quiesce')==BUSY and r.word()==1
    passed('audio_activity_after_stop_mask_clear_still_blocks_release')

    r=SessionRig();before=r.state(0)
    for i in range(16):assert r.reserve(kind=2)[0]==OK
    assert r.invoke('start',0)==FULL and r.owner()==0 and r.mask()==0
    assert r.state(0)==before and r.u32(AUDIO)==0
    passed('full_ledger_blocks_start_before_original_side_effects')

    r=SessionRig();assert r.invoke('start',0)==OK and r.invoke('stop',0)==OK
    put32(r.m,LEDGER+4,1)
    assert r.m.invoke(r.m.symbols['od_session_quiesce'],[SESSION])==BUSY
    assert r.owner() and r.field(2)==0 and r.field(5)==1 and r.field(6)==r.owner()
    put32(r.m,LEDGER+4,0)
    assert r.invoke('quiesce')==OK and r.word()==0
    passed('retirement_lock_contention_preserves_fenced_session_for_retry')

    r=SessionRig();assert r.invoke('start',0)==OK
    r.return_success=False;r.deliver=False
    assert r.invoke('scan')==BUSY and not r.queue
    assert r.invoke('stop',0)==OK and r.invoke('quiesce')==BUSY
    r.m.uc.mem_write(BASE+0x1c,b'\x00')
    assert r.invoke('quiesce')==BUSY and r.word()==1 and r.owner()
    passed('uncertain_undelivered_refill_remains_owned_after_stop_and_fence')

    r=SessionRig();assert r.invoke('start',0)==OK and r.invoke('stop',0)==OK
    put32(r.m,PORT+12,ERROR|1)
    # ERROR returns BUSY, which must remain a non-faulting wait.
    assert r.invoke('quiesce')==BUSY and not r.word()&F and r.owner()
    r.m.hooks[ERROR]=lambda a:CONFLICT
    assert r.invoke('quiesce')==FAULT and r.word()&F and r.owner()
    passed('fence_busy_is_retryable_but_contradictory_failure_faults_closed')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['Emulator-only session and port addresses; no installed patch',
          'Renderer fence/rearm acknowledgements modeled; default fence deliberately blocks',
          'Critical sections, fade progress and seek completion modeled',
          'Natural EOF does not auto-release; explicit stop/quiesce still required',
          'All ingress must route through coordinator; direct unbound callers remain',
          'Try-only serialization can skip scans; latency and retry policy unmeasured'])
    out=ROOT/'analysis/playback_session_verification.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))

if __name__=='__main__':main()
