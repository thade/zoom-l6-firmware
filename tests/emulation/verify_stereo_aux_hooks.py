#!/usr/bin/env python3
"""Stereo AUX send (AUX 1 left, AUX 2 right): stock coefficient paths, the
real gain-ramp task, and the compiled hooks of the current master build.

Original control setters, coefficient updater, bulk recompute, resets, ramp
task, mixer and retire pass execute; the build's code and the planner's patch
bytes are placed as the image would place them. Only the ramp request's queue
send is short-circuited (the target is written at once). No device access.
"""
import hashlib,json,random,re,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R4, UC_ARM_REG_R5,
                               UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_S0, UC_ARM_REG_PC,
                               UC_ARM_REG_SP, UC_ARM_REG_LR)
from verify_stereo_aux import Rig, B, C, STACK
from verify_pad_protocol import ROOT,IMAGE,BIAS
from build_master_ref import build
from plan_master_ref import plan,STEREO_SPECS

import sys
# 'everyday' runs the same groups on the clean (no query) stereo build.
EVERYDAY=__name__=='__main__' and sys.argv[1:]==['everyday']
ELF=build(trial=not EVERYDAY,stereo=True);PLAN=plan(ELF,trial=not EVERYDAY);PACK=PLAN['pack']
SA={p['adapter']:p for p in PLAN['patches'] if p['adapter'].startswith('sa_')}
NAMES=PACK['names']
MODE=0x80440dc8+0x30d          # stereo when these two bytes are A5 5A
LED=lambda sel: 0x8062939c+2*(sel+0xc)
AUX1, AUX2 = B + 0x5e84, B + 0x5eac
ST = lambda row, j: B + 0x5ed4 + 0x78*row + 12*j
f32 = lambda x: struct.unpack('<f', struct.pack('<f', x))[0]
u2f = lambda u: struct.unpack('<f', struct.pack('<I', u & 0xffffffff))[0]
f2u = lambda x: struct.unpack('<I', struct.pack('<f', x))[0]
LANES_OF = {0: [0], 1: [1], 2: [2, 3], 3: [4, 5], 4: [6, 7], 5: [8, 9]}
STATE = 0x21010000             # master-reference state (only its address matters here)
RECORDING, RECORDER_BUSY = 0x80578ebc, 0x80578ec0


class Probe(Rig):
    def __init__(self, patched, stereo=True):
        super().__init__()
        self.requests = []
        self.patched = patched
        if patched:
            j=PACK['jumps'];self.uc.mem_write(j['candidate_code_start'],PACK['code'])
            self.uc.mem_write(j['globals_start'],bytes(j['globals_end']-j['globals_start']))
            for p in SA.values():
                assert self.raw(p['site'],len(bytes.fromhex(p['original'])))==bytes.fromhex(p['original'])
                self.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
            self.uc.mem_write(MODE,bytes([0xa5,0x5a]) if stereo else bytes(2))
            self.uc.mem_write(NAMES['mr_state'],struct.pack('<I',STATE))   # the worker exists
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


def stub(p,address,result=0,calls=None):
    """Return at once from a stock function (optionally recording its arguments)."""
    def hook(uc,a,size,u):
        if calls is not None:calls.append([uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)])
        uc.reg_write(UC_ARM_REG_R0,result);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    p.uc.hook_add(UC_HOOK_CODE,hook,begin=address,end=address)

def controls(p,rnd,count=40):
    for k in range(count):
        j=rnd.randrange(10);which=rnd.randrange(6)
        if which==0:p.run(0x80002918,[j,rnd.randrange(128),1])
        elif which==1:p.run(0x80002928,[j,rnd.randrange(2),1])
        elif which==2:p.run(0x80002878,[j,1+rnd.randrange(2),rnd.randrange(128),1])
        elif which==3:p.run(0x80002890,[j,1+rnd.randrange(2),rnd.randrange(2),1])
        elif which==4:p.run(0x80002ac0,[rnd.randrange(2),rnd.randrange(128),1])
        else:p.run(0x800028d8,[rnd.randrange(4),rnd.randrange(128),1])

