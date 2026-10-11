# Simplified capture: pad handoff

After each verified take, the extra file becomes pad 1's sound, so the next
overdub pass can play it as the backing. This is the first trial of the full
capture-to-pad loop on the mixer.

**Installed 11 October 2026; the overdub loop works on the mixer.** One take
failed with an overrun (below). Recovery from an image that fails before Main
remains unproven ([experiment 18](../18-recovery-hang/README.md) is parked).

## Results

| Take | Length | Capture | Handoff | Pad 1 afterwards |
|---|---|---|---|---|
| 1 | about 18 s | `OVERRUN` after 10.4 s (3,985,408 bytes written) | none (no verified file) | unchanged, `OD_261002_181142.WAV` |
| 2 | 63.3 s | completed | assigned (serial 1) | `OD_00000004.WAV`; plays the take correctly |
| 3, over pad 1 | 50.7 s | completed, no storage packets during the take | assigned (serial 2) | `OD_00000005.WAV` |
| after cold reboot | | capture restarted cleanly | | still `OD_00000005.WAV` |

The stock rename works on the card, the stock validator and loader accept the
extra file's header, and float audio plays correctly from pad 1 (user check).
Pad 1's play mode was kept. The assignment persisted across a cold reboot, and
pads 2–4 were unchanged throughout. Worker stack peaked at 1,708 bytes with the
handoff; free heap stayed 140,936 bytes. Take 3 recorded over pad 1's backing,
so its file holds both layers: one complete overdub iteration.

Take 1's overrun is unexplained: the worker fell more than 1.365 s behind about
10 s into the take, with no user action noticed. Experiments 20 and 21 have
now captured five takes with one overrun. The abandoned partial file remains as
`OD_00000003.TMP`. Next: measure worker lag and write time on hardware, then
choose between larger writes, a higher worker priority and more history.
Evidence stays in `deployment/21_simple_handoff/`.

## How the handoff works

1. The worker verifies the take, renames `OD_n.TMP` to `OD_n.WAV` with the stock
   same-folder rename (one directory sector, no data copied), then posts a
   private category-3 Main event. No stock Main loop dispatches category 3.
2. Main's receive hook performs the stock Editor select steps for pad 1: look
   the name up in the PAD1 catalogue (inserting it if missing), require the
   catalogue path to equal the sealed file, validate the WAV, stop pad 1 if it
   plays, and queue the stock assignment. Stock code loads the file and saves
   `L6PADSETTING.ZST`.
3. While a stock take records or RecStop is still finalizing (the recorder
   task's busy word `0x80578ec0`), Main leaves the handoff posted and the
   worker reposts it about once a second for 30 seconds. A newer take
   supersedes it. A storage change after sealing, or pad 1 being the
   pad-record target, skips it. Any rename error ends it, leaving the file
   for manual selection.
4. `assigned` means the stock assignment is queued, not loaded: the stock loader
   can still fail on its own task and leave pad 1 unassigned. The trial reads
   pad 1's assigned name back to confirm.

The status query (schema 3) reports `handoff_state` (none, posted, assigned,
skipped, failed, lost), `handoff_result` and `handoff_serial`.

## What it answers

- Does the stock rename work on the real exFAT card, and does pad 1 then play
  the new take, keeping its play mode and level?
- Does `0x80009568` accept the extra file's header, and does the stock loader
  play it?
- Does the assignment persist across a reboot?
- Is the mixer's display and the Editor consistent afterwards?

## Image

- Local image: `deployment/21_simple_handoff/trial_simple_handoff/L6.BIN`.
- SHA256: `7551f0de9f1628f57706df073dc275f5f676f256b143cc9768a325dacc7c4114`.
- The experiment 20 sites and query, plus the handoff: 5,560 bytes of code,
  16 bytes of globals, 14,017 bytes spare with the stock decoder.
- Builder: `tools/firmware/build_simple_trial.py handoff`. Offline checks:
  `tests/emulation/verify_simple_pad_handoff.py` (10 groups, original catalogue
  code) and `tests/emulation/verify_simple_handoff_trial.py` (4 groups, exact image).

## Procedure

The official Editor can stay closed: `tools/device/l6_transfer_mode.py` drives
File Transfer Mode and `l6_simple_probe.py --session` queries status.
Staging uses `deployment/21_simple_handoff/stage21.py`.

1. With the mixer idle: `stage21.py precheck`, `l6_transfer_mode.py enter`,
   `stage21.py stage`, `stage21.py eject`, `l6_transfer_mode.py exit`,
   `stage21.py exit-check`.
2. PLAY/STOP-held update, wait for rapid green, reboot normally and leave idle.
3. Idle samples with `--session --manifest deployment/21_simple_handoff/manifest.json`.
4. Note pad 1's current file and mode. Before-take sample with `--session`.
5. Record about 30 seconds with something audible, then stop. Wait about ten
   seconds.
6. After-take sample with `--before-take`: one completed take and
   `handoff_state` assigned. Query pad 1's assigned name: `OD_<serial>.WAV`.
7. Play pad 1: it should play the take just recorded, in pad 1's existing mode.
8. Record a second pass over it, then repeat steps 6–7: pad 1 now holds the
   newer take.
9. Reboot normally and confirm pad 1 still holds the newest take.

A skipped, failed or lost handoff is a finding to record with its result code.
Stock recordings and pads 2–4 must stay unchanged in every case. Restore stock
with `deployment/01_usb_marker/stock_control/L6.BIN` if anything looks wrong.
