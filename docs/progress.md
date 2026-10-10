# Progress

Goal: Allow for an overdubbing workflow using just the L6 hardware.

The latest independent work adds a [concrete startup witness](research/storage_boot_findings.txt):
successful initial card setup and a matched USB request, consumption and acknowledgement
must all precede logical readiness. Nine offline groups pass, including stale replies
and native instruction preservation. This condition now gates the optional lease's
admission, while physical storage permission and capture release remain disabled.
The [next trial](../experiments/17-dormant-boot/README.md) is prepared locally to
load the full payload and create a sleeping worker. It has not been staged or installed;
diagnostic16 remains on the mixer. The trial adds no extra recording traffic.
Four further checks execute the original task allocator and its failure cleanup:
the arena, stack and task object consume26,456 additional heap bytes. Runtime
stack headroom and loaded service performance still require hardware measurement.

The card holds disposable test recordings. Routine firmware staging checks the
firmware hash/readback, settings and basic file metadata; skip full audio scans.
Read selected audio files when needed to answer a specific test question.

1. **Workflow defined.** Keep clean input recordings and the ordinary master; make an additional stereo recording for reuse on a sound pad.
2. **Firmware investigation substantially complete.** Recording, audio routing, file handling and pad assignment have been traced. Detailed findings are in [research/](research/).
3. **Simplified offline design implemented.** One history ring, 4-KiB staging, one file worker and an optional single-pad handoff. Completed takes are reused without copying audio. Temporary-file naming, safe publication failure recovery and coalesced read notifications have regression coverage. Handoff fence/seal ports remain modeled.
4. **Modified data deployed and restored.** The USB name changed from L6 to T6, then returned to L6 after reinstalling stock firmware.
5. **Modified instruction deployed and restored.** The USB name changed to ZOOM L6 through a one-instruction patch, then returned to L6 after reinstalling stock firmware. Both marker trials now have verified restoration.
6. **Added code deployed and restored.** The eight-byte detour trial produced ZOOM L6 after reboot, then stock restoration returned it to L6. USB identifiers, MIDI ports, editor connection and existing pad assignments were checked. All three marker trials now have verified restoration.
7. **In progress: capture-first integration.** One minimal offline build now combines startup/audio/control hooks, heap-owned control objects and 1024 history slots across eight fixed lane tails. Startup registers the worker and leaves it asleep. Exact offline eight-file recording, wrapping, stalls, stop, failure and rearm pass. Hardware guards have survived recording, playback, transfer and all five effects with extra capture disabled. Physical memory/alias ownership, storage admission/transitions/completion, startup release and measured worker stack/timing remain deployment gates; this buffer geometry is not yet a proven service budget.
8. **Test progressively on hardware.** Additional stereo capture, automatic pad assignment, then repeated overdubs.
9. **Validate the complete workflow.** Timing, audio integrity, clean stems, preserved masters and failure handling.
10. **Package the finished firmware.** A tested image and installation/restoration instructions, once the preceding steps pass.

The [latest Astra review](research/astra_path_forward_review_20261009.txt)
finds no new corrective code defect within the documented offline scope and
recommends keeping pre-compressor capture as the user's preferred design.
Its memory footprint is plausible: 540,672 bytes reclaimed from native recording
tails plus approximately 26.5 KB for the arena, worker and stack. Integrated code
fit, physical ownership and the extra 384,000 B/s of storage traffic remain
unproved. A [combined capture/Main/SD build](research/capture_sd_retained_findings.txt)
now contains the retained-fault storage guards. Its 27,248 bytes of code and
272 bytes of globals exceed the original compressed-source budget by 3,524 bytes.
The alternative LZ4 loader leaves 2,168 bytes spare, including its 512-byte helper.
Missing source permissions still prevent this combined build from running;
there is no capture update image.
The [isolated loader diagnostic](../experiments/15-loader/README.md) now boots
on hardware and passes automated pad playback, preserving settings and free heap.
It loads the unchanged original DSP into its original destination; it does not
qualify the proposed extra code/global memory or the finished combined image.
The latest full regression passes 882 groups across 82 suites, including the
[storage-generation gate](research/storage_lease_findings.txt). It covers manager
steps, cancellation and automatic next-TMP preparation, with nonblocking
close/join and retirement until reboot. Five Main receive sites now retain the
whole request before storage-sensitive handlers, with storage-only shutdown
independent of delayed ordinary control callbacks. Trusted native setup,
remaining ingress/lock dependencies and physical completion remain unbound.
A [native ingress audit](research/storage_ingress_findings.txt) now fixes a mismatch:
the delayed USB commands ignore subtype in stock firmware, so our guard now does
too. Five groups verify native routing and pending-file ordering; a bounded ledger
classifies44 direct callers. Four USB startup groups identify the actual
request/acknowledgement boundary and show why a requested mode alone cannot grant
storage permission.
Five additional [cold-start checks](research/native_startup_boundary_findings.txt)
identify a native successful mount/folder branch and show why special setup modes
must be excluded even if they later reach the normal Main loop. Worker release
remains disabled until physical storage admission is bound.

Three continuous-startup checks pass against the same combined ELF:
original decompression, cache/MPU setup and dormant worker registration execute
in sequence. They are included in the full regression above, together with ten
startup-enumeration guard groups. The regression includes a fix that permanently retains a
possibly partial SD transfer when block-gap stopping is observed; later clear
registers cannot turn it into a complete transfer. See
[the block-gap findings](research/sd_block_gap_findings.txt).

The [source-reuse layout](research/capture_source_reuse_findings.txt)
passes ten groups within that regression. It expands the DSP first, then reuses its consumed
input for the combined code and globals, leaving 2,054 packed bytes spare. This
avoids placing those objects in unconfirmed free gaps. The bounded reference
scan finds no confirmed later consumer; indirect uses and full-payload publication
still need qualification. The separate marker diagnostic16 passes73 offline
checks and now runs on hardware. Its eight-byte function executes from consumed
DSP input, reports0x4c36, and verifies16 zero bytes and the expected scatter records.
Instruction/data caches are enabled; original pads/MIDI/health and startup trace
pass. Automated pad playback matches the source at0.999027 with no host callback
errors,1,163 native data waits and no new detail conditions or omissions. Free
heap remains163104 bytes; comfortable levels are preserved. Staging preserved
settings and156 file metadata entries without audio scans. This qualifies the
tiny publication path, not the full capture payload. Diagnostic16 is installed;
extra capture remains disabled.

Ten [SD cold-start groups](research/sd_cold_start_findings.txt) execute original
controller setup and default/high-speed card enumeration. They identify startup
FIFO reads outside the block guard and reproduce false-success event flags in a
controlled model. The [expanded passive startup diagnostic](../experiments/14-sd-startup/README.md)
passes66 offline groups and now runs on hardware. Its frozen trace includes all
six startup reads, with31 command entries,43 IRQs/waits and zero omissions,
skipped observations or observer errors. The reads identify status, SCR and the
four CMD6 check/switch operations of high-speed negotiation. Reset is clear by
first-command entry; the earlier reset observation was too soon. This completes
the passive startup question, not physical source exclusion or capture admission.
Original pad names/counts, MIDI and retained health checks pass after reboot;
free heap remains163104 bytes. No audio test was performed in this check.
Staging preserved settings and156 file metadata entries without audio scans.
The original diagnostic image remains byte-identical and passes65 groups.
The subsequent full capture run passes836 groups/75 suites.