def switch():
    """Mono is stock exactly; holding AUX 1 + AUX 2 for 1.5 s toggles through Main."""
    stock=Probe(False);p=Probe(True,stereo=False)
    for q in (stock,p):
        for j in range(10):q.floats(C+0x70+4*j,[1.0])
        controls(q,random.Random(21))
    assert p.raw(B+0x5e34,160)==stock.raw(B+0x5e34,160)          # all four rows, bit for bit
    saves=[];stub(p,0x80006ab8,calls=saves)
    stub(p,0x80076950,1);stub(p,0x800763d8,1)                     # LED lock take/give
    p.uc.mem_write(0x801f9050,struct.pack('<I',30000))
    p.run(NAMES['sa_toggle'])
    assert p.raw(MODE,2)==bytes([0xa5,0x5a]) and len(saves)==1
    check_rows(p,'switched to stereo')
    assert p.raw(LED(4),2)==bytes([0x10,1]) and p.raw(LED(5),2)==bytes([0x10,1])     # both blink: stereo
    # AUX 2 edits while stereo are kept for mono.
    rnd=random.Random(5)
    for j in range(10):
        v=rnd.randrange(128);p.run(0x80002878,[j,2,v,1]);stock.run(0x80002878,[j,2,v,1])
    check_rows(p,'aux2 edits in stereo')
    p.run(NAMES['sa_toggle'])
    assert p.raw(MODE,2)==bytes(2) and len(saves)==2
    assert p.raw(LED(4),2)==bytes([0x10,0]) and p.raw(LED(5),2)==bytes([0x10,0])     # both steady: mono
    assert p.raw(B+0x5e34,160)==stock.raw(B+0x5e34,160)          # back to stock, AUX 2 edits included
    # Before SHOW_TICKS the redraw does nothing; after it, the view indication
    # comes back as stock draws it, once.
    p.uc.mem_write(0x804430d8,b'\x05')
    p.uc.mem_write(0x801f9050,struct.pack('<I',31999));p.run(NAMES['panel_restore'])
    assert p.raw(LED(4),2)==bytes([0x10,0]) and p.raw(LED(5),2)==bytes([0x10,0])
    p.uc.mem_write(0x801f9050,struct.pack('<I',32000));p.run(NAMES['panel_restore'])
    assert p.raw(LED(4),2)==bytes(2) and p.raw(LED(5),2)==bytes([0x10,0])
    p.uc.mem_write(LED(4),bytes([0x10,1]));p.run(NAMES['panel_restore'])
    assert p.raw(LED(4),2)==bytes([0x10,1])                      # the show already ended: no redraw
    p.uc.mem_write(LED(4),bytes(2))
    # Refused while any recording runs or finalizes: an ordinary take or a
    # pad recording (stock state 1), or a RecPlayCtl callback.
    before=p.raw(B+0x5e34,160)
    for at,value in ((RECORDING,1),(RECORDER_BUSY,1)):
        p.uc.mem_write(at,bytes([value]));p.run(NAMES['sa_toggle']);p.uc.mem_write(at,bytes(1))
    assert p.raw(MODE,2)==bytes(2) and p.raw(B+0x5e34,160)==before and len(saves)==2
    toggles,refused=(struct.unpack('<I',p.raw(NAMES[n],4))[0] for n in ('sa_toggles','sa_refused'))
    assert (toggles,refused)==(2,2)
    p.uc.mem_write(RECORDING,b'\x02');p.run(NAMES['sa_toggle'])   # playback (state 2) is no reason to refuse
    assert p.raw(MODE,2)==bytes([0xa5,0x5a]) and len(saves)==3
    p.uc.mem_write(RECORDING,b'\x00');p.run(NAMES['sa_toggle']);assert p.raw(MODE,2)==bytes(2)
    # The hold detector: both keys for 1.5 s posts once; less, one key, or a
    # longer hold do not post again; a new hold does.
    # The real key read: AUX 1/AUX 2 are bits 4/5 of the second key word.
    p.uc.mem_write(0x808cb600,struct.pack('<I',0x30))
    assert (p.run(0x80008478,[16]),p.run(0x80008478,[17]),p.run(0x80008478,[18]))==(1,1,0)
    p.uc.mem_write(0x808cb600,struct.pack('<I',0x10));assert p.run(0x80008478,[17])==0
    keys={16:0,17:0};posts=[]
    def key(uc,a,size,u):
        uc.reg_write(UC_ARM_REG_R0,keys.get(uc.reg_read(UC_ARM_REG_R0),0));uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    p.uc.hook_add(UC_HOOK_CODE,key,begin=0x80008478,end=0x80008478)
    stub(p,0x80020ca0,calls=posts)
    def poll(t,a1,a2):
        keys[16],keys[17]=a1,a2;p.uc.mem_write(0x801f9050,struct.pack('<I',t));p.run(NAMES['panel_poll'])
    toggles_posted=lambda:[q for q in posts if q[1]==0x4c364158]
    for t in range(0,9990,50):poll(t,1,1)                         # before Main received an event: never
    assert not toggles_posted()
    p.uc.mem_write(NAMES['mr_main_ready'],struct.pack('<I',35001))   # Main first received at 35 s
    for t in range(35000,36001,50):poll(t,1,1)                    # armed only 1 s later
    assert not toggles_posted()
    for t in range(36050,36250,50):poll(t,0,0)
    def hold(start,stop,a1=1,a2=1):
        for t in range(start,stop+1,50):poll(t,a1,a2)
    T=40000
    hold(T,T+2000,1,0);hold(T+2050,T+3500)                        # one key, then 1.45 s of both
    assert not toggles_posted()
    hold(T+3550,T+3600);assert len(toggles_posted())==1           # 1.5 s: toggles once
    hold(T+3650,T+6000);assert len(toggles_posted())==1           # holding on: nothing more
    hold(T+6050,T+6150,0,1);hold(T+6200,T+7800);assert len(toggles_posted())==2   # released, held again
    hold(T+7850,T+7950,0,0)
    hold(T+8050,T+9000);poll(T+9600,1,1)                          # a 600 ms stall: the hold restarts
    hold(T+9650,T+11050);assert len(toggles_posted())==2
    hold(T+11100,T+11150);assert len(toggles_posted())==3
    hold(T+11200,T+11300,0,0);hold(T+11350,T+12000);poll(T+12050,0,1);poll(T+12500,1,1)   # a misread, a 450 ms stall
    hold(T+12550,T+12800);assert len(toggles_posted())==3;hold(T+12850,T+12850);assert len(toggles_posted())==4
    poll(T+12900,1,0);hold(T+12950,T+15000);assert len(toggles_posted())==4                   # a misread re-arms nothing
    # The LED show ends SHOW_TICKS after the toggle: the worker asks Main to
    # redraw and repeats every 250 ms until Main has done it.
    p.uc.mem_write(0x801f9050,struct.pack('<I',T+20000));posts.clear();p.run(NAMES['sa_toggle'])
    hold(T+20050,T+21950,0,0);assert not posts
    hold(T+22000,T+22000,0,0);assert [q[:2] for q in posts]==[[3,0x4c364152]]
    hold(T+22050,T+22200,0,0);assert len(posts)==1
    hold(T+22250,T+22250,0,0);assert len(posts)==2                # not redrawn yet: asked again
    p.run(NAMES['panel_restore']);hold(T+22300,T+23000,0,0);assert len(posts)==2
    # A toggle Main handles after the worker read the time is not yet due.
    p.uc.mem_write(0x801f9050,struct.pack('<I',T+30000));posts.clear();p.run(NAMES['sa_toggle'])
    poll(T+29990,0,0);assert not posts
    assert p.raw(LED(4),2)[0]==0x10                               # still showing
    # Main's receive hook routes the posted event to the toggle, refusing it
    # while a pad recording runs (the master reference ignores those takes)
    # or RecStop finalizes.
    packet=0x21020000
    p.uc.mem_write(STATE,bytes(0x6000))
    stub(p,0x80020690)                                            # stock receive: packet already in place
    # Any event ends a due show on Main, even if the worker never asks.
    p.uc.mem_write(packet,struct.pack('<4I',2,0,0x10,0))
    p.uc.mem_write(0x801f9050,struct.pack('<I',T+32000));p.run(NAMES['mr_main_receive'],[packet])
    assert p.raw(LED(4),2)==bytes(2) and p.raw(LED(5),2)==bytes([0x10,0])
    p.uc.mem_write(packet,struct.pack('<4I',3,0x4c364158,0,0))
    mode=p.raw(MODE,2);refused=struct.unpack('<I',p.raw(NAMES['sa_refused'],4))[0]
    p.uc.mem_write(RECORDING,b'\x01');p.run(NAMES['mr_main_receive'],[packet])
    assert p.raw(MODE,2)==mode and struct.unpack('<I',p.raw(NAMES['sa_refused'],4))[0]==refused+1
    p.uc.mem_write(RECORDING,b'\x00');p.uc.mem_write(RECORDER_BUSY,struct.pack('<I',1))   # RecStop finalizing
    p.run(NAMES['mr_main_receive'],[packet]);assert p.raw(MODE,2)==mode
    p.uc.mem_write(RECORDER_BUSY,struct.pack('<I',0))
    p.uc.mem_write(packet,struct.pack('<4I',3,0x4c364d52,0,0));p.run(NAMES['mr_main_receive'],[packet])
    assert p.raw(MODE,2)==mode                                    # another category-3 event: no toggle
    p.uc.mem_write(packet,struct.pack('<4I',3,0x4c364158,0,0));p.run(NAMES['mr_main_receive'],[packet])
    assert p.raw(MODE,2)!=mode
    if p.raw(MODE,2)==bytes(2):p.run(NAMES['mr_main_receive'],[packet])   # end in stereo for the row check
    assert p.raw(MODE,2)==bytes([0xa5,0x5a]);check_rows(p,'toggled through Main')
    # The stock save request copies the global block, mode bytes included, into
    # the image MacPrmSave writes to flash (P+0xf20 holds CONFIG+0x308...).
    q=Probe(True);stub(q,0x800763d8,1)                            # semaphore give to MacPrmSave
    q.uc.mem_write(0x80440dc8+0x30f,bytes([0xc3,0x3c]))            # the chain switch's bytes ride along
    q.uc.mem_write(0x804439a0+0xf25,bytes(4));q.run(0x80006ab8)
    assert q.raw(0x804439a0+0xf25,4)==bytes([0xa5,0x5a,0xc3,0x3c])
    # Without the worker (startup gave up) a stored stereo mode is stock mono:
    # the switch could not bring it back.
    stock=Probe(False);q=Probe(True);q.uc.mem_write(NAMES['mr_state'],bytes(4))
    for r in (stock,q):
        for j in range(10):r.floats(C+0x70+4*j,[1.0])
        controls(r,random.Random(33))
    assert q.raw(MODE,2)==bytes([0xa5,0x5a]) and q.raw(B+0x5e34,160)==stock.raw(B+0x5e34,160)
    return dict(mono_rows='stock bit for bit',hold_ms=1500,arm_ms=10000,show_ms=2000,
                saved_at='P+0xf25 (flash image)')

