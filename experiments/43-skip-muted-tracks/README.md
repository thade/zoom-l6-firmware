# No track files for muted channels with no sends

[Release 0.3.0](../41-linked-limiters/README.md) plus an opt-in setting:
while it is on, an ordinary take creates no track file for a channel that
is muted and feeds no send. Hold **AUX 2** and **EFX** together for 1.5
seconds to switch it on or off. Everyday build.

**Prepared, not installed.** Built and emulated 19 October 2026.

## Why

A user asked for takes that keep only the tracks they used. The
[unused track files findings](../../docs/research/unused_track_files_findings.txt)
compared marking channels by hand, detecting silence and deleting files
afterwards, and a rule read from the mixer at the moment a take starts. The
project owner chose the rule, as a setting that is off until switched on.
Nothing is deleted and nothing changes on the audio path, because the files
are never created. Zoom's Master Only recorder mode leaves files out the
same way, so the stock start, stop, loader and player already handle a take
with fewer files.

## The rule

A channel 1-6 is left out of a take when its MUTE is on and nothing reaches
its sends. A send counts as carrying nothing when its level is zero, when
it is muted, or when its send point is post-fader, because a post-fader
send follows the channel mute. In mono AUX mode the sends that matter are
EFX, AUX 1 and AUX 2. In stereo AUX mode they are EFX and AUX 1, because the
AUX 2 knob does nothing there. A stereo channel is left out only when both
of its sides meet the rule, and a MONO x2 channel is still one channel.
`MASTER.WAV` is always written. Recordings onto a pad are not changed.

## Changes from 0.3.0

- One more patched site. The stock record prepare (0x80002df8) asks a
  selector (0x80008990) which of the twelve streams to record and hands the
  answer to the stream setup. The call at 0x80002e96 now goes to our
  `tm_select`, which calls the stock selector and, when the setting is on
  and the take is an ordinary one, clears both lanes of each channel that
  meets the rule. The selector itself is untouched because the project
  loader calls it too and must keep stock's answer.
- The admission hook accepts a take with fewer than seven files: an
  ordinary record target and the master's stream make it a take, so it
  still joins the chain and gets its `HISTORY.TXT`.
- The setting is the byte pair `96 69` at CONFIG+0x311, next to the AUX
  and chain switches, saved with the other settings. Off by default. The
  AUX 2 + EFX hold toggles it; both LEDs blink for 2 seconds when it is now
  on and light steadily when it is off. Refused while recording.
- When a take starts with channels left out, their MUTE LEDs blink for
  2 seconds and then show the mutes again.
- 640 more bytes of code and 128 of globals. Everything is behind the
  `TRACK_MASK` build flag, and 0.3.0 still rebuilds byte for byte.

| | 0.3.0 (experiment 41) | 43 |
|---|---|---|
| Patch sites | 15, plus 2 in the DSP code | 16, plus 2 in the DSP code |
| Code | 11,140 bytes | 11,780 bytes |
| Image SHA256 | `34df789b…` | `f1348067e0f7d18c4e1ff442be44fc351807ba35077e179db3349a995370204d` |

Build: `python tools/firmware/build_master_trial.py skip_muted` (output in
`deployment/43_skip_muted/`; the image is not pinned until it is installed).

## Checks

- `tests/emulation/verify_track_mask.py` (7 groups): the build and the
  0.3.0 rebuild; the original prepare over 24 mixer states, with the
  setting off and on, pad targets, Master Only and the project loader; the
  original record start, RecStop (finalize, postprocess, the take loader,
  the playback preparation) on an in-memory card for seven subsets, with
  the admission hook running through its adapter; subset takes joining the
  chain and getting their history; the hold through the stock key parser
  with the panel's measured key reporting; the MUTE LED show.
- `tools/firmware/verify_release.py`: the release suites, unchanged.
- One thing seen in stock on the way: the take loader accepts only a stereo
  file for streams 3-6, so a MONO x2 take's `TRACK03_L.WAV` and
  `TRACK03_R.WAV` are opened and then refused at the stop, with or without
  this build. The feature does not change it.

## Procedure (on the mixer)

Install over 0.3.0 with the browser patcher or the card. Keep a Master
Only take for comparison. Note the results below.

1. **The switch.** Hold AUX 2 and EFX for 1.5 seconds: both LEDs blink for
   2 seconds. Hold again: both light steadily. Hold once more to leave it
   on. Switch the mixer off and on: the setting must survive (there is no
   indication at start-up; the next take shows it).
2. **A take with muted channels.** Mute channels 1 and 3/4 with their sends
   down, leave the others open, record a few seconds, stop. While the take
   starts, MUTE 1 and MUTE 3/4 blink for 2 seconds. Then: PLAY on the
   mixer plays the take; a few seconds after the stop, pad 1 plays it if
   the chain is on; the take's folder on the card holds `TRACK02.WAV`,
   `TRACK05_ST.WAV`, `TRACK06_ST.WAV`, `MASTER.WAV` and `HISTORY.TXT`, and
   no `TRACK01.WAV` or `TRACK03_ST.WAV`.
3. **A send keeps a channel.** Mute channel 1 again, turn its AUX 1 send
   up with the send point at Pre Fader (ZOOM L6 Editor, AUX Send Point),
   record. MUTE 1 does not blink and `TRACK01.WAV` is written. Set the
   send point back to Post Fader and record: it is left out again.
4. **Stereo AUX.** Switch the AUX send to stereo (AUX 1 + AUX 2 hold), mute
   channel 2 with only its AUX 2 send up, pre-fader, record: channel 2 is
   left out. Switch back to mono.
5. **The Editor.** Connect the Editor and open the card's view of the take
   folders: a take with fewer files must list and play as before.
6. **Master Only.** Set Recorder Mode to Master Only in the Editor, record
   a take with the setting on: only `MASTER.WAV`, as before. Set it back.
7. **Off.** Hold AUX 2 and EFX until both LEDs light steadily, record with
   channel 1 muted: all seven files are written.

What to compare: the file lists against the mutes and sends at the start
of each take; PLAY and the pad against a Master Only take; `HISTORY.TXT`
present in every take folder.

## Results

Not yet installed.

## Drafts for the README (to place at release time)

For "What it adds":

- **Takes without the tracks you muted.** With this setting on, a channel
  that is muted and not sent anywhere gets no track file. The mixer writes
  the tracks you were using and the master, and nothing else. The setting
  is off until you switch it on.

For "Using it":

**Leaving muted channels out of a take.** Hold **AUX 2** and **EFX**
together for 1.5 seconds. If both lights blink for 2 seconds, the setting
is now on. If both light steadily, it is off. While it is on, a channel
whose MUTE is lit when you press REC gets no track file, as long as none
of its sends carries it. A send carries nothing when it is down, when it is
muted, or when its send point is Post Fader in ZOOM L6 Editor. In stereo
AUX mode only the EFX and AUX 1 sends count, because AUX 2 does nothing
then. When the take starts, the MUTE lights of the channels left out blink
for 2 seconds. `MASTER.WAV` is always written, the take still goes onto the
pads and still gets its `HISTORY.TXT`, and recordings onto a pad are not
affected. A fresh install starts with this off. Only the mutes at the moment
you press REC decide, so a channel you mute during the take is still
recorded in full.
