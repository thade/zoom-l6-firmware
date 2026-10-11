# Simplified capture: longer history, larger writes

Experiment 22 found the overrun's cause: single file writes block for up to
1.28 s over a whole song, more than the 1.365-second history can absorb. This
trial applies three changes together and repeats the measurements.

**Installed 11 October 2026; the first take after boot still overran.** The
capture approach is set aside for [experiment 24](../24-master-ref/README.md),
which references the stock master instead. Recovery from an image that fails
before Main remains unproven ([experiment 18](../18-recovery-hang/README.md) is parked).

## Results

| Take | Length | Result | `lag_max` | `write_max` | `write_long` | `gap_max` |
|---|---|---|---|---|---|---|
| 1, first after boot | about 5.5 s captured | `OVERRUN` (2,113,536 bytes written) | 2.929 s | 1,117 ms | 5 | 1,208 ms |
| 2 | 66.8 s | completed, handed off (serial 1) | 0.397 s | 363 ms | 7 | 377 ms |

Priority 10 and 16-KiB writes cut ordinary lag to about 0.4 s, but the first
take after boot met a 1.1-second write and a 1.2-second step gap early on and
still exceeded the doubled 2.73-second history. The stalls sit in the stock
filesystem and card path, outside the capture's control; more history would
need a still shorter stock ring. Worker stack peaked at 1,700 bytes; minimum
free heap 128,648 bytes. Stock files and pads were unaffected. Evidence stays
in `deployment/23_simple_buffer/`.

## Changes

| | Experiments 20–22 | Experiment 23 |
|---|---|---|
| Capture history | 1,024 blocks, 1.365 s | 2,048 blocks, **2.731 s** |
| Stock ring capacity | 223,104 frames, 4.648 s | 207,232 frames, **4.317 s** |
| Lane tails | 67,584 bytes | 131,072 bytes (256 blocks of 512) |
| Payload write size | 4 KiB | **16 KiB** |
| Worker priority | 1 | **10** (above SamplerFileAssign 9, below RecPlayCtl 12 and Main 13) |
| Capture state on the heap | 5.4 KB | about 17.7 KB |

The ring patch changes only the low half of the existing MOVW (`42f68011`,
`movw r1, #0x2980`); the stock MOVT keeps the high half. The stock ring suites
run the original initializers, audio callbacks, playback wrap and song refills
at 207,232 frames with the tails untouched (31 and 34 groups). Stock stall
tolerance falls by 0.33 s, to more than three times the worst stall measured.

## Image

- Local image: `deployment/23_simple_buffer/trial_simple_buffer/L6.BIN`.
- SHA256: `1ce0356716112bd3251a430c9c25b17a2673b80a7c880a8489250b956e8ff4b9`.
- 5,844 bytes of code, 16 bytes of globals, 13,780 bytes spare with the stock decoder.
- Builder: `tools/firmware/build_simple_trial.py buffer`. Offline checks:
  `tests/emulation/verify_simple_buffer_trial.py` (4 groups, exact image), the
  capture (21) and handoff (10) suites, and the stock ring suites.

## Procedure

As for experiment 22, with `deployment/23_simple_buffer/stage23.py`. After the
update and reboot: idle samples with `--session --manifest`, then per take a
before sample, the take, and an after sample with `--before-take`.

1. Two takes of 30–60 seconds.
2. At least two whole songs of about five minutes with pad 1 playing.

Pass: every take completes and hands off, `lag_max` stays well under 2.73 s,
and stock files stay valid. The counters show how much margin remains.
