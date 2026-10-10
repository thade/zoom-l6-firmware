#!/usr/bin/env python3
"""Demonstrate native stop arithmetic with a consumer past the saved endpoint.

Original instructions, synthetic cursor/count state; no scheduler execution or
claim that this ordering caused the observed hardware Channel 1 discrepancy.
This characterizes a remaining integration gate, not a firmware fix.
"""
import json
from verify_record_events import cursor_rig, u32
from verify_recording_writer import C
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT


def main():
    capacity = 240000
    target = 8191488
    results = []
    for distance in (-64, 0, 64):
        rig = cursor_rig()
        put32(rig.m, C+8, 0xfff)
        put32(rig.m, C+0x50, capacity)
        for stream in range(12):
            count = target + (distance if stream == 0 else -64)
            put32(rig.m, C+0x20+4*stream, count % capacity)
            put32(rig.m, C+0x484+4*stream, count)
        rig.m.invoke(0x800382a8, [target % capacity])
        limits = [u32(rig, C+0x4e4+4*stream) for stream in range(12)]
        expected = target + (capacity if distance > 0 else 0)
        assert limits[0] == expected
        assert limits[1:] == [target]*11
        results.append(dict(stream0_frames_relative_to_saved_stop=distance,
            saved_stop_frame=target, stream0_final_limit=limits[0],
            stream0_excess_frames=limits[0]-target, other_streams_final_limit=target))
    report = dict(passed_groups=1, native_entry='0x800382a8',
        capacity_frames=capacity, capacity_seconds=capacity/48000, cases=results,
        observed_master_frames=8191488, observed_channel1_frames=8431488,
        demonstrated_arithmetic_matches_observed_excess=True,
        hardware_cause_proven=False,
        limitation='Synthetic coherent cursor/count pairs. Does not demonstrate an actual in-flight producer crossing the saved stop before native limit publication, or attribute any discrepancy to memory reservation.')
    path = ROOT/'analysis/stop_cursor_lap_verification.json'
    path.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
