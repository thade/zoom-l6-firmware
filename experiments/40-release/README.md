# Release 0.2.0: the firmware writes the pad anchors

[Release 0.1.0](../38-release/README.md) with the anchors written by the
firmware ([experiment 39](../39-flash-diag/README.md), without its
diagnostics), so installing needs only `L6.BIN`. Everyday build.

**Installed 17 October 2026 with the browser patcher; passed. This is release
0.2.0.** Recovery from a firmware that hangs at startup was shown in
[experiment 18](../18-recovery-hang/README.md).

## Results

The image was made in Chrome by the browser patcher from Zoom's v1.10 file
and sent to the mixer with its send-to-mixer steps (File Transfer Mode over
USB MIDI, `L6.BIN` written to the card and read back, the card ejected, File
Transfer Mode left), then installed with the PLAY/STOP update. The user then
ran the procedure below: a take reached pad 1 with the chain on, the EFX +
PAN and AUX 1 + AUX 2 holds worked, and with the four pad folders' anchors
removed all four came back after a restart and the next takes filled pads
1–4. All passed.

| | 0.1.0 (experiment 38) | 0.2.0 (experiment 40) |
|---|---|---|
| Patch sites | 15 | 15 |
| Code | 9,236 bytes | 11,004 bytes |
| Image SHA256 | `99ded4b1…` | `0c72755eaa9e24854ddd60187765b4ff05d0f86df3edd76ef2b08423a775f0af` |

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

1. Install over experiment 39 (here: with the browser patcher, step 4).
2. A take reaches pad 1 with the chain on; EFX + PAN and AUX 1 + AUX 2
   holds work.
3. With a card whose pad folders have no `MASTER.WAV` (moved aside), restart:
   all four appear, and the next takes fill pads 1–4.
4. The browser patcher in Chrome: make `L6.BIN` from Zoom's zip, then send it
   to the mixer (File Transfer Mode, write and read back, eject, leave File
   Transfer Mode) and update with PLAY/STOP.
