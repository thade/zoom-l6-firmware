# Progress

Goal: Allow for an overdubbing workflow using just the L6 hardware.

1. **Workflow defined.** Keep clean input recordings and the ordinary master; make an additional stereo recording for reuse on a sound pad.
2. **Firmware investigation substantially complete.** Recording, audio routing, file handling and pad assignment have been traced. Detailed findings are in [research/](research/).
3. **Simplified offline design implemented.** One history ring, 4-KiB staging, one file worker and an optional single-pad handoff. Completed takes are reused without copying audio. Temporary-file naming, safe publication failure recovery and coalesced read notifications have regression coverage. Handoff fence/seal ports remain modeled.
4. **Modified data deployed and restored.** The USB name changed from L6 to T6, then returned to L6 after reinstalling stock firmware.
5. **Modified instruction deployed and restored.** The USB name changed to ZOOM L6 through a one-instruction patch, then returned to L6 after reinstalling stock firmware. Both marker trials now have verified restoration.
6. **In progress: capture-first integration.** Capture, native card/folder/file operations, packed loading and all selected instruction patches are tested offline. A smaller linked build leaves room for the remaining bindings. Device memory/cache/SD completion, storage-transition protection and automatic startup release still need evidence. The optional pad handoff also needs its native fence and checked seal binding. Further deployment progress awaits hands-on hardware validation.
7. **Test progressively on hardware.** Additional stereo capture, automatic pad assignment, then repeated overdubs.
8. **Validate the complete workflow.** Timing, audio integrity, clean stems, preserved masters and failure handling.
9. **Package the finished firmware.** A tested image and installation/restoration instructions, once the preceding steps pass.

The current [architecture](architecture.md) supersedes the broader integration
plan below. `python tools/firmware/verify_redesign.py` builds the isolated profiles
and reruns the affected regressions. The one-pad controller is connected to the
serialized worker in offline tests. It preserves old takes, verifies rollback on
safe failures, and quarantines uncertain ownership without a Main-loop gate.
The first eventual hardware milestone is capture-only; automatic pad handoff
comes afterward. No new firmware image was prepared or deployed for this redesign.

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
The consolidated redesign runner now passes 575 groups across 53 suites,
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
eight native outer setup groups, eight native rename groups and the expanded
profile isolation checks. The original
queue audit's 14-group result remains recorded. All are offline;
no new firmware image was prepared or installed.
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
hands-on evidence needed next, beginning with the prepared tiny added-code trial
or reconciliation of any unrecorded result. No capture firmware image was
prepared, staged or flashed during this work.
The current writer state is 4,160 bytes; the handoff controller is 1,684 bytes.
These are compiled structure sizes, not measured total RAM/stack requirements.

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
