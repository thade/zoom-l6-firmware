ADDITIONAL PRE-MASTER PAD RECORDING — OFFLINE PROTOTYPE

CURRENT DESIGN (2026-10-05): capture-only is the default build. The worker uses
4-KiB staging, private TMP files and bounded restart-safe collision probing.
--profile handoff adds backing_handoff.c and backing_native.c: one stopped pad
switch, no audio copy, safe-error release and uncertain-error quarantine. Typed
port results distinguish joined failures from unresolved ownership. Native
assignment/rollback use checked synchronous initial reads; a scoped public-close
interceptor retains failed handles, including settings closes. No Main/read/USB
ownership overlay is linked into either profile. Fence/seal device bindings,
close-hook installation and the full device lock audit remain unimplemented.
The bounded synchronous-read lock audit is recorded in handoff_locks_findings.txt.
pad_commands.c adds an unbound eight-command FIFO only to the handoff test fixture. Main
replays whole stock commands after admission release; the worker does no replay.
Dispatcher ownership, overflow/wakeup and mode/Record ordering remain open. See
../../docs/research/pad_commands_findings.txt for evidence and limitations.
The later pad_dispatch_findings.txt audit rules out naive raw-handler binding:
stock duplicate deletion cannot see diverted commands. The FIFO is an unbound
primitive, not a correct native input adapter; full event ownership is next.
native_event_window_findings.txt tests a simpler between-events alternative with
input left in the stock queue. Native window scheduling, ownership/wakeup and
independence from Main or blocked event senders remain unproved. Normal candidate
profiles contain no private pad-command FIFO or replacement event dispatcher.
The handoff_dependencies_findings.txt audit runs native SD command/event paths
with checked handoff on one CPU fixture. Tested I/O does not need Main/UI locks,
but timeout return still lacks physical completion evidence. The gate contract
also covers NEW handoff I/O; do not bind safe rollback to public-return or token
release alone. A synthetic sector router exists only in handoff-test.elf.
See ../../docs/architecture.md for the authoritative design.
Run tools/firmware/verify_redesign.py for current and research regressions.

--layout placement creates capture-only-placement.elf at proposed code/global
addresses for offline tests. placement_hooks.S replays the complete spans of
two tested inline absolute RAM jumps. Normal layouts omit these adapters.
capture_jump_patches.py emits JSON only; verify_capture_placement.py runs the
real bytes through stock copier/prologue/epilogue and recording windows. Loader
acceptance, RAM ownership, global initialization and remaining hooks are unbound.
No firmware image is created. See ../../docs/research/capture_placement_findings.txt
(initial placement milestone: 423 groups across 40 suites).

The packed loading alternative uses existing MAIN length and the original
startup decoder. plan_capture_packing.py emits JSON only and checks that packed
DSP/capture fit their source span. Added globals/code are initialized before
patched DSP is published. Eight groups execute complete scatter startup and
packed-code recording; only 302 source bytes remain. Default builds are unchanged.
See ../../docs/research/capture_packing_findings.txt (431 groups / 41 suites).
Physical memory, cache/IRQ, manager/worker startup and storage/native I/O joins
remain unbound; no installable firmware is generated.

--layout placement --startup-fixture creates capture-only-startup.elf separately.
Two actual MAIN jumps preserve the first initialization result, wait for stock
idle creation and register the optional worker asleep on the original boot
stack. Eight groups test replay, packed scatter loading and startup failures.
This variant has 96 global bytes and 155 packed source bytes spare. Descriptor
and configuration inputs are copied from local arrays; normal profiles exclude
the fixture. plan_capture_startup.py emits JSON only. The bounded RAM audit
retains all raw candidates and does not approve physical ownership. Storage
release, remaining hook encodings and hardware budgets remain unresolved.
See ../../docs/research/capture_startup_findings.txt (440 groups / 42 suites).

Eleven capture-only storage groups execute the underlying mount, status callback,
directory constructors and public write locks. Neither setup return nor volume
flags exclude detach: metadata can be cleared while a write owns its file-domain
token. The worker release API still requires external verified authorization.
No caller is bound. See ../../docs/research/capture_storage_findings.txt
(451 groups / 43 suites). Capture code and packed-size margins are unchanged.

Fourteen capture-transition groups now execute native extra-file OPEN/WRITE/CLOSE
under compiled capture-only cancellation. Ordinary recording continues, pending
operations retain their worker frames and close errors block reuse. A negative
control shows software write error reaching CLOSE without a physical join.
Outer USB/card routines also discard lower failure returns and mutate before
mailbox requests. Direct file ports, outer transition coverage and startup
release remain unbound; no new production guard is supplied.
See ../../docs/research/capture_transitions_findings.txt (465 groups / 44 suites).

