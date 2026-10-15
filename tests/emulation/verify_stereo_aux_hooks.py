#!/usr/bin/env python3
"""Stereo AUX send (AUX 1 left, AUX 2 right): stock coefficient paths, the
real gain-ramp task, and the compiled hooks of the current master build.

Original control setters, coefficient updater, bulk recompute, resets, ramp
task, mixer and retire pass execute; the build's code and the planner's patch
bytes are placed as the image would place them. Only the ramp request's queue
send is short-circuited (the target is written at once). No device access.
"""
import hashlib,json,random,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R4, UC_ARM_REG_R5,
                               UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_S0, UC_ARM_REG_PC,
                               UC_ARM_REG_SP)
from verify_stereo_aux import Rig, B, C, STACK
from verify_pad_protocol import ROOT,IMAGE
from build_master_ref import build
from plan_master_ref import plan,STEREO_SPECS

import sys
# 'everyday' runs the same groups on the clean (no query) stereo build.
EVERYDAY=__name__=='__main__' and sys.argv[1:]==['everyday']
ELF=build(trial=not EVERYDAY,stereo=True);PLAN=plan(ELF,trial=not EVERYDAY);PACK=PLAN['pack']
SA={p['adapter']:p for p in PLAN['patches'] if p['adapter'].startswith('sa_')}
AUX1, AUX2 = B + 0x5e84, B + 0x5eac
ST = lambda row, j: B + 0x5ed4 + 0x78*row + 12*j
f32 = lambda x: struct.unpack('<f', struct.pack('<f', x))[0]
u2f = lambda u: struct.unpack('<f', struct.pack('<I', u & 0xffffffff))[0]
f2u = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]
LANES_OF = {0: [0], 1: [1], 2: [2, 3], 3: [4, 5], 4: [6, 7], 5: [8, 9]}


