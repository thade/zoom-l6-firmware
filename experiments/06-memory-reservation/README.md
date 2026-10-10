# Candidate recorder memory reservation

**Status: reservation capacity measured; unreserved comparison aligned.
The earlier Channel 1 discrepancy and continuous-capture buffer budget remain open.**

The exact image was copied and read-back verified on the identified L6 card.
All 86 recording/pad entries and device settings stayed unchanged; all 30 saved
audio evidence files passed fresh hash checks. The card was safely unmounted,
transfer mode exited, and original pad assignments, MIDI ports and normal Editor
connection were confirmed. After the user-reported update/reboot, exact new
status replies confirmed execution with the correct budget, status untried and
zero reservation fields. All seven timing replies, original pad assignments and
the three L6 MIDI ports passed. This verifies installed behaviour; installed
flash bytes and recovery from broken firmware have not been read back or proven.

Pad 1 was then prepared with the existing Glory Box file in Loop mode at 0 dB;
the other pads stayed unchanged. One explicit reservation command succeeded.
Its reply and a separate status query agreed on held status and three distinct,
aligned pointers. Current free heap fell from 163,104 to **69,256 bytes**, an
exact **93,848-byte charge**. The allocation count rose by three with no frees;
historical minimum is now 69,256 and scheduler suspension returned to zero.
The retained timing observations are consistent and report no errors. Elapsed
reservation work reported zero ticks; that is not a measured wall-clock latency.
The three blocks remain unused and held. The subsequent recording lasted
170.656 seconds. Fourteen live query sets span 195.064 seconds, covering active
recording and the stopped period. Every reservation sample is held; sampled
current and reported historical minimum heap stay at 69,256 bytes. Final status
and all final timing snapshots are consistent, with no observed errors.

Since the pre-recording baseline, unit 1 completed 1,033 measured reads and
1,432 writes; full public file calls include 1,292 measured reads and 915 writes.
New cumulative peaks are 68/61 ticks for SD read/write and 68/92 for public file
read/write. Host timing bounds the clock at 999.83–1,000.09 Hz. One SD call and
79 public file calls went unmeasured (shared counters counted once per scope).
Two live SD read/write sets and three public file read/write sets were in
progress; they are retained as incomplete observations, not completed samples.
The user reported no audible problems. All seven saved WAVs have valid formats,
finite samples and verified copy hashes. MASTER and five channel files contain
8,191,488 frames (170.656 seconds); Channel 1 contains **240,000 extra frames**,
exactly five seconds. Its extra region is nonzero noise. The original file is
preserved and the discrepancy is unresolved; this is not an all-files-aligned
pass.

Both backing loop periods match the source length exactly, eight alignment
windows agree, and input 3 has low coherent backing correlation. All 30 earlier
evidence hashes and earlier audio metadata stayed unchanged. Card firmware and
global settings were preserved, the card was safely unmounted, transfer mode
exited, and original pad assignments, One-shot mode and level were restored.
At that check the reservation remained held with 69,256 current free bytes. After transfer,
remount and restoration, reported historical minimum is 66,816; the minimum
reported before that interval was 69,256. No worker or extra recording is enabled.

The [stop arithmetic investigation](../../docs/research/stop_cursor_lap_findings.txt)
executes original instructions with synthetic cursor/count state. A consumer
64 frames past the saved stop produces one extra 240,000-frame ring for that
stream, matching this excess. This is a possible mechanism, not a demonstrated
hardware cause or attribution to reservation. The user later recalls using
Play/Stop for the affected take rather than Record and considers it minor.
Original recording-state record/play/stop requests all queue RecStop in a
bounded offline trace; the physical-button timing remains unobserved. Defer
this follow-up, use Record consistently in subsequent trials, and prioritize
the buffering/storage investigation. No stock stop patch is justified.

The same-image comparison after normal reboot is now complete with no reserve
command or firmware update. All seven files contain **8,503,040 frames
(177.147 seconds)**, with valid formats, finite samples and verified copy hashes.
Both backing repeats have exact source-length periods and eight separated
alignment windows agree. The user reported no audible problems. Channel 1's
extra five seconds did not recur; one control does not prove its cause or a fix.
Thirteen live sets span 180.072 seconds, with untried status, zero reservation
fields and 163,104 current/reported minimum free throughout. Final snapshots
are consistent and show no measured-call errors. SD read/write peaks are
60/460 ticks; public file peaks 380/460. No SD calls and 93 public calls were
unmeasured, counted once per scope. Host bounds put 460 ticks at 459.949–460.071 ms.

That roughly **460 ms write exceeds both 128- and 256-slot histories**. Compiled
sizing rejects 345 slots; the next supported size, 512, needs 280,031 arena
bytes, more than the observed free heap before a worker stack/task. These are
ordinary native call timings including waits/scheduling, not a measured added
worker blackout or physical completion. Revise the owned-memory/storage strategy
and measure actual service/occupancy/catch-up before selecting the final budget.
See the [performance findings](../../docs/research/capture_performance_findings.txt).

