# Simplified capture: first takes

The first trial that writes the extra pre-compressor file. Every ordinary
recording also produces `SOUND_PAD/PAD1/OD_<serial>.TMP`: the pre-master mix
from the stock start cursor to the stock stop cursor. The stock pad scanner is
expected to ignore `.TMP`; this trial checks pad assignments after a take and a reboot.

**Installed 11 October 2026; both takes passed.** Recovery from an image that
fails before Main remains unproven ([experiment 18](../18-recovery-hang/README.md) is parked).

## Results

| Check | Take 1 (`261011_130946`) | Take 2 (`261011_133624`) |
|---|---|---|
| Length | 79.66 s, 3,823,680 frames | 93.05 s, 4,466,368 frames |
| Worker | completed, status OK, no skip/fault/revocation | completed, status OK, no skip/fault/revocation |
| Payload | 30,589,440 bytes = frames × 8 | 35,730,944 bytes = frames × 8 |
| Frames vs MASTER and all six stems | equal | equal |
| Lag behind MASTER | 48 frames | 48 frames |
| Correlation with MASTER | 0.9999999974 | 0.9999999970 |
| Extra file peak | 0.00016 (noise floor only) | 0.733 (real signal) |
| Worker stack, deepest use | 1,260 of 16,384 bytes | 1,260 bytes |
| Minimum free heap | 141,096 bytes | 138,656 bytes |

The extra file is the pre-master mix, sample-aligned with the stock take: it
starts and ends on the stock files' frames and differs from MASTER only by the
stock master body's 48-frame delay (master dynamics were neutral in these takes).
Audio continuity held throughout (epoch 1), including several USB
re-enumerations. One revocation at boot came from the card-ready packet
(`0x000835`) while no take was open; transfer-mode cycles added more, never
during a take.

Pad names and counts were unchanged after a transfer-mode rescan and after a
cold reboot with `OD_00000001.TMP` on the card, so the stock pad scanner ignores
`.TMP`. Staging verified the image by readback with settings and 163 file entries
unchanged. Evidence stays in `deployment/20_simple_take/`.

## What it answers

- Does a take produce an extra file with exactly as many frames as MASTER?
- Is it the pre-master mix? Against MASTER it should lag by the 48-frame stock
  master delay; correlation depends on master gain and dynamics.
- SD service: does the worker keep up with 384,000 B/s beside the stock files
  (no `OVERRUN`), and do stock files stay valid?
- Admission: does stock stream admission follow the start request within the
  1.365-second history (the take is admitted and not counted as a fault)?
- Worker stack: deepest use, measured by painting 15 KiB of the 16-KiB stack.

## Image

- Local image: `deployment/20_simple_take/trial_simple_take/L6.BIN`.
- SHA256: `bfe40713b69f258f766a64faaf3669f52061aa56cb3d7a65b16f98349bf8e3c4`.
- All twelve capture sites plus the status query: startup ×2, ring capacity,
  DSP tap/commit, stream admission `0x8000b158`, the RecStop cursor setter
  `0x80006918`, the five Main receive calls and the Editor query `0x800301f0`.
- 4,648 bytes of code in the consumed DSP source span, 16 bytes of globals,
  14,868 bytes spare with the stock decoder.
- The query also reports the last packet that revoked a take, so an unexpected
  revocation can be traced to its stock message.
- Builder: `tools/firmware/build_simple_trial.py take`. Offline checks:
  `tests/emulation/verify_simple_take.py` (4 groups) and the 21-group capture suite.

## Procedure

Staging uses `deployment/20_simple_take/stage20.py` with the steps `precheck`,
`stage`, `eject` and `exit-check`, as for experiment 19.

File Transfer Mode no longer needs the Editor. With the official Editor closed,
`tools/device/l6_transfer_mode.py enter|exit|session` drives the stock editor
session over MIDI: identity, editor open, then `31 09 01|00` (sequence from
philmillman/zoom-l6-companion, MIT). Each change is confirmed by the card volume
and by the editor-open reply's mode byte, not by the acknowledgement alone.
`exit` refuses while the card is mounted. Without the Editor's heartbeats the
session lapses, so status queries use `l6_simple_probe.py --session`.

1. With the mixer idle, run `precheck`, enter File Transfer Mode, `stage`, `eject`,
   exit File Transfer Mode, then `exit-check`.
2. PLAY/STOP-held update, wait for rapid green, reboot normally and leave idle.
3. Idle samples: `python tools/device/l6_simple_probe.py --output BOOT_LOG --manifest deployment/20_simple_take/manifest.json`.
   `revoked` must not change between the two idle samples.
4. Before recording: `python tools/device/l6_simple_probe.py --output BEFORE_LOG`.
5. Keep the computer awake and leave USB audio alone during the take. Record
   about 30 seconds as usual, optionally with a pad backing, then stop. Wait
   about ten seconds for the worker to drain, finish and check the file.
6. `python tools/device/l6_simple_probe.py --output AFTER_LOG --before-take BEFORE_LOG`
   must report one completed take, its frames and payload bytes, the worker's
   stack use and any storage packets seen during the take.
7. Enter File Transfer Mode and run `stage20.py collect`. It copies the one take
   folder and the one `.TMP` that are new since the last baseline, verifies the
   copies, runs `tools/device/analyze_capture_take.py` (equal frames to MASTER
   and every stem, finite samples, lag 48 ±2 frames, correlation at least 0.5)
   and ejects. Exit transfer mode. A failed analysis is still saved, with the
   reason, in `deployment/20_simple_take/take-<name>/analysis.json`.
8. Reboot normally and confirm pad names and counts are unchanged.
9. If everything passes, repeat steps 4–7 with a whole song.

A skipped take, `OVERRUN`, `REVOKED` or an event fault is a finding to record
and investigate, not a reason to keep recording. Stock files must stay valid in
every case. Restore stock with `deployment/01_usb_marker/stock_control/L6.BIN`
if anything looks wrong.
