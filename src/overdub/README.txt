CURRENT WORKFLOW NOTICE
This is the earlier master-copy prototype. The clarified goal preserves the
normal master and adds a separate pre-master stereo recording for the pad.
See ../capture/README.txt and ../../docs/research/extra_capture_findings.txt.
The tests below remain useful but do not implement that additional writer.

Initial reload read tracking (4 October 2026)
reload_read.c binds exact initial-read status/count to a unique child of the
requesting reload branch. Missing results retain ownership; errors and short
reads prevent successful retirement despite normal-looking stock state. Eight
new groups and 88 related regression groups pass. Native queue attribution and
startup release are not installed. See ../../docs/research/reload_read_findings.txt.
The subsequent read-queue adapter carries slot/ticket identity in 16 bytes and
requires file-worker return before read retirement. Seven new checks and 96
affected regression groups pass. Native task binding and receive-loop retention
remain open; see ../../docs/research/reload_read_queue_findings.txt.
read_worker.c subsequently binds the native file-task identity and retains
dequeued packets, read results and completion across busy retries. Nine new
groups and 103 affected regression groups pass. Producer binding, storage
lifetime, fault isolation and installed hooks remain open. See
../../docs/research/read_worker_findings.txt.
read_producer.c now binds assignment/Main task identities and retains request
tags and file handles before publication. Early wakeups retry ticket completion
without resending or waiting on the semaphore twice. Seven new groups and all
112 preceding groups pass. Synchronous caller glue, storage lifetime and fault
isolation remain open; see ../../docs/research/read_producer_findings.txt.
rp_callback subsequently adds synchronous continuation through the original
initial-prefetch callers. Seven new groups and all 119 preceding groups pass.
Tracked callbacks stay suspended until joined; invariant failures park the
caller. Scoped native routing, safe fault recovery and storage ownership still
need integration. See ../../docs/research/read_callback_findings.txt.
rp_read_entry/rp_dispatch now choose tracked initial reads from native task state
and the original caller LR; ordinary reads use a stock forwarder. Nine routing
groups plus all 126 preceding groups pass. Shared ingress binding, installation,
storage ownership and fault recovery remain unfinished. See
../../docs/research/read_routing_findings.txt.
rc_bind_reads now validates shared ingress/producer/reader configuration before
binding either read endpoint. The combined test runs actual compact ingress and
rt_run state transitions through eight initial reads, without fixture-generated
task phases or envelopes. Eight new groups and all 135 preceding groups pass.
See ../../docs/research/read_ingress_findings.txt. Storage lifetime, installation,
safe failure handling and startup release remain open.
pad_file.c optionally pins tracked reads against complete native pad load/unload
wrappers. Producer release retries cannot repeat IO or ticket retirement. Nine
new groups plus all 143 preceding groups pass. Direct closes, ordinary readers,
card teardown and lock ordering remain uncovered; see
../../docs/research/pad_file_findings.txt.
pf_close now guards public close before filesystem lock acquisition, retains
close-completion retries and revokes tracked-read admission until guarded load.
Nine new groups plus all 152 preceding groups pass. Ordinary readers, lower
close bypasses, media teardown and the full caller lock audit remain open.
See ../../docs/research/pad_close_findings.txt.

L6 AUTOMATIC MASTER-TO-PAD HISTORY: OFFLINE ARM PROTOTYPE
3 October 2026

Status
This is compiled Cortex-M7 Thumb code executed in an emulator alongside selected
original L6 v1.10 routines. It is not a flashable L6 firmware update. The original
L6.BIN is unchanged. No USB, MIDI or SD-card operations occur during these tests.

Integration update
Original AudioProcess callback ordering and alternate callback dispatch now have
seven checks, including an exact stereo working-buffer copy. Nine suites pass,
172 groups total. The end-of-block observation is not yet an all-reader fence;
the default renderer fence remains BUSY. Static pre-dynamics capture candidates
are documented but no extra recording stream is implemented.
See ../../docs/research/audio_task_and_taps_findings.txt.