Thirteen capture I/O groups run the unchanged capture core with original public
read/write and SD instructions around separate offline recovery fixtures. Errors
retain file/unit tokens and native frames before cleanup. The test-only SD probe
now has an optional final completion port, disabled by default, before returning
to the dispatcher's unlock; nominal success also waits for explicit MODEL join.
No production completion detector or native file-to-sector route is bound.
See ../../docs/research/capture_io_lifetime_findings.txt (478 groups / 45 suites).

Twenty-one native-filesystem groups now execute original file/FAT/cache and
close metadata instructions, including empty-file allocation and FAT mirrors.
A separate SD composition replaces the synthetic router with native requests
and bounce copies, retaining file/unit tokens before actual exception unwind.
Failed close can already mark its handle unused and cache clean; neither is
success or retry permission. Native OPEN/create, complete mount/bitmap/FSInfo
settings and compiled lifecycle composition remain beyond these fixtures.
Physical completion and source/cache/transition bindings remain unresolved.
See ../../docs/research/native_filesystem_findings.txt (499 groups / 47 suites).
No production capture code, packed margin or device state changed.

Thirteen native capture-file groups now connect the unchanged normal capture
ELF to original OPEN/create, SEEK, INFO, close and reopen/readback, with native
handles and LFN entries. The SD configuration uses actual sector requests,
bounce copies and the separate test-only completion probe. The whole capture
stack waits while ordinary audio/STOP proceed on a separate fixture stack.
Existing files remain intact across collision search; close/readback errors
withhold eligibility. Controlled ready-volume geometry replaces full mount,
bitmap and FSInfo initialization, which is the next software step. Physical
completion, cache/source exclusion and outer admission remain unbound.
See ../../docs/research/capture_native_files_findings.txt (512 groups / 48 suites).
No production capture code, packed margin or device state changed.

Twelve native mount groups now replace controlled ready-volume settings with
original filesystem construction, MBR/BPB parsing, cache/handle setup and
allocation-map/free-count scanning. Both sector-callback and original SD-driver
configurations complete the extra take. The tested FAT32 paths count FAT entries
without accessing FSInfo. Failed scans can leave a partial bitmap enabled, and
mount can mask write-protection-query failure; mount success alone cannot release
the worker. Card bytes, initialized SD-card state and completion remain fixtures.
Physical completion, cache/source exclusion and outer storage authorization are
the next integration requirements. Automatic release remains disabled.
See ../../docs/research/native_mount_findings.txt (524 groups / 49 suites).
No production capture code, packed margin or device state changed.

--layout placement --hooks-fixture now creates capture-only-hooks.elf with all
15 selected MAIN/startup and two DSP patch targets. Twenty-two groups execute
actual bytes, complete replay and register/FPU/stack/return-address checks,
native mounted capture, all Stop routes and retained SD lifetimes. It fits with
119 packed bytes spare. The corrected queue adapter retains stock FIFO-mode
initialization. Exact continuation, four-argument and original-kernel FIFO tests
cover both encoded builds; shared fixtures reject unsupported timeout/mode.
Deep ordinary setup and physical completion remain
fixtures. See ../../docs/research/capture_hooks_findings.txt.

Eight native outer-setup groups create RECORDER/SOUND_PAD/PAD1..4 from an empty
card through original directory drivers, then record exact extra takes through
actual hooks. The stock application's geometry policy is separate from lower
FAT32 readiness. Eight rename groups prove examined no-overwrite same-folder
TMP-to-WAV changes with no audio copy; a final barrier error can follow a name
change. No native seal port is enabled. See native_storage_setup_findings.txt
and native_rename_findings.txt under ../../docs/research/.

--layout placement --hooks-fixture --minimal-link creates a separate smaller
capture-only-minimal.elf. Grouped linker roots retain patch/control/observation entries
while unreachable research APIs are removed. No capture algorithm changes.
The C patch roots are checked against the hook plan before compilation.
Eleven groups verify boot, capture, cancellation and retained errors; this build
has 19,248 code bytes, 96 global bytes and 2,924 packed bytes spare. Default
profiles keep their executable segments. See capture_minimal_findings.txt and
remaining_device_gates.txt under ../../docs/research/. All ELFs remain offline;
automatic startup/storage release and physical completion are still unbound.
The consolidated runner passes 575 groups across 53 suites at this milestone.

