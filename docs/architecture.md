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

This is the target routing. Original effects-return mixing, gain ramps and active
master dynamics now have [focused offline checks](research/tap_processing_findings.txt):
the tap includes the returned effects and precedes master gain/dynamics. A separate
[provider audit](research/effect_memory_providers_findings.txt) executes all five
original effect engines and bounds their tested memory accesses. Combined effects
and extra capture still need hardware qualification.
Neither additional capture nor automatic pad handoff has run on the device.

The [passive upper-gap diagnostic](research/ram_activity_probe_findings.txt)
completed its hardware checks after manual update. Two full idle sweeps and disjoint
halves across two verified pad plays have matching fingerprints. Two windows
during a 165.251-second multitrack take cover the entire gap with the same result;
full sweeps after stop and normal card transfer also agree. The first recording
backing is identified in USB and saved MASTER audio. The second is unconfirmed
after a user-reported level/mute change. Full sweeps during user-reported song
playback and all five audio-verified effects also agree; the song's USB master
is silent, so its audio is unverified. Room restoration is audio-verified.
The diagnostic adds one
bounded query with no permanent state, reads fixed 1-KiB pages twice and retains
all earlier diagnostic behavior. It does not change capture placement or claim
ownership of apparently spare memory. Stable fingerprints are insufficient to
exclude read-only users, DMA activity or physical/cache aliases.

## Current design

The extra file exists only for a stock recording. It is the
[simplified capture](research/simple_capture_findings.txt) in `src/capture/simple/`:
4,024 bytes of code, 8 bytes of globals and 12 patch sites, packed with the stock
decoder into the consumed DSP source span that experiment 16 ran from.

| Participant | Entry | Owns |
|---|---|---|
| Audio | DSP tap and commit | History blocks, published frame count and epoch |
| Stock recorder task | Stream admission `0x8000b158`, stop setter `0x80006918` | One start and one stop per take |
| Main | Five original receive calls | A revocation counter; waits at most 500 ticks |
| Worker task | Polling loop | The extra file; the only filesystem caller |

Start and stop come from the stock recorder's own saved cursors, so the extra
file covers the same frames as the seven stock files. History is 1,024 blocks of
64 frames (1.365 s) in the eight shortened lane tails. The worker writes whole
4-KiB chunks, finishes at the stop frame, rewrites the header and checks the
length and header after reopening. A storage-changing packet, a continuity break,
lost history or a missing stop abandons only that take.

The first hardware step is [experiment 19](../experiments/19-simple-tap/README.md):
the tap and worker without recorder or storage hooks. Remaining questions:
lane-tail ownership, worker stack and SD service under the extra 384,000 B/s,
the admission-to-start delay, and early-hang recovery
([experiment 18](../experiments/18-recovery-hang/README.md), parked). Pad handoff
follows reliable capture.

## Earlier composition (superseded)

The sections below describe the capture-first composition that preceded the
simplified design. Its sources remain in `src/capture/` for research and to
reproduce experiment 17, which was prepared from it.

### Composition design

One audio history ring retains samples with monotonic positions. One serialized
worker selects the exact start/end range, stages up to eight blocks (4 KiB),
writes the extra file, finalizes its header, closes it and verifies readback.
Audio callbacks never perform filesystem operations. The large second queue is
gone; short first/last blocks retain their exact lengths.
Readback reuses stopped, drained staging, saving a separate 4-KiB buffer. Rearming
initializes history-slot ownership and overwrites samples before publication;
it does not bulk-clear old history payloads.

The actual staging payload and its containing allocation require 32-byte
alignment for the native sector driver. Reordered metadata gives an aligned
payload without increasing the 4,160-byte state. Sample scaling uses explicit
single-precision hardware instructions under a saved/restored FPSCR scope, so
rounding and underflow match the previous conversion independently of stock
task settings. Compiler, exact-sample, native-transfer and software context
evidence are in the [performance corrections](research/capture_performance_findings.txt).
Physical FP preemption/stack behavior remains a deployment gate.

Hardware storage measurements require a revised memory layout: the current
128-slot heap history holds 170.667 ms, while a shared filesystem held interval
reached about 481 ms. The [native storage audit](research/native_storage_layout_findings.txt)
checks fixed lane-tail layouts that could retain 0.683 or 1.365 seconds of extra
history while keeping 4.824 or 4.648 seconds for ordinary recording. These are
unselected offline proposals. The [initialization/mode audit](research/native_ring_modes_findings.txt)
finds that one existing startup size instruction feeds both native descriptors
and both cached capacities. Full original initializers, known audio callbacks
and recorded-song refills preserve the tested shortened bounds. Live resizing
is excluded: even coherent sizes can leave an invalid producer cursor. Physical
ownership, remaining aliases/mode transitions and ordinary backlog still need
qualification. The [segmented-history implementation](research/segmented_history_findings.txt)
now supports the 1024-slot geometry offline, while retaining contiguous storage.
One validated region description covers preparation, producer/consumer indexing,
manager overlap checks, handover and both retirement scans. Small runtime objects
come from the native heap; the eight external history spans are separate. This
prototype retains 1.365 seconds, which is not yet a measured safe service budget.