The [physical-capacity investigation](research/physical_ram_capacity_findings.txt)
now has hardware confirmation of one enabled **32-MiB SDRAM decode window**,
with a 16-bit bus, nine column bits, four banks and refresh enabled. Three queries
and their paired snapshots all agree. DTCM/ITCM mappings are 128/32 KiB; fuse
selection means GPR17 is not claimed as the active full bank map. The passive
diagnostic passes 42 offline groups (seven new, 35 retained) and responds after
the user's update/reboot. All 149 recording/pad files and settings were verified
unchanged during staging; original pads, MIDI ports and retained diagnostics
pass after reboot. Current/minimum free heap is 163,104 bytes and extra capture
remains disabled. Installed flash bytes, physical chip density and complete RAM
ownership remain unconfirmed.

The [gap ownership follow-up](research/ram_gap_ownership_findings.txt) adds a
bounded derived-address scan and 35 passing offline checks. The adjacent USB
constructor/table and largest startup queue stay outside the gaps in the tested
paths. Three follow-up cases extend the USB setup copy into its fixed native
buffer, outside both gaps. The subsequent
[USB provider audit](research/usb_memory_providers_findings.txt) passes 75 focused
groups: all eleven stock profile selections and the complete descriptor builder
stay in fixed memory outside both gaps. Six original worker configurations supply
five buffer ranges in internal DTCM; their pointers are traced through the native
installer and audio-state constructor. A further 22 focused groups cover native
format-dependent ring lengths and wrap operations across the recovered profiles;
endpoint transfers and physical aliases remain unresolved. Both apparent
gap constants resolve to Japanese character data via
the original decoder. No confirmed gap consumer was found, but indirect uses,
DMA, other pools and bootloader behavior remain unresolved. The upper 872-KiB
gap could hold the current 540,672-byte history in contiguous storage and allow
the ordinary five-second buffers to remain intact if qualified. No layout or
device change was made by that audit. The subsequent
[passive activity diagnostic](research/ram_activity_probe_findings.txt) passes
53 offline groups against its exact image, including all 42 prior checks. It
reads the upper gap in 872 fixed 1-KiB pages, twice per query, without writes or
reservation. Card staging/readback, safe Eject and transfer exit are verified;
the Editor, existing pads/MIDI and retained diagnostics pass. The user's update
and reboot are followed by new-query execution and two agreeing full idle sweeps.
Two automated pad plays cover disjoint halves of the gap; all 872 fingerprints
match idle. USB audio identifies both backings with no host callback errors.
Per-page reads span zero or one timer ticks, and current/minimum free heap stays
163104 bytes during recording/playback. A 165.251-second multitrack take adds
full gap coverage across two observation windows; all fingerprints match idle,
as do full sweeps after stopping and after normal card transfer. Only the first
backing is verified in USB and saved MASTER audio: the master becomes silent at
34.956 seconds, consistent with the user's reported level/mute change. The second
backing remains unconfirmed. All seven WAV headers have equal frame counts;
only the new MASTER audio and small headers were read. Normal transfer exit and
pad restoration pass; free heap returns to 163104 bytes, with a 160664-byte
low-water mark after transfer. A further full sweep during user-reported song
playback agrees, corroborated by SD reads without writes; its silent USB master
does not verify song audio. All five effects now have distinct measured audio
responses, and six full sweeps (including restored Room) match idle. Room's
restoration is audio-verified. No additional SD traffic or host audio errors
occur during the effects test, and heap figures remain stable. Remaining memory
providers, aliases and unexercised transition paths still need qualification.
The post-write full audio scan was stopped
at the user's request; settings and all 149 file metadata entries are unchanged.
Extra capture stays disabled. Unchanged CPU-visible fingerprints
cannot prove ownership or exclude cached/DMA/read-only uses; destination tracing
remains necessary before reserving that space.
The [effects provider follow-up](research/effect_memory_providers_findings.txt)
now executes all five original engines with nonzero simulated audio responses, 4,808 native
parameter updates and their delayed enable callbacks. Five focused groups find
no access to the candidate gaps or shortened ring tails in the tested paths.
This bounds another provider family without claiming physical ownership.

The [per-chunk SD guard](research/sd_chunk_guard_findings.txt) now checks completion
inside each of the four native block-data waits, before a bounce buffer is copied
or refilled. Sixteen new offline groups verify pending completion, split transfers,
error retention, cache ordering and capture metadata/payload/readback. A prior
chunk's software latch cannot release the next chunk. The completion provider
remains modeled, and a negative control still accepts a late physical interrupt
when that provider falsely reports success. Source exclusion before address
programming and actual hardware completion therefore remain unbound. The guard
is opt-in and excluded from normal profiles; no firmware was installed.

The [native admission follow-up](research/sd_chunk_admission_findings.txt) now
protects entry before the first temporary-buffer fill and each subsequent address
write. Sixteen offline groups verify real event/token draining and a compiled
nominal host-completion predicate, including capture metadata, audio and readback.
Pending admission retains file/worker frames during cancellation. The source lease
still requires the outer card/USB gate and old-source exclusion; neither status
clearing nor the new predicate establishes those contracts. No device image is
enabled by this milestone. The full runner passed 761 groups; the new suite then
passed again with one additional native filesystem metadata group against the
same compiled fixtures, bringing the consolidated total to 762.

The [Main binding](research/storage_main_findings.txt) now retains the complete
received request on Main's stack, leaving later packets in the native FIFO.
Eleven storage-shutdown groups and eight Main-binding groups pass, including
32 pending-I/O/dispatch combinations and uncertain-close retention. A separate
three-group audit reproduced a dependency between ordinary control retirement
and Main; storage-only shutdown now avoids it while retaining control objects
until reboot. The original transition executor remains an offline test seam.
The latest full run passes all 824 groups across 74 suites. These are emulator
bindings; there is still no capture update image or installed capture worker.

Four additional [USB-source groups](research/usb_storage_sources_findings.txt)
bound the known worker notification to SD-capable USB modes. Seven additional
[audio-processing groups](research/tap_processing_findings.txt) execute original
effects-return mixing, gain ramps and active master dynamics: effects reach the
tap while master processing stays downstream. The effect engines and input
samples are supplied by the test, so actual extra-file audio remains unverified.
The initialized stock master body also shows a 48-frame delay at 48 kHz with
compression off; future audio comparisons must account for that 1-ms offset.
These focused groups are separate from the full-regression count.

The [detailed SD diagnostic](research/sd_chunk_observation_findings.txt) now runs
on hardware, passing 13 separate offline groups while preserving the original
image and its ten groups. Automatic MIDI pad triggering is verified in USB
audio. The subsequent 179.196-second ordinary take has seven valid, finite,
aligned files. Its 12.972-second one-shot backing is identified in MASTER at
source correlation 0.99999987, with no backing detected in mostly quiet input
stems. The user heard the backing and reported no audio problems. This is not
a full-song simultaneous playback trial or a substantial new live layer.
All 65 prior saved audio hashes, 121 prior metadata entries and settings are
preserved; normal Eject, transfer exit, Editor connection and original pad
names/counts are verified.

The stopped recording interval adds 4,896 waits, no omitted chunk observations
and 948 detections, all on writes. Their only observed reason categories are
data inhibit and data-line activity; retained write samples show DAT0 low with
transfer-active bits clear. NXP documents card busy after a write returns, so
this is consistent with trailing card activity. Raw completion/error identity
and cache ownership remain unresolved; these observations do not establish a
physical-completion provider. Broader SD observations omit one call; stopped
current/minimum free heap is 163,104 bytes. The later transfer/hash/remount
interval is recorded separately. No additional capture is enabled.

