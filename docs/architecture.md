# Architecture

The intended workflow records a whole song, then reuses that take as a sound-pad backing track while recording the next layer.

```text
Live inputs ────────────────────────> clean channel files
     │
     └──> mixer <── previous take played from a sound pad
            │
            ├──> ordinary master processing ──> MASTER recording
            │
            └──> additional pre-compression stereo capture
                         │
                  finish and verify file
                         │
                  switch one backing pad
                         │
                    next overdub pass
```

This is the target routing. The tap is a candidate before late master dynamics;
active compression and effects-return behaviour still need independent checks.
Neither additional capture nor automatic pad handoff has run on the device.

## Current design

One audio history ring retains samples with monotonic positions. One serialized
worker selects the exact start/end range, stages up to eight blocks (4 KiB),
writes the extra file, finalizes its header, closes it and verifies readback.
Audio callbacks never perform filesystem operations. The large second queue is
gone; short first/last blocks retain their exact lengths.
Readback reuses stopped, drained staging, saving a separate 4-KiB buffer. Rearming
initializes history-slot ownership and overwrites samples before publication;
it does not bulk-clear old history payloads.

The first workflow uses one chosen backing pad (pad 1 by default). It keeps
previous takes as files, without rotating assignments across four pads or copying
audio. The manager still retains four result records for diagnostics; those
records are not a four-pad publication plan.

New captures use `OD_xxxxxxxx.TMP` names. Only a verified take may be sealed as a
`.WAV` and assigned. At startup, exclusive creation plus read-only final-name
checks skip both abandoned temporary files and completed files. Probing yields
after 32 collisions and resumes on the next worker step; it never overwrites or
deletes old material. No persistent serial counter is required. This is retention,
not automatic recovery of an interrupted recording or a storage-cleanup policy.

The optional `backing_handoff` controller uses the same worker at the completed
take boundary. It acquires a stopped-state fence, seals one file, updates one
catalogue entry, loads that backing and saves settings. Pad options are checked
against their original values. Safe failures restore/verify the previous backing
when needed and release capture. Uncertain I/O, seal or rollback outcomes retain the
hold and quarantine the optional workflow. The controller never blocks Main's
event loop or replaces ordinary reads. A BUSY acquisition must own no resources;
release contention retries only release, never the mutation.

The handoff port distinguishes success, busy, safely joined failure and uncertain
ownership. `backing_native` supplies the v1.10 pad/settings adapter. During a
stopped assignment or rollback it temporarily replaces that pad's initial-read
callback with a synchronous, exact-byte-count read. The original loader and
prefetch still run; failed or short reads reject the load, and a nonempty load
with no observed read cannot pass. The original callback is restored before
return. Ordinary playback/refill reads are unchanged. This deliberately avoids
adding another queued read/completion protocol to the handoff.

A public-close interceptor passes through outside the handoff and records any
failed close inside it. The adapter retains the handle identity even if the stock
caller discards it. An uncertain close forbids rollback, another settings save,
or fence release. This covers loader prevalidation, sample unload and both
settings write/readback closes. The adapter requires the exact interceptor entry
before initialization; it is installed only in the emulator, not in a device image.

The fence and seal are deliberately **unbound ports**, not inferred stock APIs.
The fence must exclude new playback/refill, recording, catalogue and card-mode
operations and join actual outstanding users. A stopped UI indication alone is
insufficient. Seal must use a verified no-overwrite move and confirm the resulting
file before returning success; it must distinguish no-change from uncertain
failure. Stock scanner rejection of `.TMP`, actual move failure/durability
semantics and storage admission remain to be verified before these ports can be
bound. Tests model these contracts; they do not prove device implementation.
The [bounded lock audit](research/handoff_locks_findings.txt) now executes original
prefetch, filesystem synchronization and task-context setup. It finds scratch
lock -> filesystem lock -> read -> filesystem unlock -> conversion -> scratch
unlock, and permits the calling worker's identity on the examined public-read
path. Holding either lock as the fence blocks the handoff itself. The gate must
therefore retain logical admissions while leaving those resources available.
This is offline evidence; SD/DMA lifetime, other lock paths and real scheduling
remain unverified.

