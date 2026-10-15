# Release 0.1.0: take chain, take history and the AUX mono/stereo switch

[Experiment 33](../33-daily-switch/README.md) plus the fixes from the 0.1.0
release review. Everyday build: no status query and no stack measurement.

**Prepared locally; not yet installed.** The mixer runs experiment 33.
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

| | Experiment 33 | 0.1.0 (experiment 34) |
|---|---|---|
| Patch sites | 15 | 15 |
| Code | 8,760 bytes | 8,820 bytes |
| Image SHA256 | `36f2025b…` | `47d9f90d…` (pinned on release) |

## Changes from experiment 33

- **No card access during pad recordings or playback.** The take check and
  every history file call waited only for an ordinary take or a RecPlayCtl
  callback, so they could run while a pad recording or a playback was using
  the card. They now also wait while the stock recorder state (`0x80578ebc`)
  is 1 (recording, any target) or 2 (playing); RecStop, PlayStop and the
  stock reset clear it. The chain handoff itself is unchanged.
- **History newest first, at most 100 lines.** Version 2 of `HISTORY.TXT`
  lists the pad files that played first, then what each played take included,
  so the most useful lines are never the ones dropped. Past 100 entries the
  oldest are left out and an `OMITTED` line says so; they are listed in the
  histories of the takes the file names. Version 1 files are still read. See
  the [history format](../../docs/history-format.md).
- **Simpler state and corrected comments.** The duplicated `open_take` flag is
  gone (the ordinary-take flag already marks an open take); file and header
  comments describe what the code now does, including that the worker writes
  to the card.

## Build and checks

- `tools/firmware/build_release.py` writes `release/0.1.0/` (image, anchor,
  `SHA256SUMS`, manifest); the mode is `release` in
  `tools/firmware/build_master_trial.py`.
- `tools/firmware/verify_release.py` (from a fresh clone):
  `verify_master_everyday.py` (2 groups: exact image, boot, experiments 26–33
  rebuilt), `verify_master_ref_everyday.py` (25 groups on the release link,
  including the new deferral and history-order cases) and
  `verify_stereo_aux_hooks_everyday.py` (5).

## Procedure

Install with `tools/device/install_release.py` (backs up the card's
`L6.BIN` and settings file, writes and reads back the image; the anchors are
already on the card). After the update:

1. Tone test (AUX 1/2 into an interface): the stored mode, then a hold each
   way with the LEDs (blink = stereo, steady = mono).
2. Record to a sound pad and hold AUX 1 + AUX 2 meanwhile: no LED change, the
   mode stays.
3. An ordinary take with pad 1 playing: the chain moves; its `HISTORY.TXT`
   is version 2, the played take first.
4. Stop a take and start playback straight away: the take reaches pad 1
   (before playback starts or once it stops) and its history is written.