Next close remaining Main/native lock and ingress dependencies,
resolve concrete SD source/completion ownership, and qualify memory/cache spans
with an early combined size check. Then measure one capture-only candidate in
short and whole-song hardware trials. Automatic pad assignment follows reliable
capture; automatic remount/recovery remains deferred. MASTER is a fallback if
qualification makes pre-compressor capture impractical, with its ordinary
take-folder file preserved.

The [native cache audit](research/sd_cache_contract_findings.txt) now decodes
the stock memory map and read/write maintenance. Proposed buffers use cached
RAM. Fifteen offline groups verify a small post-read invalidation experiment,
including stale-cache, advanced-address, missing-completion and error cases.
It remains outside device builds: physical transfer joining and exclusive
buffer ownership still need binding before capture can be enabled.

A separate [raw SD interrupt diagnostic](research/sd_raw_observation_findings.txt)
is prepared and passes 23 offline groups. It captures completion/error bits
before the original handler acknowledges them, together with cache and fast-memory
settings. It preserves the original interrupt handling, detailed wait observations
and ordinary buffer capacity. The exact image is now staged/readback verified;
all 128 recording/pad files and settings are preserved. Normal Eject, transfer
exit and original Editor/pad replies pass. The user's update/reboot is followed
by fresh raw/detail/health replies confirming execution. Startup and automated
18-second pad playback have zero raw errors/omissions, 1163 additional DMA-mode
TC/read-wait observations and verified USB backing. The hardware readings resolve
the native bounce CPU cache path; heap and original pads are unchanged.
Recording-write observation is now available. Two ordinary takes (136.905 and
201.279 seconds) have fourteen valid, finite WAVs, aligned within each take.
The first ends before the first pad trigger; the restarted take contains backing
and substantial input-3 notes, with no strong coherent backing in its separate
stems. Its 12.972-second backing window matches the captured USB master/stems
within 4.657e-10 per sample. Listening quality is uncertain following the user's
correction. The stopped interval adds 12776 native waits and DMA-mode TC samples,
zero raw/detail omissions and zero raw errors. Ninety-six live pages retain
sampled write-mode TC status with no errors; they do not establish command
generation or owner. Detailed write detections still contain only inhibit/line
activity, while the broad observer omits eight calls and reaches 648 ticks.
Stopped current/minimum heap is 163104 bytes. New local audio hashes, unchanged
prior metadata/settings, normal Eject, transfer exit and original pad replies
pass; the transfer interval is separate and prior audio hashes were not repeated.
Extra capture remains disabled. Next bind completion/generation and exclusive
buffer ownership beneath audio and metadata IO, then qualify storage transitions,
memory and worker capacity before a capture-only deployment.

The [command/buffer diagnostic](research/sd_command_observation_findings.txt)
is now prepared locally and passes 35 separate offline groups. It observes the
original buffer before each native address write, command task/event/length,
raw IRQ status and native wait outcome. All four read/write paths preserve
tested stock behavior; earlier diagnostic images rebuild byte-identically.
A deliberately late prior-origin IRQ can still look clean, so this journal
does not grant physical completion or exclusive ownership. Exact staging/readback
now passes with all 142 audio/pad files and settings preserved. Normal Eject,
transfer exit, Editor reconnection and original pad/MIDI/heap checks pass.
User-reported update/reboot and new-protocol replies now verify execution.
Startup records 1200 block commands and waits, with one explicitly missed
command observation. Automated pad playback matches the backing in USB audio
and adds 1163 matched programs/commands/waits and raw TC indications, with no
raw/detail errors or omissions. Two more command observations are omitted;
coverage stays partial. Six live pages fall within the backing window. Original
pads/MIDI ports and heap pass. The subsequent 262.787-second ordinary take has
seven valid, finite, aligned WAVs. Backing is identified in MASTER alongside
substantial live input, with no strong matching backing in the stems. All twelve
channels of the full 18.005-second USB capture agree with the saved files within
4.657e-10 per sample. The user reports audible backing and no audio problems.
The stopped interval adds 6579 programs/block commands/waits and DMA-mode TC,
including 4880 writes, with zero raw errors or raw/detail omissions. Five command
observations are omitted; its conditions are partial evidence, and detailed write
conditions contain only inhibit/line activity. Existing metadata/settings/pads,
normal Eject, transfer exit and Editor reconnection pass; prior audio hashes were
not repeated for this inspection. Heap is 163104/163104 before transfer and
163104/160664 afterward. The passive workload check is complete; next bind
physical completion/source exclusion and exclusive buffer/cache ownership beneath
audio and metadata IO. No new audio stream is enabled.

The current [architecture](architecture.md) supersedes the broader integration
plan below. `python tools/firmware/verify_redesign.py` builds the isolated profiles
and reruns the affected regressions. The one-pad controller is connected to the
serialized worker in offline tests. It preserves old takes, verifies rollback on
safe failures, and quarantines uncertain ownership without a Main-loop gate.
The first eventual hardware milestone is capture-only; automatic pad handoff
comes afterward. No installable extra-capture image was produced for this redesign;
the separate passive diagnostic has supplied the hardware observations above.

The [capture-only milestone](research/capture_integration_findings.txt) now saves
4 KiB by reusing drained staging for readback and removes bulk history clearing
between takes. Five new composition groups verify an exact extra TMP alongside
seven byte-identical ordinary files, including optional-failure cases. The
reproducible binding proposal inventories code/RAM/stack sizes and startup/hooks;
candidate addresses are not approved device allocations.

