#!/usr/bin/env python3
"""Storage-only closure retains control objects; all checks are offline.

Queue delivery, task scheduling and positive file/SD joins are fixtures. The
original zero-timeout kernel queue operations are checked separately below.
"""
import hashlib
import json
import struct
from unicorn import UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_storage_lease import LeaseRig, ELF
from verify_session_manager import FENCE, RESET, BLOCKED
from verify_control_transport import TASK, QHANDLE
from verify_capture_integration import CONTROL_TASK
from verify_segmented_exchange import TAILS, TAIL_BYTES
from verify_record_scheduler import word
from verify_reload_queue_audit import QueueRig, BUFFER, packed
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT, IMAGE, RETURN
from verify_scheduling_boundaries import stop

FROZEN = 12
MUTEX = 0x21033300


def ready():
    r = LeaseRig()
    assert r.boot(release=True) == 0
    r.ready()
    return r


def finish_storage(r):
    for _ in range(100):
        if r.join() == 0:
            return
        r.tick()  # No Main, control FIFO delivery, or future audio required.
    raise AssertionError((r.mstate(), r.lstate(), len(r.wire)))


def at_fence():
    r = ready()
    put32(r.m, r.worker+32, 1)  # One manager step per poll exposes the fence boundary.
    r.begin_recording(); r.audio_call(); r.tick(); r.stop_recording()
    r.drive(lambda: r.mstate() == FENCE, with_audio=False, with_queue=False)
    assert not r.wire
    return r


