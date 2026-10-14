# Everyday build: take chain and take history without diagnostics

[Experiment 28](../28-take-history/README.md) (the take chain with the
2-second minimum, plus `HISTORY.TXT` in each take folder) as a clean build for
normal use: no status query, so no hook on the Editor's MIDI parser, and no
worker stack measurement. Behaviour is otherwise identical.

**Prepared locally; not staged or installed.** The mixer runs experiment 28.
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

| | Experiment 28 (trial) | Experiment 29 (everyday) |
|---|---|---|
| Patch sites | 11 | 10 (the Editor parser stays stock) |
| Code | 8,564 bytes | 7,604 bytes |
| Status query, stack measurement | yes | none |

Without the query, behaviour is checked by ear, from the saved pad paths and
from the history files (`stage29.py settings` in File Transfer Mode prints
both). To diagnose a problem, reinstall experiment 28, which rebuilds byte
for byte.

## Image

- Local image: `deployment/29_daily/daily/L6.BIN`; SHA256 and sizes in
  `deployment/29_daily/manifest.json`.
- Builder: `tools/firmware/build_master_trial.py daily`. Offline checks:
  `tests/emulation/verify_master_ref_everyday.py` (all 24 behaviour groups on
  this build's code) and `tests/emulation/verify_master_everyday.py` (2
  groups, exact image; experiments 26–28 rebuild byte for byte).

## Procedure

Staging uses `deployment/29_daily/stage29.py`. After the update and reboot:

1. Record a take with pad 1 playing: the chain moves along.
2. `stage29.py settings` in File Transfer Mode: the new take's `HISTORY.TXT`
   lists the take pad 1 held plus that take's own history.