playback_session.c adds a compiled coordinator retaining one session owner across
playback, multiple pads, retrigger and stop. Nineteen new groups pass and all
seven preceding suites pass against the rebuilt ELF: 165 groups in eight suites.
Release requires an epoch-matched renderer fence plus idle state and no children.
That device fence remains unbound: its default adapter returns BUSY. The tests
simulate successful acknowledgement explicitly. No natural-EOF auto-release or
installed continuous-playback safety is claimed.
See ../../docs/research/playback_session_findings.txt.

The original RAM-resident AudioSubProcess task and callback registration now
execute into the guarded stream producer in the emulator. Fifteen playback
boundary checks bring the seven-suite total to 146. A negative control confirms
that refill ownership alone admits promotion during ongoing playback; sound stop
also leaves streaming enabled. Continuous playback protection is NOT complete.
See ../../docs/research/playback_lifetime_findings.txt for verified boundaries and
the remaining session/quiescence work.

emulator_stream_producer.c now wraps the whole original stream scan, reserves
child tickets before pending-state writes, and publishes ticket messages through
the original queue wrapper. The original worker consumes those messages in the
emulator. Fifteen new groups cover normal and early completion, rejected and
uncertain submission, capacity and contention. All six suites pass: 131 groups.
The underlying RTOS delivery remains modeled; stock send errors are treated as
uncertain rather than proof of nonpublication. This does not yet cover continuous
playback ownership, every prefetch caller, or installed callback bindings.
See ../../docs/research/stream_producer_findings.txt.

work_ownership.c adds a 780-byte, 16-entry ownership ledger with unique tickets,
separate producer/worker completion, parent-owned children and fault handling.
The compiled ticket encoder/decoder fits the existing 16-byte stream queue,
and is connected to the original worker in the emulator. In that earlier suite,
producer admission and submission evidence were modeled. Both endpoints adopt the
new message meaning together; this is not compatible with pending old messages.
See ../../docs/research/work_ownership_findings.txt. Its 22 groups brought the then
five-suite total to 116, including corrected low-level wait-return fixtures.

The USB/storage configuration path and sampler read/seek completion boundaries
are now traced and tested. emulator_stream_bridge.c connects one original
stream-worker call site to the gate in the emulator, including early cancellation
and a nonempty refill. Producer ownership remains supplied by the harness.
See ../../docs/research/scheduling_boundaries_findings.txt for the USB acknowledgement,
remount and failed-wait cases that must not be mistaken for local readiness.
That stage added 31 groups, for a then-total of 94 across four suites.

admission_gate.c now provides a compiled atomic admission protocol, tested
through emulator-only Port.enter/leave/checkpoint bindings. Fourteen new groups
cover activity lifetimes, 90 API-level schedules, six gated promotions and
original stock queue behavior. Stock ingress/completion hooks are NOT installed:
a negative control confirms unmodified clear-pad code can bypass this gate.
See ../../docs/research/scheduler_exclusion_findings.txt for exact coverage and the
remaining device bindings. That earlier stage comprised 63 groups in three suites.

stock_pad_adapter.c now provides compiled, version-specific snapshot, assignment,
restore and verified settings-save implementations. The integrated harness runs
original pad-selection/loader control flow and reads its actual synthetic RAM
state; these operations are no longer represented solely by Python pad objects.
14 integration groups pass in addition to the 35 baseline groups below. Physical
audio, RIFF-parser output, SD driver effects and RTOS operations remain modeled.
See ../../docs/research/stock_pad_adapter_findings.txt for evidence and caveats.

Behaviour implemented
After a qualified ordinary recording completes, prepare a copy of its stereo
master for pad1, the previous promoted master for pad2, and so on through pad4.
Six successive successful promotions produce takes 6, 5, 4, 3 on pads 1..4.
Until four takes have accumulated, pads outside the history remain untouched.
The history includes takes promoted during this prototype session; it does not
import pre-existing pad contents or reconstruct history after reboot.

