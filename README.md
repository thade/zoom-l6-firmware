# Overdub firmware for the Zoom LiveTrak L6

Unofficial custom firmware for the original **Zoom LiveTrak L6** (not the
L6max) that adds an overdub workflow using only the mixer. Version **0.1.0**,
built on Zoom's firmware **v1.10**.

Independent work, not affiliated with or endorsed by Zoom. Zoom's firmware is
not included: you download it from Zoom and build the image yourself.

## What it adds

- **Your last four takes on the sound pads (switch on with PAN + LEVEL).**
  With the overdub chain on, after each ordinary recording pad 1 plays the
  take you just made, pad 2 the one before, and so on to pad 4. Play pad 1
  while you record the next take and the new take contains both: an overdub.
  Nothing is copied; the pads play the take's own `MASTER.WAV` where it was
  recorded. Takes under 2 seconds are ignored. The chain is off until you
  turn it on, so the pads work as on a stock L6.
- **A history in every take folder.** Each take gets a `HISTORY.TXT` listing
  the earlier takes and pad sounds it includes, newest first, so you can find
  every original recording (with its separate tracks) behind a final mix.
- **Stereo AUX send, switchable.** Hold **AUX 1** and **AUX 2** together for
  1.5 seconds to switch the two AUX sends between Zoom's two independent mono
  sends and one stereo send (AUX 1 left, AUX 2 right, following each channel's
  pan). The mixer remembers the choice.

## Before you install: risks

- This changes your mixer's firmware. A firmware that fails early at startup
  could leave the mixer unable to boot, and a way to recover from that has not
  been proven. Every update during development started from a working
  firmware, and reinstalling Zoom's own firmware has worked, but there is no
  guarantee.
- Zoom's firmware licence notice forbids altering or reverse engineering its
  firmware without permission. Building and installing this is your decision
  and your responsibility. The MIT licence below covers this project's code
  only and comes with no warranty.
- Version 0.1.0 has been used daily on one mixer. Some cases are tested only
  in emulation (see [Known limitations](#known-limitations)).

## Requirements

- A Zoom LiveTrak **L6** running firmware v1.10, and a microSD card formatted
  in the L6.
- A computer (macOS or Linux) with Python 3.12 or newer and git, to build the
  image. Installing just means copying files to the card.
- Zoom's v1.10 firmware download (see [setup](docs/setup.md)).

## Install

1. **Build** the image: follow [docs/setup.md](docs/setup.md). It ends with
   `release/0.1.0/` holding `L6.BIN`, `MASTER.WAV` and `SHA256SUMS`.
2. **Copy to the card.** Mount the card (card reader, or *File Transfer Mode*
   in ZOOM L6 Editor) and run:
   ```sh
   python tools/device/install_release.py --eject
   ```
   (On Linux, or with several cards mounted, add `--card <card folder>`.)
   It checks the files, backs up the card's existing `L6.BIN` and settings
   file, copies `L6.BIN` to the card root, and puts the anchor `MASTER.WAV`
   (0.1 s of silence) into each `SOUND_PAD/PAD1`–`PAD4` folder. Without the
   tool: copy `L6.BIN` to the card root and `MASTER.WAV` into the four pad
   folders yourself, and delete any `._` files macOS leaves next to them.
3. **Update the mixer** as in Zoom's update guide: power it from the USB port,
   insert the card, then hold **PLAY/STOP** while pressing **POWER** until the
   power indicator lights. It blinks green slowly while updating (about
   30 seconds) and quickly when done. Do not switch off during the update.
   Then switch off and on again.

## Using it

**Turning the overdub chain on and off.** Hold **PAN** and **LEVEL** together
for 1.5 seconds. Both lights blink for 2 seconds when the chain turns on and
light steadily for 2 seconds when it turns off (the hold also selects the
view of the button you pressed second). It does nothing in the first 10
seconds after power-on and while recording. The mixer remembers the setting
through power cycles. A new install starts with the chain off. While it is
off, takes do not move onto the pads and the pads keep whatever you assign;
every take still gets its `HISTORY.TXT`.

**Overdubbing.** Turn the chain on, then record a take as usual. A few
seconds after you stop (the L6 finishes writing its files first) it is on
pad 1. Start the next take and
press pad 1 to play the previous one into it. The master compressor is part
of a take's `MASTER.WAV`, so overdub with the master compressor off or it is
applied again on every layer.

**The pads.** While the chain is on, pads 1–4 follow your takes: as takes
move along, they replace whatever sound a pad had; turning the chain off
leaves them as they are. Every pad shows the name `MASTER.WAV` (choosing the
anchor by hand gives silence). Recordings made *to* a pad, and recordings
under 2 seconds, do not enter the chain. To keep a hand-picked sound on a pad,
remove that pad's anchor `MASTER.WAV`: the chain stops at the first pad
without one (without PAD1's it never runs).

**History.** `RECORDER/<take>/HISTORY.TXT` lists the recordings and pad
sounds the take includes, newest first, at most 100 lines. When older entries
are left out the file says `OMITTED`; they are listed in the histories of the
takes it names. See the [history format](docs/history-format.md).

**Stereo AUX.** Hold AUX 1 + AUX 2 for 1.5 seconds. Both AUX lights blink for
2 seconds when it switches to stereo, and light steadily for 2 seconds when it
switches back to mono (the hold also selects the AUX 2 view, as a tap of AUX 2
would). It does nothing in the first 10 seconds after power-on and while
recording. A new install starts in mono. In stereo, each channel's AUX 1 send
amount and send point set its level in the pair, and its pan places it; the
AUX 2 knob does nothing until you switch back to mono, where Zoom's two
independent sends return unchanged. Pads and internal effects are not sent,
as on a stock L6.

**Effects loops.** Zoom's sends are post-fader by default, so turning a channel
down also turns its sends down. To send a channel to an external effect while
keeping it out of the main mix, set its send point to *Pre Fader* in ZOOM L6
Editor (*AUX Send Point*). The send point is saved with each scene.

## Going back to stock

Install Zoom's own v1.10 `L6.BIN` the same way:

```sh
python tools/device/install_release.py --stock --eject
```

then update the mixer as above. Your recordings, pad sounds and settings stay.
The anchor files and `HISTORY.TXT` files can stay too (stock firmware ignores
them), and pads keep playing the takes last assigned to them. A factory reset
does not clear the stored AUX mode, but stock firmware ignores it.

## Known limitations

- Only 48 kHz stereo takes join the chain; a take long enough to be split into
  two files (about 93 minutes) does not.
- Losing power in the moment right after stopping a take, while its history is
  written, is untested.
- If takes are started and stopped faster than the history files can be
  written, one take can miss the chain.
- Scene saves while in stereo, MIDI and Editor changes to sends, and the
  mono-channel pan in stereo are tested in emulation, not on the mixer.
- The stereo setting also works in the L6's setting and test modes; that has
  not been tested.

## More

- [Build from source](docs/setup.md)
- [How it works](docs/architecture.md)
- [History file format](docs/history-format.md)
- [Development log](docs/progress.md) and [experiments](experiments/)
- [Future work](docs/future-work.md)

## Licence and credits

MIT licence for this repository's code and documentation: see
[LICENSE](LICENSE). Zoom, LiveTrak and L6 are Zoom Corporation trademarks.
The File Transfer Mode message sequence used by `tools/device/l6_transfer_mode.py`
follows [philmillman/zoom-l6-companion](https://github.com/philmillman/zoom-l6-companion)
(MIT) and Magicking/L6-MassStorage.