Redesign regressions include two readers sharing one coalesced notification,
single-authorization startup, exact batched audio, repeated one-pad handoffs,
safe rollback, uncertain rollback quarantine, cancellation and release contention.
The two follow-up review defects now have explicit regression coverage: a failed
settings close retains the unresolved handle and blocks release, and assignment
and rollback both require successful exact-length initial audio reads. Tests run
the original loader/prefetch and the real early-close failure branch; they no
longer stub the initial read or assume a failed close freed the handle. The
optional handoff uses synchronous initial reads while fenced; the device fence,
close-hook installation and full device lock audit remain integration work.
The subsequent [bounded lock audit](research/handoff_locks_findings.txt) adds six
groups executing original prefetch, filesystem lock helpers and task-context
setup. The examined path supports synchronous reads by our worker, provided the
gate leaves scratch/filesystem locks and completion contexts available. Gate
acquisition and release rules are now explicit. Full device locking, admission,
SD/DMA completion and recovery remain unproved.
The [admission map](research/handoff_admission_findings.txt) now ties 35 relevant
entries and 86 bounded direct references to their completion requirements. Five
new groups show why capture-drain acknowledgement and a BUSY return from pad
start cannot provide the missing gate. The subsequent
[pad-command component](research/pad_commands_findings.txt) queues complete
commands without parking Main and replays them in order after release. Twelve
new groups cover original press/release, toggle and Record branches, contention
and retries. Raw arguments do not preserve mode/Record state: a negative control
demonstrates that changing mode changes replay behavior. Dispatcher ownership,
overflow, wake/retry and ordering of conflicting controls remain the next slice;
the device gate remains unimplemented. The
[Main dispatch audit](research/pad_dispatch_findings.txt) then reproduced why a
direct raw-handler binding is unsafe: it bypasses stock duplicate deletion and
changes repeated-press behavior. Eleven new groups also exercise actual Main
routing, receive ownership and queue saturation. The next boundary to investigate
is full event ownership; no raw-command dispatcher hook has been enabled.
The following [between-events experiment](research/native_event_window_findings.txt)
preserves stock duplicate handling by leaving input in the original queue and
running prior completions first. Ten new groups also expose stock full-queue
blocking. The private FIFO is now excluded from the normal handoff build. Native
scheduling remains unbound pending complete dependency coverage, manager
ownership, wakeup and fault recovery; the existing worker is unchanged. The
[storage dependency audit](research/handoff_dependencies_findings.txt) now runs
checked handoff and original SD commands/event waits on one CPU fixture. Seven
new groups find no Main/UI-mutex dependency on the examined read/write paths,
but reproduce unsafe reliance on timeout return as completion evidence. Native
SD completion/error observation and checked cancellation remain prerequisites.
The following [SD completion audit](research/sd_completion_findings.txt) executes
the actual clock helper and command-error reset paths. Nine new groups establish
that clock stability is not transfer idle, operation-5 cleanup requests no reset,
and a stuck command reset returns the same error as a completed reset. Raw IRQ
observation before acknowledgement preserves errors lost by stock event mapping.
Checked cancellation must join the lowest driver before its buffers unwind;
the handoff gate remains unbound.
The [scoped SD experiment](research/sd_transfer_probe_findings.txt) adds compiled
test-only guards at this boundary. Thirteen groups retain native stacks, direct
or bounce buffers and the SD unit token until an explicit modeled join. Whole
handoff tests also retain filesystem/scratch locks and prevent rollback or release
while recovery is pending. Final-status errors remain visible, and failed scopes
suppress later commands. Negative controls still expose stale completion identity
and completion without physical idle; actual cancellation remains unimplemented.
The [controller setup audit](research/sd_controller_setup_findings.txt) adds
twelve groups tracing transfer modes, reset/init callbacks and completion-event
creation. It corrects an earlier register label: MIX_CTRL is at offset 0x48;
the cleanup's offset 0xc0 write changes clock configuration. Native reset
callbacks can discard event handles and still report success after timeout.
Old completion status must be drained before setting a new transfer address.
Candidate NXP documentation also distinguishes aborting a transaction from
resetting the host; physical recovery remains unimplemented.
The [stop/card audit](research/sd_card_recovery_findings.txt) adds thirteen groups
and runs one stock stop command inside the retained failed read/write stack.
Stop success can still leave the transfer busy; only an explicit modeled join
permits unwind or rollback. Card reinitialization preserves the event handle
but accepts changed address/capacity without checking prior card or filesystem
identity. Checked abort/reset/idle and stale-event draining were the next slice;
the stop probe is excluded from normal profiles and the device gate stays unbound.
The [checked recovery experiment](research/sd_checked_recovery_findings.txt) now
adds sixteen groups. Compiled code checks reset self-clear, idle/busy state,
configuration, event identity and status draining while retaining the failing
stack. New admission runs after taking the SD token and before programming a
transfer address. Whole-handoff tests keep locks/gate held after reset until
explicit modeled physical/cache/card validity. IRQ serialization, kernel token
clearing and reset permission still require native/hardware evidence. Tracing
stock event creation/drain and IRQ ownership was the next slice; no device binding
or physical recovery guarantee has been added.
The [native-event experiment](research/sd_native_event_findings.txt) adds twenty
groups and replaces kernel clearing with original firmware routines in selected
offline tests. The actual constructor confirms an auto-clear event and binary
wakeup token; clearing flags alone leaves the token behind. New checks cover
IRQ disable/pending/rearm ordering, late arrivals, object/context faults and
read/write/whole-handoff ownership. Source/ISR/task-post exclusion, abort/reset
permission and physical/cache/card validity remain MODEL contracts. Tracing the
remaining completion posters and source exclusion was next; the device gate
remains unbound and hardware testing deferred.
The [source audit](research/sd_event_sources_findings.txt) adds eleven groups.
It traces known hardware and software SD notifications, including detach/USB
callers, and corrects test guards that accepted mixed success/fault flags. Late
hardware status can still appear after clearing and be attributed to a new
software scope. A second unit callback uses the same examined MMIO body; its
actual device configuration remains unresolved. Source exclusion and physical
abort/reset/cache/card validity still need evidence; no device gate is bound.
The consolidated redesign runner now passes 618 groups across 56 suites,
including build-profile isolation, command/dispatch/window/dependency tests,
the 15-group SD lifetime audit, nine SD completion groups and thirteen scoped
SD probe groups, twelve controller setup groups, thirteen stop/card groups and
sixteen checked-recovery groups, twenty native-event groups and eleven source
groups, the staging-reuse regression, five capture-only composition groups and
seven placement/jump groups, eight packed-loading groups and eight startup-jump
groups, eleven capture-storage groups, fourteen capture-transition groups and
thirteen capture-I/O lifetime groups, sixteen native-filesystem groups and
five native-filesystem/SD groups, thirteen native capture-file groups and twelve
native mount groups, twenty-two encoded-hook groups, eleven minimal-link groups,
eight native outer setup groups, eight native rename groups, fourteen heap-arena
groups, twenty-two native exFAT groups, six performance correction groups and the
expanded profile isolation checks. The original
queue audit's 14-group result remains recorded. All are offline;
no capture firmware image was prepared or installed by that regression.
An [Astra review at high effort](research/astra_correctness_simplicity_review.txt)
found no new defect within the documented contracts. It confirmed that physical
I/O joins, source exclusion and capture-only device integration remain unverified.
Its buffer simplifications are now implemented, and the concrete capture-only
binding plan and offline harness are complete with pad handoff disabled. Proving
code loading, RAM ownership and startup/storage authorization is the next device
integration work. Further modeled recovery expansion is deferred.
The [placement experiment](research/capture_placement_findings.txt) now relinks
a separate offline ELF and executes two actual RAM jumps with complete replay,
original scatter copying and stock DSP prologue/epilogue. Ordinary files remain
unchanged. Extended MAIN loading, global/RAM ownership and startup/storage
authorization remain unproved; no deployable image was constructed.
The [packed loading alternative](research/capture_packing_findings.txt) now
compresses DSP/capture sources inside the existing MAIN length. Stock entry and
scatter helpers expand both and zero capture globals before Main in the emulator.
All original startup outputs retain their expected bytes. Only 302 source bytes
remain, so each build must pass the size gate. Device ownership, interrupt/cache
behavior, manager/worker startup and storage/native I/O joins remain unverified.
The [startup-jump experiment](research/capture_startup_findings.txt) now executes
two actual MAIN detours and registers a sleeping worker on the original boot
stack. It retains the first initializer failure, waits for stock idle creation,
and preserves startup when optional registration fails. The separate fixture
still fits the original MAIN length, with 155 packed bytes spare. Its bounded
RAM scan retains all candidates and leaves physical ownership unresolved.
Storage release, remaining hook encodings and measured device RAM/heap/stack
behavior are the next integration requirements. No image was built or installed.
The [capture-only storage audit](research/capture_storage_findings.txt) now runs
the underlying mount and directory setup. It preserves evidence hidden by their
outer returns and reproduces teardown clearing metadata while a file write
retains the stock lock. This narrows the needed binding to storage transitions
and physical completion joins; ordinary recording/playback can coexist with the
new file. Storage release remains unwired pending that binding.
The [capture transition tests](research/capture_transitions_findings.txt) now
run native extra-file open/write/close around compiled cancellation. They keep
unfinished call frames and file tokens owned, and confirm ordinary recording
can continue after optional cancellation. They also reproduce software write
error reaching close without physical completion and show outer card/USB
routines discarding lower failures. This prevents using a mailbox-only guard
or a nominal busy return at detach. The next binding must preserve the extra
file's transfer/error lifetime before automatic release can be enabled. Capture
code, packed margins and device state are unchanged.
The [capture I/O experiment](research/capture_io_lifetime_findings.txt) now
composes original public read/write and native SD instructions with that same
capture-only manager and a separate test-only recovery ELF. Failures retain the
file, buffers and unit token before cleanup. An optional final completion port
also withholds nominal success when controller activity remains; an error-only
guard lacks that protection. Joins, sector mapping and reset permissions are
explicit fixture inputs. That composition retains the synthetic file router;
normal profiles and device state are unchanged.
The [native filesystem audit](research/native_filesystem_findings.txt) now runs
the original file drivers, FAT allocation and cache/close metadata instructions.
Its separate SD composition replaces the synthetic router with actual native
sector requests, including bounce copies and both FAT copies. Errors retain
file/unit tokens before native exception unwinding. A failed close can already
mark its handle unused and cache clean, so those flags cannot establish success
or safe retry. The following composition now supplies native creation/open;
mounted-card cache/allocator initialization is now covered by the following
FAT32 mount composition. Physical completion,
cache/source exclusion and outer storage admission are still unbound; no image
or device change was made.
The [native capture-file composition](research/capture_native_files_findings.txt)
now completes an exact private take through stock creation, finalization and
reopen/readback, including the original WAV parser. Its SD configuration retains
the whole compiled capture call before native error cleanup or nominal success;
ordinary audio and STOP continue on a separate fixture stack. Collisions preserve
existing files, and native close/readback failures withhold eligibility. The
following mount composition replaces its controlled ready-volume settings.
No production C code or firmware image changed.
The [native FAT32 mount composition](research/native_mount_findings.txt) now runs
the stock filesystem constructor, partition/BPB parsing, cache/handle setup and
allocation-map/free-count scan before capture creation. Both sector-callback and
original SD-driver configurations complete the exact extra take. The tested
paths derive free space from FAT entries without accessing FSInfo. A failed scan
can leave a partial map enabled, and mount can ignore a failed write-protection
query; neither flag nor mount success alone authorizes startup release. Card
bytes and initialized SD-card state remain controlled. Full card identity,
physical completion, cache/source exclusion and outer storage authorization are
the next integration requirements. No image or device change occurred.
The [encoded hook tests](research/capture_hooks_findings.txt) now execute all
fifteen selected MAIN/startup jumps and both DSP jumps, with complete original
instruction replay and register/FPU/stack comparisons. Original boot registers
a sleeping worker, and actual control jumps preserve exact native extra takes
and ordinary files in the fixtures. The
[native outer setup](research/native_storage_setup_findings.txt) creates all six
recorder/pad folders from an empty fixture card. Its application geometry policy
rejects a layout that the lower FAT32 mount accepts; readiness must retain that
distinction. The [native rename tests](research/native_rename_findings.txt) verify
no-overwrite TMP-to-WAV metadata changes without copying audio. A failed barrier
can follow an already changed filename, so seal errors cannot all be SAFE.
The [smaller build](research/capture_minimal_findings.txt) removes unreachable
research entry points without changing capture behavior. Its packed source has
2,924 bytes spare, compared with 119 in the full hook fixture. Normal capture,
placement and startup executable segments remain unchanged. Physical completion
and storage permission remain modeled; automatic release stays disabled.
The [subsequent Astra review](research/astra_capture_milestones_review.txt) found
one encoded queue-sender defect: its continuation skipped stock FIFO-mode setup.
That jump is corrected. New exact-continuation, four-argument and original-kernel
FIFO checks reproduce the old error and cover both encoded builds; shared queue
fixtures reject unsupported arguments. Minimal linker roots are grouped by
purpose and validated against the patch plan. These are offline changes.
The [remaining device gates](research/remaining_device_gates.txt) identify the
hands-on evidence needed next. The [tiny added-code trial](../experiments/03-added-code/README.md)
ran successfully and stock restoration was verified on 6 October 2026.
Capture-code packed loading, runtime memory ownership and physical I/O completion
remain unverified. No capture firmware image was prepared, staged or flashed.
The current writer state is 4,160 bytes; the handoff controller is 1,684 bytes.
These are compiled structure sizes, not measured total RAM/stack requirements.