The notes below describe historical research composition, including the broader
shared-audio/reload overlay. They are not instructions to install those hooks in
the simplified candidate. Use --profile research to reproduce those tests.

This prototype preserves normal input recordings and the processed MASTER. It
adds a separate stereo float32 recording intended for a selected pad directory.
It is not a firmware update and must not be installed on the mixer.

Capture and pad-shutdown completion now share one compiled outer/return hook
pair through na_bind_capture. The capture-only outer/return hooks remain for
isolated tests and must not also be installed at those shared locations. The
combined path preserves tested stock audio buffers and records exact samples
through full original DSP callbacks. The physical startup hook is still unbound.
See ../../docs/research/shared_audio_findings.txt (601 groups across 51 suites).

The compiled startup protocol now binds shared audio while the capture gateway
is closed. native_worker_bind_audio supplies na_prepare/arm/ready, validates
permanent coordinator storage, and fails the worker on prepare failure. Main
release requests arming and returns WAIT until a whole callback completes; only
then may the worker prepare the first session. The actual stock release site
and storage-readiness authorization remain unbound. See
../../docs/research/audio_startup_findings.txt.

Session handover now prepares up to 4096 sample slots on the worker before
publication. Audio-boundary initialization consumes that preparation without
walking the slot array. This permits about 5.46 seconds of retained stereo
samples at 48 kHz; physical memory placement and native scheduling remain open.
See ../../docs/research/large_capture_handover_findings.txt.

manager_boot now prepares the first session through the compiled manager,
starting with closed audio/control gateways and caller-owned storage. Ordinary
worker steps clear control objects, reset slot ownership and prepare the file;
old history payloads are overwritten before publication, not bulk-cleared.
Activation waits for a complete
first audio block. Startup-hook placement remains open.
See ../../docs/research/manager_boot_findings.txt.

native_worker.c now registers the manager through the stock task-creation ABI,
runs configurable bounded step batches and delays between passes. Offline tests
cover registration, repeated takes, waits and original allocation-failure paths.
Registration leaves the worker asleep until explicit Main-task release; the
release API requires its caller to establish initialization and storage admission.
Stock startup continues substantial initialization after scheduler start, so no
production release hook is selected. See ../../docs/research/startup_order_findings.txt.
The deeper direct-read audit verifies the original prefetch/file-worker handshake,
but normal reload completion can hide read errors and short reads. Required
read-result attribution is recorded in ../../docs/research/reload_prefetch_findings.txt.
Successful scheduling and delay completion remain fixtures; priority, stack and
polling settings are unmeasured. No startup hook or device addresses are assigned.
See ../../docs/research/native_worker_findings.txt and run
  /tmp/l6-re-tools/bin/python tests/emulation/verify_native_worker.py

Request routing now corrects the false START on Record-to-stop in the serialized
emulator adapter. Each request owns its timestamp and queue/callback lifetime.
The newer control_transport adapter uses the original current-task getter,
compiled 32-byte queue envelopes and automatic wrappers for five verified
request entries. Admission closure and a control FIFO-prefix acknowledgement
are now tested. A permanent entry gateway also fences modeled hook/worker
access after terminal file completion. Control gateway shutdown now fences
installed wrappers/callbacks and unlinks owned Transport references. Prepared
handover now reopens at a strict audio callback boundary, then
activates control after the first block. A compiled manager now sequences
worker/file/fence/reset/handover operations across six tested takes and retains
four successful result paths. Raw reset/rebind remains forbidden. Device boot,
real worker scheduling and pad assignment are not yet connected. Legacy isolated
hook mode remains only for historical low-level tests, including the negative
control reproducing its defect; do not use it as full-request integration.