Gate release is an I/O-free commit. All fallible checks happen while admissions
remain closed; a non-success result must leave them closed. Once another task
can resume, release must return success. Restoring an adapter pointer cannot
repair a gate that has already released users. These are binding requirements,
not an implemented device fence.

The [admission map](research/handoff_admission_findings.txt) records the known
entry points and required completions for pad controls, refill/file workers,
transport, assignment/reload and card/USB activity. The existing capture drain
allows later ordinary requests, so it cannot supply this gate. Pad callers also
ignore a fabricated BUSY return; their deferral must preserve the whole command
without preventing earlier completion events from running. Device admission
remains unbound until those caller and lifetime requirements are established.

The research [pad-command queue](research/pad_commands_findings.txt) retains eight
complete scalar commands. Main submits and executes them; the handoff worker
can hold admission only once accepted commands have finished, then release it
without I/O. Execution occurs outside the short metadata latch. Retry after
completion contention cannot execute the command twice. Main stays available
to process other events. This component is unbound: the dispatcher must own
rejected events, wake Main for retries and preserve FIFO even after release.
Original handlers interpret mode, assignment and Record state at replay, so
ordering conflicting controls is also a prerequisite. Neither queue emptiness
nor handler return proves that asynchronous file/audio users have finished.

The later [Main dispatch audit](research/pad_dispatch_findings.txt) rules out a
direct raw-handler binding: stock pad playback removes pending duplicate events,
which it cannot see after they have moved into the private FIFO. In a reproduced
case, one stock start becomes a start followed by a stop. Saturation also either
loses an event or blocks completion if Main waits. The FIFO remains an unbound
primitive; integration must preserve full event processing and explicitly define
overflow behavior before it can be enabled. No dispatcher hook is installed.

The [between-events experiment](research/native_event_window_findings.txt) keeps
input in the stock queue and tries handoff only after prior Main work has finished.
It preserves duplicate removal in tested paths and lets pending completions run
before attempting handoff. The private FIFO is now restricted to test fixtures.
This scheduling candidate remains modeled: stock queue saturation can block a
sender while holding a UI mutex, so independence of handoff from Main and those
senders must be established before enabling it. Manager ownership, wakeup and
fault recovery are also unbound. The serialized worker design remains unchanged.

The subsequent [storage dependency audit](research/handoff_dependencies_findings.txt)
runs checked handoff and original SD command/event code on the same CPU fixture.
The examined reads and settings writes/readback finish without Main or the UI
mutex, and the SD IRQ posts a separate completion event. A timeout counterexample
still releases software locks and triggers rollback without physical idle proof.
Gate binding must therefore cover completion/error ownership of new handoff I/O
as well as preexisting users. The native binding remains disabled until checked
completion or cancellation can preserve buffers and handles through failure.

The [SD completion audit](research/sd_completion_findings.txt) now distinguishes
clock stability from transfer idle. Original operation-5 cleanup checks only
clock stability and returns success without requesting a reset. The command
engine's error branch does attempt reset, but returns the same error whether
reset completes or remains stuck; command timeouts skip that branch. A raw IRQ
snapshot before acknowledgement preserves error bits lost by stock event
mapping. The next binding must attribute those observations and join transfers
before their lowest driver unwinds buffers, then establish checked recovery.
Neither helper can currently authorize safe rollback or gate release.

