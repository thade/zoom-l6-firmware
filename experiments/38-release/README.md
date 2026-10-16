# Release 0.1.0: the chain switch moves to EFX + PAN

[Experiment 36](../36-release/README.md) with two changes found by the
diagnostic build ([experiment 37](../37-panel-diag/README.md)). Everyday
build. This is release 0.1.0.

**Prepared locally; not yet installed.** The mixer runs experiment 37.
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

| | Experiment 36 | 0.1.0 (experiment 38) |
|---|---|---|
| Patch sites | 15 | 15 |
| Code | 9,172 bytes | 9,236 bytes |

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

## Procedure

Install with `tools/device/install_release.py`. After the update: about 4 s
after power-on, hold EFX + PAN ten times (blink on, steady off), with some
quick and uneven presses, and AUX 1 + AUX 2 a few times; a hold while
recording still does nothing.