The core:
- owns copies of all source paths before calling shared-buffer stock helpers;
- requires a successful master close, completed post-processing, ordinary
  recording target, and positive qualification as an unsplit recording;
- validates finalized RIFF/WAVE sizes and the observed stereo 48 kHz float32
  format, including metadata chunks and odd-byte padding;
- creates exclusive, uniquely numbered destination WAVs in each PADn directory;
- copies in 4 KiB blocks, checking both error status and transferred byte count;
- closes and reopens copies, validates them, and compares every byte to source;
- prepares ALL copies before adding catalogue entries or changing assignments;
- inserts using the original incremental catalogue routine without selecting;
- assigns and reads back each pad, checking preservation of modeled parameters;
- updates session history only after every assignment and grouped save succeeds;
- attempts rollback if assignment/readback/save fails, and latches a fault if
  rollback cannot be verified or a close reports an error.

The core never writes or deletes original masters or channel files. A corrupt
copy, missing source, split take, unsupported WAV, full catalogue, name collision,
short transfer or cancellation prevents successful promotion. Some failures may
leave unselected files/catalogue entries; the prototype deliberately retains
these instead of attempting unverified deletion or rename operations.

What is real firmware execution and what is modeled
Real stock code executed by the harness:
  open  0x8005ffe8     read  0x80060620     write 0x800622b0
  close 0x8005c1f8     info  0x8005ef40 -> 0x8005f0a0
  catalogue init, insertion 0x80008dd8, and count 0x80008ee8
  selected recording-stop control flow in 0x8000b698

The filesystem wrappers dispatch to modeled file drivers operating on in-memory
bytearrays. Real SD/FAT media, drivers and durability are not emulated. The info
driver itself executes against synthetic handle/volume fields.

The baseline harness keeps modeled Port functions as an independent test of core
failure handling. The integrated harness replaces snapshot/assign/restore/save
with stock_pad_adapter.c. Enter/leave, qualify and checkpoint remain PROPOSED
device bindings whose implementations have not been recovered and connected.
In particular:
- enter must exclude recording, pad playback, file transfer and catalogue scans;
- qualify must distinguish a confirmed single part from an unknown/error state;
- the adapter verifies configured path, loaded path, loaded flag and sample
  handle, and preserves the observed per-pad option bytes; physical audio and
  any additional, unidentified settings still need verification;
- the save adapter uses checked stock filesystem wrappers and verifies the
  resulting settings file. A four-pad atomic save has NOT been demonstrated;
- checkpoint needs a real scheduling/cancellation strategy and latency budget.

The existing post-record helper at 0x80008bd0 is not an adequate substitute for
the proposed assignment contract: it does not return a reliable assignment
result and may request persistence per pad. Its final return is an unlock result.
The adapter calls 0x8004b760 directly and checks the resulting loaded state.
Passing these offline rollback checks does not establish real on-device rollback
or power-loss safety.

The stop bridge is also harness-only. Unicorn redirects the BL at 0x8000b978 to
od_emulator_after_postprocess, which calls the original postprocessor address
then the new core and preserves the original return value. The postprocessor
effects, source-path capture and close-status capture are modeled. No binary
patch or installed branch trampoline is produced. The tests demonstrate ordering
at the candidate call site, not a complete recorder/audio emulation.

Verification
35 passing test groups, including 68 individually injected file-operation
failures across validation, copy and verification. These are offline checks.

Evidence includes:
- six-pass four-pad ordering and duplicate-completion suppression;
- a complete 4,982,158-byte MASTER.WAV from the earlier real L6 test, copied
  and verified with SHA256
  85267f8e901054cb73ced241c6aa334ed352e734f2be0fc7463f79628a3d7a0b;
- original shutdown ordering with successful/failed master close, pad recording,
  inactive recording, and disabled post-processing branches;
- missing/split/invalid recordings, file-info failure, full catalogue, existing
  target protection, odd metadata, corrupted copy and shared-path overwrite;
- later-pad copy failure, partial catalogue insertion, assignment failure,
  readback mismatch, save failure, cancellation, and failed rollback.

