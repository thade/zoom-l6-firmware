# Progress

## Status

**0.1.0** is the experiment 38 image: the take chain on pads 1–4 with an
EFX + PAN on/off switch (off until switched on), a `HISTORY.TXT` in every
take folder, and the stereo AUX send with the AUX 1 + AUX 2 mono/stereo
switch, on Zoom's v1.10. It was installed and passed on 16 October 2026. Its
features have run daily on one mixer since 12 October; experiments 34–38
(table below) took it from the release review build to the EFX + PAN switch.
Recovery from an image that hangs at startup was shown on 16 October 2026
([experiment 18](../experiments/18-recovery-hang/README.md)): the bootloader
runs the PLAY/STOP update before the firmware starts.

Open work: [future work](future-work.md). The detailed log up to 0.1.0 is in
[archive/progress-log.md](archive/progress-log.md).

## How it got here (October 2026)

1. **Can the firmware be changed safely? (1–4, 4–6 Oct)** A changed USB name,
   an executable-code marker, an added routine and a diagnostic probe were
   installed, and stock was restored after each.
2. **Hardware diagnostics (5–18, to 11 Oct)**: file-call and SD timing,
   memory and RAM layout, a startup loader and the source-reuse layout the
   release still uses. Stock was no longer restored between these.
3. **Pre-compressor capture (19–23, 11 Oct)**: a clean copy of each take
   written in real time and handed to a pad. The overdub loop worked, but the
   first take after boot overran its buffer.
4. **Master reference (24–29, 12–14 Oct)**: the pads play the stock
   `MASTER.WAV` in place instead, which needs no capture at all; then the
   four-pad chain, the 2-second minimum and `HISTORY.TXT`.
5. **Stereo AUX (30–33, 15 Oct)**: the stereo send, its mono/stereo switch and
   the everyday build. **34** carries the release review fixes, **35** adds
   the chain on/off switch, **36** hardens the switch holds, **37** diagnoses
   the PAN + LEVEL hold and **38**, 0.1.0, moves the chain to EFX + PAN.

## Experiments

"Installed" means the image ran on the mixer; each README has the results.

| # | Experiment | Outcome |
|---|---|---|
| 01 | [USB name: stored data](../experiments/01-usb-name/README.md) | Installed; stock restored |
| 02 | [USB name: code marker](../experiments/02-code-marker/README.md) | Installed; stock restored |
| 03 | [Added-code detour](../experiments/03-added-code/README.md) | Installed; stock restored |
| 04 | [Memory and SD timing probe](../experiments/04-health-probe/README.md) | Installed; stock restored |
| 05 | [File-call timing](../experiments/05-timing-probe/README.md) | Installed |
| 06 | [Recorder memory reservation](../experiments/06-memory-reservation/README.md) | Installed |
| 07 | [Storage service](../experiments/07-storage-service/README.md) | Installed; storage redesign needed |
| 08 | [Ring layout](../experiments/08-ring-layout/README.md) | Installed |
| 09 | [SD completion](../experiments/09-sd-completion/README.md) | Installed |
| 10 | [Raw SD interrupts](../experiments/10-sd-raw/README.md) | Installed |
| 11 | [SD commands](../experiments/11-sd-command/README.md) | Installed |
| 12 | [RAM configuration](../experiments/12-memory-capacity/README.md) | Installed |
| 13 | [RAM activity](../experiments/13-ram-activity/README.md) | Installed |
| 14 | [SD startup](../experiments/14-sd-startup/README.md) | Installed |
| 15 | [Startup loader](../experiments/15-loader/README.md) | Installed |
| 16 | [Source reuse](../experiments/16-source-reuse/README.md) | Installed; the release layout |
| 17 | [Dormant boot](../experiments/17-dormant-boot/README.md) | Superseded, not installed |
| 18 | [Early-hang recovery](../experiments/18-recovery-hang/README.md) | Passed (16 October, after experiment 39) |
| 19 | [Capture: tap](../experiments/19-simple-tap/README.md) | Installed; passed |
| 20 | [Capture: takes](../experiments/20-simple-take/README.md) | Installed; passed |
| 21 | [Capture: pad handoff](../experiments/21-simple-handoff/README.md) | Installed; first overdub loop on the mixer |
| 22 | [Capture: worker diagnostics](../experiments/22-simple-diag/README.md) | Installed; found the overrun cause |
| 23 | [Capture: larger buffer](../experiments/23-simple-buffer/README.md) | Installed; first take still overran |
| 24 | [Master reference](../experiments/24-master-ref/README.md) | Installed; passed |
| 25 | [Take chain](../experiments/25-take-chain/README.md) | Installed; passed |
| 26 | [Ignore takes under 2 s](../experiments/26-short-takes/README.md) | Installed; passed |
| 27 | [Everyday build of 26](../experiments/27-everyday/README.md) | Superseded by 28, not installed |
| 28 | [Take history](../experiments/28-take-history/README.md) | Installed; passed |
| 29 | [Everyday build of 28](../experiments/29-daily/README.md) | Installed; passed |
| 30 | [Stereo AUX](../experiments/30-stereo-aux/README.md) | Installed; passed on the jacks |
| 31 | [Everyday build of 30](../experiments/31-daily-stereo/README.md) | Superseded by 32, not installed |
| 32 | [AUX mono/stereo switch](../experiments/32-aux-switch/README.md) | Installed; passed |
| 33 | [Everyday build of 32](../experiments/33-daily-switch/README.md) | Installed; superseded by 34 |
| 34 | [Release review build](../experiments/34-release/README.md) | Installed 16 Oct; passed |
| 35 | [Chain on/off switch](../experiments/35-release/README.md) | Installed 16 Oct; passed |
| 36 | [Misread-tolerant holds](../experiments/36-release/README.md) | Installed 16 Oct; PAN + LEVEL still unreliable |
| 37 | [Panel switch diagnostics](../experiments/37-panel-diag/README.md) | Installed 16 Oct; found PAN lost while LEVEL held |
| 38 | [Release 0.1.0: EFX + PAN](../experiments/38-release/README.md) | Installed 16 Oct; passed |
| 39 | [Firmware-written anchors, flash backup](../experiments/39-flash-diag/README.md) | Passed (toward 0.2.0) |
| 40 | [Release 0.2.0](../experiments/40-release/README.md) | Prepared |

## Checks

`tools/firmware/verify_release.py` builds 0.1.0 and runs its suites from a
fresh clone. `tools/firmware/verify_redesign.py` runs every offline suite in
the repository, research included (see [setup](setup.md)).