The [heap-backed alternative](research/capture_heap_findings.txt) now allocates
runtime arenas/history/manager/worker through the original allocator in a
separate offline build. Fourteen groups cover exact extra and ordinary files,
exhaustion, overrun, later stock allocations, native task-allocation failure,
native FAT32 mount/file/SD composition and retained SD failure frames. Eight
existing profiles retain their loaded bytes. Device startup/global placement,
live heap headroom and physical storage completion remain unbound.
The [native exFAT composition](research/native_exfat_findings.txt) adds twenty-two
groups covering the format reported by the connected card. Original mount,
allocation, fragmented files, checksummed entries, readback, folder creation,
rename/collisions and failures run on virtual sectors. A heap-backed composition
also runs native SD instructions with 256-KiB clusters and preserves all seven
ordinary files.
The actual card's complete geometry/contents and physical completion remain
unverified; observed heap and SD call timings are recorded below;
automatic release and pad handoff are still unbound.
The separate loading trial was skipped at the user's request. A
[memory and SD timing probe](../experiments/04-health-probe/README.md) is now
prepared locally with capture disabled. It reuses the original DSP source span
and startup decompressor, adds 56 bytes of state, and reports heap counters and
ordinary SD call counts/durations through the existing editor MIDI route.
Thirteen additional offline check groups cover image boundaries, all eight
startup outputs, native reply copying, ordinary editor/file behavior and retained
SD errors. This separate diagnostic suite is not part of the 612-group capture
regression. The exact diagnostic image was staged, read-back verified and safely
unmounted with stock backed up locally. After the user-reported update/reboot on
6 October, all three diagnostic queries answered. The editor reconnected after
relaunch with existing pad assignments. Idle heap free/minimum was 163,104 bytes;
573 SD reads were observed with no skips, a successful latest return and maximum
66 ticks. Host calibration measured approximately one millisecond per tick.
This confirms execution of this packed diagnostic addition. After the requested
normal recording, counters showed 187 additional measured reads and 300 writes,
with heap free/minimum still 163,104 bytes. The combined SD maximum increased to
approximately 142 ms, latest return was successful, and one call went unmeasured.
The counter does not identify that peak as a read or write. The proposed 128-slot
history holds only 170.67 ms; the small margin and incomplete coverage do not
justify selecting it for capture. Recording with pad playback, audio-file checks,
stack headroom, physical completion and stock restoration were the next checks.
The subsequent pad-recording interval added 321 measured reads, 299 writes and
three unmeasured calls. Free/minimum heap and the 142-ms maximum stayed unchanged;
latest return was successful. Four calls are now cumulatively unmeasured.
Both saved takes (18.59 and 19.13 seconds) contain seven valid, aligned float WAVs
with finite samples. In the pad test, backing plus channels explain more than
99.9999% of master sample energy; channels alone explain 30.69%, and no channel
shows substantial coherent backing correlation. The user reported no audible
problems. This supports ordinary master/stem separation during this short trial,
not full-song stability or extra capture. Untouched stock was staged with exact
readback; settings and recording/pad files were preserved. After safe unmount,
transfer-mode exit and the user-reported physical update/reboot, ordinary pad
queries answered both before and after a three-second diagnostic query timeout.
Assignments matched, all three MIDI ports remained, and the editor was connected
with firmware 1.10. Restoration from this working diagnostic trial is verified;
no flash readback or recovery from broken firmware was tested.
Stack reserve, history sizing and physical completion remain unresolved. Total
free heap alone does not prove contiguous allocation capacity or reserve under
the future additional workload.

