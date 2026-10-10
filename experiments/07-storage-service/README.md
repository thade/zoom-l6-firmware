# Attributed storage service

**Status: hardware workload inspected; storage/buffer redesign required.**

The exact image is on the identified L6 card. All 100 recording/pad file entries
and global settings were preserved; all 44 saved audio evidence hashes passed
before and after staging. The previous root image and settings have private
backups. Safe unmount, transfer exit and normal status/pad/MIDI queries passed,
with 163,104 current free bytes and no observed errors. Original pad assignments,
One-shot modes and levels were restored before updating. After the user-reported
update and normal reboot, all 41 new diagnostic pages and all seven legacy timing
pages pass. Four unique native tasks have observation slots; every page is
consistent, with no active file/token scope at the check. All six omission
counters and observed file/take/give/SD error counters are zero. Current and
historical-minimum free heap are both 163,104 bytes. Original pads and MIDI ports
are unchanged, and the official Editor is connected. This confirms new diagnostic
behaviour; installed flash bytes have not been read back. Seventeen offline groups
and 40 prior diagnostic regression groups passed before staging.

The completed take is 258.204 seconds: all seven float32/48-kHz WAVs have
12,393,792 finite frames. Three backing-loop joins repeat exactly the source
length, and eleven separated alignment windows agree. The user reports no
audible problems. All 44 earlier evidence files pass their hashes; global
settings and prior audio metadata are preserved. The card was safely unmounted,
transfer exited, and original pad assignments, One-shot mode and 0-dB levels
restored and verified. No extra recorder is enabled.

Twenty-three restarted snapshots separate a long write from a waiting reader.
The public writer's job 1132 takes 484 ticks for 512 KiB; the same task/job,
handle and byte count have a 419-tick SD held body. A separate filesystem held
maximum reaches 481 ticks in that task, with no public READ/WRITE parent. Do not
pair that independently retained maximum with job 1132 or a specific close.
The public reader's job 453 takes 414 ticks for 96,256 bytes, including a
396-tick filesystem take. Another task's take reaches 962 ticks without a
READ/WRITE parent; it includes scheduling and is not 962 ticks of lock ownership.
The long peaks rise between live snapshots with subsequent reads/writes, before
slot exhaustion. The pre-existing 598-tick boot held peak is excluded.

At approximately one millisecond per tick, 481 ms produces 184,704 bytes of
new stereo samples, exceeding all 163,104 free heap bytes before overhead.
This strengthens the rejection of the proposed 170.667-ms history; it does not
measure an added consumer's actual blackout, occupancy or catch-up.

Coverage is incomplete. The first idle collector timed out before this take;
the restarted series begins after the user reported recording. All new per-task
pages are consistent, but eight legacy pages were unavailable during active
calls. Eight permanent task slots fill; 22 full-slot omissions and 22 unmatched
gives first appear when the file counts reach their final values. They are
omitted observations, not storage failures. After transfer/remount/restoration,
these counters are 62,337 each. All observed errors are zero; omitted calls have
no such guarantee. Sampled current/minimum heap stays 163,104; the later
transfer/restoration minimum is 160,664, with current heap restored to 163,104.

Audio matching has limits too: the full constant-gain model explains 35.184%
of master energy, while 128 of 130 local two-second windows exceed 99%; one
window at 48 seconds explains only 27.073%. Levels remain deferred, and finite
files, selected alignment windows and listening do not prove every sample is
free of dropout or leakage.

Next, audit the native writer and shared staging lifetime offline, alongside
an explicitly owned larger history layout. Improve bounded task attribution
before another measurement image. Capture deployment remains gated.

The roughly 460 ms write from experiment 06 exceeded the proposed history
buffer. This capture-disabled diagnostic separates public file-call duration,
native token-take duration, the held body, and native token-give duration. It
keeps eight fixed task slots, so a waiting caller does not hide another caller.
No extra audio, file, worker or memory reservation is enabled.

Each slot follows one stable native task identity, two filesystem-domain tokens
and two SD-unit tokens. Public READ/WRITE jobs supply their operation, handle,
requested bytes and sequence number to nested token observations. Other token
users, including CLOSE flushing, have no parent READ/WRITE job and report zero
parent identity. The recorder UI/backend state is sampled at take entry for
held peaks, and at file completion for public peaks. These bytes are context
hints; they are not a sample-accurate recording boundary.

The held interval starts at **successful take return** and ends at **give
entry**. It is a lower bound on actual ownership and includes any scheduling
within that interval. Take/give durations also include scheduling. It does not
separate card busy time from preemption, measure physical completion, or prove
how long an additional recorder would be unable to progress. Equal independent
maxima are not a complete event trace. Jobs correlate only within the same task;
pages are individually checked snapshots, not one simultaneous multi-page state.

Prepare and verify with the dependencies in [setup](../../docs/setup.md):

```sh
python tools/firmware/build_service_probe.py
python tests/emulation/verify_service_probe.py
```

Private image: `deployment/07_service_probe/trial_service_probe/L6.BIN`.
SHA256:

```text
9680fba71788974ac8cfd3794395084e7d9015904880a591dc8e0e3ae986863b
```

Code and loaded zero state occupy 8,024 bytes in the already audited stock DSP
source tail, beginning at `0x800b2400`, within the original MAIN length. State
occupies 4,280 bytes including alignment and the unchanged timing counters.
The exact container, original entry/all eight startup outputs, full DSP decode,
integer-only ABI, concurrent task snapshots, failure retention and protected
153-byte reply copying pass offline. Original native file/SD requests, sectors,
results and close flushing match the baseline. Eight-slot exhaustion, a failed
weak claim and unsupported contexts report omitted observations while the
original calls continue. The previous three diagnostic images keep their exact
hashes and pass all 40 regression groups.

On the exercised native file/SD fixture, stack use rises from 1,176 to 1,336
bytes. The largest query uses 248 bytes. These are modeled path measurements,
not hardware stack high-water or cycle counts. This diagnostic adds overhead;
its wall-clock effect must be checked on the device.

After exact staging/readback, safe unmount and transfer exit, use the established
manual [update procedure](../01-usb-name/README.md). Reboot normally, reconnect
the official Editor, then read the new fixed observations:

```sh
python tools/device/l6_service_probe.py --output deployment/07_service_probe/status-01.jsonl
python tools/device/l6_timing_probe.py --output deployment/07_service_probe/timing-01.jsonl
```

Use fresh log names. Requests use command 77, replies 76: kind 1 gives layout,
heap and omission counters; 2..9 give task file observations; 10..41 give four
token pages per task. All queries are read-only. Legacy seven-page timing
queries remain available; experiment 06's reservation command is absent.

A subsequent hardware workload should use the established looping recording, with the same looping backing and input 3, starting and stopping with
Record. Collect before, during and after snapshots; preserve all prior takes
and validate all seven new files and listening observations. A new peak must
be interpreted using its task, parent job, state and separate boundaries.
Slot exhaustion, claim misses, unsupported contexts, ambiguous identities,
nested takes and unpaired gives remain explicit limitations. Slots persist
until reboot; task deletion/reuse is outside this bounded trial.

Queue enqueue/dequeue, exact kernel ownership instants, command submission,
IRQ/card-busy attribution and runtime priorities are not instrumented yet.
Further instrumentation should follow what this narrower probe establishes.
Owned memory, actual added-recorder service/catch-up, physical SD/cache lifetime,
storage transitions and startup release remain separate capture gates.