Machine-readable results: ../../analysis/overdub_prototype_verification.json
State storage: 17,244 bytes, plus the job, port table, code and call stack. This
has not been assigned a safe location in the real device. Stack/watchdog/runtime
limits and SD copy duration have not been measured. ARM ELF address 0x10000000
and harness memory at 0x21000000 are arbitrary emulator mappings, not device
placement recommendations. Cortex-M7 is the analysis target, not a newly read
silicon identifier. Code uses integer operations and the soft-float ABI.

Storage and failure limitations
Each successful promotion creates up to four new complete master copies.
Old copies are retained, so storage consumption grows; garbage collection,
capacity reservation, persistence of the sequence/history and crash recovery
are not implemented. Exclusive creation prevents overwriting a collision after
a fresh start but a collision aborts that attempt. A future implementation must
recover its sequence and identify orphan files before becoming a useful product.
Files are created with final .WAV names, so exclusion of concurrent scans is a
required port contract. No atomicity across four assignments or power loss is
claimed. A latched fault blocks subsequent promotion until explicitly recovered.

Timing/count-in, automatic transport start, pad colours, level changes and any
audio mixing algorithm are outside this prototype. It reuses completed masters;
the physical L6 routing tests already established cumulative-master/clean-stem
behaviour, but those audio paths do not run in this emulator.

Reproduction
Analysis environment currently installed only under /tmp/l6-re-tools:
  ziglang 0.13.0, pyelftools 0.32, capstone 5.0.9, unicorn 2.1.4
From the repository root:
  /tmp/l6-re-tools/bin/python tools/firmware/build_overdub_prototype.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_overdub_prototype.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_stock_pad_adapter.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_admission_gate.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_scheduling_boundaries.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_work_ownership.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_stream_producer.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_playback_lifetime.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_playback_session.py
  /tmp/l6-re-tools/bin/python tests/emulation/verify_audio_task_boundaries.py

The build uses temporary Zig caches under /tmp. On this Mac, Unicorn needs the
previously approved execution outside the restricted sandbox for host CPU/cache
discovery. This does not give the harness a device communication code path.
The ELF and source belong to this offline prototype only; never rename the ELF
to L6.BIN or copy it to an SD card as an update.

Next integration work
Connect scheduler admission to verified stock entry/completion paths, especially
USB/card ownership and sampler asynchronous work; the new gate by itself cannot
exclude those paths. Implement real finalized-master/segment/close-status
capture. The existing assignment busy boolean is not nestable: an inner stock
assignment clears it even if an outer operation set it. Resolve history
persistence and storage growth before a hardware workflow trial. Firmware
packaging, memory placement and recovery remain separate requirements before
producing or installing a device image.

Additional-capture integration (4 October 2026)
The shared publication body also accepts trusted completed-path snapshots from
src/capture/pad_publisher.c. The original od_promote MASTER workflow
remains for its existing tests; the new manager path supplies verified additional
pre-master WAVs instead. See docs/research/pad_publisher_findings.txt for simulation
boundaries, exclusion requirements and outstanding device integration.

Compiled control admission (4 October 2026)
control_coordinator.c queues copied scalar payloads for five whole handlers and
closes execution admission while joining an already-running operation. Completion
is published only after original handler return. Run verify_control_coordinator.py
following build_overdub_prototype.py. 11 new groups and relevant regressions pass
(231 groups across 14 suites); see docs/research/control_coordinator_findings.txt.
Submission is a proposed upstream ABI; no original dispatcher is patched. The
control drain result is not a renderer, stream, card or recorder fence.

Compiled audio completion (4 October 2026)
The coordinator now occupies 372 bytes. audio_completion.c adds a nonblocking
entry/return protocol, and control_coordinator.c pins a requested closed epoch
until a subsequent whole callback returns. Changed or unbalanced callbacks
latch a fault. Run verify_audio_completion.py after rebuilding: 14 new groups;
245 relevant groups across 15 suites. See docs/research/audio_completion_findings.txt
and audio_completion_regression.json for scope and hashes. The proposed hook
calls are supplied by the emulator, not installed assembly. This is a past
completion barrier: later audio and looping pads keep running. It is not the
all-reader fence, and automatic publication remains unbound.

