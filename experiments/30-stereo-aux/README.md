# Stereo AUX send: AUX 1 left, AUX 2 right

The take chain and take history ([experiment 28](../28-take-history/README.md))
plus an always-on stereo AUX pair, as agreed in
[future work](../../docs/future-work.md#optional-stereo-aux-send): an
independent stereo send mix on the two AUX jacks, for a stereo external effect
or a separate stereo monitor mix.

**Installed 15 October 2026; passed on the jacks.** A trial build with the
status query.

## Results

Test setup: the computer played test signals into the L6 over USB, which
reaches input 5 (a stereo channel; AUX 1, AUX 2 and level at their unity
marks, a combined send gain of 0.342), while a two-input interface (an
Elektron Syntakt) recorded AUX 1 and AUX 2
(`tools/device/l6_aux_tone_test.py`: left 1 kHz, right 1.5 kHz, or 1 kHz on
both). Tone levels are band RMS in dBFS at the interface, input at −20 dBFS.

| Condition | AUX 1 | AUX 2 | Status gains (lanes 6/7) |
|---|---|---|---|
| Stock (experiment 29), stereo tones | both tones (mono sum) | both tones, equal | |
| Balance centre, stereo tones | 1 kHz −30.4 | 1.5 kHz −30.1 | AUX1 0.342/0, AUX2 0/0.342 |
| Balance centre, 1 kHz on both | −30.6 | −30.6 (0 delay, correlation 1.0) | |
| Balance fully left | 1 kHz −30.3 | silent (−120) | AUX2 0/0 |
| Balance fully right | silent (−122) | 1.5 kHz −30.0 | AUX1 0/0 |
| AUX 2 send fully down | −30.4 | −30.1 | unchanged |
| After a cold reboot | −30.3 | −30.0 | unchanged |

- Left and right reach their own jacks with the stock path's gain; the jacks
  match within 0.3 dB with no delay between them; output is linear (20 dB less
  input gave 20 dB less output).
- With the firmware's cross gains exactly zero, the other side still appears
  36–52 dB down, varying between runs: electrical crosstalk in the outputs,
  cables or interface. A by-product of the 1 kHz tone near 1.5 kHz, present
  on both jacks even in the mono test, comes from the USB playback path.
- Balance on a stereo channel turns the opposite side down (it does not move
  it across), exactly as in the main mix.
- With input 5's send and level at maximum the path gain is about +29 dB and
  test signals above about −45 dBFS drove the AUX outputs into their stock
  limiters; at the unity marks nothing limited.
- Not exercised on the jacks: a mono channel's pan (no USB route to the mono
  inputs here; covered by emulation), scene recall and Editor changes.

Evidence stays in `deployment/30_stereo_aux/`.

## Behaviour

- AUX 1 carries left and AUX 2 right, always (a mono/stereo switch can follow).
- Each channel's **AUX 1** send amount and pre/post choice set its level in the
  pair; with post, channel level and mute apply as before.
- Placement follows the channel's own pan (mono channels) or balance (stereo
  channels), so the send image matches the main mix. A stereo channel keeps its
  left and right separate.
- The **AUX 2** knob and pre/post choice do nothing while stereo; their stored
  settings are kept.
- Input channels only: sound pads and internal effects are not in the stock
  AUX sends and are not added.

Levels differ from the stock mono sends by the pan law: a hard-panned mono
channel is 3 dB louder on its side, and a centred stereo channel is up to 6 dB
lower per side for material common to both sides (it is no longer summed into
each send). The two AUX outputs keep their stock protection limiters, which
act per side: a strong overload on one side can shift the image while it
limits.

## How it works

Stock code computes each lane's AUX 1 gain and hands every gain change to one
ramp request (`0x80010398`), which smooths it over 16 ms. A filter there turns
an AUX 1 request for lane *j* into two: AUX 1 = gain × the lane's left pan
factor, AUX 2 = gain × its right factor (the mixer's own factors), using the
stock ramps for both. AUX 2 requests are dropped. The mono-pan and balance
controls, which stock updates only in the main mix, also refresh the pair.
The Editor's mixer reset modes 1 and 2 store the gain rows directly, so their
veneers are replaced to run the stock bulk recompute afterwards. This covers
send level, pre/post, channel level, mute, scene recall, startup restore,
Editor resets and MIDI/Editor changes. The mixer's sample loops are unchanged.
Stereo is an explicit build option (`build(stereo=True)`); other builds stay
two mono sends.

## Image

- Local image: `deployment/30_stereo_aux/trial_stereo_aux/L6.BIN`; SHA256 and
  sizes in `deployment/30_stereo_aux/manifest.json`. 16 patch sites (five
  for the stereo pair), 8,960 bytes of code. The status query's stack frame
  on Main grows from 484 to 568 bytes for the larger reply.
- Builder: `tools/firmware/build_master_trial.py stereo`. Offline checks:
  `tests/emulation/verify_stereo_aux_hooks.py` (4 groups: stock paths, the real
  ramp task moving a pair, the hooks on every path including startup and the
  Editor resets, the main mix unchanged),
  `verify_master_ref.py` (24) and `verify_master_trial.py` (6, exact image).

## Status query and measurement

`l6_padref_probe.py` schema 4 adds the live AUX 1 and AUX 2 gain rows.
`tools/device/l6_aux_measure.py` records both jacks through a two-input
interface (AUX 1 to input 1, AUX 2 to input 2) and reports each side's level,
the balance, correlation and delay.

## Procedure

Staging uses `deployment/30_stereo_aux/stage30.py`. After the update:

1. A mono source on channel 1, its AUX 1 send up, other sends down. Pan
   centre: equal levels, delay 0. Hard left: AUX 2 silent. Hard right: AUX 1
   silent.
2. A stereo source with different left and right on a stereo channel, balance
   centre: AUX 1 carries its left, AUX 2 its right.
3. Main outputs unchanged; turning AUX 2 knobs changes nothing.
4. Reboot: the pair is still stereo (startup restore).
