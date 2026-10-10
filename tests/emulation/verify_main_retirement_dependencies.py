#!/usr/bin/env python3
"""Original UI sender / recording STOP dependency, with modeled RTOS blocking.

Constructed full-queue input is an architectural counterexample, not a claim
that ordinary mixer controls can generate this backlog. No device access.
"""
import hashlib
import json
import struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP
from verify_reload_queue_audit import QueueRig, BUFFER, packed
from verify_pad_protocol import ROOT, IMAGE, REGS, RETURN, STACK
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop

UI_MUTEX = 0x70001100
MARKER = 0x2103f000
STUBS = (0x8001e4d8, 0x80007c20, 0x8000b698, 0x8000acf0,
         0x8000b9b8, 0x80008a80, 0x80008880, 0x80008890,
         0x800068c8, 0x8000bab8, 0x8000bbe8, 0x80008a60,
         0x80006968, 0x80006740, 0x8000ac00)


def run(m, address, args):
    # The unchanged stock reducer is quadratic for unique category-1 packets.
    # Use a finite larger instruction cap instead of mocking that reducer.
    for addr in {RETURN, *m.hooks}-m.installed:
        m.uc.hook_add(UC_HOOK_CODE, m._hook, begin=addr, end=addr)
        m.installed.add(addr)
    m.uc.reg_write(UC_ARM_REG_SP, STACK)
    m.uc.reg_write(UC_ARM_REG_LR, RETURN | 1)
    for reg, value in zip(REGS, args):
        m.uc.reg_write(reg, value)
    resume(m, address)


def resume(m, address=None):
    m.reached_return = False
    m.uc.emu_start((address if address is not None else m.uc.reg_read(UC_ARM_REG_PC)) | 1,
                   RETURN+2, count=1000000000)
    assert m.reached_return, hex(m.uc.reg_read(UC_ARM_REG_PC))


def main():
    results = []
    producer = QueueRig()
    events = [(1, 4, 26, i+1, i+2) for i in range(4096)]
    producer.seed(events)
    assert producer.queues[producer.ui]['depth'] == 4096
    put32(producer.m, 0x80446810, UI_MUTEX)
    held = False
    blocked = []

    def take(a):
        nonlocal held
        if a[0] == UI_MUTEX:
            assert not held and a[1] == 0xffffffff
            held = True
        return 1

    def give(a):
        nonlocal held
        if a[0] == UI_MUTEX:
            assert held
            held = False
            return 1
        if a[0] == producer.ui and len(producer.events()) == 4096:
            assert held and a[2:4] == [0xffffffff, 0]
            blocked.append(bytes(producer.m.uc.mem_read(a[1], 20)))
            return stop(producer.m)
        return producer.send(a)

    producer.m.hooks[0x80076950] = take
    producer.m.hooks[0x800763d8] = give
    producer.m.uc.mem_write(BUFFER, packed((1, 4, 27, 0, 0)))
    run(producer.m, 0x8006e4b8, [BUFFER, 0])
    assert held and blocked == [packed((1, 4, 27, 0, 0))]
    assert producer.events() == events
    results.append('Original full-4096 UI compaction preserves distinct ticket packets; subsequent send waits while holding UI mutex')

    worker = QueueRig()
    put32(worker.m, 0x80446810, UI_MUTEX)
    control = worker.word(0x801f8f38)
    pending = [packed((0x8004ba41, 0, 0, 0, 0, 0, 0, 0)),
               packed((MARKER | 1, 0, 0, 0, 0, 0, 0, 0))]
    marks = []
    waits = []
    for address in STUBS:
        worker.m.hooks[address] = lambda a: 0

    def receive(a):
        assert a[0] == control
        if not pending:
            return stop(worker.m)
        worker.m.uc.mem_write(a[1], pending.pop(0))
        return 0

    def wait(a):
        if a[0] == UI_MUTEX:
            waits.append(tuple(a[:2]))
            assert held and a[1] == 0xffffffff
            return stop(worker.m)
        return 1

    worker.m.hooks[0x800483a8] = receive
    worker.m.hooks[0x80076950] = wait
    worker.m.hooks[MARKER] = lambda a: marks.append('marker') or 0
    run(worker.m, 0x80034bc8, [])
    assert waits == [(UI_MUTEX, 0xffffffff)] and len(pending) == 1 and not marks
    results.append('Original RecPlayCtl STOP reaches original 20360 UI cleanup and waits on producer-held mutex before FIFO marker')

    # Model one Main receive, completing the producer's pending kernel send.
    producer.queues[producer.ui]['items'].popleft()
    producer.queues[producer.ui]['items'].append(blocked[0])
    producer.sync(producer.ui)
    producer.m.uc.reg_write(REGS[0], 1)
    resume(producer.m)
    assert not held
    # Resume STOP's already retained frame after its modeled mutex acquisition.
    # No new UI messages are supplied to this CPU; its cleanup gets an empty
    # queue. This is enough to demonstrate the dependency, not complete shared
    # RTOS execution or a production deferral adapter.
    worker.m.uc.reg_write(REGS[0], 1)
    resume(worker.m)
    assert marks == ['marker'] and not pending
    results.append('After a modeled Main receive and producer continuation, original STOP returns and queued marker executes')

    report = dict(passed_groups=len(results), cases=results,
        stock_sha256=hashlib.sha256(IMAGE).hexdigest(),
        conclusion='A separate RecPlayCtl queue does not establish Main-independent drain; do not install unconditional parked-Main retirement',
        limitations=[
            'Constructed category-1 ticket backlog; normal production reachability not established',
            'Original queue depth, sender, compactor, STOP callback, cleanup and worker dispatch execute',
            'STOP deep recorder/filesystem/UI-state callees explicitly stubbed; their other dependencies remain open',
            'Kernel blocking, one Main receive and cross-CPU lock handoff modeled; no simultaneous RTOS',
            'No installed deferral, firmware edit, device interaction or real deadlock reproduced'])
    path = ROOT/'analysis/main_retirement_dependencies_verification.json'
    path.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results), report=str(path))))


if __name__ == '__main__':
    main()