The [scoped SD experiment](research/sd_transfer_probe_findings.txt) now runs a
compiled test-only probe with original read/write, command, IRQ and event code.
Detected faults retain the native stack and unit token until an explicit modeled
join, including command failures before a wait and errors in final status. It
suppresses subsequent commands after failure. Direct and bounce buffers remain
live at that boundary. This defines where cancellation must run; the model
does not implement physical cancellation. Negative controls still expose stale
same-unit completion attribution and completion without physical idle. Every
probe symbol is excluded from normal builds; the device gate remains unbound.
Whole-handoff tests keep the filesystem/scratch locks and gate through pending
join, then perform rollback only after the model explicitly confirms completion.
The filesystem-to-sector mapping and physical join remain synthetic ports.

The [controller setup audit](research/sd_controller_setup_findings.txt) traces
the actual transfer-mode register separately from clock configuration and
corrects the earlier completion fixture's register label. Examined data paths
use a simple DMA address with preexisting mode/endian setup; transfer submission
does not restore those global settings. Stock reset callbacks can clear the
completion-event handle while returning success after timeout. Recovery must
preserve/recreate valid event state, check controller/card recovery and drain
old TC before programming a new address. The candidate reference manual's
abort/reset sequence still needs binding to the actual silicon; no physical
recovery implementation or gate admission is claimed.

The [stop/card audit](research/sd_card_recovery_findings.txt) executes stock CMD12
inside that retained failed transfer. It attempts the stop once, observes its
errors separately and preserves the outer failed scope until explicit modeled
join. A stop success, including with the emulator's explicit abort-type variant,
can still leave DAT0 busy and transfer activity asserted. The upper card-init
path preserves the existing event but can accept changed card address/capacity
without checking prior card identity or open filesystem handles. Neither return
can authorize rollback. Checked physical abort/reset/idle, serialized completion
draining and card/filesystem validity remain prerequisites for a device binding.
These test fixtures add no normal-profile recovery path.

The [checked recovery experiment](research/sd_checked_recovery_findings.txt)
adds compiled checks for data-reset self-clear, no activity/card busy, stable
configuration/event identity and cleared hardware/software status. Its data-entry
hooks run admission after the original SD lock and before a new DMA address.
Failed or pending checks hold that same stack and token; they do not repeat the
stop/reset. The whole handoff holds its gate/filesystem/scratch locks after reset
until explicit modeled validity permits rollback. The following
[native-event experiment](research/sd_native_event_findings.txt) selects original
flag clearing, binary-token take/count and IRQ mask/enable routines instead of
MODEL kernel draining. It verifies pending-state clearing and rearm readback
with explicit NVIC effects, including late arrivals and unsupported contexts.
IRQ/source/post exclusion, reset permission and physical/cache/card validity
remain MODEL contracts. These are test-only additions; a checked device recovery provider and
normal gate binding are still absent. Normal successful transfers retain the
existing completion contract, so this is not an all-path physical join guarantee.
The [source audit](research/sd_event_sources_findings.txt) now traces the known
controller and software notification families. Card detach can change registration
and post without the SD lock or target IRQ. Test guards reject success mixed with
fault/wakeup flags, but a late old hardware completion can still appear current.
The audit also records a second unit callback reaching the same MMIO body; its
actual device use is unresolved. Closing outer admissions and physically joining
old work remain prerequisites; clearing signals cannot provide those guarantees.

## Build profiles

`build_extra_capture.py` defaults to **capture-only**, producing
`src/capture/capture-only.elf`. This contains capture and its worker, without any
pad publication, global reload/read/USB hooks, or synthetic DSP fixtures.
Completed captures remain temporary files for this first milestone.
The [capture-only integration harness and binding plan](research/capture_integration_findings.txt)
now verify one exact extra file beside seven byte-identical ordinary files using
this normal ELF. Code/RAM/stack candidates and startup requirements are sized,
but physical placement, loader acceptance and storage authorization remain open.

`--layout placement` creates a separate offline capture-only ELF at candidate
addresses. The [placement experiment](research/capture_placement_findings.txt)
executes two actual RAM jump encodings, complete instruction replay and stock
scatter copying. It preserves the seven ordinary files in the capture test.
Extended MAIN loading, RAM ownership, startup initialization and remaining hook
encodings are still unverified. This option creates no firmware image.