def main():
    cases = []
    def passed(case):
        cases.append(case)

    # Execute real kernel queue copying, rather than assume a failed nonblocking
    # call is an uncertain queued send. Full/empty operations must return zero
    # without mutating a live queue, and successful sends copy all 32 bytes.
    r = QueueRig()
    q = r.word(0x801f8f38)
    r.m.hooks.pop(0x800763d8)
    r.m.hooks.pop(0x80076950)
    payload = packed(tuple(range(8)))
    r.m.uc.mem_write(BUFFER, payload)
    for _ in range(512):
        assert r.m.invoke(0x800763d8, [q, BUFFER, 0, 0]) == 1
    assert r.word(q+0x38) == 512
    before = bytes(r.m.uc.mem_read(q, 80+512*32))
    assert r.m.invoke(0x800763d8, [q, BUFFER, 0, 0]) == 0
    assert bytes(r.m.uc.mem_read(q, len(before))) == before
    r.m.hooks.pop(0x80076710)
    for _ in range(512):
        assert r.m.invoke(0x80076710, [q, BUFFER+64, 0]) == 1
        assert bytes(r.m.uc.mem_read(BUFFER+64, 32)) == payload
    before = bytes(r.m.uc.mem_read(q, 80+512*32))
    assert r.m.invoke(0x80076710, [q, BUFFER+64, 0]) == 0
    assert bytes(r.m.uc.mem_read(q, len(before))) == before
    # Native binary semaphore constructor, then real zero-timeout take/give.
    r.m.hooks.pop(0x80076318)
    sem = r.m.invoke(0x80076318, [1, 1])
    assert sem and r.m.invoke(0x80076950, [sem, 0]) == 1
    before = bytes(r.m.uc.mem_read(sem, 80))
    assert r.m.invoke(0x80076950, [sem, 0]) == 0
    assert bytes(r.m.uc.mem_read(sem, 80)) == before
    assert r.m.invoke(0x800763d8, [sem, 0, 0, 0]) == 1
    passed('Original kernel full send and unavailable token return zero without mutation; successful sends copy exactly 32 bytes')

    for queued in ('start', 'stop'):
        r = ready()
        if queued == 'stop':
            r.begin_recording()
            for _ in range(5):
                r.audio_call(); r.tick()
            r.request(1)
        else:
            r.request()
        pending = list(r.wire)
        assert len(pending) == 1
        arena = r.arena
        assert r.close_gate() == 0
        finish_storage(r)
        assert r.mstate() == FROZEN and r.wire == pending and not r.opened
        assert r.result() == 12 and r.admit(2) == r.resume() == 12
        assert word(r.m, r.syms['ct_active']) == r.d[0]
        assert word(r.m, r.syms['bridge_gateway_readers']) == 0x80000000
        # Old envelopes still run ordinary callbacks; no capture memory is
        # reset/reclaimed and later ordinary control remains usable.
        before = len(r.calls)
        r.dispatch_all()
        for _ in range(4):
            r.audio_call(); r.tick()
        r.request(1); r.dispatch_all()
        assert r.arena == arena and r.mstate() == FROZEN and not r.opened
        assert len(r.calls) == before and not r.wire
        passed('Storage joins without queued '+queued+' callback, which remains executable afterward')

    # An entered callback is paused before a deep UI operation. Its original
    # stack and Transport ownership survive cancellation on another task stack.
    r = ready(); r.begin_recording(); r.audio_call(); r.tick(); r.request(1)
    r.m.hooks[0x80020360] = lambda a: stop(r.m)
    r.dispatch_all()
    saved = r.m.uc.context_save()
    sp = r.m.uc.reg_read(A.UC_ARM_REG_SP)
    frame = r.raw(sp, r.m.stack-sp)
    assert not r.wire
    assert r.other(r.close_gate) == 0
    r.other(lambda: finish_storage(r))
    assert r.mstate() == FROZEN and not r.opened and r.raw(sp, len(frame)) == frame
    r.m.uc.context_restore(saved); put32(r.m, TASK, CONTROL_TASK)
    r.m.reached_return = False
    r.m.uc.emu_start(r.m.uc.reg_read(A.UC_ARM_REG_PC)|1, RETURN+2, count=100000000)
    assert r.m.reached_return and r.mstate() == FROZEN
    passed('Entered ordinary STOP can stay blocked on UI while file closure joins; its retained frame later returns')

    # An in-flight audio gateway reservation must complete, even though a
    # long-lived control reservation need not complete for storage-only closure.
    r = ready()
    gateway = r.syms['bridge_gateway_readers']
    put32(r.m, gateway, 1)  # MODEL an old audio hook already admitted.
    assert r.close_gate() == 0
    for _ in range(4):
        r.tick(); assert r.join() == 11
    assert r.mstate() == FENCE and word(r.m, gateway) == 0x80000001
    assert not r.opened
    put32(r.m, gateway, 0x80000000)  # MODEL that hook's final leave.
    finish_storage(r)
    writes = []
    hooks = []
    for base in TAILS:
        hooks.append(r.m.uc.hook_add(UC_HOOK_MEM_WRITE,
            lambda uc, access, address, size, value, user: writes.append((address, size)),
            begin=base, end=base+TAIL_BYTES-1))
    for _ in range(4):
        r.audio_call(); r.tick()
    for hook in hooks:
        r.m.uc.hook_del(hook)
    assert not writes and r.mstate() == FROZEN
    passed('Storage join waits for admitted audio access and future real tap paths cannot write retained history')

    # A previously started normal retirement attempt cannot hold the manager pin
    # forever inside a marker mutex/send. Both waits use timeout zero and retry
    # only a known non-enqueue; later storage revocation can then take over.
    for busy in ('mutex', 'queue'):
        r = at_fence()
        observed = []
        def take(a):
            if a[0] == MUTEX:
                assert a[1] == 0
                observed.append('take')
                return 0 if busy == 'mutex' else 1
            return 1
        def send(a):
            if a[0] == QHANDLE:
                assert a[2:4] == [0, 0]
                observed.append('send')
                return 0
            if a[0] == MUTEX:
                observed.append('give')
            return 1
        r.m.hooks[0x80076950] = take; r.m.hooks[0x800763d8] = send
        for _ in range(3):
            assert r.tick() == 11 and r.lstate() == 1 and r.mstate() == FENCE
        assert observed == (['take'] if busy == 'mutex' else ['take', 'send', 'give'])*3, (busy, observed, r.wire)
        assert r.close_gate() == 0
        finish_storage(r)
        assert r.mstate() == FROZEN and not r.wire and r.result() == 12
        passed('Busy marker '+busy+' never retains the manager pin and storage cancellation needs no marker')

    r = at_fence()
    r.send_result = 1
    assert r.tick() == 11 and not r.wire
    r.send_result = 0
    count = word(r.m, 0x806b2f20)
    assert r.tick() == 10 and len(r.wire) == 1
    assert word(r.m, 0x806b2f20) == (count+1) & 0xffffffff
    assert r.tick() == 11 and len(r.wire) == 1
    r.dispatch_all(); r.tick()
    assert r.mstate() == RESET and r.result() != 12
    passed('Known non-enqueue retries once space is available, preserves diagnostic count and never duplicates a queued marker')

    for failure in ('acquire', 'send', 'release'):
        r = at_fence()
        def take_bad(a):
            if a[0] != MUTEX:return 1
            assert a[:2] == [MUTEX, 0]
            return 2 if failure == 'acquire' else 1
        def send_bad(a):
            if a[0] == MUTEX:
                return 0 if failure == 'release' else 1
            if failure == 'send':
                return 2
            return r.kernel_send(a)
        r.m.hooks[0x80076950] = take_bad; r.m.hooks[0x800763d8] = send_bad
        assert r.tick() == 30 and r.mstate() == BLOCKED
        if r.wire:r.dispatch_all()
        assert r.tick() == 30 and r.result() == 12
    passed('Unexpected kernel results or failed release remain sticky and cannot publish a take after late marker delivery')

    for send_ok in (True, False):
        r = at_fence()
        def early(a):
            if a[0] != QHANDLE:return 1
            assert a[2:4] == [0, 0]
            peer = ready()
            assert peer.d[0] == r.d[0]
            size = word(r.m, r.syms['ct_layout'])
            peer.m.uc.mem_write(peer.d[0], r.raw(r.d[0], size))
            peer.wire = [r.raw(a[1], 32)]
            peer.dispatch_all()
            r.m.uc.mem_write(r.d[0], peer.raw(peer.d[0], size))
            return int(send_ok)
        r.m.hooks[0x800763d8] = early
        result = r.tick()
        assert r.mstate() == (RESET if send_ok else BLOCKED), result
        assert (r.result() != 12) == send_ok
    passed('Early marker delivery waits for confirmed send/release; a contradictory non-enqueue result is a fault')

    # Uncertain ordinary send remains owned forever, yet after a positive file
    # close it need not prevent storage mutation: no object is freed or reused.
    r = ready(); r.send_result = 1; r.request()
    assert r.close_gate() == 0
    finish_storage(r)
    assert r.mstate() == FROZEN and not r.opened and not r.wire
    assert word(r.m, r.syms['ct_active']) == r.d[0]
    passed('Uncertain old control send retains its permanent objects without blocking positively closed storage')

    report = dict(passed_groups=len(cases), cases=cases,
        stock_sha256=hashlib.sha256(IMAGE).hexdigest(),
        fixture_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        limitations=['Storage-only terminal state is not control retirement or memory reclamation',
            'Deep file completion, task scheduling and old audio reservation are modeled',
            'Physical SD completion, RAM ownership and whole native transition binding still required',
            'No firmware image, device operation, pad publication or capture enablement'])
    out = ROOT/'analysis/storage_stop_verification.json'
    out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases), report=str(out))))


if __name__ == '__main__':
    main()