# The panel controller as the main firmware sees it: each key press or release
# arrives as a message (0x91 press, 0x90 release, with the key's group and bit
# from the stock key table 0x800a153c) that the stock parser 0x800393d0 turns
# into the key bit the switches read. Measured on the mixer (experiment 37):
# while a key is held, a press of the key at the same bit in another group is
# often never reported; the model always loses it (the worst case).
PANEL=0x808c7528
KEY_GROUP={k:struct.unpack_from('<II',IMAGE,0x800a153c+8*k-BIAS)[::-1] for k in range(32)}   # key -> (group, bit)
SOURCE_PAIRS=[(int(a),int(b),magic) for a,b,magic in re.findall(r'\{(\d+),(\d+),([A-Z_]+_MAGIC)\}',
              (ROOT/'src/capture/master/panel.c').read_text())]
# The AUX 2 + EFX pair is compiled only with TRACK_MASK (experiment 43):
# verify_track_mask.py holds it on that build.
BUILT_PAIRS=[(a,b) for a,b,magic in SOURCE_PAIRS if magic!='TM_TOGGLE_MAGIC']

class Panel:
    def __init__(self,p,lossy=True):
        self.p,self.lossy,self.held,self.lost=p,lossy,set(),set()
    def message(self,kind,key):
        group,bit=KEY_GROUP[key]
        self.p.uc.mem_write(PANEL+0x4025,bytes([kind,group,bit]));self.p.uc.mem_write(PANEL+0x404c,struct.pack('<HH',3,3))
        self.p.run(0x800393d0)
    def press(self,key):
        g,b=KEY_GROUP[key];self.held.add(key)
        if self.lossy and any(KEY_GROUP[h][1]==b and KEY_GROUP[h][0]!=g for h in self.held-{key}):self.lost.add(key)
        else:self.message(0x91,key)
    def release(self,key):
        self.held.discard(key)
        if key in self.lost:self.lost.discard(key)
        else:self.message(0x90,key)

