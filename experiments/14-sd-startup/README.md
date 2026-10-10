# Passive SD startup diagnostic

**Status: running on hardware; first startup trace collected.**

Observe the first controller reset and card-enumeration attempt after power-on.
This covers the small FIFO reads used to identify the card, which are outside
the existing block-transfer observations. It adds no SD commands, register
writes, reset/retry behavior, allocation, worker or extra audio recording.
It keeps diagnostic 13's observations and 223104-frame ordinary buffers.

The exact image now passes 65 offline groups: twelve startup/query checks and all 53
retained diagnostic checks. Original commands, waits, FIFO data and controller
writes match the unmodified path in the tested card model. Reset-hook registers,
flags and stack alignment are preserved. The new queries also reject disconnected
Editor and interrupt-handler contexts in Cortex-M7 emulation. Diagnostic 13
still rebuilds to its previous bytes. The separate capture regression passes
824 groups across 74 suites.

Image: `deployment/14_sd_startup/trial_sd_startup/L6.BIN`.
SHA256: `5887a6b4df5bc68ba104645a6da8b715836509be7f407fab832c5f712effab84`.
Code/state: 9164 bytes, including 1420 persistent bytes. The new startup record
uses 364 bytes plus alignment. All eight original scatter outputs are retained.
Private verification: `analysis/sd_startup_probe_verification.json`.

The initial staging verified this exact image on the L6 card. The preceding diagnostic13 image
and settings are backed up. Settings and metadata for all 156 recording/pad files
are unchanged; no audio was scanned. Normal Eject and Editor transfer exit
completed. The Editor, original pad names/counts and MIDI ports reconnected;
retained health queries report 163104 free heap bytes. After the user's update
and reboot, new replies verify diagnostic14 execution. Original pad names/counts,
MIDI ports, retained observers and memory configuration agree. Installed flash
bytes have not been read back.

The first startup attempts enumeration once and returns zero, observing 31
command entries, 43 IRQs/waits and six PIO completions. There are no busy-claim
skips or observer errors. Only four PIO entries fit, so two are explicitly omitted
and the host correctly refuses a complete-trace claim. The early reset snapshot
still has RSTA set; it is clear by the first retained PIO completion. This early
snapshot cannot be the proposed successful-reset admission point.

The four retained reads are 64, 8, 64 and 64 bytes, all with native flags4 and
raw0x23. A synthetic four-bit/high-speed card now reproduces all aggregate counts
and the first four read positions through original instructions. This explains
the extra reads plausibly; the two omitted physical request identities remain
unobserved. No firmware fault or capture permission follows from these readings.

```sh
python tools/firmware/build_sd_startup_probe.py
python tools/firmware/build_sd_command_fixture.py
python tests/emulation/verify_sd_startup_probe.py
```

Stage only while the mixer is idle. Use the official Editor's File Transfer
Mode, identify the L6 card, back up the existing firmware and settings, copy
the verified image as card-root `L6.BIN`, and verify its readback. Check settings
and basic recording/pad file metadata; do not scan all audio. Safely eject and
exit transfer mode before the [tested physical update](../01-usb-name/README.md):
hold PLAY/STOP while powering on with stable power, wait for rapid green
blinking, then reboot normally. Card-file verification does not verify installed
flash bytes.

After reboot, keep the official Editor connected and collect the frozen record
before any further transfer, reset or card change. No test recording is needed:

```sh
python tools/device/l6_sd_startup_probe.py --output deployment/14_sd_startup/first-boot.jsonl
```

Six read-only queries return a summary, the first reset snapshot and up to four
PIO completion samples. Queries read saved RAM only, without controller reads
or state resets. Later enumeration attempts, missed observations, inconsistent
epochs and journal overflow remain visible and invalidate complete coverage.
An unsuccessful first attempt cannot be replaced by a later successful one.

