# Release 0.1.0: the chain switch moves to EFX + PAN

[Experiment 36](../36-release/README.md) with two changes found by the
diagnostic build ([experiment 37](../37-panel-diag/README.md)). Everyday
build.

**Installed 16 October 2026; passed. This is release 0.1.0.** Recovery from
an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked). (Shown on
16 October: experiment 18 passed.)

## Results

Installed over experiment 37 with `tools/device/install_release.py` (image
read back identical; the previous image and settings file backed up). The
user held EFX + PAN about ten times after power-on, including quick and
uneven presses: **every hold worked** (experiment 37 had 6 of about 10 PAN +
LEVEL holds fail). Not reported on this image: AUX 1 + AUX 2, a hold while
recording, a take reaching pad 1 (unchanged since experiments 35–36).
Evidence stays in `deployment/38_release/`.

| | Experiment 36 | 0.1.0 (experiment 38) |
|---|---|---|
| Patch sites | 15 | 15 |
| Code | 9,172 bytes | 9,236 bytes |
| Image SHA256 | `c796f4e6…` | `99ded4b1fcefa1d968a7317e5df4ee65c670018c4a495cfc1ed903aa5aa70bb0` |

## Changes

- **Hold EFX + PAN** (keys 18 and 19) to turn the take chain on or off; the
  EFX and PAN lights blink (on) or light steadily (off) for 2 s. PAN + LEVEL
  often lost PAN on the panel; EFX and PAN are in the same panel key group as
  the always-reliable AUX 1 + AUX 2. While EFX is held, stock shows the
  effect-send mutes on the MUTE lights (a MUTE press would mute an effect
  send), as for any EFX hold.
- **Armed sooner.** The switches arm 1 s after Main first returns from a
  receive (measured at 2.99 s after start-up), about 4 s after power-on,
  instead of a fixed 10 s; the arming no longer depends on the tick counter's
  value, so the 49.7-day wrap no longer disables holds.

The chain setting (`CONFIG+0x30f/0x310`) is unchanged, so the chain stays on
or off as last set.

## Build and checks

- `tools/firmware/build_release.py` writes `release/0.1.0/`;
  `tools/firmware/verify_release.py` checks it from a fresh clone
  (experiments 26–37 rebuilt; the hold detector groups now cover the EFX +
  PAN pair and the arming after Main's first receive).
- Since the hardware run, `verify_stereo_aux_hooks.py` also drives the
  switches the way the panel does: each key change is a panel message (0x91
  press, 0x90 release) through the stock parser `0x800393d0` into the key bits
  the real key read returns, with the panel's measured behaviour (a press at
  the same bit of another key group is lost while a key is held). Every pair
  in `panel.c` must be within one key group (a static guard that would have
  rejected PAN + LEVEL), and both pairs toggle once per hold for either press
  order and staggers up to 400 ms; the model reproduces experiment 37 (PAN
  reads up while LEVEL is held).

## Procedure

Install with `tools/device/install_release.py`. After the update: about 4 s
after power-on, hold EFX + PAN ten times (blink on, steady off), with some
quick and uneven presses, and AUX 1 + AUX 2 a few times; a hold while
recording still does nothing.
