# Simplified capture: worker service diagnostics

Experiment 21 lost one take of five to an `OVERRUN`: about 10 seconds in, the
worker fell more than 1.365 seconds behind the tap. This trial measures why,
before choosing a fix. Behavior is the same as experiment 21 (capture plus pad
handoff); only measurements are added.

**Prepared locally; not staged or installed.** The mixer runs experiment 21.
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

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
