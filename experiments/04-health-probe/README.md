# Memory and SD timing probe

**Result, 6 October 2026:** after the user-reported update/reboot, all three
diagnostic queries answered on the mixer. The editor reconnected after relaunch
with firmware 1.10 and the existing pad assignments. Normal MIDI ports remained
available. Post-recording counters now show write activity and unchanged heap
free/minimum. Both short takes have valid, aligned master and channel files.
The pad test contains the backing in the master without a substantial coherent
copy in the channel files; the user reported no audible problems. Restoration
from this working diagnostic trial to untouched stock is verified.

This diagnostic trial reports the original allocator's available and minimum
free memory, allocation counters, the system tick and selected existing card
state. It counts ordinary SD reads/writes and reports the latest native return,
latest duration and longest observed duration for each of the two packet units.
These measurements will help choose an overdub buffer size.

Overdub capture remains disabled. The probe adds no task, allocation, audio file,
SD request, recovery command or pad assignment. Normal recording and playback
continue through the original routines. The additional persistent state is 56
bytes. Timing includes native waiting and task scheduling. The observed tick
rate is approximately 1,000 Hz, measured against host time over 61 seconds.

The trial packs the unchanged 55,004-byte DSP source into 36,172 bytes and uses
the original startup decompressor to restore it. Probe code and state occupy 984
bytes of the unused source tail, inside the original MAIN payload length. Only
the DSP scatter helper, two four-byte entry branches, that source span and the
package checksum change. No new scatter record or separate BSS is introduced.

Staging preserved an exact local backup of the previous stock update file.
`ZOOM_L6.SYS` remained byte-identical, and metadata for all 58 inspected recording
and pad files stayed unchanged. The binary and card report remain private local
artifacts. The staged image was read-back verified before safe unmount and the
physical update. Live replies confirm diagnostic execution; installed flash
bytes were not read back.

Three idle sample sets reported 163,104 bytes free and the same minimum free
space, 203 allocations and one free. Packet unit 1 had 573 observed reads, no
writes or skipped observations, and a successful latest return. Its longest
observed call was 66 ticks, approximately 66 ms. Unit 2 had no observed data
transfers. Heap and SD counters stayed unchanged across the idle queries.
Clock calibration bounded the rate at 999.59–1,000.59 ticks per second; durations
also have tick quantization. These are idle/startup observations, not recording
write performance, historical error coverage or worst-case timing guarantees.

After the user completed the requested normal recording and stop, the counters
showed 187 additional measured reads and 300 additional measured writes compared
with the final idle baseline. Heap free/minimum remained 163,104 bytes; allocation
and free counts each increased by one. The combined read/write maximum grew to
142 ticks (approximately 142 ms), and the latest native return was successful.
One call went unmeasured. The observer skips when its slot is busy or a weak
atomic claim fails; these counters cannot distinguish the cause. Unit 2 still
had no measured transfers. Counts cover the interval between queries and are not
scoped to one take; the peak's read/write identity is not recorded.

After recording with pad 1 playing, the next query interval added 321 measured
reads, 299 measured writes and three unmeasured calls. The cumulative maximum
remained 142 ticks; heap free/minimum stayed at 163,104 bytes. Allocation and free
counts each rose by two, and the latest native return was successful. There are
now four cumulative unmeasured calls, so timing coverage remains incomplete.

The saved takes lasted 18.59 and 19.13 seconds. All seven files in each take are
valid 48-kHz, 32-bit float WAVs with matching frame counts and finite samples.
The first master is explained by the separate channels. In the second, fitting
the existing backing plus channels explains more than 99.9999% of master sample
energy, while channels alone explain only 30.69%. Backing-to-channel absolute
correlations are below 0.04. This supports the expected master/stem separation
for this brief test; it does not exclude every subtle artifact or acoustic bleed.
The backing starts about two seconds into the second take, reflecting the manual
test sequence rather than a measurement of device latency. Local evidence copies
were byte-verified against the card; the recordings and pad files were unchanged.
This is not full-song or endurance validation, nor added capture functionality.

Untouched stock was staged with exact readback verification and a local
backup of the diagnostic update file. Settings remained byte-identical, all 72
recording/pad file metadata entries stayed unchanged, and the 15 evidence files
still matched byte-for-byte. The card was safely unmounted; transfer mode exited,
the editor reconnected with the same pads, and all three normal MIDI ports
returned. After the user completed the physical stock update/reboot, fixed
ordinary pad queries answered before and after a three-second diagnostic heap
query timeout. All four assignments matched and all three normal MIDI ports
remained available. The editor showed firmware 1.10 and the same pads. This
positive-control check, together with exact stock staging and the user report,
verifies restoration from the working diagnostic trial. Flash bytes were not
read back; it does not establish recovery from a broken firmware image.

The proposed 128-slot history holds 170.67 ms at 48 kHz, only about 29 ms beyond
this measured peak. Incomplete timing coverage, later latency spikes and added
capture I/O prevent treating that margin as sufficient. Aggregate free heap
also does not prove contiguous allocation capacity or additional worker reserve.
Capture remains disabled. Next investigate additional worker reserve,
a justified history budget and physical SD completion
before preparing capture firmware.

Prepare and verify locally:

```sh
python tools/firmware/build_health_probe.py
python tests/emulation/verify_health_probe.py
```

See [setup](../../docs/setup.md) for dependencies and vendor input. Images and
local reports remain under ignored `deployment/04_health_probe/`. Trial SHA256:

```text
383ce93268c0a2f865d68667ecbb49261bedac07f66e64e172652dd063ca23cd
```

Thirteen offline check groups cover exact allowed image changes; original DSP
decoding; entry and all eight stock scatter initializers; the bounded source
reference audit; original heap counters; strict host decoding; existing editor
messages; malformed requests; original MIDI reply copying; SD calls and timing;
counter wrap and overlapping calls; ordinary native file/SD behavior; and a
retained error with a concurrent diagnostic query. Normal native sector requests
and resulting file bytes match the baseline. RTOS, DMA, completion and sectors
remain fixture inputs. This is separate from the 612-group capture regression.

Use the established [physical update procedure](../01-usb-name/README.md) after
exact card readback verification and safe unmount. After a normal reboot, connect
the official L6 Editor before sampling:

```sh
python tools/device/l6_health_probe.py --output deployment/04_health_probe/idle-01.jsonl
```

The host sends only three fixed diagnostic queries; it does not start recording
or playback. Each log must have a new filename. Collect idle observations, then
observations during and after ordinary recording and pad playback. Check for
missing responses, uninitialized heap state, skipped SD observations, errors and
memory pressure. A reply with an odd or changing epoch indicates an incomplete
observation. Matching even epochs describe observer consistency only.

Only the latest native return is retained; a later success can hide an earlier
error. Total free heap does not establish a sufficiently large contiguous block
or the reserve needed during recording/playback. Native SD return and elapsed
time do **not** establish physical completion,
cache visibility or permission to recover/reuse buffers. The source audit cannot
exclude every computed pointer or bootloader consumer. This specific packed
diagnostic addition executes on hardware, while full DSP/audio behavior, stack
headroom and timing effects under longer or additional capture load still require
checks. Recovery from broken firmware remains unproven. Stock restoration from
this working diagnostic image is verified, as described above.
