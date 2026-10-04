ADDITIONAL PRE-MASTER PAD RECORDING — OFFLINE PROTOTYPE

This prototype preserves normal input recordings and the processed MASTER. It
adds a separate stereo float32 recording intended for a selected pad directory.
It is not a firmware update and must not be installed on the mixer.

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
four successful result paths. Raw reset/rebind remains forbidden. Initial boot,
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
audio_fixture.c: synthetic callback body for lifetime tests only; not Zoom DSP.
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
Pad assignment is not connected.
session_manager.c / session_manager.h: sole worker orchestration, 4-KiB clearing
steps after fencing, unique-file preparation, staged activation, cancellation,
explicit resume and four copied result records outside reusable session memory.

Current evidence and limitations:
  ../../analysis/extra_capture_findings.txt
  ../../analysis/extra_lifecycle_findings.txt
  ../../analysis/record_events_findings.txt
  ../../analysis/record_boundaries_findings.txt
  ../../analysis/history_capture_findings.txt
  ../../analysis/block_exchange_findings.txt
  ../../analysis/emulator_bridge_findings.txt
  ../../analysis/bridge_events_findings.txt
  ../../analysis/record_scheduler_findings.txt
  ../../analysis/request_router_findings.txt
  ../../analysis/control_transport_findings.txt
  ../../analysis/auto_requests_findings.txt
  ../../analysis/control_drain_findings.txt
  ../../analysis/session_detach_findings.txt
  ../../analysis/transport_shutdown_findings.txt
  ../../analysis/audio_invocation_findings.txt
  ../../analysis/session_handover_findings.txt
  ../../analysis/session_manager_findings.txt
  ../../analysis/pad_publisher_findings.txt

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
now owns the operation order; cold boot and wakeup remain fixture setup. Isolated legacy
hooks alone still admit the demonstrated late tap.

Reproduction from repository root using the existing analysis environment:
  /tmp/l6-re-tools/bin/python tools/build_extra_capture.py
  /tmp/l6-re-tools/bin/python tools/verify_extra_capture.py
  /tmp/l6-re-tools/bin/python tools/verify_extra_lifecycle.py
  /tmp/l6-re-tools/bin/python tools/verify_record_events.py
  /tmp/l6-re-tools/bin/python tools/verify_record_boundaries.py
  /tmp/l6-re-tools/bin/python tools/verify_history_capture.py
  /tmp/l6-re-tools/bin/python tools/verify_block_exchange.py
  /tmp/l6-re-tools/bin/python tools/verify_emulator_bridge.py
  /tmp/l6-re-tools/bin/python tools/verify_bridge_events.py
  /tmp/l6-re-tools/bin/python tools/verify_record_scheduler.py
  /tmp/l6-re-tools/bin/python tools/verify_request_router.py
  /tmp/l6-re-tools/bin/python tools/verify_control_transport.py
  /tmp/l6-re-tools/bin/python tools/verify_auto_requests.py
  /tmp/l6-re-tools/bin/python tools/verify_control_drain.py
  /tmp/l6-re-tools/bin/python tools/verify_session_detach.py
  /tmp/l6-re-tools/bin/python tools/verify_transport_shutdown.py
  /tmp/l6-re-tools/bin/python tools/verify_restart_boundary.py
  /tmp/l6-re-tools/bin/python tools/verify_audio_invocation.py
  /tmp/l6-re-tools/bin/python tools/verify_session_handover.py
  /tmp/l6-re-tools/bin/python tools/verify_session_manager.py

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

Build both ELFs, then run tools/verify_pad_publisher.py. Eleven new groups pass;
343 groups across 26 relevant suites pass on the current builds. Exact inventory
and hashes: ../../analysis/pad_publisher_regression.json. Two earlier stock-only
record-event/boundary suites are not included in this rerun total. Full limitations
and next investigation: ../../analysis/pad_publisher_findings.txt.

Real renderer boundary evidence (4 October 2026)
Twelve new checks execute the complete original pad/input renderer through return,
including natural EOF, looping, zero-gain reads, fade/stop and retrigger. See
../../analysis/pad_renderer_boundary_findings.txt and run
  /tmp/l6-re-tools/bin/python tools/verify_pad_renderer_boundary.py
No ELF rebuild is required. The callback return is a tested candidate completion
point; the installed all-reader fence remains unresolved and defaults to BUSY.

Remaining callback audit (4 October 2026)
Fourteen new checks run all four known stock audio callbacks, including all later
DSP in the normal chain using ARM MAX for its double-precision instructions.
A second pad renderer and mode-switch race require shared-dispatcher ownership;
parameter-copy producer entries need admission covering direct and queued paths.
Run tools/verify_pad_reader_audit.py. Details and limits:
  ../../analysis/pad_reader_audit_findings.txt
The default CPU choice in earlier fixtures remains unchanged. No ELF is rebuilt
or installed; all-reader completion is not yet bound to the publication guard.

Control-call deferral evidence (4 October 2026)
Nine checks execute the effects import initializer, original parameter handlers,
mode-setter callers and suspended control continuation. Existing shared effects
lock waits can hold the covered controls pending while audio runs, but their
callers ignore failure returns; mode changes also require earlier workflow
admission. Run tools/verify_control_admission.py. See:
  ../../analysis/control_admission_findings.txt
No new installed coordinator or ELF change is claimed by this evidence stage.

Publisher ownership integration (4 October 2026)
The shared publication body now propagates a fault raised during enter/leave.
verify_guarded_publisher.py runs manager_publish_pads using the other prototype's
compiled lease under playback shutdown's retained exclusive ticket. This is an
explicit cross-emulator state-transfer test; real recorder/card admission and
async sample-loader descendants are still unbound. See
analysis/storage_publication_findings.txt for the newly verified weak stock
status paths and the remaining entry/completion work. No device writes occur.

Original recorder final-write integration (4 October 2026)
The new emulator_recorder_drained_hook intercepts 0x8000b78c after stock stream
completion and before WAV finalization. ct_record_drained attributes the stock
file-worker error latch to the still-owned ordinary STOP request and retains
optional error 33, preventing automatic publication of a failed take. It does
not modify the ordinary recorder's error or cleanup. This is emulator-only
binding, not a flashed hook. Nine focused groups and 164 affected regression
groups pass; see analysis/recorder_file_worker_findings.txt for the controlled
producer/file-worker schedule, remaining buffer-lifetime issue and limitations.