capture.c: bounded sample snapshots and extra-file write queue.
history.c: continuous history, 64-bit sample ranges and exact partial endpoints;
all access currently requires external serialization.
block_exchange.c: separate single-producer/single-worker slot ownership and
stock-cursor publication experiment.
emulator_bridge.c / emulator_hooks.S: register-preserving PC interceptions and
worker-owned file lifecycle/cancellation and an eight-event control mailbox.
A permanent gateway reserves hook/worker entry before session-pointer access;
terminal detachment closes admission. An opt-in outer/return pair now
holds a pinned session across the entire selected callback. Strict taps/commits
require that invocation. Prepared handover alone can reopen the gateways;
blind reset/rebind is rejected.
../../tests/fixtures/audio_fixture.c: synthetic callback body for lifetime tests only; not Zoom DSP.
request_router.c: owned request snapshots, accepted-start classification, send
outcome and callback attribution. Router operations require serialization; the
older emulator suite supplies explicit scopes and a queue identity sidecar.
control_transport.c: original task identity, guarded request operations, owned
message arguments and compiled queue dispatch without a Python identity sidecar.
Eight envelopes/task bindings and sixteen automatic request slots. Only ignored,
never-submitted request slots may be recycled during a take. Whole-arena reuse
requires complete shutdown and the prepared handover protocol.
Admission close preserves earlier requests and forwards later ordinary work.
Drain acknowledgement covers control work only. Combined shutdown adds
permanent caller ownership, waits through hook/worker detach and unlinks owned
references. Raw direct APIs still require external lifetime ownership.
lifecycle.c: unique-file preparation, recording, finalization, checked close and
full readback verification, prepared-state checks and stable result-path copy.
Readback reuses stopped, drained staging; no separate 4-KiB verification buffer.
Pad assignment is not connected.
session_manager.c / session_manager.h: sole worker orchestration, 4-KiB control
object clearing steps after fencing, unique-file preparation, staged activation, cancellation,
explicit resume and four copied result records outside reusable session memory.
Capture-only composition and a sized placement/startup proposal are recorded in
../../docs/research/capture_integration_findings.txt. The normal capture-only ELF
is tested beside all seven stock files; physical bindings remain unapproved.

Current evidence and limitations:
  ../../docs/research/extra_capture_findings.txt
  ../../docs/research/extra_lifecycle_findings.txt
  ../../docs/research/record_events_findings.txt
  ../../docs/research/record_boundaries_findings.txt
  ../../docs/research/history_capture_findings.txt
  ../../docs/research/block_exchange_findings.txt
  ../../docs/research/emulator_bridge_findings.txt
  ../../docs/research/bridge_events_findings.txt
  ../../docs/research/record_scheduler_findings.txt
  ../../docs/research/request_router_findings.txt
  ../../docs/research/control_transport_findings.txt
  ../../docs/research/auto_requests_findings.txt
  ../../docs/research/control_drain_findings.txt
  ../../docs/research/session_detach_findings.txt
  ../../docs/research/transport_shutdown_findings.txt
  ../../docs/research/audio_invocation_findings.txt
  ../../docs/research/session_handover_findings.txt
  ../../docs/research/session_manager_findings.txt
  ../../docs/research/pad_publisher_findings.txt

Latest integration finding: startup clears the history flags and selects no
lookback; no setter for the 0.5/2-second branches has been found. Regardless of
mode, ordinary files use a saved starting sample and an exclusive saved endpoint.
Original writer tests now verify that endpoint across repeated ring wraps.
The prototype retains setup audio and matches exact sample ranges in the
emulator, including partial blocks. Compiled adapters now intercept original
callback and cursor-setter sites, with deferred worker-side file cancellation.
No hooks are installed on the device. Control delivery now uses a bounded
mailbox tested with explicit emulator interleavings; no complete device fence,
safe RAM placement or timing is proved.
A startup memory gap is only an audit candidate.
The separate exchange now tests publication after stock cursor advancement and
immutable worker claims. Event sample tokens must be captured synchronously;
cached modulo cursors alias later audio after a wrap. The complete concurrent
RTOS scheduling/wakeup is not connected yet. Queue overflow or producer
contention cancels the optional file. Completion closes event admission and
waits for existing hook reservations before exposing a verified path. Session
retirement still requires external lifetime fencing. The new control marker
accounts for earlier admitted requests and a FIFO prefix, but later ordinary
wrappers could still touch Transport. Combined shutdown now also fences those
installed control entries before unlinking owned session references. Raw direct
APIs remain outside the fence. Full-program reclamation and real SD/DMA
completion remain unproved. Reopening requires ownership of the whole DSP
invocation; the opt-in adapter now supplies that ownership for the inspected
dispatch path. Prepared boundary handover is tested, but real callback coverage,
SD/DMA lifetime and real worker scheduling remain unproved. The compiled manager
now owns the operation order; compiled cold boot and a native task adapter are
covered offline, while actual startup placement and scheduling remain open. Isolated legacy
hooks alone still admit the demonstrated late tap.

Reproduction from repository root using the existing analysis environment:
  /tmp/l6-re-tools/bin/python tools/firmware/build_extra_capture.py --profile research
  /tmp/l6-re-tools/bin/python tests/emulation/verify_extra_capture.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_extra_lifecycle.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_record_events.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_record_boundaries.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_history_capture.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_block_exchange.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_emulator_bridge.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_bridge_events.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_record_scheduler.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_request_router.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_control_transport.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_auto_requests.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_control_drain.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_session_detach.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_transport_shutdown.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_restart_boundary.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_audio_invocation.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_session_handover.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_session_manager.py