The [minimal composition](research/capture_composition_findings.txt) now combines
encoded startup/audio/control hooks with heap-owned controls and segmented
history in one offline build. Cold registration leaves the worker asleep; no
storage release is wired. It requests 9,855 heap bytes plus a separate experimental
16-KiB task stack and native task metadata. The packed proposal has 2,279 bytes
spare and 100 proposed global bytes; executable/global ownership and storage
admission/transition/completion bindings still precede device deployment.

The separate [storage-gated composition](research/storage_lease_findings.txt)
now pins each manager operation, including automatic next-TMP creation, against
one admitted generation. Closing admission requests cancellation and remains
closed until reboot. Storage-only shutdown closes the extra file and audio
gateway while retaining all control objects for ordinary callbacks to finish
later. It does not authorize memory reclamation. Lower physical completion/cache
validity remains a prerequisite; the pin cannot repair premature driver unwinding.

The separate [native transition executor](research/storage_transition_executor_findings.txt)
closes/joins that lease without waiting, then runs the unchanged selected USB/card
body on Main only after retirement. Its separate
[Main binding](research/storage_main_findings.txt) now wraps five original receive
calls in the offline transition fixture. The current request remains on Main's
stack while optional file cleanup completes; later packets stay in the native
FIFO. No private queue or synthetic retry event is added. An uncertain close
keeps the request held. Original handlers continue once storage closes, and old
ordinary callbacks retain their memory until reboot. The fixture leaves 870
packed bytes spare, with a 9,887-byte arena and 104 proposed global bytes.
Exhaustive ingress/lock dependencies, physical source/cache ownership, trusted
normal-mode admission and startup release remain open. Startup still leaves the
worker asleep and no capture update image is produced.
The [cold-start audit](research/native_startup_boundary_findings.txt) identifies
the native successful mount/folder branch and distinguishes ordinary boot from
setup modes that later reach the same Main loop. That logical witness cannot
replace the missing physical storage admission.
The [SD cold-start audit](research/sd_cold_start_findings.txt) also executes the
native reset/setup and enumeration chain. Two small FIFO reads bypass the
block-DMA scope; source qualification must cover these before ordinary and
extra-file traffic. Passive diagnostic14 records the first reset/enumeration
without supplying admission or changing the driver's decisions.
An isolated [LZ4 packing experiment](research/lz4_packing_findings.txt) leaves
6,244 bytes spare with a 512-byte decoder. Original startup and malformed-input
checks pass offline. Default/device builds retain Zoom's decoder; the alternative
needs exact combined-fit and physical startup qualification before selection.

The [focused SD diagnostic](research/sd_chunk_observation_findings.txt) observes
controller state at four native chunk waits before buffer copy/reuse. It keeps
the extra recorder disabled and preserves the current ordinary capacity. Its
observations will guide that lower completion binding; quiet snapshots alone
cannot establish it. The installed diagnostic's startup baseline records 1,200
waits with no omitted chunk observations and 16 detections. The first retained
successful read has data-line activity/inhibit remaining but read-transfer
activity clear. This narrows the physical question without proving DMA is still
using a buffer; no physical join is bound.
The short ordinary take subsequently reaches all four sites with 997 new waits
and 181 detections, no omitted chunk observations and seven valid aligned files.
Concurrent pad audio was unconfirmed in that first take. A separate detail profile retains per-site
counts/reason unions/latest bad samples to classify the new detections; it
changes no native completion or storage policy. That detail profile now runs on
hardware. A later 179.196-second take has seven valid, finite, aligned files and
the one-shot backing is identified in MASTER, with no backing detected in mostly
quiet input stems and no audible problems reported. Its recording interval adds
4,896 waits with zero omitted chunk observations. The 934 direct-write and 14
bounce-write detections contain only data-inhibit/line-active reason categories;
retained write samples show DAT0 low with transfer-active bits clear. Candidate
NXP driver documentation allows card busy after a write returns, so those bits
alone are not a DMA-lifetime certificate or a reason to treat every write as a
failure. Raw completion/error identity and exact cache ownership remain unbound.
Transfer/hash/remount observations are kept separate from recording evidence.