class Probe(Rig):
    def __init__(self, patched):
        super().__init__()
        self.requests = []
        self.patched = patched
        if patched:
            j=PACK['jumps'];self.uc.mem_write(j['candidate_code_start'],PACK['code'])
            self.uc.mem_write(j['globals_start'],bytes(j['globals_end']-j['globals_start']))
            for p in SA.values():
                assert self.raw(p['site'],len(bytes.fromhex(p['original'])))==bytes.fromhex(p['original'])
                self.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
        core = 0x8001039c      # after the displaced prologue: the queue send, short-circuited
        self.uc.hook_add(UC_HOOK_CODE, self.core, begin=core, end=core)

    def core(self, uc, address, size, user):
        dst, ms, state = (uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        g = u2f(uc.reg_read(UC_ARM_REG_S0))
        self.requests.append((dst, ms, state, g))
        uc.mem_write(dst, struct.pack('<f', g))
        uc.reg_write(UC_ARM_REG_PC, 0x800103d4 | 1)   # add sp,#16; pop {r4,pc}

    def f(self, a):
        return self.values(a, 1)[0]



def expected_g(p, j):
    send = p.f(C + 0x110 + 8*j)
    post = p.raw(C + 0x114 + 8*j, 1)[0]
    if post:
        return f32(f32(p.f(C + 0x70 + 4*j) * send) * p.f(C + 0x98 + 4*j))
    return send


def check_rows(p, label):
    for j in range(10):
        g = expected_g(p, j)
        l, r = p.values(C + 0xc0 + 8*j, 2)
        a1, a2 = p.f(AUX1 + 4*j), p.f(AUX2 + 4*j)
        assert a1 == f32(g*l) and a2 == f32(g*r), (label, j, g, l, r, a1, a2)
        m = p.f(C + 0x70 + 4*j)
        lvl = p.f(C + 0x98 + 4*j)
        assert p.f(B + 0x5e34 + 4*j) == f32(f32(m*l)*lvl), (label, 'masterL', j)
        assert p.f(B + 0x5e5c + 4*j) == f32(lvl*f32(m*r)), (label, 'masterR', j)


def stock_facts():
    out = {}
    # 1. Updater: where G is, what is requested, for both buses and pre/post.
    p = Probe(False)
    seen = []

    def at_issue(uc, address, size, user):
        seen.append(dict(row=uc.reg_read(UC_ARM_REG_R0), lane=uc.reg_read(UC_ARM_REG_R4),
                         ramp=uc.reg_read(UC_ARM_REG_R2), g=u2f(uc.reg_read(UC_ARM_REG_S0))))
    p.uc.hook_add(UC_HOOK_CODE, at_issue, begin=0x80048d44, end=0x80048d44)
    for j in range(10):
        p.floats(C + 0x70 + 4*j, [1.0])
        p.floats(C + 0x98 + 4*j, [0.5])
    for aux in (1, 2):
        for post in (0, 1):
            for j in (0, 3, 9):
                seen.clear(); p.requests.clear()
                p.run(0x80002890, [j, aux, post, 1])
                p.run(0x80002878, [j, aux, 100, 1])
                send = p.f(C + 0x110 + 0x50*(aux-1) + 8*j)
                g = send * (0.5 if post else 1)
                assert seen[-1] == dict(row=aux+1, lane=j, ramp=1, g=f32(g)), seen[-1]
                assert p.requests[-1] == (B + 0x5e34 + 40*(aux+1) + 4*j, 16, ST(aux+1, j), f32(g))
    out['updater_issue_point'] = 'at 0x80048d44: r0=bus row (2=AUX1,3=AUX2), r4=lane, r2=ramp, s0=G'
    # Level and mute setters call updater for buses 0,1,2 (ramped).
    p.requests.clear()
    p.run(0x80002918, [4, 90, 1])
    rows = [((d - (B + 0x5e34)) // 40, (d - (B + 0x5e34)) % 40 // 4) for d, *_ in p.requests if B+0x5e34 <= d < B+0x5ed4]
    assert rows == [(0, 4), (1, 4), (2, 4), (3, 4)], rows
    p.requests.clear()
    p.run(0x80002928, [4, 1, 1])
    assert p.f(C + 0x70 + 16) == 0.0
    rows = [((d - (B + 0x5e34)) // 40) for d, *_ in p.requests if B+0x5e34 <= d < B+0x5ed4]
    assert rows == [0, 1, 2, 3], rows
    out['level_mute_requests'] = 'masterL, masterR, AUX1, AUX2 per lane (16 ms ramps)'
    # Pan/balance: master only.
    p.requests.clear()
    p.run(0x80002ac0, [1, 10, 1])
    assert [d for d, *_ in p.requests] == [B+0x5e34+4, B+0x5e5c+4]
    p.requests.clear()
    p.run(0x800028d8, [1, 20, 1])
    assert [d for d, *_ in p.requests] == [B+0x5e34+16, B+0x5e5c+16, B+0x5e34+20, B+0x5e5c+20]
    out['pan_balance_requests'] = 'master rows only'
    # Bulk recompute (scene recall/startup restore): AUX1 and AUX2 requests per lane.
    p.requests.clear()
    p.run(0x8000c648, [1])
    aux_req = [(d, s) for d, _, s, _ in p.requests if AUX1 <= d < AUX2 + 40]
    assert aux_req == [x for j in range(10) for x in ((AUX1+4*j, ST(2, j)), (AUX2+4*j, ST(3, j)))]
    out['bulk_recompute_requests'] = len(p.requests)
    return out


def ramp_machinery():
    """Run the real ramp-task body for an AUX1/AUX2 pair, then the mixer and retire pass."""
    r = Probe(False)
    SLOT, SLOTSZ = 0x80540a0c, 0xc08
    dummy = 0x8021383c
    for k in range(64):
        r.uc.mem_write(SLOT + k*SLOTSZ, struct.pack('<II', 0, dummy))
    r.uc.mem_write(B, struct.pack('<I', 48000))     # rate word read at 0x800102b4
    j = 2
    r.floats(AUX1 + 4*j, [0.25])
    r.floats(AUX2 + 4*(j+1), [0.5])
    msgs = [(AUX1 + 4*j, 1.0, ST(2, j)), (AUX2 + 4*(j+1), 0.0, ST(3, j+1))]
    pending = list(msgs)

    def recv(uc, address, size, user):
        if not pending:
            uc.emu_stop(); return
        d, g, s = pending.pop(0)
        sp = uc.reg_read(UC_ARM_REG_SP)
        uc.mem_write(sp, struct.pack('<IfII', d, g, 16, s))
        uc.reg_write(UC_ARM_REG_R0, 0)
        uc.reg_write(UC_ARM_REG_PC, 0x80010270 | 1)

    def skip(uc, address, size, user):
        uc.reg_write(UC_ARM_REG_PC, (address + 4) | 1)
    r.uc.hook_add(UC_HOOK_CODE, recv, begin=0x8001026c, end=0x8001026c)
    for a in (0x8001027c, 0x80010296):
        r.uc.hook_add(UC_HOOK_CODE, skip, begin=a, end=a)
    sp = STACK - 0x40
    r.uc.reg_write(UC_ARM_REG_SP, sp)
    for reg, v in ((UC_ARM_REG_R6, SLOT), (UC_ARM_REG_R4, 0x801f8f20), (UC_ARM_REG_R7, 0xc08),
                   (UC_ARM_REG_R5, sp), (UC_ARM_REG_R8, 1)):
        r.uc.reg_write(reg, v)
    r.uc.emu_start(0x8001024e | 1, 0x80010248, count=200000)
    assert not pending
    s1, s2 = (struct.unpack('<III', r.raw(ST(row, ln), 12)) for row, ln in ((2, j), (3, j+1)))
    assert s1[0] == 1 and s2[0] == 1
    assert r.f(AUX1 + 4*j) == 1.0 and r.f(AUX2 + 4*(j+1)) == 0.0   # target written at once
    nsamp = (s1[2] + 4 - s1[1]) // 4
    assert nsamp == 768 == (s2[2] + 4 - s2[1]) // 4
    # Mixer: lane 2 and 3 carry constant 1.0; observe per-sample AUX gains.
    r.input(j, [1.0]*64); r.input(j+1, [1.0]*64)
    a1, a2 = [], []
    for blk in range(14):
        r.mix()
        a1 += r.values(B + 0x35b8, 64); a2 += r.values(B + 0x36b8, 64)
        r.run(0x80010150)                # retire pass from audio task (0x8001078e)
    exp1 = [f32(0.25)] ; d1 = f32(f32(1.0 - 0.25) / 768.0)
    v = 0.25; e1 = []
    for k in range(768):
        v = f32(v + d1); e1.append(v)
    v = 0.5; d2 = f32(f32(0.0 - 0.5) / 768.0); e2 = []
    for k in range(768):
        v = f32(v + d2); e2.append(v)
    assert tuple(a1[:768]) == tuple(e1), (a1[:3], e1[:3])
    assert tuple(a2[:768]) == tuple(e2)
    assert set(a1[768:]) == {1.0} and set(a2[768:]) == {0.0}
    s1 = struct.unpack('<I', r.raw(ST(2, j), 4))[0]
    s2 = struct.unpack('<I', r.raw(ST(3, j+1), 4))[0]
    assert s1 == 0 and s2 == 0
    return dict(samples=768, last_ramp_values=(a1[767], a2[767]), slot_buffer='0x80540a0c+k*0xc08')


def prototype():
    rnd = random.Random(6)
    p = Probe(True)
    for j in range(10):
        p.floats(C + 0x70 + 4*j, [1.0])
    # Native controls through the real dispatch-level setters.
    for ch, lanes in LANES_OF.items():
        for j in lanes:
            p.run(0x80002918, [j, rnd.randrange(60, 120), 1])     # level (apply)
            p.run(0x80002890, [j, 1, rnd.randrange(2), 1])        # AUX1 pre/post
            p.run(0x80002878, [j, 1, rnd.randrange(128), 1])      # AUX1 send
            p.run(0x80002890, [j, 2, rnd.randrange(2), 1])        # AUX2 pre/post (ignored)
            p.run(0x80002878, [j, 2, rnd.randrange(128), 1])      # AUX2 send (ignored)
        if ch < 2:
            p.run(0x80002ac0, [ch, rnd.randrange(128), 1])
        else:
            p.run(0x800028d8, [ch-2, rnd.randrange(128), 1])
        check_rows(p, f'controls ch{ch}')
    # AUX2 knob changes leave both rows unchanged.
    before = p.raw(AUX1, 80)
    for j in range(10):
        p.run(0x80002878, [j, 2, rnd.randrange(128), 1])
        p.run(0x80002890, [j, 2, rnd.randrange(2), 1])
    assert p.raw(AUX1, 80) == before
    # Pan sweeps, mute, level on post and pre lanes.
    for pan in (0, 32, 64, 96, 127):
        p.run(0x80002ac0, [0, pan, 1]); p.run(0x800028d8, [2, pan, 1]); check_rows(p, f'pan {pan}')
    for j in (0, 5, 8):
        p.run(0x80002928, [j, 1, 1]); check_rows(p, f'mute {j}')
        p.run(0x80002918, [j, 30, 1]); check_rows(p, f'level {j}')
        p.run(0x80002928, [j, 0, 1]); check_rows(p, f'unmute {j}')
    # Stock bulk recompute after store-only changes (scene recall / startup restore path).
    for j in range(10):
        p.run(0x800028c0, [j, 1, rnd.randrange(128), 1])          # store-only AUX1 send
        p.run(0x800028c0, [j, 2, rnd.randrange(128), 1])          # store-only AUX2 send
        p.run(0x800028a8, [j, 1, rnd.randrange(2), 1])            # store-only AUX1 pre/post
        p.run(0x80002920, [j, rnd.randrange(128), 1])             # store-only level
    p.run(0x80002ac8, [1, 5, 1]); p.run(0x800028f0, [3, 120, 1])  # store-only pan/balance
    p.requests.clear()
    p.run(0x8000c648, [1])
    check_rows(p, 'bulk recompute')
    n_aux = sum(1 for d, *_ in p.requests if AUX1 <= d < AUX2 + 40)
    assert n_aux == 20
    # Ramped unity reset 0x8000d810(1).
    p.run(0x8000d810, [1]); check_rows(p, 'reset')
    # Startup: unity stored directly (pan 1/1, self-consistent), then the restore's bulk recompute.
    p.run(0x8000d810, [0]); check_rows(p, 'startup unity')
    p.run(0x800028c0, [3, 1, 90, 1]); p.run(0x8000c648, [1]); check_rows(p, 'startup restore')
    # Editor mixer resets 1 and 2 store rows directly; the replaced veneers recompute after them.
    for veneer in (0x80002b78, 0x80002b90):
        for j in range(10): p.run(0x80002878, [j, 1, rnd.randrange(128), 1])
        p.run(veneer, []); check_rows(p, f'editor reset {veneer:#x}')
        assert struct.unpack('<I', p.raw(C + 0x1fc, 4))[0] == 1
    # Request accounting for one stereo-lane level change.
    p.requests.clear(); p.run(0x80002918, [6, 100, 1])
    seq = [((d - (B+0x5e34))//40, (d - (B+0x5e34)) % 40//4) for d, *_ in p.requests if B+0x5e34 <= d < B+0x5ed4]
    assert seq == [(0, 6), (1, 6), (2, 6), (3, 6)], seq
    return dict(aux_requests_per_bulk=n_aux, level_change_requests=seq)


def master_unchanged():
    """The same control sequence leaves the master rows identical to stock."""
    rows=[]
    for patched in (False,True):
        p=Probe(patched);rnd=random.Random(11)
        for j in range(10):p.floats(C+0x70+4*j,[1.0])
        for k in range(60):
            j=rnd.randrange(10);which=rnd.randrange(5)
            if which==0:p.run(0x80002918,[j,rnd.randrange(128),1])
            elif which==1:p.run(0x80002928,[j,rnd.randrange(2),1])
            elif which==2:p.run(0x80002878,[j,1+rnd.randrange(2),rnd.randrange(128),1])
            elif which==3:p.run(0x80002ac0,[rnd.randrange(2),rnd.randrange(128),1])
            else:p.run(0x800028d8,[rnd.randrange(4),rnd.randrange(128),1])
        rows.append(p.raw(B+0x5e34,80))
    assert rows[0]==rows[1]
    return dict(master_rows_bytes=80)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    assert sorted(SA)==sorted(s['adapter'] for s in STEREO_SPECS) and len(SA)==5
    passed('stock_paths_issue_aux_requests_through_the_ramp_request',**stock_facts())
    passed('the_real_ramp_task_moves_an_aux_pair_with_matching_768_sample_ramps',**ramp_machinery())
    passed('hooks_set_aux1_to_G_times_left_and_aux2_to_G_times_right_on_every_path',**prototype())
    passed('master_rows_are_unchanged_by_the_hooks',**master_unchanged())
    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=PLAN['elf_sha256'],limitations=[
            'The ramp request queue send is short-circuited; the ramp task is run separately with real slots',
            'MIDI/Editor parameter routing, MONO x2 and USB input selection are not executed',
            'The per-bus AUX limiters and the physical jacks are not exercised'])
    result['build']='everyday' if EVERYDAY else 'trial'
    (ROOT/('analysis/stereo_aux_hooks_everyday_verification.json' if EVERYDAY else 'analysis/stereo_aux_hooks_verification.json')).write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
