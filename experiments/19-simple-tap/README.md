# Simplified capture: tap only

First hardware run of the [simplified capture](../../docs/research/simple_capture_findings.txt).
The pre-master tap fills the history continuously and the worker polls, but no
take can start: the recorder and storage hooks are not installed, so no file
is created. The mixer still makes its ordinary master and channel recordings.

**Prepared locally; not staged or installed.** Diagnostic16 remains on the mixer.
The [early-hang recovery check](../18-recovery-hang/README.md) is parked, so
recovery from an image that fails before Main is still unproven.

## What it answers

- Does the packed build expand and register on hardware with the stock decoder?
- Does the tap run every callback? Frames should advance 48 per 1-ms tick.
- Does audio continuity hold? The epoch should stay at 1 when idle. Any change
  during recording, playback or effect changes shows where a take would be lost.
- Heap cost: one 5,439-byte allocation (5,408-byte state) plus the 16-KiB worker
  stack and task object.
  Expected free heap is about 141,000 bytes (163,104 before).

## Image

- Local image: `deployment/19_simple_tap/trial_simple_tap/L6.BIN`.
- SHA256: `a3ad034ca0bf178c59fea9238e00f11fb9271487379e371440848bd3f6053a8c`.
- Trial build (capture code plus the query): 4,456 bytes in the consumed DSP
  source span, as in experiment 16; globals: 8 bytes; packed spare: 15,042
  bytes with the stock decoder.
- Patches: two startup sites, ring capacity (223,104 frames), the Editor query
  at `0x800301f0`, and the DSP tap and commit. Recorder admission, the stop
  setter, the five Main receive calls and all SD paths remain stock.
- Builder: `tools/firmware/build_simple_trial.py`. Offline checks:
  `tests/emulation/verify_simple_trial.py` (7 groups).

## Procedure

1. Confirm the mixer is idle with its card inside. Stage and read back only this
   image, settings and basic metadata, then eject normally and leave transfer mode.
2. Run the usual PLAY/STOP-held update, wait for rapid green, then reboot normally
   with the card inside and leave the mixer idle.
3. Take two idle samples, one second apart:
   `python tools/device/l6_simple_probe.py --output NEW_LOG --manifest deployment/19_simple_tap/manifest.json`.
   Expected: startup 4, epoch 1, 46–50 frames per tick, worker idle, no take,
   correct code/global bounds, both caches enabled.
4. Check original pad replies and automated one-shot playback at the existing
   levels, then sample again without `--manifest` and note the epoch.
5. Make a short ordinary recording. Sample during it and after stopping, and
   check the take's seven WAV headers. Note any epoch change at start or stop.

Frames advance only with the normal 48-kHz callback `0x2022a791`. A stalled
count in a mode that selects another callback is a finding, not a fault.
New on hardware: hooks in the audio path (their stack cost on the audio task is
unmeasured), the tap writing all eight lane tails in every mode, and the stock
decoder writing 4,456 bytes of code over its own consumed input.

An epoch change during recording is a design result, not a firmware fault: it
would mean the stock recorder restarts the audio ring, and capture start would
need to follow it. Missing startup, a stalled frame count or changed heap during
idle is a failed trial. Restore stock with
`deployment/01_usb_marker/stock_control/L6.BIN` if anything looks wrong.
