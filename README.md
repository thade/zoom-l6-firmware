# Overdub/stereo AUX firmware for the Zoom LiveTrak L6

Unofficial custom firmware for the original **Zoom LiveTrak L6** (not the
L6max) that adds an overdub workflow using only the mixer and a switchable
stereo AUX send. Version **0.1.0**, built on Zoom's firmware **v1.10**.

Independent work, not affiliated with or endorsed by Zoom. Zoom's firmware is
not included: you download it from Zoom and build the image yourself.

## What it adds

- **Your last four takes on the sound pads (switch on with EFX + PAN).**
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

- This changes your mixer's firmware. The SD-card updater is in the mixer's
  bootloader, which these images never change, and it runs before the
  firmware does when PLAY/STOP is held at power-on. A deliberately broken
  firmware that hung at startup was recovered this way (see
  [If the mixer won't start](#if-the-mixer-wont-start)). That is good
  evidence, not a guarantee.
- Zoom's firmware licence notice forbids altering or reverse engineering its
  firmware without permission. Building and installing this is your decision
  and your responsibility. The MIT licence below covers this project's code
  only and comes with no warranty.
- Its features have been used daily on one mixer since 12 October 2026; the
  0.1.0 image itself was installed and checked on 16 October. Some cases are
  tested only in emulation (see [Known limitations](#known-limitations)).

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
   (On Linux, or with several cards mounted, add `--card <card folder>`;
   `--eject` is macOS only, so eject the card yourself elsewhere.)
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

**Turning the overdub chain on and off.** Hold **EFX** and **PAN** together
for 1.5 seconds. Both lights blink for 2 seconds when the chain turns on and
light steadily for 2 seconds when it turns off (the hold also selects the
view of the button you pressed second). While EFX is held the MUTE lights
show the effect-send mutes, as on a stock L6, so don't press a MUTE button
during the hold. It does nothing for about 4 seconds after power-on, or
while recording. The mixer remembers the setting
through power cycles. A new install starts with the chain off. While it is
off, takes do not move onto the pads and the pads keep whatever you assign;
every take still gets its `HISTORY.TXT`.

**Overdubbing.** Turn the chain on, then record a take as usual. A few
seconds after you stop (the L6 finishes writing its files first) it is on
pad 1. Start the next take and
press pad 1 to play the previous one into it.

Keep the **MASTER** and **SOUND PAD** knobs at their unity (0 dB) marks while
you overdub, and set your listening level with **MONITOR** or your speakers.
A take's `MASTER.WAV` is recorded after the master volume and compressor, and
the pads (and **PLAY/STOP** playback) send it through them again: with the
master below unity every layer gets quieter on each pass, and with the master
compressor on it is applied again on every layer, so keep it off. This is how
the stock L6 records and plays back.

**The pads.** While the chain is on, pads 1–4 follow your takes: as takes
move along, they replace whatever sound a pad had; turning the chain off
leaves them as they are. Every pad shows the name `MASTER.WAV` (choosing the
anchor by hand gives silence). Recordings made *to* a pad, and recordings
under 2 seconds, do not enter the chain. To keep a hand-picked sound on a pad,
remove that pad's anchor `MASTER.WAV`: the chain stops at the first pad
without one (without PAD1's it never runs).

**History.** `RECORDER/<take>/HISTORY.TXT` lists the recordings and pad
sounds the take includes, newest first, at most 100 entries. When older entries
are left out the file says `OMITTED`; they are listed in the histories of the
takes it names. See the [history format](docs/history-format.md).

**Stereo AUX.** Hold AUX 1 + AUX 2 for 1.5 seconds. Both AUX lights blink for
2 seconds when it switches to stereo, and light steadily for 2 seconds when it
switches back to mono (the hold also selects the AUX 2 view, as a tap of AUX 2
would). It does nothing for about 4 seconds after power-on, or while
recording. A new install starts in mono. In stereo, each channel's AUX 1 send
amount and send point set its level in the pair, and its pan places it; the
AUX 2 knob does nothing until you switch back to mono, where Zoom's two
independent sends return unchanged. In stereo, AUX 1's send mute mutes the
pair and AUX 2's does nothing. Pads and internal effects are not sent, as on
a stock L6.

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
does not clear the stored AUX and chain settings, but stock firmware ignores
them.

## If the mixer won't start

A firmware that hangs at startup leaves the L6 dark (no lights, no USB
device), which looks as if it won't switch on. It is still powered, and stuck.

1. Put Zoom's v1.10 `L6.BIN` on the card with a computer card reader
   (`python tools/device/install_release.py --stock --card /Volumes/<card> --eject`),
   since the mixer cannot enter File Transfer Mode, and put the card back.
2. **Power it fully off:** unplug both USB cables and take out the batteries.
   Either USB port, or the batteries, can keep it powered.
3. Reconnect USB power, then hold PLAY/STOP and press POWER, holding PLAY/STOP
   until the power light comes on. It updates as usual, then switch off and on.

This works because the bootloader reads PLAY/STOP and runs the update before
the firmware is started ([experiment 18](experiments/18-recovery-hang/README.md),
[bootloader findings](docs/research/bootloader_findings.txt)).

## Known limitations

- Only 48 kHz stereo takes join the chain; a take long enough to be split into
  two files (about 93 minutes) does not.
- The stereo send was last measured on the AUX jacks with experiment 32;
  later builds, 0.1.0 included, checked its switch by the lights only.
- A take layered over one recorded with experiments 28–33 inherits that
  take's version 1 history lines in their original (oldest-first) order.
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