This is evidence about startup behavior, not permission to enable capture.
Raw interrupt flags are associated by time, without proven request identity or
exclusion of old sources. A successful native result does not establish physical
completion. See [cold-start findings](../../docs/research/sd_cold_start_findings.txt).

Continuous cold setup uses generic ARM emulation for the native double-precision
clock code; query IPSR reads there are explicitly modeled as Thread mode.
Separate Cortex-M7 cases execute the actual query context checks, reset adapter
and retained diagnostics. Traced software stack use is 892 bytes versus 672
without the observer in the modeled enumeration. Physical exception nesting,
stack headroom and timing remain unmeasured; other card negotiations are not
exhaustively covered. Firmware images and raw device evidence remain private.

## Expanded journal revision

**Status: running on hardware; complete first-enumeration trace collected.**

The preceding diagnostic14 image and settings are backed up. Settings and all
156 recording/pad file metadata entries are unchanged, with no audio scan.
Normal Eject, transfer exit, original pads/MIDI and retained health replies pass;
free heap is163104 bytes. The original first four PIO records still match their
pre-transfer values. After the user's update and normal reboot, all eleven
schema2 replies now verify execution of the detail revision. Installed flash
bytes have not been read back.

The frozen trace contains one successful enumeration, 31 command entries,
43 IRQs/waits and all six PIO completions, with zero omissions, skipped claims
or observer errors. The enclosing request codes/arguments identify ACMD13
status (64 bytes), ACMD51 SCR (8 bytes), and four CMD6 reads (64 bytes each):
check, check, switch, check. This matches the original high-speed path exercised
offline. All six final waits return status0, flags4 and raw0x23.

SYSTEM changes from `0x018f801f` at early reset observation to `0x008f801f`
before the first command: reset has cleared by command entry. At that later
snapshot, raw/signal status and IRQ pending/active bits are zero, with IRQ110
enabled. This closes the missing trace and reset-timing observations; it does
not prove exclusion of earlier sources or authorize capture.

Original pad names/counts, MIDI ports and retained health replies pass after
the update. Free heap remains163104 bytes, and three paired memory-configuration
snapshots agree. No audio test or card-file scan was performed in this check.
Private evidence: `deployment/14_sd_startup_detail/installed_startup_verification.json`
and `first-boot-interpretation.json` in the same directory.

The original four-entry log omitted two of the six observed startup reads.
The detail revision keeps eight entries, adds each enclosing software request's
code/argument, and takes a second fixed register snapshot when the first command
starts. The recursive CMD55 prefix cannot overwrite its parent request identity.
The new snapshot is inside the native clock-enabled command callback; it does
not read the controller from the outer, potentially clock-gated dispatcher.

This revision passes 66 offline groups, including all 53 retained diagnostics,
the original high-speed card path, bounded journal overflow, deferred reset clear
and unchanged original command/wait/register behavior. Diagnostic14's original
image rebuilds byte-for-byte and passes65 groups. The cold-start suite separately
passes10 groups; the last full capture run remains824 groups across74 suites.

Image: `deployment/14_sd_startup_detail/trial_sd_startup_detail/L6.BIN`.
SHA256: `551d67a35fa6249496ed7d9815ba1d518a0e8d20775026ee48ae4f2e235f831c`.
Code/state:9652 bytes, including1780 persistent bytes; this is488 additional
loaded bytes, of which360 are persistent state. Modeled enumeration stack remains
892 bytes. No additional audio buffer, heap request, task, command, register write,
reset/retry behavior or capture permission is added. Precise hardware timing and
physical stack headroom remain unmeasured.

```sh
python tools/firmware/build_sd_startup_detail.py
python tests/emulation/verify_sd_startup_probe.py --detail
python tools/device/l6_sd_startup_probe.py --output deployment/14_sd_startup_detail/first-boot.jsonl
```

The host reads the summary first, recognizes schema1 or2, then requests only the
corresponding six or eleven pages. It retains missing/overflow/inconsistent
observations as incomplete and never reports physical completion. A clear later
reset snapshot is still not the missing source-exclusion proof.
