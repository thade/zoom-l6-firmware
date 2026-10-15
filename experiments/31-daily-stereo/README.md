# Everyday build: take chain, take history and stereo AUX

[Experiment 30](../30-stereo-aux/README.md) (the take chain with the 2-second
minimum, `HISTORY.TXT` in each take folder, and the always-on stereo AUX pair)
as a clean build for normal use: no status query, so no hook on the Editor's
MIDI parser, and no worker stack measurement. Behaviour is otherwise
identical.

**Prepared 15 October 2026; never installed.** Superseded by
[experiment 32](../32-aux-switch/README.md), whose everyday build is
[experiment 33](../33-daily-switch/README.md).
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

| | Experiment 30 (trial) | Experiment 31 (everyday) |
|---|---|---|
| Patch sites | 16 | 15 (the Editor parser stays stock) |
| Code | 8,960 bytes | 7,936 bytes |
| Status query, stack measurement | yes | none |

Without the query, the stereo pair is checked on the jacks
(`tools/device/l6_aux_tone_test.py` with a two-input interface), and the chain
and histories from the card (`stage31.py settings`). To diagnose a problem,
reinstall experiment 30, which rebuilds byte for byte.

## Image

- Local image: `deployment/31_daily_stereo/daily_stereo/L6.BIN`; SHA256 and
  sizes in `deployment/31_daily_stereo/manifest.json`.
- Builder: `tools/firmware/build_master_trial.py daily_stereo`. Offline checks:
  `tests/emulation/verify_master_ref_everyday.py` (24 behaviour groups on the
  clean code), `verify_stereo_aux_hooks_everyday.py` (4 stereo groups on this
  build's code) and `verify_master_everyday.py` (2 groups, exact image;
  experiments 26–30 rebuild byte for byte).

## Procedure

Staging uses `deployment/31_daily_stereo/stage31.py`. After the update:

1. The stereo tone test at the unity marks: left on AUX 1, right on AUX 2.
2. A take with pad 1 playing; `stage31.py settings`: the chain moved and the
   new history is right.