Combined playback shutdown (4 October 2026)
playback_shutdown.c now joins control drain, an explicit stream-disable adapter,
full audio completion and ledger-owned read completion. Session storage grows
from 28 to 32 bytes for a hold that persists through exclusive publication.
The combined state is 40 bytes plus its 8-byte port table. Finish releases the
exclusive owner and admission holds only after the caller reports completion;
uncertain publication faults closed. Two-cycle rearm is tested.
19 new groups and 264 relevant groups across 16 suites pass. See
docs/research/playback_shutdown_findings.txt and playback_shutdown_regression.json.
This suite explicitly binds the new emulator ports; default unbound session
ports remain blocked. Actual USB/card/ordinary-recorder admission is unfinished,
and the pad publisher has not yet been given this exclusive ticket. No device
or SD-card writes are enabled by the new coordinator.

Inherited publication ownership (4 October 2026)
publication_lease.c supplies an emulator-only publisher port that owns an explicit
child under playback shutdown's existing exclusive ticket. Finish waits for the
child; uncertain close or release failure keeps ownership and faults closed.
The shared publisher reports a fault raised by its void leave callback.
verify_guarded_publisher.py adds eight groups; verify_storage_readiness.py adds
seven original-firmware audit groups. See docs/research/storage_publication_findings.txt
and guarded_publisher_regression.json. Ordinary recorder/USB/card lifetime roots
and real async assignment descendants remain unbound; their fixtures must not be
mistaken for an installed all-storage fence. Remount return zero and recorder idle
are explicitly shown to be insufficient readiness evidence.

Deferred reload audit (4 October 2026)
verify_pad_reload.py executes the original reload producer, worker, full callback
and UI completion branch. The UI performs another four-pad unload/reload/save
sequence after the worker event, which must inherit storage ownership. Nineteen
new checks demonstrate misleading assignment returns, identical completion events,
ignored close errors and busy clearing while another reload is queued. No compiled
prototype changes in this audit. See docs/research/pad_reload_findings.txt and
pad_reload_regression.json; real storage lifetime binding remains blocked.

Reload worker/UI ownership (4 October 2026)
reload_ownership.c adds a 392-byte permanent coordinator with non-reused owners
and separate worker/UI branches. Reserve the UI branch before publishing its
event; retain both actual returns, producer return, I/O descendants and errors.
Final verification is blocked until every descendant joins and remains unbound
until explicit evidence arrives. Nineteen new groups and 329 groups across 21
relevant suites pass; see docs/research/reload_ownership_findings.txt and
reload_ownership_regression.json. The 16-byte tagged envelope is a proposed
transport ABI supplied by the harness, not installed stock queue/UI wiring.
A linker assertion now prevents the offline image overlapping the capture fixture.

Compiled reload transport endpoints (4 October 2026)
reload_transport.c adds explicit producer, worker/UI packet construction, copied
consumer contexts, return-phase retries and open/write/close error observation.
Original worker, UI reload and settings-save bodies run on the same emulator CPU.
The new worker/UI packets are 48/36 bytes, not drop-in stock 32/20-byte messages.
Fourteen new groups and all 343 groups across 22 relevant suites pass; see
docs/research/reload_transport_findings.txt and
reload_transport_verification.json. Native queue allocation, endpoint trampolines
and task attribution are still modeled. Public-wrapper errors, read policy and
real asynchronous descendants remain unbound; no hardware change is enabled.