The [native cache audit](research/sd_cache_contract_findings.txt) decodes stock
MPU region 10 as 32 MiB of cached normal memory covering the proposed staging,
history, code and globals. Original direct reads clean/invalidate before DMA;
the exercised paths have no post-read invalidation. An opt-in offline helper
invalidates only the original owned read lines after modeled completion, inside
native frames. It snapshots the start before command launch and requires this
command's raw TC, rejecting an earlier TC plus a software success event. Fifteen
groups verify the ordering and explicitly modeled stale-line case. It supplies
neither physical join nor memory reservation and is excluded from all normal
and composed builds; the installed passive diagnostic is unchanged.

The [passive memory query](research/physical_ram_capacity_findings.txt) now
independently reports one enabled 32-MiB SDRAM decode window on hardware, with a
16-bit bus and refresh enabled; three paired snapshots agree. Internal core
TCM mappings are 128 KiB data and 32 KiB instruction memory. Fuse selection means
the recorded GPR17 is not treated as an active full bank map. These observations
strengthen capacity evidence without reserving either apparent external gap,
detecting physical chip density or changing the proposed history layout. Full
ownership remains a requirement before choosing an alternative to ring tails.

The [derived-address ownership audit](research/ram_gap_ownership_findings.txt)
bounds the adjacent free table, USB setup object and native queue allocation
in 35 offline groups. Its two new gap constants are character-table data;
no confirmed consumer inside either gap was recovered. The upper 872-KiB gap
could hold the current 1024-slot history contiguously using the existing API,
avoiding native ring shortening, but remains unreserved. Static absence and
unchanged passive fingerprints cannot establish complete ownership or
physical alias safety. Current device and offline placement remain unchanged.

The [USB provider follow-up](research/usb_memory_providers_findings.txt) adds
75 focused checks of original profile selection, complete descriptor construction
and six worker-generated pool configurations. Their five supplied buffer ranges
lie in internal DTCM, outside the external candidate gaps. Original installation
and audio-state pointer consumption execute; subsequent dynamic length arithmetic,
endpoints and physical aliasing remain unresolved. Neither gap is reserved.

A separate [raw IRQ diagnostic](research/sd_raw_observation_findings.txt) now
runs on the device. It stores full status before native
acknowledgement, including errors lost by the original event mapping, plus the
active cache/TCM configuration. Twenty-three offline groups preserve native IRQ
behavior and the existing detailed wait protocol. It adds no completion guard,
cache change or capture permission. Exact staging/readback and settings/audio
preservation are verified. After update/reboot, fresh protocol replies confirm
execution; startup and automated pad playback pass with no observed raw errors
or omissions. The bounce CPU cache question is resolved; cached SDRAM staging/
history and concrete completion/ownership binding remain unfinished. Two ordinary
takes now have valid aligned WAVs; the restarted take includes backing and strong
live input, with its backing window agreeing with USB master/stems. The recording
interval adds 12776 native waits/DMA-mode TC samples, zero raw/detail omissions
and zero raw errors. Ninety-six stored live write-mode TC snapshots have no
error flags, but lack a command generation or owner. Detailed write snapshots
retain trailing inhibit/line activity; broad call observations omit eight calls
and peak at 648 ticks. Actual worker headroom remains unmeasured. These
observations do not enable capture; one concrete guard beneath audio and metadata
IO still needs completion/generation and exclusive cache-line ownership.

The [command/buffer journal](research/sd_command_observation_findings.txt) is a
separate, locally verified passive diagnostic. Four before-address adapters and
the native command entry retain original buffer spans, submitting context and
temporally associated raw/wait observations. Its 35 offline groups preserve
tested native behavior; a late prior-origin TC can still appear clean. Software
association therefore supplies context for the next binding, without granting
physical completion, source exclusion, cache ownership or capture admission.
Its exact image is staged/readback verified, preserving all 142 audio/pad files
and settings. Normal Eject, transfer exit and original pad/MIDI/heap checks pass.
New replies after user-reported update/reboot verify execution. Startup and
automated one-shot playback identify original bounce spans/task context; live
queries fall inside the backing window. Three command observations are omitted
across boot/playback, so coverage is partial despite zero raw/detail errors.
The ordinary backing/live-input recording check now passes: seven valid aligned
files over 262.787 seconds, identified master backing, no strong coherent backing
in the stems and agreement across all twelve USB channels for the full captured
18.005-second interval. The stopped interval adds 1366 direct and 3514 bounce
writes, with zero raw errors or raw/detail omissions. Five more command
observations are omitted; complete coverage is not claimed. Original settings,
pads and prior audio metadata are preserved, and normal operation is restored.
These observations inform the write-side binding; they grant no capture or
completion permission. Physical source exclusion before address programming,
nominal/error completion and exclusive buffer/cache ownership remain next.

