#!/usr/bin/env python3
"""Explore a between-events handoff without diverting stock UI packets.
The window scheduler and all-domain readiness are models, NOT installed hooks.
Original event receive/dispatch/filter and checked handoff code execute.
"""
import json
from unicorn import UC_HOOK_CODE
from verify_pad_dispatch import Dispatch,PRESS,RELEASE,COMPLETE
from verify_handoff_locks import Locks
from verify_reload_queue_audit import QueueRig
from verify_scheduling_boundaries import stop
from verify_pad_protocol import ROOT

class Window(Dispatch):
    def __init__(self,arrivals=()):
        super().__init__(native=True)
        self.handoff=Locks();self.arrivals=list(arrivals);self.attempts=[]
        self.tried=False;self.pending_completion=False;self.closed=False
        h=self.handoff;h.task=0x7100
        original_read=h.read
        def read(a):
            if self.arrivals:
                # Model another producer's kernel copy while this Main is busy.
                # No recursive execution on Main's CPU and no private FIFO.
                self.seed(self.events()+self.arrivals);self.arrivals=[]
            assert self.closed
            return original_read(a)
        h.m.hooks[0x80060818]=read
        def unexpected(a):raise AssertionError('handoff required stock Main event service')
        for addr in (0x8006e4b8,0x80020ca0,0x80020548,0x80020690,0x8002d568):
            h.m.hooks[addr]=unexpected
        self.m.hooks[0x80008b68]=self.complete
        def boundary(uc,addr,size,opaque):
            # Deliberately conservative: never extract/classify a queued event.
            # Counts are observations in this fixture, not a device fence.
            if self.tried or self.events() or self.pending_completion or self.playing:return
            self.tried=True;self.closed=True
            result=h.step();self.attempts.append(result)
            if result==10:
                # Unknown I/O ownership: no invented timeout release/replay.
                stop(self.m);return
            assert not h.locked
            self.closed=False
        self.m.uc.hook_add(UC_HOOK_CODE,boundary,begin=0x80020690,end=0x80020690)
    def complete(self,a):
        assert not self.closed
        self.effects.append(('reload',));self.pending_completion=False
        return 0

def main():
    cases=[]
    def passed(name):cases.append(name)
    r=Window([PRESS,PRESS,RELEASE]);r.loop()
    assert r.attempts==[0] and r.handoff.seals==1 and not r.closed
    assert r.audio_events()==[('start',2)] and not r.events()
    assert r.handoff.contexts and set(r.handoff.contexts)=={0x7100}
    assert not r.handoff.queue_calls
    passed('modeled_between_events_window_runs_checked_handoff_then_preserves_stock_duplicate_removal')

    r=Window([PRESS,(2,3,86,0,0),RELEASE]);r.loop()
    assert r.attempts==[0] and r.audio_events()==[('start',2)]
    passed('stock_deletion_sees_both_physical_and_category_2_packets_after_handoff')

    r=Window([PRESS]);r.pending_completion=True;r.seed([COMPLETE]);r.loop()
    assert r.attempts==[0] and r.effects.index(('reload',))<r.effects.index(('start',2))
    passed('already_queued_reload_dispatches_before_window_is_considered')

    r=Window();r.pending_completion=True;r.loop()
    assert not r.attempts and not r.closed and not r.handoff.seals
    passed('empty_queue_does_not_override_unjoined_completion_evidence')

    r=Window();r.seed([PRESS]);r.loop()
    assert r.audio_events()==[('start',2)] and not r.attempts
    passed('queued_input_keeps_priority_and_playing_pad_postpones_optional_handoff')

    r=Window([PRESS]);r.handoff.fenced=False;r.loop()
    assert r.attempts==[2] and not r.handoff.seals and not r.closed
    assert r.audio_events()==[] # No read took place to inject new input.
    passed('unavailable_all_domain_gate_returns_BUSY_without_holding_Main_or_mutating_files')

    r=Window([PRESS]);r.handoff.fail=('settings_write',2,'short');r.loop()
    assert r.attempts==[8] and not r.closed and r.audio_events()==[('start',2)]
    passed('joined_save_failure_rolls_back_before_original_input_dispatch_resumes')

    r=Window();r.handoff.seal_status=10;r.loop()
    assert r.attempts==[10] and r.closed and r.handoff.locked
    assert not r.waits
    passed('uncertain_handoff_does_not_fabricate_release_to_resume_input')

    # Real stock capacity and reducer, not the eight-entry experimental FIFO.
    r=QueueRig();r.seed([PRESS]*4096)
    assert r.event((0,0,24,0,0))==0
    assert r.events()==[PRESS,(0,0,24,0,0)]
    passed('stock_full_queue_compacts_duplicate_input_using_original_sender_and_reducer')

    # Constructed unsupported-kind packets establish the mechanical limit only;
    # no claim that normal producers can generate this particular backlog.
    r=QueueRig();packets=[(3,0,23,i,0) for i in range(4096)]
    r.seed(packets);held=[];blocked=[];original=r.send
    r.m.hooks[0x80076950]=lambda a:held.append(a[0]) or 1
    def send(a):
        if a[0]==r.ui and len(r.queues[r.ui]['items'])==4096:
            blocked.append(a[2]);return stop(r.m)
        if a[0] not in r.queues:held.remove(a[0])
        return original(a)
    r.m.hooks[0x800763d8]=send;r.event((0,0,24,0,0))
    assert blocked==[0xffffffff] and held and r.events()==packets
    passed('negative_control_noncoalescing_full_stock_queue_blocks_sender_while_holding_UI_mutex')

    report=dict(passed_groups=len(cases),cases=cases,limitations=[
        'The between-events scheduler and joined-user evidence are fixture policy, not a compiled gate.',
        'Main and handoff use separate sequential CPU fixtures; no native ownership transfer or RTOS timing claim.',
        'Device/file bytes, seal, audio effects and reload completion body remain modeled.',
        'No full producer graph, bounded queue pressure or physical I/O latency proof.',
        'No device hook, Main wakeup, overflow fix or safe uncertain-fault UI is implemented.'])
    (ROOT/'analysis/native_event_window_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
