# Overdub and stereo AUX firmware for the Zoom LiveTrak L6

Unofficial replacement firmware for the original **Zoom LiveTrak L6** (not
the L6max). It lets you overdub using only the mixer, and adds a stereo AUX
send you can switch on and off. Version **0.2.0**, made from Zoom's own
firmware **v1.10**.

This is independent work, not affiliated with or endorsed by Zoom. Zoom's
firmware is not included here: you download it from Zoom, and the
[patcher page](https://thade.github.io/zoom-l6-firmware/) turns it into the
new firmware file on your own computer (or you can
[build it yourself](docs/setup.md)).

## What it adds

- **Your last four takes on the sound pads.** Switch the *overdub chain* on
  (hold EFX + PAN) and every take you record goes onto pad 1 a few seconds
  after you stop; the one before moves to pad 2, and so on to pad 4. Play
  pad 1 while you record the next take and the new take contains both: that
  is the overdub. Nothing is copied, so no card space is used up. Takes
  shorter than 2 seconds are skipped. The chain is off until you switch it
  on, so out of the box the pads work exactly as they always did.
- **A list of what went into each take.** Every take folder gets a
  `HISTORY.TXT` naming the earlier takes and pad sounds it contains, newest
  first, so you can always find the original recordings (with their separate
  tracks) behind a finished mix.
- **A stereo AUX send, switchable.** Hold **AUX 1** and **AUX 2** together
  for 1.5 seconds to switch between Zoom's two separate mono sends and one
  stereo send (AUX 1 is the left side, AUX 2 the right, following each
  channel's pan). The mixer remembers your choice.

## Before you install

- **This replaces your mixer's firmware.** If a firmware ever fails to start,
  you can put Zoom's own firmware back from the card: the small built-in
  program that performs updates is never touched by this project. That
  recovery was tested with a deliberately broken firmware (see
  [If the mixer won't start](#if-the-mixer-wont-start-after-an-update)).
  That is strong evidence, but not a guarantee.
- **Zoom's licence forbids altering or reverse-engineering its firmware
  without permission.** Installing this is your decision and your
  responsibility. This project's MIT licence covers its own code only and
  comes with no warranty.
- **Testing so far is limited.** These features have been used every day on
  one mixer since 12 October 2026; the 0.2.0 file itself was installed with
  the patcher page and checked on 17 October. Some situations have only been
  tested in a software simulation of the mixer, not on a real one (see
  [Known limitations](#known-limitations)).

## What you need

- A Zoom LiveTrak **L6** (not the L6max) with firmware v1.10, and a microSD
  card that was formatted in the L6.
- A computer with a web browser. In Chrome or Edge the patcher page can also
  send the file to the mixer for you; in any other browser you copy it to
  the card yourself.
- Zoom's own v1.10 firmware download (the patcher page links to it).

To build the file from source instead, see
[Building and developing](#building-and-developing).

## Install

1. **Make the firmware file.** Open the
   [patcher page](https://thade.github.io/zoom-l6-firmware/), download
   Zoom's v1.10 zip from the link there, and drop the zip on the page. It
   makes `L6.BIN` on your computer; nothing is uploaded. In Chrome or Edge
   the page can then send the file to the mixer for you: follow its steps,
   then skip to **Update the mixer** below.
2. **Copy `L6.BIN` to the card** (if the page didn't do it for you). Either
   put the card in a card reader, or connect the mixer by USB and click
   **File Transfer Mode** in ZOOM L6 Editor (Zoom's free app; File Transfer
   Mode makes the card appear on your computer as a drive). Copy `L6.BIN`
   to the card's top folder, next to `RECORDER` and `SOUND_PAD`, replacing
   any `L6.BIN` already there. Then eject the card.
3. **Update the mixer.** Power it from its USB port (batteries may not be
   enough). Switch it off with the card in. Hold **PLAY/STOP**, then press
   and hold **POWER** until the power light comes on; let go. The light
   blinks green slowly while it updates (about 30 seconds), then quickly
   when it's done. Don't switch off during the update. Then switch the mixer
   off and on again.
   - Quick **red** blinking means the update failed: switch off, check that
     `L6.BIN` is in the card's top folder, and try again.
   - If the mixer stays dark afterwards, see
     [If the mixer won't start](#if-the-mixer-wont-start-after-an-update).

## Using it

**Switching the overdub chain on and off.** Hold **EFX** and **PAN** together
for 1.5 seconds. Both lights blink for 2 seconds: the chain is on. Both light
steadily for 2 seconds: it is off. (Afterwards the mixer shows the view of
whichever of the two buttons you pressed second, as a normal press would.)
While you hold EFX the MUTE buttons act on the effect sends, as they always
do, so don't touch MUTE during the hold. The combination does nothing in the
first 4 seconds after switching on, or while recording. The mixer remembers
the setting when switched off. A fresh install starts with the chain off:
takes don't go onto the pads and the pads keep whatever you put on them, but
every take still gets its `HISTORY.TXT`.

**Overdubbing.** Switch the chain on, then record a take as usual. A few
seconds after you stop (the mixer finishes saving first) it is on pad 1.
Start the next take and press pad 1 to play the previous one into it.

**Keep MASTER and SOUND PAD at their 0 dB marks** while you overdub, and keep
the master compressor off. Set your listening level with **MONITOR** or your
speakers instead. The reason: the mixer records each take *after* the master
volume and compressor, and playing it from a pad (or with **PLAY/STOP**)
sends it through them again. With MASTER turned down, every layer gets
quieter each time round; with the compressor on, every layer gets compressed
again. (This is simply how the L6 records and plays back.)

**The pads.** While the chain is on, pads 1–4 belong to your takes: each new
take pushes the older ones along and replaces whatever sound a pad had.
Switching the chain off freezes the pads as they are, so switch it off when
you want to keep your own sounds on them. Every pad in the chain shows the
name `MASTER.WAV` (choosing that name by hand in the pad menu gives silence).
Recordings made *onto* a pad, and recordings under 2 seconds, don't join the
chain.

**Small `MASTER.WAV` files in the pad folders.** While the chain is on, the
firmware puts a tiny silent `MASTER.WAV` (a tenth of a second) into each of
the card's `SOUND_PAD/PAD1`–`PAD4` folders if there isn't one. Without it,
the mixer would forget the pad's take when switched off. Leave these files
alone; if you delete one it comes back a few seconds after the card is next
in use (after leaving File Transfer Mode, or at the next start with the chain
on).

**History files.** Each take's folder on the card
(`RECORDER/<take name>/HISTORY.TXT`) lists the recordings and pad sounds it
contains, newest first, up to 100 of them. If older ones had to be left out
the file says `OMITTED`; you will find them in the history files of the takes
it names. Details: [history file format](docs/history-format.md).

**Stereo AUX.** Hold **AUX 1** and **AUX 2** together for 1.5 seconds. Both
AUX lights blink for 2 seconds: stereo. Both light steadily for 2 seconds:
back to two mono sends. (Afterwards the mixer shows the AUX 2 view, as a tap
of AUX 2 would.) The combination does nothing in the first 4 seconds after
switching on, or while recording. A fresh install starts in mono. In stereo,
each channel's **AUX 1** level (and its send point) sets how loud it is in
the stereo send and its **PAN** places it left or right; the AUX 2 level does
nothing until you switch back to mono, where Zoom's two separate sends come
back exactly as they were. In stereo, muting AUX 1 mutes the whole stereo
send and muting AUX 2 does nothing. Pads and the built-in effects are not
sent, same as always.

**Effects loops.** Zoom's sends follow the channel fader by default
("post-fader"), so turning a channel down also turns its sends down. To send
a channel to an external effect while keeping it out of the main mix, set its
send point to *Pre Fader* in ZOOM L6 Editor (*AUX Send Point*). The send point
is saved with each scene.

## Going back to Zoom's firmware

Copy the `L6.BIN` from Zoom's own zip to the card's top folder (replacing
this one), then update the mixer exactly as in [Install, step 3](#install).
Your recordings, pad sounds and settings stay. The small `MASTER.WAV` files in
the pad folders and the `HISTORY.TXT` files can stay too; Zoom's firmware
ignores them, and the pads keep playing the takes that were last on them. The
mixer also keeps the stored chain and stereo settings (even through a factory
reset), but Zoom's firmware ignores those as well.

## If the mixer won't start after an update

A firmware that gets stuck while starting leaves the mixer completely dark:
no lights, and your computer doesn't see it over USB. It looks dead, but it is
only stuck, and you can fix it from the card.

1. **Put Zoom's own firmware on the card.** Take the card out, put it in a
   card reader on your computer, and copy the `L6.BIN` from Zoom's own v1.10
   zip into the card's top folder, replacing the one there. (A card reader is
   the only way here: a stuck mixer can't show you its card.) Put the card
   back in the mixer.
2. **Switch the mixer off completely:** unplug *both* USB cables and take
   out the batteries. Any one of those can keep it powered.
3. **Update as usual:** plug USB power back in, hold **PLAY/STOP**, then
   press and hold **POWER** until the power light comes on; let go. Wait for
   the slow green blinking to turn quick, then switch off and on.

This works because the update is done by a small built-in program that runs
*before* the firmware starts, and this project never changes that program.
Evidence: [experiment 18](experiments/18-recovery-hang/README.md),
[bootloader findings](docs/research/bootloader_findings.txt).

## Known limitations

- Only takes recorded at 48 kHz join the chain; a take long enough to be
  split into two files (about 93 minutes) does not.
- The stereo send's sound was last measured at the AUX jacks on an earlier
  build ([experiment 32](experiments/32-aux-switch/README.md)); on 0.1.0 and
  0.2.0 only the switch and its lights were checked.
- Losing power in the moment right after stopping a take, while its history
  is written, is untested.
- If takes are started and stopped faster than the history files can be
  written, one take can miss the chain.
- Saving scenes while in stereo, changing sends from ZOOM L6 Editor or over
  MIDI, and the pan of mono channels in stereo were tested in a software
  simulation of the mixer, not on a real one.
- The stereo switch also works in the L6's settings and test modes; that has
  not been tried.

## Building and developing

- **[Build from source](docs/setup.md).** macOS or Linux, git and Python 3.12
  or newer; the build ends with `release/0.2.0/L6.BIN`.
- **Installer script.** With the mixer's card mounted,
  `python tools/device/install_release.py --eject` copies the built `L6.BIN`
  to it (after backing up the card's existing `L6.BIN` and settings file) and
  ejects the card. `--stock` installs Zoom's own `L6.BIN` instead (for going
  back, or for recovery with `--card /Volumes/<card>`). On Linux, or with
  several cards mounted, add `--card <card folder>`; `--eject` is macOS only.
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
