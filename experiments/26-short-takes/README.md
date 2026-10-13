# Take chain: ignore takes under 2 seconds

Experiment 25's chain worked, but an accidental quick start and stop of the
recorder (0.25 s) took a pad like any real take. This trial leaves takes
shorter than 2 seconds off the pads; they are recorded normally.

**Installed 13 October 2026; passed.**

## Results

| Take | Result | Pads afterwards |
|---|---|---|
| about 1 s | refused (`refused` 1, no handoff) | unchanged (user check) |
| about 5.8 s (`261013_182040`) | assigned on the first post, all four pads | `182040`, `165450`, `165447`, `165438`; `165012` dropped off |

Only the latest status code is kept, so `short` itself was not read back; the
one refusal with the pads untouched is consistent with it. Worker stack
2,356 bytes; minimum free heap 152,848 bytes. Evidence stays in
`deployment/26_short_takes/`.

## Change

The worker already reads each master's header. It now also computes the
take's length from the data size and the frame size in the `fmt` chunk, and
refuses a take under 96,000 frames (2 s at 48 kHz) with status `short`. The
chain and pads are left as they were. Exactly 2 s is accepted. Everything
else is experiment 25.

## Image

- Local image: `deployment/26_short_takes/trial_short_takes/L6.BIN`; SHA256
  and sizes in `deployment/26_short_takes/manifest.json`. 4,548 bytes of code.
- Builder: `tools/firmware/build_master_trial.py minimum`. Offline checks:
  `tests/emulation/verify_master_ref.py` (15 groups; short takes in 32-bit
  float and 16-bit, and the exact 2 s boundary) and
  `tests/emulation/verify_master_trial.py` (6 groups, exact image; the
  experiment 24 and 25 images rebuild byte for byte).

## Procedure

Staging uses `deployment/26_short_takes/stage26.py` (the anchors are already
on the card). After the update and reboot: idle samples, then

1. a take of about 1 second: status `short`, pads unchanged;
2. a normal take: assigned, the chain moves one pad along.