Native queue/dispatch audit (4 October 2026)
verify_reload_queue_audit.py executes original queue allocation, worker/Main
routing, UI backlog filtering and explicit deletion. Compact 32/20-byte candidate
formats fit existing buffers; enlarged transport packets remain emulator-only.
Distinct UI tickets survive duplicate filtering, but queue flush and broader
filter rules can still discard them. Compiled ownership correctly remains blocked
when the continuation is lost. Fourteen new groups; focused regression 66 groups.
No C/ELF change. See docs/research/reload_queue_audit_findings.txt for native addresses,
queue sizes, task identities, evidence limits and the required cleanup policy.

Compact reload and deferred cleanup (4 October 2026)
reload_compact.c and its assembly forwarders fit tagged reload messages into the
stock 32/20-byte queues. Original worker/Main dispatch executes compiled decoders;
receive ingress retries retained work before fetching another message. Consumer
task lookup uses the original getter and a compiled interrupt-context guard.
The reload coordinator is now 396 bytes. A cleanup admission lease closes the
race with new reloads; live jobs defer filtering, whole clear and targeted delete.
UI queue sends are nonblocking so a full queue returns failure while ownership
remains held. Fourteen new groups and all 371 groups across 24 suites pass; see
docs/research/reload_compact_findings.txt
and reload_compact_regression.json. Native entry patches, surrounding transition
deferral and full-queue recovery remain unfinished. No device change is enabled.

Retained delivery and Main mode-5 continuation (4 October 2026)
Compact UI send failures now retain an immutable ticket in bounded retry storage.
Main receive retries delivery; ambiguous duplicates cannot repeat the UI body.
The recovered mode-5 branch closes admission before setup and cooperatively
services owned reloads until verified retirement. Full ordinary queues can use a
direct owned-event transfer without running unrelated controls. Actual prefix,
clear and suffix instructions execute once; lease release can retry independently.
Coordinator size is now 400 bytes. Seventeen new groups and all 388 groups
across 25 suites pass. See docs/research/reload_recovery_findings.txt and
reload_recovery_regression.json for checks and limitations. Final evidence and
producer retirement remain explicit external actions. Native entry/return patches,
USB/storage lifetimes and physical effects remain unbound; no device change.

2026-10-04 — automatic reload completion
reload_manager.[ch] copies a pre-reload intended pad/settings plan, serializes
reload admission, seals the joined owner, checks actual pad snapshots and reads
L6PADSETTING.ZST back through checked public wrappers, then retires the producer.
Optional rc_bind_manager connects this to Main receive and mode-5 draining.
An explicit continuous external exclusion port remains required; the capture
SessionManager/publication-to-plan handoff is not yet wired. No device patch.
See docs/research/reload_manager_findings.txt and tests/emulation/verify_reload_manager.py.

2026-10-04 — capture/publication/reload handoff
publication_workflow.[ch] binds the capture manager's completed-take RESET
boundary, retains a child under playback shutdown's exclusive owner across
publication and reload, builds the expected plan from baseline options plus
publisher destinations, and releases capture only after checked completion.
Main defers ordinary controls/mode setup until the entire handoff ends.
The ordinary recorder/card/USB exclusion port remains external and modeled.
Stock auto-assignment of an unassigned pad with catalogue files is rejected,
not silently accepted. See docs/research/publication_workflow_findings.txt and
tests/emulation/verify_publication_workflow.py. Emulator-only; no firmware patch.

2026-10-05 — ordinary read/seek lifetime core
ordinary_io.[ch] retains a root or explicit child session and a pad-file pin
until matching decode, result observation, full worker return and producer
join. Short reads/EOF and original errors remain results, not reload failures.
Eight ordinary contexts use pin slots 2..9 alongside initial-read slots 0/1.
Ten new groups and 171 groups across 16 related suites pass. Native ordinary
callback routing and file-worker hooks remain uninstalled; this is a core
adapter test, not end-to-end ordinary playback protection. See
docs/research/ordinary_io_findings.txt. No device access or firmware staging.

