# AUX mono/stereo switch: hold AUX 1 + AUX 2

[Experiment 30](../30-stereo-aux/README.md)'s stereo AUX pair, now switchable
between the stock two mono sends and the stereo pair by holding the **AUX 1**
and **AUX 2** buttons together for 1.5 seconds. The choice is kept in the
mixer's internal settings and survives power-off.

**Prepared locally; not staged or installed.** A trial build with the status
query. The mixer runs experiment 30.

## Behaviour

- **Mono** (the stock behaviour): AUX 1 and AUX 2 are two independent sends,
  exactly as stock.
- **Stereo**: as experiment 30 (AUX 1 left, AUX 2 right, AUX 1's send amount
  and pre/post, channel pan).
- **Switching**: hold AUX 1 and AUX 2 together; after 1.5 s the mode toggles
  once (keep holding: nothing more; release and hold again to toggle back).
  All AUX gains move to the new mode through the stock 16 ms ramps. AUX 2
  settings changed while in stereo apply when back in mono. Refused while a
  take records or is finalizing.
- **Feedback**: for 2 seconds both AUX LEDs blink (now stereo) or light
  steadily (now mono), a pattern the stock view indication (one steady select
  LED) never shows; then the normal view indication returns. A refused toggle
  shows nothing. Stock treats the hold as a tap of AUX 2 (it shows the AUX 2
  view); AUX + MUTE still mutes a send.
- Holds in the first 10 seconds after power-on are ignored (Main may still be
  starting up), and a hold restarts if the worker was stalled for over 100 ms
  (a release could have been missed).
- **Starting state**: the mode is read from the internal settings at power-on.
  A mixer that has never been switched starts in **mono**: after installing,
  hold AUX 1 + AUX 2 once to get stereo.
- A factory reset leaves the mode as it was.

## How it works

- The mode is two bytes in the mixer's global settings that stock code never
  uses, checks or stores in scenes (`CONFIG+0x30d/0x30e`, `A5 5A` = stereo;
  anything else, including the never-written zero, is mono). Switching asks
  for the stock settings save, which writes them to internal flash with the
  other globals; the stock flash save is power-cut safe (the old settings stay
  valid until the new ones are complete).
- The worker reads the two buttons' live state (stock key read `0x80008478`,
  bits 4/5 of the second key word) every poll; a 1.5 s hold posts a private
  event to Main. Main's receive hook toggles the mode bytes, runs the stock
  bulk recompute (`0x8000c648`, as a scene recall does), requests the save
  (`0x80006ab8`) and sets both AUX select LEDs (level and mode under one lock);
  2 s later the worker asks Main to redraw them from the current view.
- A gain request blocked on another task while the mode flips can land after
  the recompute and leave one AUX row stale until that control is next
  touched (rare; accepted).
- In mono the stereo filter passes every gain change through unchanged, so the
  AUX rows match stock bit for bit.

## Image

- Local image: `deployment/32_aux_switch/trial_aux_switch/L6.BIN`; SHA256 and
  sizes in `deployment/32_aux_switch/manifest.json`. 16 patch sites (no new
  ones: the switch uses the worker and Main hooks), about 9.7 KB of code.
- Builder: `tools/firmware/build_master_trial.py switch`. Offline checks:
  `tests/emulation/verify_stereo_aux_hooks.py` (5 groups; the switch group:
  mono equals stock bit for bit, toggling both ways with the save and LEDs,
  the LED redraw, AUX 2 edits kept, refusal while recording or finalizing, the
  real key read, the hold timing, arming and stall restart, Main's routing of
  the event, and the stock save carrying the mode bytes),
  `verify_master_trial.py` (6, exact image).

## Status query

`l6_padref_probe.py` schema 5 adds the mode bytes (`aux_stereo`), the number
of toggles and of refusals.

## Procedure

Staging uses `deployment/32_aux_switch/stage32.py`. After the update (AUX 1,
AUX 2 and level at their unity marks on input 5, balance centre):

1. Tone test: mono (both jacks carry the same sum, as the stock baseline).
2. Hold AUX 1 + AUX 2 for 1.5 s: both AUX LEDs blink for 2 s; tone test:
   stereo.
3. Hold again: both AUX LEDs light steadily for 2 s; mono again. Turn AUX 2 down and back while in
   stereo, then check mono uses AUX 2's setting.
4. Switch to stereo, power-cycle: still stereo. Start a take and try to
   switch while recording: refused.
