# Consumed-source publication diagnostic

**Status: installed; marker execution and ordinary pad playback verified on hardware.**

Test whether startup can reuse the DSP's compressed input for executable code
after the DSP has finished loading. This avoids needing a separate free memory
region for the proposed capture code and globals.

The original scatter loop loads the unchanged DSP first, expands an eight-byte
marker over consumed input second, and zeros 16 bytes third. The 552-byte loader
and unread compressed marker remain outside both destinations. A read-only query
executes the marker and reports its value, the zeroed region, cache-control state
and fixed scatter records. Existing diagnostics remain available. No capture,
worker, allocation, storage guard or native buffer change is introduced.

The exact image passes **73 offline groups**: seven new checks and all 66 retained
diagnostic checks. Original destinations remain byte-exact; malformed input and
overlap stop before Main; the published marker executes on the same emulated
memory after original cache setup; the original USB sender handles its full reply.
Cache effects, board hardware and interrupt timing remain modeled.

| Item | Value |
|---|---|
| Loader | `0x800a9408`, 552 bytes |
| DSP compressed source / marker destination | `0x800a9688` |
| Unchanged DSP destination / length | `0x20220000`, 55,004 bytes |
| Marker result | `0x4c36` |
| Zeroed region | `0x800b0a00`, 16 bytes |
| Retained diagnostic payload | 10,164 bytes, including 1,780 state bytes |

Image: `deployment/16_source_reuse/trial_source_reuse/L6.BIN`.
SHA256: `012dd6b55b065d4ec18c9287c92c4dfcdf9cc2aab891b3a3741b4784ebf192da`.

```sh
python tools/firmware/build_source_reuse_probe.py
python tests/emulation/verify_source_reuse_probe.py
python tools/device/l6_source_reuse_probe.py --output deployment/16_source_reuse/first-boot-reuse.jsonl
```

Before staging, confirm the mixer is idle with its card inside. The local staging
script checks the exact verified image and card, backs up the current root image
and settings, replaces only `L6.BIN`, and verifies readback/settings/file metadata.
It does not scan audio. Normal Eject and transfer exit precede the physical
update. Keep the current comfortable volume; no level change is needed.

The user confirmed idle before staging. The copied image matches the exact
verified hash; settings and all156 recording/pad metadata entries are unchanged,
without audio scans. Normal Eject and transfer exit pass. Existing pad names and
counts, all three MIDI ports, retained health and diagnostic15's loader reply
pass after reconnection; free heap is163104 bytes. After the user's physical
update/reboot, the new query executes marker0x4c36, reports a zero region and the
exact expected scatter records, with instruction/data caches enabled. All three
MIDI ports, retained health and the complete first-enumeration trace pass.

An automated18.005333-second USB capture identifies pad1's backing with0.999027
whole-source correlation, no host callback errors and1,163 native data waits
without new detail conditions or omissions. Pad assignments and163104-byte free
heap are unchanged. No level, effect or assignment change was made.

Private evidence: `deployment/16_source_reuse/hardware-summary.json`,
`installed_reuse_verification.json` and `pad-playback-01/summary.json`.
The staged file was read back; the running application's reply is not installed
flash readback.

Success qualifies this tiny publication path, not the entire combined capture
payload, source lifetime in every mode, history memory, storage-source exclusion
or additional recording. See
[the source-reuse findings](../../docs/research/capture_source_reuse_findings.txt).
