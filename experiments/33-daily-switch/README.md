# Everyday build: take chain, take history and the AUX mono/stereo switch

[Experiment 32](../32-aux-switch/README.md) (the take chain with the 2-second
minimum, `HISTORY.TXT` in each take folder, and the stereo AUX pair switched
by holding **AUX 1** + **AUX 2** for 1.5 s) as a clean build for normal use:
no status query, so no hook on the Editor's MIDI parser, and no worker stack
measurement. It also carries three fixes from a review of the switch.

**Prepared locally; not staged or installed.** The mixer runs experiment 32.
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

| | Experiment 32 (trial) | Experiment 33 (everyday) |
|---|---|---|
| Patch sites | 16 | 15 (the Editor parser stays stock) |
| Code | 9,732 bytes | 8,760 bytes |
| Status query, stack measurement | yes | none |

The stored mode carries over: a mixer last switched to stereo under
experiment 32 starts in stereo.

## Review fixes

- **Refused during every recording.** Experiment 32 refused the switch only
  during an ordinary take (the master reference's own flag), so a pad
  recording could be switched mid-recording, with a settings save. The
  refusal now reads the stock recorder state (`0x80578ebc` = 1 from record
  start, ordinary or to a pad, until RecStop has finalized) and the RecPlayCtl
  busy word. Playback does not refuse.
- **Stock mono if the switch cannot run.** Only the master-reference worker
  polls the hold. If startup does not create it, a stored stereo mode would
  have left AUX in stereo with no way back. The stereo filter now also
  requires the worker to exist; it is published before any task starts (no
  gain request runs earlier, checked in emulation), so such a mixer is stock
  mono from power-on.
- **The LED show always ends.** Main now ends the show itself: on any event it
  receives once 2 s have passed, it clears the show and redraws the view. The
  worker's redraw request only wakes Main and repeats every 250 ms until Main
  has done it, so a starved worker or a lost request no longer leaves the AUX
  LEDs blinking. The timing is signed, so a toggle handled just after the
  worker read the clock no longer ends its own show at once.

Not changed (minor review findings): holds are ignored for 10 s after the
1 ms tick counter wraps (every 49.7 days of uptime); a lost toggle request
gives no feedback until the hold is repeated.

## Image

- Local image: `deployment/33_daily_switch/daily_switch/L6.BIN`; SHA256 and
  sizes in `deployment/33_daily_switch/manifest.json`.
- Builder: `tools/firmware/build_master_trial.py daily_switch`. Offline
  checks: `tests/emulation/verify_master_ref_everyday.py` (24 behaviour groups
  on the clean code), `verify_stereo_aux_hooks_everyday.py` (5 stereo and
  switch groups on this build's code, including the fixes) and
  `verify_master_everyday.py` (2 groups, exact image; experiments 26–32
  rebuild byte for byte).

Without the query, the switch is checked by its LEDs and on the jacks
(`tools/device/l6_aux_tone_test.py`), and the chain and histories from the
card (`stage33.py settings`). To diagnose a problem, reinstall experiment 32,
which rebuilds byte for byte.

## Procedure

Staging uses `deployment/33_daily_switch/stage33.py`. After the update (AUX 1,
AUX 2 and level at their unity marks on input 5):

1. Tone test: the mode experiment 32 stored (stereo).
2. Hold AUX 1 + AUX 2: both LEDs steady for 2 s, then the normal view; mono
   on the jacks. Hold again: both blink, stereo.
3. Record to a sound pad and hold AUX 1 + AUX 2 while it records: no LED
   change, the mode stays.
4. An ordinary take with pad 1 playing; `stage33.py settings`: the chain
   moved and the new history is right.
