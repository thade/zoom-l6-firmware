# Stereo AUX send: AUX 1 left, AUX 2 right

The take chain and take history ([experiment 28](../28-take-history/README.md))
plus an always-on stereo AUX pair, as agreed in
[future work](../../docs/future-work.md#optional-stereo-aux-send): an
independent stereo send mix on the two AUX jacks, for a stereo external effect
or a separate stereo monitor mix.

**Prepared locally; not staged or installed.** A trial build with the status
query. The mixer runs experiment 29.

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
