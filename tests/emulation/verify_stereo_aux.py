#!/usr/bin/env python3
"""Bounded L6 v1.10 stereo AUX feasibility checks, entirely offline.

Original mixer, control setters, integer output conversion and output copy run
on synthetic state. Proposed stereo coefficients are host memory writes, not a
compiled/installed feature. ADC, EQ configuration, dynamics, DMA and DAC are not
modeled. No generated firmware image, device access or dependency on a custom ELF.
"""
import hashlib
import json
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_CPU_ARM_CORTEX_M7, UC_ARM_REG_FPEXC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R6, UC_ARM_REG_R8,
    UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_LR,
    UC_ARM_REG_S0, UC_ARM_REG_S20, UC_ARM_REG_PC,
)
from verify_pad_protocol import ROOT, IMAGE, BIAS

B = 0x20010a48
C = 0x20016f68
INPUT = B + 0x10
MATRIX = B + 0x5e34
BUS = B + 0x33b8
OUT = 0x20010648
RETURN = 0x20000000
STACK = 0x2003f000
REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


def packed(values):
    return struct.pack('<%df' % len(values), *values)


class Rig:
    def __init__(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M7)
        for address, size in ((0x80000000, 0x1000000), (0x20000000, 0x40000),
                              (0x20220000, 0x10000), (0x21000000, 0x40000)):
            self.uc.mem_map(address, size)
        self.uc.mem_write(0x80001000, IMAGE[0x200:0xb5ce4])
        self.uc.mem_write(0x20220000, IMAGE[0x800a9408-BIAS:0x800a9408-BIAS+0xd6dc])
        self.uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
        self.end = RETURN
        self.stopped = False
        self.uc.hook_add(UC_HOOK_CODE, self.hook)

    def hook(self, uc, address, size, user):
        if address == self.end:
            self.stopped = True
            uc.emu_stop()

    def run(self, address, args=(), end=RETURN):
        self.end = end
        self.stopped = False
        self.uc.reg_write(UC_ARM_REG_SP, STACK)
        self.uc.reg_write(UC_ARM_REG_LR, RETURN | 1)
        for reg, value in zip(REGS, args):
            self.uc.reg_write(reg, value)
        self.uc.emu_start(address | 1, RETURN + 2, count=1000000)
        assert self.stopped, hex(address)
        return self.uc.reg_read(UC_ARM_REG_R0)

    def floats(self, address, values):
        self.uc.mem_write(address, packed(values))

    def raw(self, address, size):
        return bytes(self.uc.mem_read(address, size))

    def values(self, address, count):
        return struct.unpack('<%df' % count, self.raw(address, count*4))

    def input(self, lane, values):
        self.floats(INPUT + lane*256, values)

    def row(self, row, values):
        assert len(values) == 10
        self.floats(MATRIX + row*40, values)

    def mix(self):
        # Original whole mixer function; zero synthetic EQ/ramp enable flags.
        self.run(0x20224b90)

    def bus(self, row):
        return self.raw(BUS + row*256, 256)


