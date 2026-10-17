# Future work

Open work after 0.2.0. Items are ideas or agreed requirements, not
implemented features; check one off only with a linked implementation or
hardware result. An emulator result does not complete a hardware item.

## Release follow-ups

- [ ] Test on the mixer: scene saves and recalls in stereo, MIDI and Editor
      send changes in stereo, a mono channel's pan in stereo, and the AUX
      switch in the setting and test modes (all covered in emulation only).
- [ ] Power loss right after stopping a take, while its history is written.
- [ ] Rapid back-to-back takes: queue a second stopped take instead of
      dropping one when the history of the first is still being written.
- [ ] Measure the hooks' stack use on the stock recorder and Main tasks (only
      the worker's has been measured).
- [ ] While the firmware writes a pad folder's `MASTER.WAV` (about a dozen
      file calls in one worker step), the switch-hold detector does not poll,
      so on a slow card a hold in progress may restart. Only when an anchor
      is created; could write one chunk per step
      ([experiment 40](../experiments/40-release/README.md)).
- [x] The PAN + LEVEL hold was unreliable on the mixer. Experiment 36 made
      the holds tolerate a misread poll; the diagnostic build (experiment 37)
      then showed the panel often never reports PAN while LEVEL is held (they
      are in different key groups), so experiment 38 uses EFX + PAN, in the
      same group as the reliable AUX 1 + AUX 2.
- [x] Small code tidy-ups for the next image: the switch arming compares
      signed; inherited version 1 history lines are taken newest first; one
      shared header for stock addresses (`stock.h`) and `panel_recording`
      next to `recorder_busy` (0.2.0, [experiment 40](../experiments/40-release/README.md)).
- [x] 0.2.0: recovery from an image that hangs before start-up completes:
      the bootloader read and emulated from a full flash backup
      ([experiment 39](../experiments/39-flash-diag/README.md),
      [bootloader findings](research/bootloader_findings.txt)), then
      [experiment 18](../experiments/18-recovery-hang/README.md) passed on
      the mixer. The README and the patcher say so.
- [x] 0.2.0: the firmware writes the pad folders' `MASTER.WAV` anchors itself
      (experiment 39), so installing needs only `L6.BIN`
      ([experiment 40](../experiments/40-release/README.md), passed on the
      mixer); the installer, README and setup no longer copy the anchor.

## Browser patcher

Done: the [patcher page](https://thade.github.io/zoom-l6-firmware/) makes
the release from Zoom's file and, in Chrome or Edge, sends it to the mixer
([patcher/](../patcher/README.md), [experiment 40](../experiments/40-release/README.md)).

- [ ] Send to the mixer on Windows (Chrome or Edge): the L6's MIDI port names
      there, and whether the folder picker accepts the card's top folder
      (a drive root). Only Chrome on macOS has been tried.
- [ ] The download route in Safari and Firefox, end to end on a real card.
- [ ] At each release, keep the previous recipe in `patcher/recipes/` so
      `?version=` can rebuild the exact image someone installed.

## Four-pad take history

Done: pads 1–4 hold the four newest takes, newest first, independent of which
take was used as backing ([experiment 25](../experiments/25-take-chain/README.md)).

- [ ] Selecting an older backing, undo, redo and starting a new song: today
      the user picks any pad, and the chain always shows the newest four.

## Normal and overdub modes

Done: hold EFX + PAN to turn the chain on or off, remembered through power
cycles, off until first switched on; off leaves the pads as they are
([experiments 35](../experiments/35-release/README.md) and
[38](../experiments/38-release/README.md)).

- [ ] Optional: separate normal and overdub pad banks, so switching off
      restores the sounds you had before the chain took over (both banks
      saved in a card file, swapped only when the recorder is stopped).

## Take links and recording history

Done: `HISTORY.TXT` in every take folder
([format](history-format.md), [experiment 28](../experiments/28-take-history/README.md)).
The original design record is in [archive/history-design.md](archive/history-design.md).

- [ ] A stem-collecting script: walk the histories back from a take and
      gather every recording folder, reporting missing ones.
- [ ] DAW export: choose the first DAW, and whether it gets aligned stems,
      the heard mix or both. Timing (backing started midway, looped, stopped
      early) is not recorded and would need its own extension.

## Browser configurator

**Confirmed requirement:** a web-based configurator to replace Zoom's editor.

- [ ] Agree supported computers and browsers and the editor functions needed.
- [x] Test whether browser MIDI with SysEx permission reaches the L6's
      endpoints: it does (the patcher's send-to-mixer, Chrome on macOS,
      experiment 40). Windows is untested.
- [ ] Connection and read-only settings first, then verified settings
      changes and pad configuration, then this firmware's features (AUX mode,
      chain on/off).

The [device helpers](../tools/device/) and the
[editor findings](research/editor_findings.txt) are starting points.

## Optional stereo AUX send

Done: a global mono/stereo mode switched by holding AUX 1 + AUX 2, AUX 1 left
and AUX 2 right, following channel pan, inputs only
([experiments 30–34](../experiments/30-stereo-aux/README.md)).

- [ ] Send mute in stereo: today AUX 1's mute mutes the pair and AUX 2's mute
      applies only in mono; decide whether that is right.
- [ ] The two AUX output limiters are independent, so in stereo a strong
      transient on one side moves the image while that side limits; the
      master pair's limiter is linked. Linking them needs a 12-byte change in
      each of two audio-code loops, delivered in the image or written into
      RAM at startup; not built
      ([AUX limiter findings](research/aux_limiter_link_findings.txt)).
- [ ] Optional: send pads or internal effects to the pair (needs new routing).
- [ ] Optional: switch the mode over MIDI (an NRPN pair; see the
      [AUX switch findings](research/aux_switch_findings.txt)) or from the
      configurator.

The scene proposal written before the build is in
[archive/stereo-aux-scenes.md](archive/stereo-aux-scenes.md).