2026-10-05 — ordinary callback and file-worker integration
ordinary_producer.[ch] binds permanent task identities, explicit parent
attribution, distinct read/seek semaphores and one context/pin per task.
rp_dispatch and the new seek entry select it alongside strict reload reads.
rw_next/read/seek now decode, check and observe ordinary operations, and only
acknowledge return after original error handling/zero fill/signal completes.
Once enabled, raw ordinary packets cannot bypass ownership. The parent port
and physical entry patches remain unbound; the test harness supplies them.
Nineteen new groups include two independently suspended native callers;
all 236 groups across 19 suites pass. Faults still park shared participants,
and the full caller lock audit remains open. See
docs/research/ordinary_routing_findings.txt. No device access or firmware staging.

2026-10-05 — playback IO ownership provider
playback_io.[ch] binds Main restart seeks to the held OdSession owner and
queued refill reads to the stream worker's claimed ticket. The receiver retains
packets through contention and releases its shared lock before native waits;
completion cannot repeat the stock refill. pi_parent never infers attribution
from a globally active session. op_bind checks shared ledger/caller binding.
Fifteen new groups and 307 groups across 23 suites pass. The fixed-address scan
producer context, renderer fence and final firmware hooks remain unbound.
See docs/research/playback_io_findings.txt. No device access or staging.

2026-10-05 — native background scan binding
native_scan.[ch] and native_scan_hooks.S bind AudioSubProcess to the session
and shared stream queue. The no-argument callback uses session admission;
whole-scan and refill child tickets retain ownership through queue delivery,
completion and producer return. Metadata retries do not repeat native work.
Tests run the original registered callback/dispatcher and full refill/read path,
including a relocated ledger and a poisoned, untouched legacy scan context.
Twelve new groups and 334 groups across 25 suites pass. Renderer completion,
other direct callers, final activation patches and physical placement remain
open. See docs/research/native_scan_findings.txt. No device access or staging.

2026-10-05 — native whole-audio completion observer
native_audio.[ch] and native_audio_hooks.S wrap original callback dispatch and
return with the existing nonblocking completion protocol. The compiled observer
and four original DSP callbacks run on one emulator CPU. Shutdown integration
also joins the native scan/refill/read chain, retains unknown delivery, blocks
new playback during exclusive access, and requires fresh completion per cycle.
Seventeen new groups; all 431 groups across 33 related suites pass. ARM MAX's
IPSR probe is modeled, with the actual helper checked separately on Cortex-M7.
Capture already uses both hook sites: compose the observers before installation.
Completion alone does not exclude later readers. Control ingress, other direct
callers and hardware placement remain open. See
docs/research/native_audio_findings.txt. No device access or staging.

2026-10-05 — shared capture/completion hooks
na_bind_capture binds the permanent capture bridge after na_bind, before the
first observation, and enables strict invocation capture. na_entry_hook and
na_return_hook now use na_observe_begin/end: completion begins before capture,
and capture releases its scope before completion can acknowledge. These are the
only outer/return replacements for a combined integration. Historical capture
outer/return hooks must not also be installed. Tap/commit hooks are unchanged.
Fifteen new groups include exact file samples through full original DSP and
unchanged stock DSP/ring memory. All 601 groups across 51 related suites pass.
Next bind startup readiness; physical patches, timing and admission coverage
remain open. See docs/research/shared_audio_findings.txt. No device access.

2026-10-05 — dormant shared-audio startup
na_prepare composes both observers without enabling them. Main's na_arm request
is adopted at the next AudioProcess entry; na_ready waits for its successful
full return. Earlier dormant returns cannot acknowledge activation. The native
worker binds this protocol after manager_boot closes capture, and release waits
for readiness before manager/file work. Storage readiness remains an external
precondition with no installed caller. Nine new groups and all 610 groups across
52 suites pass. See docs/research/audio_startup_findings.txt. No device access.
CURRENT STATUS (2026-10-05): this directory's broad ownership/reload/read/USB
overlay and four-pad copy workflow are retained as research, not included in
the capture-only or handoff profiles. The replacement is
../capture/backing_handoff.c. See ../../docs/architecture.md. Bounded completion
waits and safe publication rollback are fixed here for regression coverage;
remaining startup guards and terminal parking must not be installed by default.
