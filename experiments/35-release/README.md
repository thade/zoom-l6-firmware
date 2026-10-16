# Chain switch: the take chain gets an on/off switch

[Experiment 34](../34-release/README.md) plus a panel switch for the take
chain: hold **PAN** + **LEVEL** for 1.5 s to turn it on or off. Everyday
build: no status query and no stack measurement.

**Installed 16 October 2026; passed.** Superseded by
[experiment 36](../36-release/README.md), which makes the holds tolerate a
misread key (0.1.0 is [experiment 38](../38-release/README.md)). Recovery from
an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

## Results

Installed over experiment 34 with `tools/device/install_release.py` (image
read back identical; the previous image and settings file backed up). The
user ran the procedure below, partly out of order, and confirmed every check:

| Check | Result |
|---|---|
| A take with the chain never switched | Stayed off pad 1: off by default |
| Hold PAN + LEVEL, then a take | Blinked (on); the take reached pad 1 |
| Power-cycle, then a take | Still on; the take reached pad 1 |
| Hold PAN + LEVEL, then a take | Steady (off); pad 1 kept the previous take |
| Both holds while recording | No light change: refused |
| AUX 1 + AUX 2 after recording | Steady (mono), then blinking (stereo) |

Every take recorded, with the chain on or off, has a version 2 `HISTORY.TXT`
and no temp file left. The user found the PAN + LEVEL hold unreliable at
first and could not reproduce it later (probably released too early); a
possible cause, a single poll misreading one button, which would restart the
hold, is recorded in [future work](../../docs/future-work.md). Playback of a
take sounding quieter than while recording is stock: the recorded master is
taken after the MASTER knob and played back through it again (manual,
signal flow), so overdub with MASTER and SOUND PAD at their unity marks.
Evidence stays in `deployment/35_release/`.

| | Experiment 34 | Experiment 35 |
|---|---|---|
| Patch sites | 15 | 15 |
| Code | 8,820 bytes | 9,144 bytes |
| Image SHA256 | `47d9f90d…` | `824e37c69c2086b4c4464b14ab5b698c32d154352b0aa1537095fd6cb5134932` |

## Behaviour

- **Off by default.** A new install, or a mixer that never switched, keeps
  the stock pads: takes do not move onto them. Hold PAN + LEVEL once to turn
  the chain on. A mixer updated from an earlier experiment also starts off.
- **Off** leaves the pads exactly as they are; assign them as usual. Every
  take still gets its `HISTORY.TXT` (listing the pad sounds it included).
- **On** works as before: after each ordinary take the chain moves along
  pads 1–4.
- **The hold**: PAN and LEVEL together for 1.5 s, once per hold. Both lights
  blink for 2 s when the chain turns on and light steadily when it turns off,
  then the normal view returns (the hold also selects the view of the button
  pressed second, as stock does for any view press). Ignored for 10 s after
  power-on; refused, with no light change, while any recording runs or
  finalizes.
- **Remembered through power cycles**: two spare global settings bytes
  (`CONFIG+0x30f/0x310`, `C3 3C` = on), saved to internal flash at once with
  the stock settings save, like the AUX mode. A factory reset leaves them.

Removing the anchor files still stops the chain as before (it stops at the
first pad without one).

## How it works

- `src/capture/master/panel.c` now holds both two-button holds (PAN + LEVEL
  and AUX 1 + AUX 2) and their LED confirmation; the AUX switch behaves as in
  experiment 34. The redraw after a show now redraws all nine select LEDs
  from the view, as a stock view press does.
- Main's handoff skips a take while the chain is off (handoff result 6); the
  take check and history are unchanged.
- PAN and LEVEL are view buttons: stock only changes the view for them, has
  no long press on them, combines no keys, and saves nothing for a view
  change ([panel keys findings](../../docs/research/panel_keys_findings.txt)).

## Build and checks

- Rebuilt by `tools/firmware/build_master_trial.py chain_switch` (pinned to
  e258bd6). Its checks at the time, through `tools/firmware/verify_release.py`:
  `verify_master_everyday.py` (exact image; experiments 26–34 rebuilt),
  `verify_master_ref_everyday.py` (26 groups on the release link, including
  the chain switch: off keeps takes off the pads with histories written, a
  never-switched mixer is off, refusal while recording, the save, the LEDs
  and the hold detector) and `verify_stereo_aux_hooks_everyday.py` (5; the
  settings save carries both mode pairs).

## Procedure

Install with `tools/device/install_release.py`. After the update:

1. Record a short take: it must **not** reach pad 1 (the chain starts off).
2. Hold PAN + LEVEL: both lights blink for 2 s (on). Record a take with pad 1
   playing: it reaches pad 1.
3. Power-cycle: the chain is still on (record a take; it reaches pad 1).
4. Hold PAN + LEVEL: steady (off). Record a take: pad 1 unchanged; its
   folder still gets `HISTORY.TXT`.
5. Hold PAN + LEVEL while recording: no light change. AUX 1 + AUX 2 still
   switches as before.
