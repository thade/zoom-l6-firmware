# Take chain: pads 1–4 hold the last four takes

Experiment 24 made pad 1 play the last take's stock master in place. This
trial keeps a chain across all four pads: after each ordinary take, pad 1 plays
the newest take, pad 2 the one before, and so on to pad 4. The oldest take
drops off pad 4; its files stay on the card.

**Prepared locally; not staged or installed.** The mixer runs experiment 24.
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

## How the chain moves

The stock saved pad paths are the only record, so the chain survives reboots
without any state of its own. After each verified take, Main reads the four
saved paths and:

- builds the new chain: the new take's `MASTER.WAV`, then the take masters
  saved on pads 1–4 in pad order, skipping hand-picked or empty pads and
  repeats, cut to four;
- assigns it from pad 1 on; pads past its end keep their sound, and a pad
  already holding its entry is not reassigned.

So no take repeats or is lost, and a sound you picked by hand is replaced when
a take reaches its pad. Example: pads [hand-picked, T2, T1, T0] plus a new
take T4 become [T4, T2, T1, T0]. From the current pads (pad 1 a take, pads 2
and 3 hand-picked, pad 4 empty), the first take reaches pad 2, the second pad
3 and the third pad 4.

Every pad's format is checked before any assignment is queued, so either the
whole shift happens or none of it does. Assignments are queued oldest first,
so a shift cut short (power loss mid-way) repeats a take rather than losing
one. While an earlier assignment is still loading (its path not yet saved),
the shift waits for it. Pads being reassigned are stopped first if they are
playing; a pad whose sound does not change keeps playing. Recording to any pad
(a pad record target) skips the handoff. Each take saves the settings file up
to four times, once per completed assignment.

Each of `A:\SOUND_PAD\PAD1`–`PAD4` needs the anchor `MASTER.WAV`: stock reload
keeps a pad's path only while its folder lists that name. Staging adds the
three new ones. The chain ends at the first pad without an anchor, so with
only PAD1's it behaves as experiment 24. Carried takes are not re-checked: a
deleted take folder keeps moving along as a dead path until it drops off. As
in experiment 24, every pad's name shows `MASTER.WAV`.

The state (about 1.8 KB) now lives in one native-heap allocation made at
startup, instead of the reused globals interval.

## What it answers

- Do four queued assignments per take all load, with the settings saved?
- Does the chain move correctly over several takes and survive a reboot and a
  File Transfer Mode cycle?
- Can several pads play masters from `A:\RECORDER` while a take records?

## Image

- Local image: `deployment/25_take_chain/trial_take_chain/L6.BIN`; anchor
  `deployment/25_take_chain/anchor/MASTER.WAV` (the same file as experiment 24's).
- SHA256 and sizes: in `deployment/25_take_chain/manifest.json`. 4,540 bytes
  of code, 16 bytes of globals; the same ten patch sites as experiment 24.
- Builder: `tools/firmware/build_master_trial.py chain` (`reference` rebuilds
  experiment 24 from its pinned sources). Offline checks:
  `tests/emulation/verify_master_ref.py` (15 groups) and
  `tests/emulation/verify_master_trial.py` (6 groups, exact image, including
  experiment 24's image rebuilt byte for byte).

## Status query

`tools/device/l6_padref_probe.py`, schema 2: as experiment 24, plus the chain
mask (pads the last handoff assigned) and each pad's saved path as the stock
loader left it: the take folder name, or `#` and the file name for a sound that
is not a take. `--before-take` checks the shift itself.

## Procedure

Staging uses `deployment/25_take_chain/stage25.py` with the MIDI transfer tool.

1. Idle samples with `--session --manifest deployment/25_take_chain/manifest.json`.
2. Record four takes of 15–30 seconds, each with a before sample, then an after
   sample with `--before-take` about five seconds after stopping. Start one
   take straight after the previous stop, to load the card while assignments
   and settings saves land. Play pads 1–4 after the fourth: newest to oldest.
3. Record a fifth take with pads playing: the first take drops off pad 4.
4. Reboot, then cycle File Transfer Mode (`stage25.py settings` reads the four
   saved paths): the chain is unchanged.

Stock recordings must stay intact. Restore stock with
`deployment/01_usb_marker/stock_control/L6.BIN` if anything looks wrong.