Tests execute original instruction windows and separate compiled code with
synthetic memory and files. The preceding manager milestone passed 180 groups: 11 capture, 11 lifecycle,
6 record events, 7 record boundaries, 15 history, 8 block exchange,
11 emulator bridge, 9 queued bridge events, 11 scheduling, 12 request routing,
9 control transport, 12 automatic requests, 9 control drain, 9 session detach,
5 transport shutdown, 2 restart-boundary checks, 10 whole audio invocations,
11 prepared session handovers, 12 compiled manager groups.
The legacy-mode restart negative control passes
by reproducing unsafe admission of an old audio tap after a forced reset.
These include historical negative controls and do not establish real concurrent
request transport or device readiness. Repeated-session handover is bounded
by the serialized-manager, strict audio and synchronous-file fixture contracts.
Synthetic addresses and Cortex-M7 emulator configuration do not
prove device memory availability or physical chipset identification.

Manager-to-pad publication (4 October 2026)
The locked result visitor now feeds complete newest-first extra-capture snapshots
into the existing copy/catalogue/assignment/settings protocol. This does not use
the processed MASTER. Tests transfer compiled manager state/files between two
CPU fixtures; the renderer fence and global exclusion remain modeled and default
to refusing publication. The worker must call manager_publish_pads at M_RESET
before advancing the manager, and retry BUSY without stopping a playing pad.
That production scheduling and error policy are not yet wired.

Build both ELFs, then run tests/emulation/verify_pad_publisher.py. Eleven new groups pass;
343 groups across 26 relevant suites pass on the current builds. Exact inventory
and hashes: ../../analysis/pad_publisher_regression.json. Two earlier stock-only
record-event/boundary suites are not included in this rerun total. Full limitations
and next investigation: ../../docs/research/pad_publisher_findings.txt.

Real renderer boundary evidence (4 October 2026)
Twelve new checks execute the complete original pad/input renderer through return,
including natural EOF, looping, zero-gain reads, fade/stop and retrigger. See
../../docs/research/pad_renderer_boundary_findings.txt and run
  /tmp/l6-re-tools/bin/python tests/emulation/verify_pad_renderer_boundary.py
No ELF rebuild is required. The callback return is a tested candidate completion
point; the installed all-reader fence remains unresolved and defaults to BUSY.

Remaining callback audit (4 October 2026)
Fourteen new checks run all four known stock audio callbacks, including all later
DSP in the normal chain using ARM MAX for its double-precision instructions.
A second pad renderer and mode-switch race require shared-dispatcher ownership;
parameter-copy producer entries need admission covering direct and queued paths.
Run tests/emulation/verify_pad_reader_audit.py. Details and limits:
  ../../docs/research/pad_reader_audit_findings.txt
The default CPU choice in earlier fixtures remains unchanged. No ELF is rebuilt
or installed; all-reader completion is not yet bound to the publication guard.

Control-call deferral evidence (4 October 2026)
Nine checks execute the effects import initializer, original parameter handlers,
mode-setter callers and suspended control continuation. Existing shared effects
lock waits can hold the covered controls pending while audio runs, but their
callers ignore failure returns; mode changes also require earlier workflow
admission. Run tests/emulation/verify_control_admission.py. See:
  ../../docs/research/control_admission_findings.txt
No new installed coordinator or ELF change is claimed by this evidence stage.

Publisher ownership integration (4 October 2026)
The shared publication body now propagates a fault raised during enter/leave.
verify_guarded_publisher.py runs manager_publish_pads using the other prototype's
compiled lease under playback shutdown's retained exclusive ticket. This is an
explicit cross-emulator state-transfer test; real recorder/card admission and
async sample-loader descendants are still unbound. See
docs/research/storage_publication_findings.txt for the newly verified weak stock
status paths and the remaining entry/completion work. No device writes occur.

Original recorder final-write integration (4 October 2026)
The new emulator_recorder_drained_hook intercepts 0x8000b78c after stock stream
completion and before WAV finalization. ct_record_drained attributes the stock
file-worker error latch to the still-owned ordinary STOP request and retains
optional error 33, preventing automatic publication of a failed take. It does
not modify the ordinary recorder's error or cleanup. This is emulator-only
binding, not a flashed hook. Nine focused groups and 164 affected regression
groups pass; see docs/research/recorder_file_worker_findings.txt for the controlled
producer/file-worker schedule, remaining buffer-lifetime issue and limitations.
