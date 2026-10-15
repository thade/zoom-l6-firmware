# Future work

Open work after 0.1.0. Items are ideas or agreed requirements, not
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
- [ ] Recovery from an image that hangs before startup completes
      ([experiment 18](../experiments/18-recovery-hang/README.md), parked).

## Four-pad take history

Done: pads 1–4 hold the four newest takes, newest first, independent of which
take was used as backing ([experiment 25](../experiments/25-take-chain/README.md)).

- [ ] Selecting an older backing, undo, redo and starting a new song: today
      the user picks any pad, and the chain always shows the newest four.

## Normal and overdub modes

**Confirmed requirement:** a setting to switch between the overdub chain and
normal sound-pad use. Today the only switch is removing the anchor files.

- [ ] Decide where the setting lives (panel, configurator) and whether it
      survives a reboot.
- [ ] Keep separate normal and overdub pad banks, changed only when the
      recorder is stopped, and restore each bank's assignments and settings.

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
- [ ] Test whether browser MIDI with SysEx permission reaches the L6's
      endpoints; evaluate a local bridge only if not.
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
- [ ] Optional: send pads or internal effects to the pair (needs new routing).
- [ ] Optional: switch the mode over MIDI (an NRPN pair; see the
      [AUX switch findings](research/aux_switch_findings.txt)) or from the
      configurator.

The scene proposal written before the build is in
[archive/stereo-aux-scenes.md](archive/stereo-aux-scenes.md).
