# Everyday build: the take chain without diagnostics

The take chain with the 2-second minimum ([experiment 26](../26-short-takes/README.md))
as a clean build for normal use: no status query, so no hook on the Editor's
MIDI parser, and no worker stack measurement. Behaviour is otherwise
identical.

**Prepared 13 October 2026; never installed.** Superseded by
[experiment 28](../28-take-history/README.md), whose everyday build is
[experiment 29](../29-daily/README.md).
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

## What changes

| | Experiment 26 (trial) | Experiment 27 (everyday) |
|---|---|---|
| Patch sites | 10 | 9 (the Editor parser stays stock) |
| Code | 4,548 bytes | 3,620 bytes |
| Status query (`l6_padref_probe.py`) | yes | none |
| Worker stack measurement | yes | none |

Without the query, behaviour on the mixer is checked by ear and from the saved
pad paths (`stage27.py settings` in File Transfer Mode). To diagnose a
problem, reinstall experiment 26, which rebuilds byte for byte.

## Image

- Local image: `deployment/27_everyday/everyday/L6.BIN`; SHA256 and sizes in
  `deployment/27_everyday/manifest.json`.
- Builder: `tools/firmware/build_master_trial.py everyday`. Offline checks:
  `tests/emulation/verify_master_ref_everyday.py` (all 15 behaviour groups on
  this build's code) and `tests/emulation/verify_master_everyday.py` (2 groups,
  exact image; experiment 26 rebuilds byte for byte).

## Procedure

Staging uses `deployment/27_everyday/stage27.py` (the anchors are already on
the card). After the update and reboot:

1. Record a normal take: pad 1 plays it and the others moved one along.
2. Record a take of about 1 second: the pads stay as they were.
3. Cycle File Transfer Mode with `stage27.py settings`: the saved pad paths are
   the last takes, newest first.