All 37 prior evidence hashes and earlier audio metadata were preserved. The
card was safely unmounted, transfer mode exited, and original pad file,
One-shot mode and level restored. Normal controls pass; current heap is 163,104
and historical minimum is 160,664 after transfer/remount/restoration. The image
continues running with untried status, no worker and no extra capture.

This trial tests whether the L6 can spare the proposed recorder memory during
ordinary recording and sound-pad playback. It retains experiment 05's timing
measurements. It adds no audio tap, worker task, file operation or pad change.

The mixer boots normally with no reservation. After the official Editor connects,
one explicit host command can reserve three unused blocks through the original
allocator:

| Purpose | Requested bytes | Normal split-case heap charge |
| --- | ---: | ---: |
| Current 128-slot capture arena | 77,279 | 77,288 |
| Experimental worker stack allowance | 16,384 | 16,400 |
| Native task object allowance | 148 | 160 |
| Total | 93,811 | 93,848 |

The arena request is derived from the current compiled capture ABI and checked
against the compiled sizing function. The two worker blocks reserve capacity;
they do not create a worker or test its stack/scheduling. Successful allocations
are held until reboot and their payloads are never cleared or used.

Admission requires an initialized heap, running scheduler, current task, no
existing scheduler suspension and clear BASEPRI/PRIMASK interrupt masks. Handler
context is rejected. One weak atomic claim admits at most one attempt per boot;
a missed claim does no allocation and remains untried. Accepted failures are not
retried automatically. Native scheduler suspension covers the preflight,
allocations and rollback. The original nested allocator/free and outer resume
remain responsible for their normal scheduling behaviour.

The experimental remaining-heap floor is **65,536 bytes**. Preflight requires
159,432 bytes free: the 93,848 normal charge, 48 bytes for three unsplittable
remainders, and the floor. A post-allocation check also enforces that floor.
Insufficient headroom performs no allocation; partial allocation failure frees
only these unpublished blocks in reverse order. Freed blocks restore current
free bytes, but allocation/free counts and the historical minimum can change.
This floor is an admission safeguard, not a proven later-stock reserve.

Prepare and verify using the dependencies in [setup](../../docs/setup.md):

```sh
python tools/firmware/build_reservation_probe.py
python tests/emulation/verify_reservation_probe.py
```

The private image is
`deployment/06_reservation_probe/trial_reservation_probe/L6.BIN`. SHA256:

```text
c06f9d567eae7880fc704852e4f34d8053e55f13af7ce269056c4828baeb69b7
```

Code and state occupy 2,624 bytes in the original MAIN/DSP-tail span, with 480
bytes of state including the unchanged 444-byte timing state and alignment.
No startup hook is added. Fifteen offline groups check exact image boundaries,
all eight original startup outputs, compiled ABI, read-only status, real native
allocation/rollback/fragmentation, all three unsplittable remainders, context
refusal, once-only admission, concurrent status, native pending PendSV handling,
strict messages, protected reply copying and unchanged native file/SD results.
The previous health/timing images retain their exact hashes and pass all 25
groups; the native heap-backed capture suite passes its 14 groups.

After exact staging/readback and safe unmount, use the established manual
[update procedure](../01-usb-name/README.md). Reboot normally and reconnect the
Editor. Read status before sending the explicit reservation command:

```sh
python tools/device/l6_reservation_probe.py --output deployment/06_reservation_probe/status-01.jsonl
python tools/device/l6_reservation_probe.py --reserve --output deployment/06_reservation_probe/reserve-01.jsonl
```

Use fresh logs. Default invocation reads status only; `--reserve` is a mutation.
Requests use command 79, replies 78: kind 1 reads status, kind 2 attempts the
fixed reservation. There is no arbitrary size/address, release or reset command.
Existing 7B/7A timing queries are unchanged. Status-before/status-after agreement
with a non-busy status distinguishes completed observations from partial ones.
Elapsed ticks cover the protected reservation work, excluding the final native
resume and any subsequent scheduling delay.

For workload tests, collect a fresh baseline and record for about three minutes
with looping backing and live input 3. Report the start immediately so host
readings cover the recording, then report completion and listening observations.
Verify all saved master/stem files and restore the original pad 1 assignment
and One-shot mode afterward. Keep earlier recordings preserved. Stock swapping
between working trials is deferred by user choice. A normal reboot releases the
unused reservation and leaves this same trial installed with status untried.

This tests reserved capacity under stock load. It does not select the final
buffer, establish extra-file throughput, measure an added worker's stack or prove
physical SD completion/storage transitions. The first functional capture trial
still requires those bindings. Recovery from a broken image remains unproven.
