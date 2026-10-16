# Architecture (0.1.0)

The release adds about 9.1 KB of code to Zoom's v1.10 firmware and patches 15
stock instruction sites. It records nothing and copies no audio: the pads play
the stock recorder's own `MASTER.WAV` files in place. The DSP code, the
recorder, the SD driver and every recording file stay stock. Source:
`src/capture/master/` ([source map](../src/README.md)).

## Image layout

Built by `tools/firmware/build_release.py` from the stock `L6.BIN`:

- The added code (`0x800a9688`-`0x800ab8fc`) and 44 bytes of zeroed globals
  (`0x800b0a00`) are packed into the span the stock scatter loader frees after
  expanding the compressed DSP code at boot; the loader itself places them
  ([source-reuse findings](research/capture_source_reuse_findings.txt)).
- Each patch site is a 4- or 6-byte branch to an adapter that saves the
  registers, calls C, replays the displaced stock instructions and resumes.
- The container length, descriptors, version strings and checksum are
  checked; no byte outside the planned spans changes. The build is
  reproducible byte for byte.
- The state (about 23 KB, history buffers included) is one allocation from
  the stock heap at startup.

## Participants

| Task | Entry (stock site) | Does |
|---|---|---|
| Startup | `0x80067a84`, `0x800745e8` | Notes the first initialisation result; after the idle task exists, allocates the state and creates the worker (priority 1, 8 KiB stack), then publishes the state |
| Recorder (RecPlayCtl) | Stream admission `0x8000b158`; stop cursor setter `0x80006918` (RecStop's call only) | Marks an ordinary take (all seven streams, no pad record target); at RecStop notes the take folder (`0x8060ff80`) and the pad files that played |
| Main | Pad start `0x80018316` | Notes each pad file started during a take (its saved path) |
| Main | The five stock receive calls (`0x8002c258`...`0x8002c440`) | Assigns the chain; counts storage changes (card and transfer-mode events); toggles the chain and AUX modes |
| Worker | Its own loop (every 25 ms) | Waits for the recorder, checks the master, writes `HISTORY.TXT`, polls the EFX + PAN and AUX 1 + AUX 2 holds |
| Gain requests (any task) | Ramp request `0x80010398`; pan, balance and Editor reset veneers `0x80002ac0`, `0x800028d8`, `0x80002b78`, `0x80002b90` | The stereo AUX filter |

## Take chain

The chain runs only while it is switched on (below); off, takes are checked
and get their history but are not posted to the pads.

1. After RecStop the worker waits until the stock recorder is idle (not
   recording, playing or finalizing), then opens the master read-only: it must
   be a 48 kHz stereo PCM or float WAV whose data chunk ends at the end of the
   file, at least 2 seconds long, with no second part (`MASTER_01.WAV`).
2. It posts the take to Main. Main builds the new chain: the new take, then
   the takes saved on pads 1–4 in order, skipping hand-picked or empty pads
   and repeats, cut at the first pad without an anchor. It checks every pad's
   format first, stops pads that will change, then queues the stock
   assignments (`0x80008c68`, as the Editor's select does) oldest first, so a
   shift cut short repeats a take rather than losing one.
3. Stock reload keeps an assigned path only if the pad's folder lists a file
   with the same name, so each pad folder holds the anchor `MASTER.WAV`. The
   saved pad paths are the only record: the chain survives reboots with no
   state of its own.

A storage change during a take, or while a file is open, refuses that take.
Details: [master reference findings](research/master_reference_findings.txt),
experiments [24](../experiments/24-master-ref/README.md)–[26](../experiments/26-short-takes/README.md)
and [29](../experiments/29-daily/README.md).

## Take history

The worker writes `HISTORY.TMP` in one write, closes it and renames it to
`HISTORY.TXT` in the take folder. It reads each played take's history to
include its entries (newest first, at most 100). Every file call waits while
the recorder records, plays or finalizes, because the stock filesystem locks
do not raise a low-priority holder's priority. Format:
[history format](history-format.md); design:
[experiment 28](../experiments/28-take-history/README.md).

## Stereo AUX and the switch

- **Mode**: two spare bytes in the global settings (`CONFIG+0x30d/0x30e`,
  `A5 5A` = stereo), saved to internal flash with the other settings. Stock
  code never reads, checks or puts them in scenes. Stereo also requires the
  worker to exist, so a mixer whose worker did not start is stock mono.
- **Filter**: every runtime gain change goes through the stock ramp request.
  In stereo, a request for AUX 1 lane *j* becomes a pair: AUX 1 gets the gain
  times the channel's left pan factor and AUX 2 the right one; AUX 2 requests
  are dropped. Pan, balance and Editor resets refresh the pair. In mono every
  request passes through unchanged.
- **Switch**: the worker reads the AUX 1 and AUX 2 keys (`0x80008478`); a
  1.5 s hold posts a toggle to Main, which refuses it while any recording or
  RecStop runs, otherwise flips the bytes, runs the stock bulk recompute
  (`0x8000c648`, as a scene recall does: every gain again, as 16 ms ramps),
  requests the stock settings save and sets the two AUX LEDs for 2 s. Main
  then redraws them from the current view.

Details: [stereo AUX findings](research/stereo_aux_findings.txt),
[AUX switch findings](research/aux_switch_findings.txt), experiments
[30](../experiments/30-stereo-aux/README.md) and
[32](../experiments/32-aux-switch/README.md)–[34](../experiments/34-release/README.md).

## The panel switches

`panel.c` serves both holds. The worker reads the live key state
(`0x80008478`): EFX + PAN (keys 18, 19) or AUX 1 + AUX 2 (16, 17) held for
1.5 s posts one event to Main, armed 1 s after Main first received an event
(about 4 s after power-on). All four keys are in one panel key group: PAN +
LEVEL, across two groups, often lost the second key on the mixer
(experiment 37). A release ends a
hold only when seen on three polls running, so a one-off misread neither
restarts the 1.5 s nor allows a second toggle; a hold restarts if both keys
went unseen for over 500 ms (a stall may hide a release). Main refuses either while any recording or RecStop runs;
otherwise it flips the mode bytes, requests the stock settings save and lights
the pair's select LEDs for 2 s (blink = on or stereo, steady = off or mono),
then redraws all nine select LEDs from the current view, as a view press does.
View buttons have no stock long press or combination, and their presses save
nothing ([panel keys findings](research/panel_keys_findings.txt)).

- **Chain mode**: `CONFIG+0x30f/0x310`, `C3 3C` = on, anything else (a mixer
  that never switched) off.
- **AUX mode**: `CONFIG+0x30d/0x30e` (below).

## Verification

`tools/firmware/verify_release.py` rebuilds the image and runs the release
suites. They execute the original firmware's instructions in an emulator
(Unicorn) together with the release code: boot and scatter expansion of the
exact image, the chain, history and storage-change cases, the stereo
filter against the real gain-ramp task, and the switches driven by panel
messages through the stock parser with the panel's measured key reporting. Hardware results are in each
experiment's README.

## Research behind it

The project first built an overdub prototype, then captured a pre-compressor
copy of each take in real time (experiments 19–23). Reusing the stock master
in place made both unnecessary. Those designs are kept in
[archive/architecture-research.md](archive/architecture-research.md).
