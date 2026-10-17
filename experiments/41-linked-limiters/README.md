# Linked AUX output limiters

[Release 0.2.0](../40-release/README.md) with the two AUX output limiters
linked in stereo: each detector reads the louder of the two sides, so both
sides get the same gain and the image holds while one side limits, as the
master pair's limiter already does. Candidate for the next release.

**Installed 17 October 2026; passed on the jacks.**

## Results

Setup as in experiment 30: the computer plays tones into input 5 over USB
(AUX 1 send and level at maximum, balance centre), and an Elektron Syntakt
records AUX 1 and AUX 2. `tools/device/l6_aux_limiter_test.py` plays 1 kHz
in one-second bursts on the left and a steady 1.5 kHz at −40 dBFS on the
right, which reaches the interface at −28.1 dBFS and never limits on its
own, then reads each tone's level per 50 ms window (Hann-windowed band RMS
in dBFS at the interface). The same runs were made on 0.2.0 as a control,
reinstalled between the two sets with nothing else touched.

| Left bursts (dBFS in) | 41: right while left on | 41: turned down by | 0.2.0: right while left on |
|---|---|---|---|
| −14 | −28.1 | 0 | |
| −10 | −28.1 | 0 | −28.1 |
| −8 | −30.1 | 2.0 | |
| −6 | −32.1 | 4.0 (three runs) | −28.1 |
| −4 | −34.1 | 6.0 | |
| −2 | −36.1 | 8.0 (two runs) | −28.1 |

- On 0.2.0 the right side never moves. On 41, below the threshold (about
  −10 dBFS in, where the left jack reaches the interface's full scale) it
  is untouched, and above it it is turned down one dB for every dB the left
  goes further over: the two sides share one gain, as the master pair does.
- The attack is within one 50 ms window; the release lets the right climb
  back about 1 dB per 50 ms after a burst, so at −2 dBFS it has not fully
  settled half a second later and the tool's own on/off figure reads 7.6 dB
  (the table measures against the untouched level).
- The left jack reads at the interface's full scale once limiting, so the
  left side's own reduction is read from the right side's dip.
- Mono (both builds, same signal): AUX 2 silent (its send down), AUX 1
  carries both tones and limits as one channel; 41 and 0.2.0 agree within
  0.6 dB on every reading. The standard stereo tones (left 1 kHz on AUX 1
  only, right 1.5 kHz on AUX 2 only, −31.5 and −31.4 dBFS, the same tone on
  both sides with zero delay and correlation 1.0) are the same on both.
- The AUX 1 + AUX 2 hold switched mono and stereo both ways; the EFX + PAN
  hold switched the chain on; a take went to pad 1 and its folder holds
  `HISTORY.TXT` (`END 0`) with the seven stock files.

Not measured: the left side's gain reduction directly (the interface
clips there). Evidence stays in `deployment/41_linked/` (recordings,
`limiter-results.json`, the 0.2.0 control under `control-0.2.0/`).

## Changes from 0.2.0

- Two call sites in the copied audio code (0x20227c6a and 0x20227eee): each
  AUX limiter's per-sample detector (load the sample, take its absolute
  value, compare with the envelope) calls a routine of ours instead. In
  stereo, with the worker running, AUX 1's routine takes the louder of the
  two sides and keeps it in a 64-float buffer; AUX 2's reads it back,
  because AUX 1's block has already written its output over its own
  samples. In mono, or without the worker, each routine does what stock did.
- The release recipe gains `span.dsp_edits` (format 2) for the 24 changed
  bytes, and the browser patcher applies them. A recipe without edits stays
  format 1, so the 0.2.0 recipe is unchanged.
- 136 more bytes of code and 256 of globals.

| | 0.2.0 (experiment 40) | 41 |
|---|---|---|
| Patch sites | 15 | 15, plus 2 in the DSP code |
| Code | 11,004 bytes | 11,140 bytes |
| Image SHA256 | `0c72755e…` | `34df789bc9eabf0b6060a12700cbd889d39ef4b8833f2c34db05b3bf72f3e90b` |

Build: `python tools/firmware/build_master_trial.py linked`.

## Checks

- `tests/emulation/verify_aux_limiter.py`: the plan changes only the two
  sites; stock limiters are independent and delay by 48 samples; patched,
  in stereo, both sides' gains equal the series stock computes for the
  louder side, bit for bit, and each output is its own delayed sample times
  that gain; in mono or without the worker everything is as stock,
  registers included; the recipe carries the edits and rebuilds the image.
- `tests/emulation/verify_patcher.py`: the browser patcher's JavaScript
  rebuilds a recipe with the two edits.
- `tools/firmware/verify_release.py` still passes for 0.2.0.

## Procedure (on the mixer)

The experiment 30 setup: USB tones into input 5, both AUX jacks recorded by
a two-input interface, stereo mode.

1. `tools/device/l6_aux_limiter_test.py` at left levels from −14 to −2 dBFS,
   on this build and on 0.2.0 as a control.
2. The standard tone test (`l6_aux_tone_test.py`) in stereo and in mono, on
   both builds.
3. The AUX 1 + AUX 2 hold both ways, the EFX + PAN hold, a take onto pad 1,
   its `HISTORY.TXT` read from the card.
All done on 17 October 2026.
