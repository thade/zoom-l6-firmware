# SD command and buffer diagnostic

**Status: running on hardware; startup, pad playback and ordinary recording verified.**

The verified image is on the identified L6 card. All 142 recording/pad files
(3960862988 bytes) have matching hashes and metadata before/after staging;
the earlier 128 files also match their saved diagnostic-10 hashes. Settings
are unchanged and have a local backup, alongside the preceding update file.
Normal Eject and transfer exit pass. The Editor reconnects, original pad
names/counts and all three MIDI ports respond unchanged, and current/minimum
free heap was 163104/160664 bytes before updating. After the user-reported update
and normal reboot, all three new command pages and the retained protocols
respond. Original pads/ports and current/minimum heap (163104/163104 bytes)
pass. This verifies diagnostic-11 execution; installed flash is not read back.
Evidence is private under `deployment/11_sd_command/`.

Two stopped startup sets agree on 1200 programs/block commands/data waits and
no unmatched scope. One command observation was omitted; the retained sample
explicitly reports missing TC plus an observer gap. Raw/detail observers have
no omissions or errors. Latest command context matches the original bounce
address and task, with DS_ADDR advancing by the recorded 512 bytes.

The automated 18.005-second USB capture identifies the 12.972-second backing at
source correlation 0.99226, with three separated windows above 0.9859 and no
host buffer warnings. It adds 1163 bounce-read programs/commands/waits and raw
TC/DMA-mode TC indications. Raw/detail observers remain error/omission-free.
The command observer omits two more observations and adds 45 conditions; only
its latest condition is retained, showing preprogram/entry raw 0x08 without a
native wait/command failure or raw error. Complete command coverage is not
claimed. Six consistent live pages were collected during the backing; the middle
pair has different epochs and must not be treated as one snapshot. Pads and
heap remain unchanged.

The subsequent ordinary take lasts 262.787 seconds. All seven native WAVs are
valid, finite and aligned. The backing is identified in MASTER after accounting
for substantial live input, with no strong matching backing signal in the stems.
All twelve channels of the entire 18.005-second USB capture agree with the saved
files within 4.657e-10 per sample. The user reports audible backing and no audio
problems. Existing audio metadata, settings, pad assignments and the update file
are preserved; safe Eject, transfer exit and Editor reconnection pass. Earlier
audio hashes were not repeated during this inspection.

From the last stopped playback checkpoint to the stopped recording checkpoint,
6579 programs/block commands/waits and raw DMA-mode TC observations are added,
including 1366 direct and 3514 bounce writes. Raw/detail observers omit nothing
and retain no raw errors. The command observer omits five observations; its 2795
new conditions cannot all be attributed from the one retained condition. Detailed
write conditions contain only inhibit/line activity. Current/minimum heap is
163104/163104 before transfer and 163104/160664 afterward. Transfer observations
are separate. This qualifies the exercised ordinary workload; physical completion,
exclusive ownership and extra capture remain unproved.

This diagnostic connects the existing raw SD interrupt observations to the
native command that was running. It records the proposed buffer before the
original address write, the submitting task and event, the original byte count,
raw completion/error bits, and the native wait result. This answers the remaining
address/context question before binding safe storage handling for extra capture.

It preserves ordinary recording, original pads, diagnostic 10's raw/detail/health
queries and the 223104-frame native capacity. It enables no extra recording,
worker, allocation, cache policy, controller recovery or buffer retention.

Prepare and verify locally:

```sh
python tools/firmware/build_sd_command_probe.py
python tools/firmware/build_sd_command_fixture.py
python tests/emulation/verify_sd_command_probe.py
```

All 35 offline groups pass: the 23 retained groups against this exact image,
plus 12 command-journal groups. All four before-address adapters preserve the
displaced instructions, registers, flags and controller writes. Original native
read/write, command, IRQ and event-wait instructions run with modeled hardware
and kernel endpoints. Error, timeout, observer contention and stale-ticket cases
preserve native behavior. A negative control deliberately delivers an older
transfer's interrupt during a new command: it can still look clean, so the
journal never grants physical completion. Earlier diagnostic 09, 09 detail and
10 images rebuild byte-identically. The main capture regression's separate
730-group result is unchanged; these diagnostic groups are not added to it.

Private image: `deployment/11_sd_command/trial_sd_command/L6.BIN`.
SHA256: `c17c662b40f516fc34bea2e987c825a79a0ecd5362123f0caecc555588e114fc`.
Code/state uses 6524 bytes, including 1052 aligned state bytes. The modeled
native caller reaches 700 stack bytes; the retained IRQ adapter reaches 132
bytes without an active command. Real exception stack, headroom and timing
remain unmeasured. The emulator delivery helper is absent from the image.

Stage only the exact verified image on the identified card. Back up the previous
update/settings and compare recording/pad files before and after. Verify readback,
use normal Eject and exit transfer mode, then follow the previously tested
[physical update procedure](../01-usb-name/README.md). Staged readback is not
installed flash readback.

After normal reboot, connect the official Editor and collect three fixed pages:

```sh
python tools/device/l6_sd_command_probe.py --output deployment/11_sd_command/startup-01.jsonl
```

Pages show the latest completed block command, latest condition and counters.
They return stored state and never clear it. Start with stopped startup and
automated one-shot pad playback. Then record an ordinary take with pad backing
and live input; inspect all seven files and compare with USB audio. A condition
may be normal trailing card activity. Busy/changing epochs or omissions make
coverage incomplete. Do not inject card faults for this trial.

These are temporal observations. Even a clean, consistent page does not prove
physical IRQ freshness, exclusive ownership or safe cache/buffer reuse. The
next implementation still needs an explicit completion/source-exclusion
contract, followed by storage-transition and memory binding, before extra
capture is enabled. See [findings](../../docs/research/sd_command_observation_findings.txt).
