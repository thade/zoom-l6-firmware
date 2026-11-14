# Release 0.3.1: holds that keep working after weeks of power

[Release 0.3.0](../41-linked-limiters/README.md) with one fix to the
two-button holds. Everyday build.

**Built 15 November 2026; not yet installed.** The image is built from the
current sources and its hash can change until the release checks pin it
(`tools/firmware/build_master_trial.py release`):

```text
39273f1dc1b190fed18f29d7a0500906bd437161e331257f711b02d250a3fa4a  L6.BIN
```

## The fault

On a mixer left on for a few weeks with 0.3.0, holding AUX 1 + AUX 2 gave
neither blink pattern. Restarting the mixer brought the hold back. This was
seen on 15 November 2026.

The holds are armed 1 s after Main first receives an event. The worker
checked that on every poll with a signed difference between the 1 ms tick
and the tick Main first received at. After 2^31 ms, which is 24.9 days, the
difference reads as negative, so the worker treated the holds as not yet
armed. EFX + PAN uses the same check and stopped with it. The difference
turns positive again at 49.7 days, when the tick wraps. 0.1.0 and 0.2.0 have
the same check.

## Change from 0.3.0

The worker latches the armed state the first time the check passes
(`panel.c`). The code is 4 bytes shorter and uses one more word of globals.
Nothing else in the image's sources changed.

## Checks

- `tests/emulation/verify_long_uptime.py` (7 groups, new): the holds, the
  LED show, the arming and the pad folder settle time run on fresh rigs at
  six ages of the mixer, including across 2^31 ms and the tick wrap. The
  worker's poll count, the take serial and the played generation are run
  across their wraps. Breaking each of eight timing expressions in turn made
  the suite fail, the old arming check among them.
- `tools/firmware/verify_release.py`: the exact image (sites, boot, every
  earlier installed image rebuilt, 0.3.0 from its tag), the take chain,
  history and anchor groups, the stereo AUX and switch groups, the long
  uptime groups and the patcher.
- `tests/emulation/verify_aux_limiter.py`, `verify_bootloader.py` and
  `verify_stack_diag.py` pass on the new sources.

All of this is emulation. The tick is a value the tests write, and nothing
ran for days. Zoom's own use of the tick was not examined.

## Procedure (release checks)

1. Install over 0.3.0 with `install_release.py --any-image`.
2. After start-up, AUX 1 + AUX 2 and EFX + PAN each toggle after a 1.5 s
   hold and show their LEDs for 2 s. The chain and stereo settings from 0.3.0
   are kept.
3. A take reaches pad 1 with the chain on.
4. Leave the mixer on for 25 days or more, then repeat step 2.

Step 4 is the only check of the fix on a mixer. Steps 1 to 3 show that the
new image behaves as 0.3.0 does.