The [per-chunk SD checkpoint](research/sd_chunk_guard_findings.txt) now holds each
native block-data wait before bounce copy/refill or driver-frame unwinding. One
32-byte record retains the original span, submitting task and fresh raw latch;
only exact positive modeled completion releases it. Sixteen offline groups cover
direct/bounce reads and writes, split chunks, pending completion, errors, identity
changes and cache ordering, including capture metadata/payload/readback. The
enclosing operation checkpoint remains for final status. No new task, allocation,
reset or retry is added. Both checkpoints remain test-only: old physical sources
must be excluded before each address store, and actual nominal/error joining and
exclusive cache-line ownership are not supplied by these callbacks. The full
regression results pass 774 groups across 67 suites; the installed diagnostic is unchanged.

The [native admission candidate](research/sd_chunk_admission_findings.txt) now
holds entry before the first bounce fill/cache effects, then drains native status,
flags, binary token and pending IRQ before each address write. Four inline adapters
preserve stock register state and consume a matching preparation marker at command
entry. A compiled host-completion predicate replaces the chunk's positive MODEL
reply in sixteen new test groups, including unchanged capture metadata/payload/
readback and pending-admission cancellation. A 24-byte record and one opt-in port
are added only to fixtures. Actual old hardware/IRQ/task exclusion and exclusive
spans remain a MODEL source lease; a false lease still admits a late old TC. The
native outer card/USB gate must therefore bind before this can run on hardware.
The original filesystem's allocation-table, mirror and directory sector updates
also execute under this guard; physical sectors and source exclusion remain models.

The preceding [ring-layout diagnostic](research/ring_probe_findings.txt) ran on the
device with extra capture disabled. It changes only the original startup size
instruction, plants bounded guards after cold clearing, reports requested IO
spans and samples ordinary modulo backlog. All twelve tails remain intact after
two idle scans, a 197.6-second ordinary backing recording, transfer/pad restoration,
exercised recorded-song playback and stopped Editor parameter changes/restoration
for all five effects. A computer-controlled USB test also exercises all five
effect audio paths and restores Room. Seven more full scans reach sweep 26 with
all tails intact, distinct effect-energy responses and no new source omission.
Original numeric parameters/pads and final heap/MIDI controls pass. The preserved
audio corrects a phase-sensitive waveform assertion using decay-energy envelopes
and wrong-effect controls; this is not sample-identical reverb reproduction.
The USB-only workload does not test SD service or the additional capture tap.
Five new source observations were omitted
during the recording interval and one during sampled playback. Broader mode and tail
ownership qualification remains pending; clean guards cannot establish reads,
aliases or physical cache/DMA ownership. Segmented history is now implemented offline;
its physical ownership and a justified service budget remain unfinished.

The audit also reproduces premature staging reuse at a final-stream transition
under controlled delay. It does not establish a device defect, but it prevents
assuming extra work is safe inside the native writer. The separate optional
worker remains the design until native staging and scheduling are proved.

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

### Build profiles

`build_extra_capture.py` defaults to **capture-only**, producing
`src/capture/capture-only.elf`. This contains capture and its worker, without any
pad publication, global reload/read/USB hooks, or synthetic DSP fixtures.
Completed captures remain temporary files for this first milestone.
`--heap-fixture` adds a separate [native heap arena experiment](research/capture_heap_findings.txt).
It allocates the runtime objects and a smaller history through the original
allocator instead of placing them in the scatter-table gap. Allocation failure
leaves capture disabled. This experiment is excluded from normal/placement
profiles and supplies no device startup hook or storage release. Experiment 06
reserved the exact 128-slot arena and unused worker allowance during ordinary
recording, leaving 69,256 free bytes. This establishes those allocations' capacity,
not actual worker service or later stock reserve. The subsequent unreserved
comparison measured a roughly 460 ms native write, exceeding both 128-slot
(170.667 ms) and 256-slot (341.333 ms) histories. The next supported size, 512,
requests 280,031 arena bytes and exceeds the observed 163,104-byte free heap.
The memory/storage strategy must be revised before reliable continuous capture;
larger unowned RAM or a reduced reserve floor is not justified. Native elapsed
calls include waits/scheduling; actual worker blackouts, occupancy/catch-up and
stack headroom remain unmeasured. See the latest
[performance findings](research/capture_performance_findings.txt).
Code/permanent-global placement is a separate requirement.
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
The [native exFAT composition](research/native_exfat_findings.txt) now covers
the format reported by the connected card, including contiguous/fragmented
allocation, entry checksums, cross-cluster readback and errors. A combined case
uses a native heap arena, original folder/file/SD instructions and 256-KiB
clusters. It still uses virtual sectors and modeled completion; actual-card
geometry and behavior remain unmeasured. Stock mount can write usage metadata
before a later error and accepts the examined boot-checksum mismatch, so mounted
state or an error alone cannot establish safe storage authorization.
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