The [Astra performance and buffer review](research/astra_performance_buffer_review.txt)
on 7 October 2026 recommends keeping one history ring, one worker and shared
staging/readback. It found two reproducible performance issues: the staging
payload's offset forced three native data submissions for a full 4-KiB batch,
and the compiler target emitted software float multiplication. Both are now
[corrected in the offline builds](research/capture_performance_findings.txt).
No new correctness defect was found within the modeled contracts.
After the corrections, all 618 capture groups across 56 suites pass, along with
the separate 13 experiment-04 diagnostic groups. Including allocator charges and the experimental 16-KiB
worker stack/task, 128 slots leave 69,256 bytes against the observed free heap;
256 leave only 1,672. The former is a conditional measurement candidate, not a
reliable deployment budget. Measure complete worker service, ring occupancy and catch-up
alongside stock recording before choosing the final buffer. Physical completion,
storage authorization and startup binding remain independent requirements.

The next [timing trial](../experiments/05-timing-probe/README.md) is prepared and
passes twelve separate offline groups. It records separate SD read/write peaks,
histograms, earlier errors and request identities, distinguishes skipped
observations, and measures complete public file calls including lock waits.
Its integer-only code and 444-byte state fit in 1,756 bytes inside the original
MAIN length. No capture, allocation, task or additional SD request is enabled.
On 7 October the exact image was staged and read-back verified on the expected
card, then safely unmounted. Settings and all 72 recording/pad file entries were
unchanged; 15 saved evidence files also matched byte for byte. Transfer mode was
exited and ordinary MIDI queries confirmed the existing pad assignments and all
three ports. After the user-reported update/reboot, all seven exact-schema
diagnostic replies confirmed execution and the editor was connected. Idle
free/minimum heap remained 163,104 bytes; 579 SD reads and 266 complete public
reads had no errors or skips and maxima of 57/59 ticks. Host calibration bounded
the clock at 999.38–1,000.19 Hz. The longer recording test is prepared with the
original 71.405-second Glory Box backing on pad 1 in Loop mode. The post-preparation baseline
has no errors/skips, public read maximum 60 ticks and write maximum 7 ticks.
The saved take is 20.04 seconds: seven valid, aligned WAVs with finite samples,
backing in the master and low coherent backing correlation in input 3. The user
reported no audible issues. Post-recording counters have no errors, SD read/write
peaks 81/53 ticks and public file peaks 82/112 ticks. Nine public calls were
unmeasured; heap free/minimum remains 163,104 bytes. The 40 host polling sets
captured only idle counts, so observations rely on retained device counters.
Earlier audio entries were preserved and 15 prior evidence files matched byte
for byte. Pad 1's original file, One-shot mode and level were restored.
The user confirmed stopping that short take deliberately, then completed a
187.263-second repeat. All seven WAVs are finite and aligned; both backing repeat
periods exactly match the source length. The user reported no audible problems.
New audio copies passed hash verification, and all 23 prior evidence files remain
unchanged. Retained counters have no observed errors and unchanged cumulative
peaks; 105 additional public calls went unmeasured. Free heap is 163,104 bytes;
the 160,664-byte cumulative minimum already predates this longer recording.
No live host samples were collected, so no recording time series is available.
Pad 1's original assignment/mode/level are restored. Untouched stock is staged
and read-back verified, with settings/all 86 card entries unchanged and all 30
saved evidence hashes preserved. The card was safely unmounted, transfer mode
exited, and normal editor/pad/MIDI controls passed. The user chose to retain the
running timing firmware and defer restoration; the staged stock file is not
installed. Routine stock restoration is not a development gate. These are stock
workload timings; contiguous heap reserve, added
capture load and stack high-water remain unmeasured.

The next [memory-reservation trial](../experiments/06-memory-reservation/README.md)
is now prepared and passes 15 offline groups. It boots normally, then one explicit
command can reserve the exact candidate 128-slot arena and experimental worker
allowance through the original allocator. The expected charge is 93,848 bytes;
native remainder charges are accounted for, and the experimental remaining-free
floor is 65,536 bytes. Failure leaves the optional addition disabled and partial
allocations are freed. Successful unused blocks remain held until reboot; no
worker or extra file is created. Code/state fit in 2,624 bytes inside the original
MAIN length. Previous diagnostic images retain their exact hashes and all 25
checks pass; the native capture allocation suite passes its 14 groups. This
exact trial is staged and read-back verified, with all 86 card entries/settings
unchanged and 30 saved audio evidence hashes preserved. Safe unmount, transfer
exit and original editor/pad/MIDI checks passed. After the user-reported
update/reboot, exact new replies confirmed execution and the correct untried
budget; all seven timing replies and ordinary controls passed. One explicit
reservation then obtained all three blocks, charged exactly 93,848 bytes and
left 69,256 free. The allocation count rose by three with no frees; status
readback is held and native scheduler suspension returned to zero. No worker
was created, and no timing errors are observed. Installed flash bytes have not
been read back. Pad 1 now has the existing Glory Box backing in Loop mode at
0 dB; other pads are unchanged. The subsequent take lasts 170.656 seconds. Fourteen live query sets cover
active recording and the stopped period, with the reservation held and sampled
current/reported historical minimum free heap unchanged at 69,256 bytes. Final
retained counters are consistent and report no observed errors; one SD call
and 79 public file calls went unmeasured. New cumulative SD read/write peaks
are 68/61 ticks, public file peaks 68/92, at approximately 1 ms per tick. The
user reported no audible problems. All seven saved WAVs are valid and finite,
but Channel 1 is exactly five seconds longer than MASTER and the other five
channel files. The backing's two loop periods are exact and eight alignment
windows agree; input 3 has low coherent backing correlation. Earlier audio
metadata and all 30 evidence hashes are preserved. Safe unmount, transfer exit
and original pad restoration passed. Current free heap stays 69,256; the
reported minimum becomes 66,816 after transfer/remount/restoration. The
[stop arithmetic check](research/stop_cursor_lap_findings.txt) demonstrates
one extra native ring from synthetic consumer state beyond the saved stop,
but does not establish the hardware cause.

The same-image comparison after normal reboot is complete with no reservation
command or firmware update. All seven files contain 8,503,040 frames
(177.147 seconds), pass format/finite-sample checks and have verified copies.
Both backing repeats have exact source-length periods; eight alignment windows
agree. The user reports no audible problems. Thirteen live query sets span
180.072 seconds, with UNTRIED status and 163,104 current/reported minimum free
bytes throughout. Final measured counters are consistent with no observed
errors; no SD calls and 93 public calls went unmeasured. SD read/write peaks
reach 60/460 ticks, public file peaks 380/460. The clock is approximately
1 ms per tick. All 37 earlier evidence hashes and prior audio metadata are
preserved. Safe unmount, transfer exit and original pad restoration pass;
current heap is 163,104 bytes and minimum is 160,664 only after the
transfer/remount/restoration interval. The earlier five-second discrepancy
did not recur, but this single comparison establishes neither its cause nor
a fix. The user subsequently recalls using Play/Stop to stop the affected take
rather than Record and considers it a minor issue. The original high-level
record/play/stop requests converge on the same RecStop callback in an offline
recording-state trace; button-specific hardware timing is unobserved. Defer the
stop investigation and use Record consistently in subsequent trials, noting
the stop action. Keep the discrepancy as a follow-up without blocking buffer
development or claiming a cause/fix.

