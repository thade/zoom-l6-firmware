# Fixed ring-layout diagnostic

**Status: idle, recording, playback and effect-parameter guard scans pass; active effects pending.**

The exact image is on the identified L6 card. All 107 recording/pad file entries
retain their metadata, global settings are unchanged, and all 51 saved audio
evidence hashes pass before and after staging. The previous update file and
settings have local backups. Safe unmount and transfer exit passed; original pad
assignments/counts, normal MIDI ports and legacy timing replies are unchanged.
Following the user-reported update/reboot, fixed diagnostic replies confirm the
new layout: both native capacities and both cached capacities are 223104 frames.
All 202752 guard words (811008 bytes) were initialized, and two complete idle
scans pass across twelve tails. Current/minimum free heap is 163104 bytes.
Pad 1 was prepared with GLORY_BOX.WAV, Loop, 0 dB, in Multi Track mode. Flash has
not been read back; execution confirmation is behavioral.

One historical storage-source observation was omitted; its cause is unknown.
It remains in the evidence. No new source omission or observed span conflict
occurred during the checked intervals, including 59 requests while preparing
the backing pad. Two missed guard-check claims were safely retried without
rewriting guards. These limits do not qualify complete boot coverage.

The completed 197.6-second ordinary take has seven finite, equally long WAVs.
The stopped full scan passes across twelve tails; both backing loop periods
match the source exactly and the user reports no audible problems. All 51 prior
evidence hashes are preserved, along with global settings and existing audio
metadata. Five further source observations were omitted during the recording
interval (six total), so complete storage-source exclusion is still unproved.
Sampled ordinary backlog reaches 1.565 seconds; this is not a maximum service
blackout or selected extra-capture budget. Amplitude/level analysis remains
deferred. No extra recording stream is enabled.

Separate full scans after safe transfer exit and pad restoration also pass.
Original assignments/counts, pad 1 One-shot/0 dB and normal MIDI ports are
restored; the mixer remains powered with guards armed. Source omissions rise to
63 during transfer, while stopped scan windows have no fresh omissions. Current
heap is 163104 bytes; historical minimum after transfer is 160664. Next qualify
effects. Recorded-song playback also passes a full stopped guard scan, with no
user-reported audible problems. One further source observation is missed during
sampled playback (64 total); full source coverage remains unproved. Original
pads/counts and heap remain good. After explicit user authorization, one parameter
in each of Hall, Room, Spring, Delay and Echo is changed by one unit and restored.
Ten full scans after changes/restorations pass; a final scan reaches sweep 17.
All ten original values persist after reopening the Editor effect dialog. Source
counts remain 85988 requests and 64 historical omissions, with none newly omitted.
Nine missed guard claims are safely retried across the step scans; the final scan
has none. Fresh pad/count/MIDI/legacy controls also pass. Stopped parameter updates
and active effect engine/audio-path checks remain separate qualifications: the
latter are next. The earlier approval rejection is resolved.

The user then prepared channel 5's EFX send/return, and the Python USB test
completed all five effects plus a restored Room pass. Seven full scans reach
sweep 26 with all twelve tails intact; no new source omission or layout fault is
observed. All five effect responses are distinct, Room's restored decay matches,
and original numeric parameters/pads, MIDI ports and heap pass final checks.
A strict waveform comparison initially flagged restoration; the same saved
captures pass the corrected energy-envelope comparison and wrong-effect controls.
The initial failure report remains preserved. This qualifies checked writes for
the exercised effect paths; SD service, complete ownership and an extra-capture
budget remain unproved. The user's send/return setup remains in place.

This trial tests whether the ends of the existing audio buffers can support a
larger overdub history. One original startup instruction sets ordinary history
to 4.648 seconds. No extra recorder is enabled. It plants guard patterns while
idle, checks for corruption, observes requested storage buffer addresses, and
samples ordinary recorder backlog. Each guard operation touches at most 2 KiB.

Twenty new offline groups and 128 groups across eight focused suites pass.
Nine additional host groups verify interval checks, bounded retries and full
circular scans; the twenty firmware probe groups were rechecked. Host fixes
leave the deployed firmware image unchanged.
See [findings](../../docs/research/ring_probe_findings.txt) for evidence, source
aliases and limits. Clean guards qualify the exercised modes; they do not prove
complete memory ownership, physical DMA/cache lifetime or a sufficient budget.
The prospective 1.365-second extra history is not yet implemented.