def panel():
    """Switch pairs survive the panel's measured key reporting."""
    for a,b,_ in SOURCE_PAIRS:   # static guard: both keys of a pair in one panel key group
        assert KEY_GROUP[a][0]==KEY_GROUP[b][0] and KEY_GROUP[a][1]!=KEY_GROUP[b][1],(a,b,KEY_GROUP[a],KEY_GROUP[b])
    assert [p[:2] for p in SOURCE_PAIRS]==[(16,17),(18,19),(17,18)] and BUILT_PAIRS==[(16,17),(18,19)]
    assert KEY_GROUP[19][1]==KEY_GROUP[20][1] and KEY_GROUP[19][0]!=KEY_GROUP[20][0]
    def holds(pair,order,stagger,lossy=True):
        """Press the pair (first key, then the second after stagger ms), hold
        2 s, release; polls every 25 ms through the real key read. Toggles posted."""
        p=Probe(True);posts=[];stub(p,0x80020ca0,calls=posts);stub(p,0x8001fb80)   # Main events; long-press timer
        p.uc.mem_write(NAMES['mr_main_ready'],struct.pack('<I',1001))
        panel=Panel(p,lossy);first,second=pair if order==0 else pair[::-1]
        magic=0x4c364158 if pair==(16,17) else 0x4c364348
        def at(ms):p.uc.mem_write(0x801f9050,struct.pack('<I',ms));p.run(NAMES['panel_poll'])
        for ms in range(5000,5200,25):at(ms)
        for n in range(3):                       # three holds in a row
            start=6000+n*4000;panel.press(first)
            for ms in range(start,start+stagger,25):at(ms)
            panel.press(second)
            for ms in range(start+stagger,start+stagger+2000,25):at(ms)
            panel.release(first);panel.release(second)
            for ms in range(start+stagger+2000,start+4000,25):at(ms)
        return [q for q in posts if q[1]==magic]
    results={}
    for pair in BUILT_PAIRS:
        for order in (0,1):
            for stagger in (0,150,400):
                got=len(holds(pair,order,stagger));results[f'{pair}/{order}/{stagger}']=got
                assert got==3,(pair,order,stagger,got)                 # one toggle per hold, every time
    # Negative control: the model reproduces experiment 37 through the stock
    # parser and key read: with LEVEL held, a PAN press never sets PAN.
    reads={}
    for lossy in (True,False):
        p=Probe(True);stub(p,0x80020ca0);stub(p,0x8001fb80);panel=Panel(p,lossy)
        panel.press(20);panel.press(19);reads[lossy]=(p.run(0x80008478,[19]),p.run(0x80008478,[20]))
    assert reads=={True:(0,1),False:(1,1)},reads
    return dict(pairs=[list(x) for x in BUILT_PAIRS],holds=results,pan_with_level_held_reads=reads[True])

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
    passed('mono_is_stock_and_holding_aux1_aux2_toggles_with_save_and_leds_refused_while_any_recording',**switch())
    passed('switch_pairs_stay_in_one_panel_key_group_and_survive_the_panels_measured_key_reporting',**panel())
    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=PLAN['elf_sha256'],limitations=[
            'The ramp request queue send is short-circuited; the ramp task is run separately with real slots',
            'MIDI/Editor parameter routing, MONO x2 and USB input selection are not executed',
            'The per-bus AUX limiters and the physical jacks are not exercised'])
    result['build']='everyday' if EVERYDAY else 'trial'
    (ROOT/('analysis/stereo_aux_hooks_everyday_verification.json' if EVERYDAY else 'analysis/stereo_aux_hooks_verification.json')).write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