The 460 ms native write observation also supersedes the earlier buffer argument:
128 slots retain 170.667 ms, and 256 retain 341.333 ms. Compiled sizing rejects
non-power-of-two 345 slots; 512 retain 682.667 ms but request 280,031 bytes,
already exceeding observed free heap before a worker stack/task. These elapsed
calls include scheduling/waits and do not measure an added worker's blackout
or physical completion. A revised owned-memory/storage strategy and actual
service/occupancy/catch-up measurements are needed before continuous capture.
The 128-slot reservation remains capacity evidence, not a justified production
buffer. Physical completion, storage transitions and worker stack/startup remain
separate gates.

The [Astra high-effort storage investigation](research/astra_storage_strategy_review_20261007.txt)
recommends an attributed, capture-disabled contention probe as the next
milestone. Original public WRITE holds its filesystem-domain lock through the
native driver, so subdividing only SD commands does not admit another writer.
Measure wait versus held time and task/request identity before treating the
460 ms call as the added recorder's blackout. A narrow native-writer composition
could remove the optional task/polling, but still needs separate signal history
and verified staging lifetime. Fixed stock-ring tails offer a concrete larger
history layout if their bounds and ownership can be audited; they are currently
occupied and cannot be allocated from the existing contiguous arena unchanged.
No capture source or device change was made by this investigation.

The next [attributed storage-service diagnostic](../experiments/07-storage-service/README.md)
is prepared and passes 17 offline groups. Eight fixed task slots track public
READ/WRITE jobs and filesystem/SD token take, held-body and give intervals,
retaining observable pending states and missing-observation counters. Original
native file/SD requests, data, results, close flushing and failure-stack ownership
match the baseline in modeled tests. Its 8,024-byte code/state span preserves
all eight original startup outputs and complete stock DSP bytes. The previous
diagnostics retain their exact hashes and pass 40 regression groups. No extra
capture, file, worker or heap reservation is enabled. Held body is a lower bound
including scheduling; it does not identify physical card busy or a new consumer's
blackout. The exact image is now staged/read-back verified on the identified
card. All 100 audio/pad entries, global settings and 44 saved audio hashes are
preserved, with a private backup of the previous update file. Safe unmount,
transfer exit and normal status/pad/MIDI checks pass; current free heap remains
163,104 bytes, with no observed errors. After the user-reported update/reboot,
all 41 new service pages and seven legacy timing pages confirm experiment 07
execution. Four task slots are populated; all pages are consistent, all omission
and observed error counters are zero, and current/minimum heap are 163,104 bytes.
Original pads and MIDI ports are unchanged. Installed flash is not read back.
The completed 258.204-second take has seven finite, aligned files and three
exact source-length loop joins; the user reports no audible problems. Twenty-three
restarted snapshots show a 484-tick public write with a same-job 419-tick SD held
body, a separate 481-tick filesystem held maximum, and a 414-tick read containing
a 396-tick filesystem take. Long peaks rise during the sampled workload before
omissions. The 598-tick boot peak predates recording and is excluded. A 481-ms
sample backlog alone requires 184,704 bytes, beyond all available heap.

Coverage is partial: the original idle collector failed before this take,
recording start was not sampled live, and eight permanent slots fill near the
end, omitting 22 acquisitions with 22 unmatched gives. All new per-task pages
are consistent; eight active legacy pages are unavailable. All observed errors
are zero, not proof for omitted calls. Heap remains 163,104 during samples.
All 44 prior audio hashes/settings are preserved, safe transfer exit passes and
original pads/modes/levels are restored. Transfer/remount/restoration increases
omission counts to 62,337 each and lowers historical minimum heap to 160,664;
current heap returns to 163,104. Constant-gain audio matching has one unexplained
local window; levels remain deferred. The next milestone is the offline native
writer/staging-lifetime and owned-history audit, with improved bounded task
attribution before another probe. No extra recorder is enabled.

The [native staging and ring-layout audit](research/native_storage_layout_findings.txt)
adds 27 offline groups; 65 groups across seven focused suites pass. A controlled
final-stream schedule reuses queued staging before consumption, so combining
writers remains unproved and the separate extra worker is retained. Both fixed
tail layouts pass original twelve-lane DSP copying, mono/stereo float readers,
PCM16/24/float alternate writers and master playback. Negative controls show why
both descriptors and cached capacities must agree and why reinitialization can
invalidate the layout. These tests establish useful bounds, not hardware tail
ownership or a sufficient capture budget. Next audit cold startup and alternate
mode users before adapting history addressing; no device layout is changed.

The [initialization and audio-mode follow-up](research/native_ring_modes_findings.txt)
adds 24 groups; 115 groups across eleven related suites pass. One existing size
instruction supplies both descriptors, and full original recorder configuration
caches both values. Reinitialization retains the proposed sizes. All four full
audio callbacks match stock-sized samples across shortened wrap in the tested
idle-effects states. Recorded-song refills also preserve exact samples for all
mono/stereo PCM16/PCM24/float32 lanes. Negative controls reproduce tail writes
from a stale playback cache or an invalid cursor after live shrinking. The
candidate therefore changes the native startup constant and stays fixed;
additional capacity hooks and live resizing are unnecessary. Remaining aliases,
physical/source/cache users, mode transitions and real ordinary backlog need
qualification before a tail-memory probe or segmented capture. No image or
device change occurred, and the full redesign runner was not rerun.

The [ring-tail diagnostic](research/ring_probe_findings.txt) is staged/readback
verified, and new diagnostic execution is confirmed after the user-reported
update/reboot. Twenty new groups and 128 groups across eight focused
suites pass; earlier diagnostic images retain their exact hashes. Cold scatter
clears the native arena, so the probe plants guards only after coherent idle
initialization. Fixed 2-KiB chunks cover all twelve tails; faults retain the first
bad address, and live initialization or capacity repair is excluded. Requested
file/SD spans and sampled modulo ordinary backlog are observable. Generic effect
copies accept computed destinations, so alias/source/DMA/cache ownership is not
claimed. Extra capture remains disabled. All 107 audio/pad entries and global
settings are preserved, and all 51 earlier evidence hashes pass before/after
staging. Safe unmount/transfer exit and original pad/MIDI/legacy queries pass;
current/minimum free heap is 163104 bytes. All four capacities match 223104
frames, 202752 guard words were initialized, and two complete idle scans pass.
One historical source omission remains unknown; no fresh omissions or observed
source conflicts occur in the checked windows, including 59 backing-preparation
requests. Two missed guard checks were safely retried. Nine host groups verify
interval accounting, bounded retries and complete circular scans; twenty probe
groups were rechecked without changing the firmware image. Pad 1 was prepared
with GLORY_BOX.WAV in Loop at 0 dB for the completed recording test. The 197.6-second
take has seven finite, equally long WAVs, two exact source-length backing loops
and no user-reported audible problems. All twelve tail guards pass a complete
stopped scan, and all 51 prior evidence hashes/global settings are preserved.
Five additional source observations are omitted (six total); complete source
exclusion remains unproved. Sampled ordinary lag reaches 1.565 seconds without
qualifying unsampled peaks or a capture budget. Amplitude behavior remains
deferred. Next qualify recorded-song playback and effects separately. Separate
scans after file transfer and original pad/mode
restoration also pass; all assignments/counts and normal MIDI ports are restored.
Source omissions rise to 63 during transfer, with no new omissions in the stopped
scan windows. Current heap returns to 163104, with historical minimum 160664.
Installed flash readback, segmented history, service attribution/budget, broader mode/alias
ownership and physical completion remain unfinished.

