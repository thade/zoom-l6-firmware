# Simplified capture: worker service diagnostics

Experiment 21 lost one take of five to an `OVERRUN`: about 10 seconds in, the
worker fell more than 1.365 seconds behind the tap. This trial measures why,
before choosing a fix. Behavior is the same as experiment 21 (capture plus pad
handoff); only measurements are added.

**Installed 11 October 2026; the measurements found the cause.** Recovery from
an image that fails before Main remains unproven ([experiment 18](../18-recovery-hang/README.md) is parked).

## Results

Runtime priorities: StreamFileAccess 28, Main 13, RecPlayCtl 12,
StreamUpdateRecStream 11, SamplerFileAssign 9, capture worker 1.

| Take | Length | Result | `lag_max` | `write_max` | `write_long` | `gap_max` |
|---|---|---|---|---|---|---|
| 1 | 49.3 s | completed, handed off | 0.468 s | 411 ms | 9 | 432 ms |
| 2 | 52.8 s | completed, handed off | 0.401 s | 368 ms | 8 | 386 ms |
| 3, whole song | 338.6 s | `OVERRUN` at 237.4 s | 1.564 s | 1,276 ms | 35 | 1,596 ms |

Single 4-KiB writes regularly block for about 0.4 s and, over a whole song,
once for 1.28 s: card latency or waits for the filesystem lock behind the
priority-28 stock writer. The step gap exceeding the longest write by about
320 ms adds some CPU starvation of the priority-1 worker. The 1.365-second
history cannot cover that; the stock recorder rides it out on its 4.6-second
ring. Stock files, pads and handoffs were unaffected. Experiment 23 doubles the
history, writes 16 KiB at a time and raises the worker to priority 10.

## Measurements (per take, reset when a take starts)

| Field | Meaning |
|---|---|
| `lag_max` | largest distance in frames between the tap and the worker (overrun above 65,472) |
| `write_max` | longest single file write in ticks (1 ms), including waits for the filesystem lock |
| `write_long` | writes that took 250 ticks or more |
| `gap_max` | longest interval in ticks between worker capture steps (CPU starvation) |
| `writes` | file writes in the take, headers included |
| `prio_*` | runtime priorities from the task control blocks: StreamFileAccess, StreamUpdateRecStream, RecPlayCtl, SamplerFileAssign, Main and the capture worker |

How to read them: a large `gap_max` with short writes means the worker is
starved of CPU. A large `write_max` means it waits on the card or the lock; if
that coincides with stock catch-up, the worker is queued behind higher-priority
stock writers (stock raises StreamUpdateRecStream to priority 11; the worker
runs at 1). The candidate fixes follow: a higher worker priority, fewer and
larger writes, or more history from a slightly shorter stock ring.

## Image

- Local image: `deployment/22_simple_diag/trial_simple_diag/L6.BIN`.
- SHA256: `947c8ddb36c4e5109b37dc5895980ec1e7937086bf4f6c78e085e08f8ee7e99f`.
- Experiment 21 plus the counters and schema-4 query: 5,828 bytes of code,
  16 bytes of globals, 13,791 bytes spare with the stock decoder.
- Builder: `tools/firmware/build_simple_trial.py diag`. Offline checks:
  `tests/emulation/verify_simple_diag_trial.py` (4 groups, exact image), plus the
  capture and handoff suites.

## Procedure

Staging uses `deployment/22_simple_diag/stage22.py` with the MIDI transfer tool,
as for experiment 21. After the update and reboot:

1. Idle samples with `--session --manifest deployment/22_simple_diag/manifest.json`.
2. For each take, a before sample with `--session`, then record, stop, wait ten
   seconds and take an after sample with `--before-take` (the take check still
   applies; an overrun fails it and still records the counters).
3. Record three or four takes of 30–60 seconds, then a whole song of about five
   minutes, ideally with pad 1 playing as in real overdubbing.

Every take keeps its counters in the after sample, including failed ones.
