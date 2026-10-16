# Release 0.2.0: the firmware writes the pad anchors

[Release 0.1.0](../38-release/README.md) with the anchors written by the
firmware ([experiment 39](../39-flash-diag/README.md), without its
diagnostics), so installing needs only `L6.BIN`. Everyday build.

**Prepared locally; not yet installed.** The image hash changes until the
release checks pin it (`tools/firmware/build_master_trial.py release`).
Recovery from a firmware that hangs at startup was shown in
[experiment 18](../18-recovery-hang/README.md).

## Changes from 0.1.0

- **Anchors.** While the chain is on, each `SOUND_PAD/PADn` folder without
  `MASTER.WAV` gets it from the firmware: at start-up, when the chain is
  switched on, and after each storage change once the card has settled (Main
  has handled the change, 2 s, not in File Transfer Mode). The writer stops
  for a recording and finishes later; Main adds the file to the pad's list,
  or the worker asks again (at most 30 times per storage change) while the
  recorder is busy or an assignment to that pad loads. A deleted anchor comes
  back, so the chain always uses pads 1–4 while on; turn it off to keep
  hand-picked pad sounds.
- **Release files.** `release/0.2.0/` holds only `L6.BIN`; the installer no
  longer copies `MASTER.WAV` (it still does for a 0.1.0 folder).
- **Tidy-ups** from the 0.1.0 reviews: the switch arming compares signed (a
  Main store just after the worker's tick read could look armed for a poll);
  lines inherited from a version 1 `HISTORY.TXT` are taken last first, so a
  new history stays newest first; one shared header (`stock.h`) for the stock
  addresses, with `panel_recording` next to `recorder_busy`.

Known limit: while an anchor is written (about a dozen file calls in one
worker step), the switch-hold detector does not poll; on a slow card an
EFX + PAN or AUX 1 + AUX 2 hold in progress may restart. It happens only
when an anchor is created (the first switch-on, or after one was deleted).

## Checks

- `tools/firmware/verify_release.py`: the exact image (sites, boot, every
  earlier installed image rebuilt, 0.1.0 from its tag), then the take chain,
  history and anchor groups and the stereo AUX and switch groups on the
  release link.
- `tests/emulation/verify_master_ref.py`: 27 groups, including the anchor
  cases (settled card, File Transfer Mode, recording and storage change
  mid-write, no card, busy listing, the 30-post cap) and version 1 history
  order.
- `tests/emulation/verify_bootloader.py`: the bootloader accepts the image.

## Procedure (release checks)

1. Install over experiment 39 with `install_release.py --any-image`.
2. A take reaches pad 1 with the chain on; EFX + PAN and AUX 1 + AUX 2
   holds work.
3. With a card whose pad folders have no `MASTER.WAV` (moved aside), restart:
   all four appear, and the next takes fill pads 1–4.
4. The browser patcher in Chrome: make `L6.BIN` from Zoom's zip, then send it
   to the mixer (File Transfer Mode, write and read back, eject, leave File
   Transfer Mode) and update with PLAY/STOP.
