# Read, write and complete file-call timing

**Status: diagnostics and a 3-minute recording verified on 7 October 2026;
timing firmware retained on the device by user choice.** After exact staging/readback, safe unmount and the user-reported
update/reboot, all seven fixed diagnostic queries answered. Ordinary MIDI
queries confirmed the original pad assignments and ports; L6 Editor connected.
This trial adds measurements needed before choosing an overdub buffer size.
Capture remains disabled. Installed flash bytes have not been read back.

The initial idle sample reported 163,104 bytes free/minimum heap, 579 SD reads
and 266 public file reads, with no observed errors or skipped calls. Maxima were
57 and 59 ticks respectively; no writes had been observed. A 30-second host
calibration bounded the clock at 999.38–1,000.19 ticks per second.
For the longer test, the existing 71.405-second `GLORY_BOX.WAV` was selected on
pad 1 in Loop mode at its existing 0 dB level; other pad assignments were
unchanged. The new baseline includes those settings writes: 8 SD writes and
4 public file writes, both peaking at 7 ticks, with no errors/skips. Public reads
now peak at 60 ticks.

The saved take is **20.04 seconds**, with seven valid, aligned float WAVs and no
audible issues reported. Post-recording counters show no errors, SD read/write
peaks of 81/53 ticks and public file read/write peaks of 82/112 ticks. Nine
public file calls were unmeasured (8 busy skips and 1 missed claim, shared across
read/write). Free/minimum heap remained 163,104 bytes. The computer's 40 bounded
samples captured only idle counts; the subsequent mixer counters retained the
recording observations. This does not verify three minutes or a backing loop
join. Pad 1 was restored to `OD_261002_181142.WAV`, One-shot, at 0 dB. The
user confirmed deliberately stopping that short take, then completed the longer
repeat with Glory Box looping on pad 1.

The longer take is **187.263 seconds**, with seven valid, finite float WAVs,
each containing 8,988,608 frames. Both backing repeat periods equal the source's
3,427,439 frames exactly; eight separated waveform windows retain their offsets.
The user reported no audible problems. All seven copies passed fresh card/hash
verification, and 23 earlier evidence files remained unchanged. Pad 1's original
assignment, One-shot mode and 0 dB level are restored.

Counters collected before restoration/transfer show no observed errors. Since
the longer-test baseline, timed SD read/write counts increased by 1,146/1,580
and public file counts by 1,313/988. There were 105 additional unmeasured public
calls (96 busy skips and 9 missed claims, shared across read/write); no new SD
skips. Cumulative peaks remain 81/53 ticks for SD and 82/112 for public files.
Free heap is 163,104 bytes; the cumulative minimum of 160,664 was already present
before this longer recording. No host sample captured live recording, so these
are retained observations without a recording time series. Capture is disabled;
these results do not select the final buffer or establish a worst-case delay.

Untouched stock was subsequently staged and read-back verified. All 86 card
recording/pad entries and the device settings stayed unchanged; all 30 saved
audio evidence files passed hash verification. The card was safely unmounted,
transfer mode exited, and normal editor connection plus original pad/MIDI replies
were confirmed. The user subsequently chose to retain the timing firmware and
defer stock restoration. Staging stock did not install it. Restoration is an
available option, not a prerequisite to the next development milestone.
The card-root update file has since been replaced with the verified experiment
06 reservation trial; that trial awaits manual installation. Stock remains
available locally for an optional future restoration.

The [device findings](../../docs/research/timing_probe_device_findings.txt)
separate these observations from the remaining performance gates.

It reports separate read/write counts, errors, first errors, longest durations,
peak request sizes and identities, and eight duration bins. Two scopes observe
the original SD packet units; a third observes complete public file reads and
writes, including their native lock waits and scheduling. Busy observations and
missed weak atomic claims have separate counters. Existing heap counters remain
available. Only fixed read-only MIDI queries are supported.

The unchanged DSP is packed and restored through the same stock decoder used by
experiment 04. Code and state occupy 1,756 bytes inside the original MAIN length,
including 444 bytes of persistent state. Four original entry prologues receive
four-byte branches; their complete displaced instructions are replayed. The
probe creates no allocation, task, audio file, SD request, recovery operation or
pad assignment. Its observers use integer instructions only.

Twelve offline groups verify exact allowed image changes, all eight startup
outputs, compiler isolation, separate peaks/errors/histograms, tick wrap, skipped
observations, original public-file arguments/results, host schemas, ordinary
editor messages, protected reply copying, unchanged native file/SD behavior and
retained failure stacks. The earlier trial still builds to its exact original
hash and passes its thirteen diagnostic groups. Sector/DMA effects, scheduling
and physical completion remain fixture inputs.

Prepare and verify locally using the dependencies in [setup](../../docs/setup.md):

```sh
python tools/firmware/build_timing_probe.py
python tests/emulation/verify_timing_probe.py
```

The private local image is
`deployment/05_timing_probe/trial_timing_probe/L6.BIN`; untouched stock is retained
beside it under `stock_restore/`. Trial SHA256:

```text
5a70ab7cbe20b0b2525b89c2c2267d38b908696ecd600d8461dc4eda25f11fb9
```

Use the established [physical update procedure](../01-usb-name/README.md), with
fresh card identity, exact readback verification, preserved settings/audio and
safe unmount before updating. No device operation is performed by the build or
verification scripts. After updating, reboot normally and connect L6 Editor.

```sh
python tools/device/l6_timing_probe.py --output deployment/05_timing_probe/idle-01.jsonl
```

Use a new log filename each time. Collect an idle baseline, several samples
during a full-song recording with pad playback, and another after stopping.
Check audible behavior and verify the saved master/stem files. If restoring
untouched stock, use the same readback and ordinary-MIDI positive controls as
experiment 04. Routine restoration between working trials is deferred by user
choice. These are manual test steps; the host sends no playback or record
commands and makes no pad changes.

The fixed query kinds are:

| Kind | Observation |
| --- | --- |
| 1 | Existing heap/card counters and clock |
| 2 / 3 | SD packet unit 1 read / write |
| 4 / 5 | SD packet unit 2 read / write |
| 6 / 7 | Complete public file read / write |

The request/reply command bytes are distinct from experiment 04 (7B/7A). Timing
is reported in ticks. Recalibrate against host time; the earlier trial measured
approximately 1,000 ticks per second. Bins are 0, 1–4, 5–16, 17–64, 65–128,
129–256, 257–512 and 513+ ticks. Maxima update on strictly longer calls; their
amount/identity describes that first observed peak. Amount is sectors for SD or
requested bytes for public files; identity is starting sector or native handle.
Counters are cumulative modulo uint32 and reset only by reboot. Skips describe
unmeasured calls, not storage errors. Counts include calls in progress; rely on
matching even epochs when interpreting completed operation statistics. Skip
counters and heap words are individually aligned observations rather than a
single atomic snapshot. The sender copies each reply before its stack expires.
Operation fields use atomic accesses under the observer epoch, so concurrent
queries do not race with plain counter stores.

This trial measures stock load only. It cannot establish a largest contiguous
heap allocation, later stock reserve, worker/interrupt stack headroom, extra-file
throughput, history occupancy, catch-up or physical completion. The 128-slot
history remains a conditional experiment candidate; 256 slots leave too little
reserve with the current experimental stack. Full call peaks are a better input
than experiment 04's combined SD peak, but still do not establish a guaranteed
blackout bound. Broken-image recovery remains unproven.