Recorded-song playback also retains all twelve guards in a full stopped scan
(sweep 6), and the user reports no audible problems. Twenty-nine sampled cursor
advances span 145.075 seconds; exact start/duration is unknown. One new source
observation is omitted (64 total), so source coverage stays partial. Fresh
original pad/count replies and legacy controls pass; heap remains 163104/160664.
The user then authorized small changes to one parameter in each of the five
effects, restoring each before the next. Ten complete guard scans pass after
the changes/restorations, and a final scan reaches sweep 17. All ten original
values persist after reopening the Editor dialog; pads/counts, MIDI ports and
legacy controls also pass. Source requests stay 85988 with 64 historical
omissions and none newly omitted. Nine missed guard checks are safely retried.
This qualifies checked writes through stopped parameter updates; selecting and
hearing every effect with live audio remains next. Segmented history, broader
ownership and a justified service budget remain unfinished.

A [Python USB-audio test](../tools/device/l6_effect_audio_test.py) now automates
effect selection, returned-audio analysis and stopped guard scans. Original
firmware instructions verify the complete CC117 decoder and channel-1 parser.
The first Room pass confirms USB-to-master routing and intact guards through
sweep 19, with no new source omissions. Its output has no effect tail above
background, so it stops before switching any effect. The earlier route check's
post-burst noise is corrected rather than counted as an effect response. The
five-engine test awaits a nonzero channel-5 EFX send and EFX RTN setup; original
Room selection remains unchanged. No firmware or extra recorder is enabled.

After that setup, the computer completed five effect passes and a restored Room
pass. Seven full scans reach sweep 26 with all twelve tails intact, no layout
fault and no new source omission. All five measured effect responses are
distinct, Room's restored decay matches, and original parameters/pads, MIDI ports
and heap remain good. A strict waveform comparison initially rejected restoration;
the preserved captures pass a corrected energy-envelope comparison with explicit
wrong-effect and silent controls. This qualifies checked writes through exercised
effects. USB-only audio does not test SD service or synchronize an overdub take.
Segmented history, broader ownership and a justified buffer budget remain next.

The following paragraphs retain the earlier research sequence. They describe
experimental components, not the hooks selected for the current candidate.

The [startup audit](research/startup_order_findings.txt) found that the worker could run before hardware/storage setup finishes. Registration now leaves it asleep until explicit release. Choosing that release point, preserving stock initialization failures and leaving allocation capacity for stock tasks are the next integration steps.

The [sample-read audit](research/reload_prefetch_findings.txt) verifies that direct pad reloads wait for their file-worker reads. A [compiled read tracker](research/reload_read_findings.txt) now keeps failures, short reads and missing results from passing reload verification in the emulator. Native request attribution and card/storage admission still need binding before that evidence can release the startup worker.

[Read tickets](research/reload_read_queue_findings.txt) fit the stock 16-byte file queue. The [file-task adapter](research/read_worker_findings.txt) checks native task identity and retains packet/result/completion retries alongside original worker instructions in the emulator. The [producer adapter](research/read_producer_findings.txt) binds both requesting tasks, snapshots file handles and retries matching completion after early wakeups without resending. A [synchronous callback](research/read_callback_findings.txt) runs through all eight original initial-prefetch calls, keeping the caller suspended until its matching read joins. [Compiled routing](research/read_routing_findings.txt) selects tracked initial reads by task state and original call site, preserving stock reads for ordinary callers. [Shared ingress binding](research/read_ingress_findings.txt) now connects these adapters to the actual compiled reload handlers: task phases and envelopes are created by those handlers rather than inserted by the test fixture. All 143 related emulator groups pass. Installation, storage ownership and fault isolation remain before startup release can be wired; the prototype currently parks callers on tracking faults.

The [pad-file guard](research/pad_file_findings.txt) pins each tracked read against wrapped native load/unload operations until verified completion. A [public-close guard](research/pad_close_findings.txt) now waits before stock filesystem locks, and prevents further tracked reads until guarded reloading after a close attempt. All 161 related emulator groups pass. Ordinary readers, lower-level close bypasses, card teardown and the full caller lock audit remain unfinished; this is not complete storage ownership.

The [ordinary read/seek tracker](research/ordinary_io_findings.txt) reserves files through matching operation completion while preserving normal short reads, end-of-file behavior and seek results. [Callback and file-worker integration](research/ordinary_routing_findings.txt) connects it to original firmware instructions in the emulator, including two simultaneous callers. [Playback ownership binding](research/playback_io_findings.txt) supplies session owners for restart seeks and claimed refill owners for queued reads. The [native scan binding](research/native_scan_findings.txt) connects the original audio background callback to this chain without fixed ownership test addresses.

The [native audio observer](research/native_audio_findings.txt) executes alongside all four original audio callbacks in the emulator. Combined shutdown tests wait for both callback completion and outstanding reads, then keep playback blocked while replacement is allowed. [Shared hooks](research/shared_audio_findings.txt) run capture and completion through one pair of firmware locations, with capture cleanup preceding completion acknowledgment. Full audio tests capture exact samples and preserve the tested stock audio state and ring buffers.

[Startup readiness](research/audio_startup_findings.txt) now binds those hooks while capture is closed, then requires a whole audio callback before Main can release the recording worker. Early callbacks leave capture storage untouched; failed preparation leaves the worker disabled. All 610 groups across 52 related emulator suites pass, including nine new startup groups. Final firmware hooks, fault recovery, physical placement and the storage lock audit remain unfinished. Hardware testing remains deferred.

The [stock startup-site audit](research/startup_sites_findings.txt) now verifies a registration candidate after the stock idle task is created. It also exposes two release gaps: Main's direct startup pad load needs its own tracked ownership, and Main's indefinite event wait needs an explicit wakeup or polling mechanism to retry release. With the current guards enabled without that startup scope, the emulator reproduces failed opens and cleared pad assignments. That broader startup integration is now deferred. Current profiles omit these guards; the retained shared-audio worker also polls readiness after one Main authorization. All nine new audit groups and 76 groups across eight targeted suites pass. Automatic release remains unwired.

The dated [experiments](../experiments/) record hardware evidence. Emulation uses original instructions and compiled prototype code with synthetic memory, files and selected scheduling/driver responses. It is not a full mixer simulator. Restoring a working modified image does not establish recovery from broken firmware.

Historical research notes describe intermediate states. Earlier statements that no modified firmware has been deployed predate the successful marker trials.

The [segmented-history milestone](research/segmented_history_findings.txt) now
passes 685 groups across 61 redesign suites, plus the existing nine-group tap
suite. The offline buffer has 1024 slots across eight fixed lane tails, with
small heap-owned control objects. Exact audio, repeated modeled stalls, both
ring wraps, continued production after stop, partial endpoints, rearm and
failure rejection pass. Both retirement scans and all region overlap checks
cover the segments. Native filesystem/SD instruction fixtures preserve the
seven ordinary files and independently verify the eighth. Allocation/packing
figures and a finite access inventory are recorded with the remaining gates.
This completes the offline addressing milestone; device startup, owned code/
globals, storage admission/completion, physical memory/alias/cache ownership,
real service/stack/FP behavior and active effects/dynamics at the tap still need
integration before capture firmware deployment. No new BIN was produced.