The [packed loading experiment](research/capture_packing_findings.txt) now fits
the DSP and capture code into the existing loaded payload. Original startup
expands both and zeros the added globals in the emulator, with 302 source bytes
to spare. The plan rejects overflow after a build. This avoids changing MAIN
length for the current proposal; physical ownership, startup registration and
storage/native I/O bindings remain prerequisites to an installable image.

`--layout placement --startup-fixture` builds a separate offline ELF with
[tested startup jumps](research/capture_startup_findings.txt). It remembers the
first stock initialization result, waits for successful idle-task creation, and
registers the added worker asleep on the original boot stack. Failures preserve
stock startup. This variant has 155 packed source bytes spare and initializes
96 global bytes. Its fixed RAM addresses are test candidates; the bounded RAM
audit leaves ownership unresolved. Storage release, remaining hook encodings,
physical memory and measured heap/stack/interrupt behavior are still required.

`--layout placement --hooks-fixture` adds a separate
[encoded audio/control build](research/capture_hooks_findings.txt). Its fifteen
MAIN/startup and two DSP patches consume complete instructions, replay stock
effects and execute as actual bytes in offline tests. Callback and replaced-BL
return addresses are preserved. This does not bind storage release or physical
I/O completion. The complete fixture has only 119 packed bytes spare.
The corrected common-sender adapter resumes before stock FIFO-mode initialization.
Tests check control/DSP continuations against the patch specs and execute the
original kernel sender with a preexisting message and varied incoming mode values;
append-only fixtures now reject unsupported timeout/mode arguments.
Adding `--minimal-link` produces a
[smaller separate build](research/capture_minimal_findings.txt): unreachable C
research entries are collected, with explicit roots for patch-address entries,
external control APIs and test observation records. The C patch roots are
validated against the hook plan before compilation. Runtime dependencies and
all patches remain present. It has 2,924 packed bytes spare and the same global
and arena sizes. Default profiles retain their executable bytes. Both variants
remain offline experiments, with physical memory/cache/IRQ/timing unresolved.

The [capture-only storage audit](research/capture_storage_findings.txt) executes
native mount and directory setup and demonstrates why their convenient flags
cannot release the worker. Card teardown can clear metadata while a file write
holds its stock domain lock. Capture-only needs storage-transition protection
and physical I/O completion joins; ordinary playback/recording may coexist and
does not require the broader pad-publication overlay. Release remains unwired.

The [capture transition tests](research/capture_transitions_findings.txt) now
compose native extra-file open/write/close with the capture-only manager.
Cancellation can close that file while ordinary recording continues. A guard
must run before outer card/USB effects and hold no file tokens needed by cleanup;
stock outer routines discard lower failures. A software write-error negative
control reaches close before physical completion is established. Direct file
ports therefore still need a completion/recovery binding before automatic
release can be enabled. No transition guard has been installed.

The [capture I/O experiment](research/capture_io_lifetime_findings.txt) now
composes that unchanged capture core with the existing test-only SD recovery
guard. Errors retain the file/transfer frames until explicit modeled completion.
A final checkpoint before returning to the dispatcher's unlock also handles
nominal success while the controller still appears busy. It uses a separate
offline ELF and synthetic sector mapping. These fixtures are excluded from
normal device profiles.

