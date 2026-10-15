# Release 0.1.0: take chain, take history and the AUX mono/stereo switch

[Experiment 33](../33-daily-switch/README.md) plus the fixes from the 0.1.0
release review. Everyday build: no status query and no stack measurement.

**Installed 16 October 2026; passed. This is release 0.1.0.** Recovery from
an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

## Results

Installed over experiment 33 with `tools/device/install_release.py` through
File Transfer Mode: image written and read back identical, the card's
previous `L6.BIN` and `ZOOM_L6.SYS` backed up, card found by its layout. (Its
first run stopped before writing anything: copying the card file's flags into
the backup was refused; fixed to copy data only.)

| Check | Result |
|---|---|
| Hold AUX 1 + AUX 2, twice | Steady (mono), then blinking (stereo) |
| Hold while recording to pad 4 | No LED change: refused |
| Ordinary take `261016_001314` with pad 1 playing, then playback straight away | Pad 1 played the new take afterwards |
| Its `HISTORY.TXT` | `L6 HISTORY 2`, `SOUND SOUND_PAD/PAD1/261016_000950.WAV` (a pad recording was on pad 1), `END 1`; no temp file left |
| Saved pads afterwards | 1 the new take; 2 `261014_123107`; 3 `261014_120212`; 4 the pad recording `261016_001030.WAV` |

The chain moved as designed: pad 1's pad recording counted as a hand-picked
sound, so the new take led and the takes on pads 2-3 followed; pad 4's sound,
past the chain's end, stayed. The status query is absent in this build, so
the version 2 history is what identifies the running image. Not exercised:
the stereo tone test (the mixer was rewired), a history over 100 entries
(emulation covers it). Evidence stays in `deployment/34_release/`.

| | Experiment 33 | 0.1.0 (experiment 34) |
|---|---|---|
| Patch sites | 15 | 15 |
| Code | 8,760 bytes | 8,820 bytes |
| Image SHA256 | `36f2025b…` | `47d9f90d8fab846a3a28f51a28ff22332435c6d7ad7058fb2ea585d8be8a3e59` |

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
