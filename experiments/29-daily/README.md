# Everyday build: take chain and take history without diagnostics

[Experiment 28](../28-take-history/README.md) (the take chain with the
2-second minimum, plus `HISTORY.TXT` in each take folder) as a clean build for
normal use: no status query, so no hook on the Editor's MIDI parser, and no
worker stack measurement. Behaviour is otherwise identical.

**Installed 14 October 2026; passed. This is the current everyday image.**

## Results

A take (`261014_120212`, about 17 s) recorded with pad 1 playing the previous
take `261014_112757`: the chain moved to `120212`, `112757`, `112705`,
`112637`, and the new `HISTORY.TXT` listed `112613`, `112637`, `112705` and
`112757` (`END 4`): the played take's own history plus its folder. The take
folder held its seven stock files and `HISTORY.TXT`, no temp file was left,
and all four anchors were intact.

### A missing take folder

Pad 1's take (`261014_122711`, a throwaway) was moved off `A:\RECORDER` in
File Transfer Mode (renamed into `A:\L6_HOLD`, nothing deleted), to look
deleted to the mixer:

- At the rescan when leaving File Transfer Mode, the stock loader could not
  open the master and cleared pad 1 (no file assigned); pads 2–4 kept their
  takes. Pressing pad 1 was simply silent.
- The next take (recorded with pad 2 playing) went to pad 1; the chain
  closed up over the empty pad, so pads 2–4 stayed `120212`, `112757`,
  `112705`, and nothing was pushed off. Its history listed pad 2's take and
  that take's history (`END 5`); the missing take appears nowhere.
- Emulation of the stock reload predicts that a later rescan would give the
  empty pad its folder's anchor (silent), which the chain also replaces.

The take was then moved back to `A:\RECORDER` as an ordinary take no pad
refers to. Deleting take folders therefore needs no special handling.
Evidence stays in `deployment/29_daily/`.
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