Prepare using the dependencies in [setup](../../docs/setup.md):

```sh
python tools/firmware/build_ring_probe.py
python tests/emulation/verify_ring_probe.py
```

Private image: `deployment/08_ring_probe/trial_ring_probe/L6.BIN`.
SHA256:

```text
35aa147f5024a6dd563dac1766c6f39963144105b221e44b87c87650d7ec2f91
```

Stage exactly, preserve existing audio/settings, verify readback, safely unmount
and exit transfer mode before following the existing manual update procedure.
Reboot normally and connect the official Editor. Read status first:

```sh
python tools/device/l6_ring_probe.py --output deployment/08_ring_probe/status-01.jsonl
```

With recording and playback stopped, explicitly initialize the guards and check
one full sweep:

```sh
python tools/device/l6_ring_probe.py --initialize-guards --scan --output deployment/08_ring_probe/armed-01.jsonl
```

Guard initialization writes 396 bounded chunks. A full scan requires 396
successful check chunks, returning to its starting index even when resuming
partway through the ring. A missed guard claim may be retried up to three total
attempts only when a consistent reply proves the body did not run. Missing
transport replies, faults and activity refusals are not retried.
Armed guards cannot be rewritten. A fault retains its first address and values;
stop the trial and preserve logs. Reboot clears the diagnostic state and guards.
Never initialize while recording or playing a recorded song. The tool refuses
such initialization, incomplete progress or incompatible native layout.

Keep the mixer powered to preserve guards. For the ordinary-recording test,
record about three minutes of
the established backing plus input 3, starting/stopping with Record.
Initially collect status/backlog during the take and scan only after stopping:

```sh
python tools/device/l6_ring_probe.py --scan --output deployment/08_ring_probe/after-recording-01.jsonl
```

Check all seven files, prior evidence hashes, backing repeats, listening and
settings/pad restoration. Then test recorded-song playback and effect changes
separately; check guards after each. Add a live scan only after the stopped
baseline passes. Transfer/remount is another separate qualification step.
Use a fresh log name every time. Stop on corruption, span overlap, invalid source
spans or newly omitted source observations. The tool reads source status before
guard commands and between chunks, retains historical omissions and checks for
new omissions in each measured interval. Incomplete coverage is not a pass.

The five-effect audio test can also run from the computer on macOS. Connect the
official Editor, confirm MIDI channel 1 and EFX TYPE controller 117 in its MIDI
mapping, and note the currently selected effect. Enable USB 1/2 input to channel
5, turn up its EFX send and the EFX RTN knob, and keep native recording/song
playback stopped. These are test setup controls, not changes to the overdubbing
workflow. Install `numpy`, `sounddevice` and `soundfile` in the host Python
environment, then use a new computer-only output folder:

```sh
python tools/device/l6_effect_audio_test.py --original-effect room --verified-cc117-channel1 --output deployment/08_ring_probe/effects-audio-01
```

The script sends quiet repeatable bursts into the L6, captures all twelve USB
inputs, switches the five effects, and checks a full guard sweep after each
24-second pass. Only effect type changes over MIDI; the original type is restored
in cleanup. A final audio pass compares the restored response with the original.
The comparison uses background-corrected stereo energy in 20ms bins, preserving
decay/repeat timing while tolerating changing reverb phase. Wrong-effect references
must also fail the restoration match. It does not require identical waveforms.
Source/backlog/layout status is sampled during audio; guard scans run after the
host stream stops. Missing effect response, new source omissions or guard faults
stop the test. Audio and reports stay on the computer. This tests effect audio
paths and checked tail writes; it does not exercise the SD recorder, additional
capture or synchronized overdubbing.

Queries are fixed commands 75/74, kinds 1..5; only kind 2 writes guards. Default
queries write no guards. Legacy timing remains available; experiment 07's
per-task service protocol is absent. Sampled modulo backlog cannot reveal
missed whole laps or unsampled peaks. Guard scans detect writes, not reads or
aliases, and introduce workload whose hardware effect remains unmeasured.
