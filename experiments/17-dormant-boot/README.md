# Full payload, dormant worker

This trial loads the full recording code and creates its worker, which stays
asleep. It checks startup and memory use before adding extra recording traffic.
The mixer still makes its ordinary master and channel recordings.

**Prepared locally; not staged or installed.** Diagnostic16 remains on the mixer.
No mixer controls, levels, pad assignments or card contents were changed while
preparing this trial.

The new code observes successful initial card setup and the actual USB task
request/consumption/acknowledgement. Missing or unexpected startup observations
disable the optional witness for that boot. This does not authorize capture.

The image enables only startup, startup observations, existing Main closure and
a fixed read-only status query. Original DSP, recording controls and SD driver
paths remain unhooked. The already-tried223104-frame native ring capacity is
retained. There is no capture release command or automatic pad assignment.
Earlier passive diagnostic queries are replaced by this smaller status query;
normal Editor and pad messages still use the original handlers.

## Prepared artifact

- Local image: `deployment/17_dormant_boot/trial_dormant_boot/L6.BIN`.
- SHA256: `7ffdd68a9081e8dd60574bac90dc2b9aa4152bcf31fcc39e62bf0e3c009770cf`.
- Full code:29,060 bytes; globals:288 bytes; packed spare:882 bytes.
- Arena request:9,887 bytes; worker stack:16,384 bytes, plus native task/allocator overhead.
- Actual additional native heap use:26,456 bytes (9,896 arena +16,400 stack +160 task object), verified offline through the original allocator and task creator.
- Offline report: `analysis/boot_probe_verification.json`.
- Startup witness report: `analysis/storage_boot_verification.json`.

Twelve dedicated offline groups pass, including the exact image's original
scatter outputs, cache/startup ordering, a sleeping worker, allocation failures,
dormant-lease closure, query validation and preserved pad routing. Linker tests
reject code and globals that exceed their bounded regions. Task scheduling,
hardware cache effects and physical storage behavior remain modeled.
Four further groups execute the original task creator and ready-list/initial
frame setup. Stack-allocation failure stays closed; task-object allocation
failure frees its stack while retaining the arena, without a retry. A successful
initial saved frame reserves76 bytes; that is not a runtime stack measurement.

## When the user is available

1. Confirm the mixer is idle with its card inside. Stage and read back only this
   image, settings and basic metadata, then eject normally and leave transfer
   mode. Do not scan all audio files.
2. Perform the usual PLAY/STOP-held firmware update, wait for rapid green, and
   reboot normally with the card inside. Leave the mixer idle.
3. Run the fixed query twice, one second apart, using
   `tools/device/l6_boot_probe.py --output NEW_LOG --manifest deployment/17_dormant_boot/manifest.json`.
   The script changes no settings. The log must be a new path.
4. Check native pad replies and automated one-shot backing playback at the
   user's existing comfortable levels. Compare heap before/after and confirm
   the worker stays asleep. No recording or knob changes are needed for this
   first trial.

Expected initial observations: startup registered, witness READY9, worker
WAITING4, manager RESET4, lease CLOSED0, zero physical ports and active capture
hooks, correct code/global bounds, both caches enabled, and a worker poll count
that advances at the idle interval. Missing readiness or unexpected activity is
a failed trial, not permission to enable capture. Any later card/USB transition
permanently revokes the witness until reboot; do not interpret that as a new
normal-startup result.

Successful boot would qualify only this dormant payload and the exercised
startup path. Physical SD/cache ownership, loaded worker timing/stack margin,
extra-file capture and automatic pad publication remain unqualified. Do not
install an offline capture ELF or manually set its readiness/physical ports.