def main():
    results = []

    def passed(case, **details):
        results.append(dict(case=case, passed=True, **details))

    # Original channel expansion and high-level AUX setter. Intercept only the
    # asynchronous ramp builder, recording its targets/values without running it.
    for channel, lane in enumerate((0, 1, 2, 4, 6, 8)):
        for aux in (0, 1):
            r = Rig()
            assert r.run(0x80040ae8, [channel]) == lane
            calls = []

            def ramp(uc, address, size, user):
                calls.append((uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_S0)))
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

            r.uc.hook_add(UC_HOOK_CODE, ramp, begin=0x80010398, end=0x80010398)
            r.run(0x8003d998, [channel, aux, 100])
            lanes = [lane] if channel < 2 else [lane, lane+1]
            assert [a for a, v in calls] == [MATRIX+(aux+2)*40+i*4 for i in lanes]
            assert len({v for a, v in calls}) == 1
    passed('native_channel_mapping_and_aux_control_apply_equal_gain_to_stereo_input_sides',
           limitation='Ramp builder intercepted; its scheduling/execution not tested')

    # Each physical input lane can reach every output sum independently.
    for row in range(4):
        for lane in range(10):
            r = Rig()
            x = [(lane+1)*(i-32)/1024 for i in range(64)]
            r.input(lane, x)
            weights = [0]*10
            weights[lane] = 1
            r.row(row, weights)
            before = r.raw(INPUT, 2560)
            r.mix()
            for destination in range(4):
                assert r.bus(destination) == (packed(x) if row == destination else bytes(256))
            assert r.raw(INPUT, 2560) == before
    passed('all_40_independent_input_to_bus_routes_execute_original_mixer')

    # Native controls select the last two rows; pre/post changes level scaling.
    for aux in (1, 2):
        for lane in range(10):
            for post in (0, 1):
                r = Rig()
                r.floats(C+0x70+lane*4, [1])  # unmuted
                r.floats(C+0x98+lane*4, [.25])  # channel level
                r.run(0x80002890, [lane, aux, post, 0])
                r.run(0x80002878, [lane, aux, 100, 0])
                level = struct.unpack('<f', IMAGE[0x8008c664-BIAS+27*4:0x8008c664-BIAS+28*4])[0]
                expected = level*(.25 if post else 1)
                assert r.values(MATRIX+(aux+1)*40+lane*4, 1)[0] == expected
                other = 2 if aux == 1 else 1
                assert r.raw(MATRIX+(other+1)*40, 40) == bytes(40)
    passed('original_aux_setters_identify_rows_and_preserve_independent_pre_post_level')

    left = [(i-32)/128 for i in range(64)]
    right = [(63-i)/256 for i in range(64)]
    for lane in (2, 4, 6, 8):
        r = Rig()
        r.input(lane, left)
        r.input(lane+1, right)
        for row in (2, 3):
            weights = [0]*10
            weights[lane:lane+2] = [.5, .5]
            r.row(row, weights)
        r.mix()
        expected = packed([(a+b)*.5 for a, b in zip(left, right)])
        assert r.bus(2) == expected == r.bus(3)
        # Host models proposed new coefficient policy, not new DSP code.
        lweights, rweights = [0]*10, [0]*10
        lweights[lane], rweights[lane+1] = .5, .5
        r.row(2, lweights)
        r.row(3, rweights)
        r.mix()
        assert r.bus(2) == packed([v*.5 for v in left])
        assert r.bus(3) == packed([v*.5 for v in right])
    passed('all_four_stereo_pairs_preserve_left_right_with_modeled_coefficients')

    r = Rig()
    r.input(2, left)
    r.input(3, [-v for v in left])
    r.row(2, [0, 0, 1, 1, 0, 0, 0, 0, 0, 0])
    r.row(3, [0, 0, 1, 1, 0, 0, 0, 0, 0, 0])
    r.mix()
    assert r.bus(2) == r.bus(3) == bytes(256)
    r.row(2, [0, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    r.row(3, [0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
    r.mix()
    assert r.bus(2) == packed(left)
    # Addition to +0 can canonicalize a negative zero; compare numerical values.
    assert r.values(BUS+3*256, 64) == tuple(-v for v in left)
    passed('opposite_polarity_stereo_survives_proposal_but_cancels_in_equal_mono_sends')

    pan_results = []
    for lane in (0, 1):
        for pan in (0, 64, 127):
            r = Rig()
            r.floats(C+0x70+lane*4, [1])
            r.floats(C+0x98+lane*4, [.5])
            r.run(0x8000d630, [lane, pan, 0, 1])
            pan_l, pan_r = r.values(C+0xc0+lane*8, 2)
            main_l = r.values(MATRIX+lane*4, 1)[0]
            main_r = r.values(MATRIX+40+lane*4, 1)[0]
            assert (main_l, main_r) == (pan_l*.5, pan_r*.5)
            r.input(lane, [1]*64)
            lweights, rweights = [0]*10, [0]*10
            lweights[lane], rweights[lane] = pan_l*.25, pan_r*.25
            r.row(2, lweights)
            r.row(3, rweights)
            r.mix()
            assert r.bus(2) == packed([pan_l*.25]*64)
            assert r.bus(3) == packed([pan_r*.25]*64)
            pan_results.append(dict(lane=lane, pan=pan, left=pan_l, right=pan_r))
    passed('original_mono_pan_factors_can_drive_independent_send_level', cases=pan_results)

    for lane in (2, 4, 6, 8):
        for pan in (0, 64, 127):
            r = Rig()
            for side in (lane, lane+1):
                r.floats(C+0x70+side*4, [1])
                r.floats(C+0x98+side*4, [.5])
            r.run(0x8000cb70, [lane, pan, 0, 1])
            ll, lr, rl, rr = r.values(C+0xc0+lane*8, 4)
            assert lr == rl == 0
            assert (ll, rr) == {0: (1, 0), 64: (1, 1), 127: (0, 1)}[pan]
            r.input(lane, left)
            r.input(lane+1, right)
            lweights, rweights = [0]*10, [0]*10
            lweights[lane], rweights[lane+1] = ll*.25, rr*.25
            r.row(2, lweights)
            r.row(3, rweights)
            r.mix()
            assert r.values(BUS+512, 64) == tuple(v*ll*.25 for v in left)
            assert r.values(BUS+768, 64) == tuple(v*rr*.25 for v in right)
    passed('native_stereo_balance_factors_support_follow_pan_without_mono_summing')

    r = Rig()
    for lane in range(10):
        r.input(lane, [(lane+1)*(i+1)/4096 for i in range(64)])
    r.row(0, [.5]*10)
    r.row(1, [.25]*10)
    r.row(2, [.125]*10)
    r.row(3, [.125]*10)
    before = r.raw(INPUT, 2560)
    r.mix()
    master = r.raw(BUS, 512)
    r.row(2, [.25, .125, .5, 0, .25, 0, .125, 0, 1, 0])
    r.row(3, [.125, .25, 0, .5, 0, .25, 0, .125, 0, 1])
    r.mix()
    assert r.raw(BUS, 512) == master
    assert r.raw(INPUT, 2560) == before
    assert r.bus(2) != r.bus(3)
    passed('modeled_aux_policy_preserves_master_mix_and_input_buffers')

    # A subsequent stock setter can undo a one-time coefficient change.
    r = Rig()
    r.row(2, [0, 0, .5, 0, 0, 0, 0, 0, 0, 0])
    r.run(0x80002890, [3, 1, 0, 0])
    r.run(0x80002878, [3, 1, 100, 0])
    assert r.values(MATRIX+80+3*4, 1)[0] > 0
    passed('stock_control_update_overwrites_stereo_zero_so_persistent_binding_is_required')

    # Execute exact normal-output conversion windows with synthetic scaled audio.
    # Dynamics/scaling before conversion are deliberately not part of this check.
    r = Rig()
    lout = [float(1024+4*i) for i in range(64)]
    rout = [float(-2048-8*i) for i in range(64)]
    r.floats(BUS+512, lout)
    r.floats(BUS+768, rout)
    r.uc.mem_write(OUT, b'\xa5'*512)
    r.uc.reg_write(UC_ARM_REG_R11, B)
    r.uc.reg_write(UC_ARM_REG_R6, OUT)
    r.uc.reg_write(UC_ARM_REG_S0, struct.unpack('<I', packed([-2147483648.0]))[0])
    r.uc.reg_write(UC_ARM_REG_S20, struct.unpack('<I', packed([2147483648.0]))[0])
    r.run(0x202291a0, end=0x20229538)
    li, ri = [int(v)-1 for v in lout], [int(v)-1 for v in rout]
    assert r.raw(OUT+512, 256) == struct.pack('<64i', *li)
    assert r.raw(OUT+768, 256) == struct.pack('<64i', *ri)
    assert r.raw(OUT, 512) == b'\xa5'*512
    passed('original_aux_integer_conversion_keeps_two_output_lanes_separate')

    r.uc.reg_write(UC_ARM_REG_R8, 0x21000000)
    r.uc.reg_write(UC_ARM_REG_R10, 0x21001000)
    r.run(0x800107a0, end=0x80010872)
    expected = struct.pack('<128i', *[v for pair in zip(li, ri) for v in pair])
    assert r.raw(0x21001000, 512) == expected
    passed('original_audio_task_interleaves_aux_pair_into_second_output_buffer')

    report = dict(
        passed_groups=len(results), results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        boundaries=dict(mixer='0x20224b90', control='0x80048c78',
                        aux1_coefficients=hex(MATRIX+80), aux2_coefficients=hex(MATRIX+120),
                        aux1_bus=hex(BUS+512), aux2_bus=hex(BUS+768)),
        limitations=[
            'Synthetic input/control state; original EQ and gain-ramp enable flags are zero',
            'Stereo policy is host-injected coefficients, not a compiled or installed feature',
            'Mono pan and stereo balance endpoints/centre tested; MONO x2 and USB mode integration unverified',
            'Mixer and output conversion are separate bounded checks, not a complete output-chain run',
            'Intervening gain/dynamics, ADC, physical output/DMA, timing and analogue behavior unverified',
            'No pad/effects-to-AUX routing addition and no persistence or UI implementation',
        ],
    )
    out = ROOT/'analysis/stereo_aux_verification.json'
    out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results), report=str(out)), indent=2))


if __name__ == '__main__':
    main()