The [native filesystem audit](research/native_filesystem_findings.txt) separately
executes original READ/WRITE/CLOSE, FAT-scan allocation, partial-sector caching,
FAT mirrors and directory updates into the registered SD callback. Its SD
composition retains actual file/metadata calls at the same completion checkpoint
and uses native bounce copies. A failed close leaves the handle unused and can
leave an unwritten cache sector marked clean. Actual filesystem exception unwind
propagates that error; bookkeeping cannot authorize success or a close retry.
The [native capture-file composition](research/capture_native_files_findings.txt)
now connects OPEN/create, SEEK, INFO, native handles and reopen/readback to the
unchanged compiled lifecycle on one CPU. Its SD configuration also retains the
entire capture call at the existing test-only completion checkpoint, while
ordinary audio/STOP run on a separate fixture stack. Real filename collisions,
close failures and changed sector bytes withhold or advance results as intended.
The [native FAT32 mount composition](research/native_mount_findings.txt) replaces
the controlled ready-volume geometry with original filesystem construction,
MBR/BPB parsing, cache/handle initialization and bitmap/free-count scanning.
The tested paths count FAT entries without accessing FSInfo. Card bytes, initial
folders and initialized SD-card state remain controlled. A failed scan can leave
the map enabled, and mount ignores a failed write-protection query; readiness
cannot rely on those flags alone. Full board/card initialization and identity,
physical completion, cache/source exclusion and outer storage authorization
remain unbound. Automatic worker release is still disabled.
The [native outer setup](research/native_storage_setup_findings.txt) now creates
the recorder/pad folders through stock filesystem instructions from an empty
card fixture. Application capacity/cluster policy is checked separately from
lower filesystem mount. The [native rename](research/native_rename_findings.txt)
path rejects an existing destination and preserves audio/cluster metadata without
copying payload. It is a candidate for the seal port only after its physical
I/O is joined and results checked: barrier failure can follow a changed filename.
Neither the seal nor storage admission/transition provider is bound. The
[remaining device gates](research/remaining_device_gates.txt) describe the next
hardware evidence needed before those bindings can be enabled.

`--profile handoff` adds the controller and checked native adapter and produces
`handoff.elf`. The raw pad-command FIFO is included only with `--test-fixtures`. It has
no default fence/seal callbacks and cannot automatically enable publication.
After binding the gate/seal and close interceptor, `bn_init` constructs the typed
port. Use `backing_init` then `backing_attach_worker` at cold initialization; attachment
checks the shared manager and distinct permanent storage before binding the step.
Physical placement and startup/storage authorization remain explicit prerequisites.

`--profile research` produces the historical `capture.elf` for earlier tests,
including four-pad copying and synthetic fixtures. The separate `overdub.elf`
is also a research build. Its startup guard regression and terminal stock-task
parking are **not part of the current candidate**. Do not merge those hooks into
the simplified profiles. The shared-audio startup adapter is retained for research;
its worker can now poll first-callback readiness after one Main authorization.

`--test-fixtures` creates a separately named test ELF. The consolidated
`tools/firmware/verify_redesign.py` builds every required profile and checks their
symbol isolation, sample boundaries, batching, repeated handoffs, failure paths,
startup and coalesced read notifications.

- [src/capture/](../src/capture/) contains capture, buffer ownership, file completion, request routing and session management.
- [src/capture/backing_handoff.c](../src/capture/backing_handoff.c) contains the new single-pad handoff.
- [src/capture/backing_native.c](../src/capture/backing_native.c) checks native handoff reads and close outcomes.
- [src/overdub/](../src/overdub/) retains the broader ownership overlay and four-pad copy prototype for research and regression tests. Only the private stock pad/settings helpers are reused by the checked handoff adapter; the broader overlay is excluded.
- [tests/emulation/](../tests/emulation/) executes recovered firmware routines and compiled prototypes. Hardware, storage and scheduling boundaries are modeled.
- [tests/fixtures/](../tests/fixtures/) contains synthetic callback bodies.
- [tools/firmware/](../tools/firmware/) inspects the vendor image, builds emulator executables and prepares minimal deployment probes locally.
- [tools/device/](../tools/device/) contains macOS MIDI and file-transfer helpers, separate from the eventual hardware-only workflow.

The source and linker layouts are experimental. Emulator addresses are not safe device addresses. The hardware probes alter existing bytes in place; they do not establish where new code or capture buffers can safely live.
