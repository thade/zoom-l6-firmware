# SD chunk-completion diagnostic

**Status: detailed probe tested with recording and backing; completion binding remains unresolved.**

For the initial revision, the identified L6 card received the exact diagnostic image with verified readback.
All 114 recording/pad file entries retain their metadata; settings and all 58
saved audio evidence files match before and after staging. The previous update
file and settings have local backups. Normal macOS Eject succeeded after two
unmount attempts were refused by loginwindow; no forced operation was used.
Transfer mode is closed, original pad assignments/counts and native capacity
respond correctly. The user completed the physical update and reboot; valid
73/72 replies confirm execution of this diagnostic. Installed flash has not
been read back. No new guard sweep was performed; historical source omissions rose
from 64 to 191 during transfer, so this is not source-ownership qualification.

Two consistent baseline query sets agree on 1,200 observed waits, zero omitted
chunk observations, both read paths reached and 16 anomaly detections. The first
retained anomaly is a successful bounce-read wait: completion flags are `4`,
`PRES_STATE` is `0xff88800e` and its activity mask is `6` (data inhibit and data
line active; read/write transfer activity is clear). The latest sample is quiet.
The first sample uses multi-block reads with automatic CMD12. A trailing stop or
busy phase is a hypothesis, not a measured explanation or proof of unfinished
DMA. The other 15 samples are not retained, so their causes are unknown. At this
startup checkpoint no write path had been observed. Pad filenames/counts remain unchanged and
current/minimum free heap is 163,104 bytes. See the findings for evidence limits.

The completed 29.279-second take has seven valid, finite, aligned recording files.
Counters add 997 waits, zero omitted chunk observations and 181 detections; all
four read/write sites have now been reached. The retained first anomaly is still
the startup read, so these new detections cannot yet be classified. The broader
SD observer adds 269 reads, 383 writes and one omitted call; free heap is unchanged.
All 58 earlier evidence hashes, settings and prior audio metadata are preserved.
The master closely matches the input stems; the assigned pad 1 backing could not
be identified. Concurrent audible pad playback remains unconfirmed, and the
user's listening report is pending.

The separate **detail** build adds counters, a union of observed reason bits and
the latest anomaly for each of the four sites. It preserves the first anomaly,
latest sample and existing health protocol. Querying never clears observations.
It adds 640 code/state bytes and passes 13 offline groups; the original build
remains byte-identical and passes its ten groups. No extra recorder is enabled.

```sh
python tools/firmware/build_sd_completion_probe.py --detail
python tests/emulation/verify_sd_completion_probe.py --detail
```

Private detail image: `deployment/09_sd_completion/detail/trial_sd_completion/L6.BIN`.
SHA256: `2ab527c9fc7971a969a37faebaa940dcee09d5c6423da529389e5ee388756cae`.
The detail image is now staged with matching readback; 121 audio/pad metadata
entries, settings and all 65 saved audio hashes are preserved. Normal Eject and
transfer exit succeeded, with the original pad names/counts verified again.
The user has completed the detail update and reboot. All seven fixed pages
respond, confirming execution of the detail code; installed flash has not been
read back. At its first stopped startup checkpoint, all pages agree on 1,200
waits, zero omitted chunk observations and 13 detections, all at the bounce-read
site. The only categories in its reason union are data inhibit and data-line
activity (`0x600`). No wait-error, fault, reset, unexpected-mode/argument or
read/write-transfer-active category is observed. The latest sample is quiet.
Both read paths are reached; neither write path is reached yet. Heap free and
minimum are 163,104 bytes, and all original pad names/counts are verified again.
Reason unions do not count individual categories, show whether every detection
had both bits, measure busy duration or establish physical completion.
See `detail/startup_baseline_summary.json` for the validated local checkpoint.

Collect all seven fixed pages using `--detail` and a fresh log. The initial probe
does not support the extra pages.

```sh
python tools/device/l6_sd_completion_probe.py --detail --output deployment/09_sd_completion/detail/baseline-01.jsonl
```

This trial checks whether the card controller still reports activity when each
native recording/read chunk returns. That determines where buffer protection
must go before enabling the extra overdub recording.

It observes four existing data-wait sites normally used for DMA. Stock write-error
diagnostics can also enter one of them with DMA disabled, which is classified as
an unexpected mode rather than silently excluded. General PIO paths are not
covered. Recording, pads, settings and
the existing 223104-frame buffer capacity keep their current behaviour. There
is no extra recorder, buffer retention, reset, retry or pad assignment.

Prepare and verify locally:

```sh
python tools/firmware/build_sd_completion_probe.py
python tests/emulation/verify_sd_completion_probe.py
```

Ten offline groups pass. Private image:
`deployment/09_sd_completion/trial_sd_completion/L6.BIN`.
SHA256: `e786b5142e25c39731dc1cac41a8326d5843b68615a156fb5d1198df2298901f`.
See [findings](../../docs/research/sd_chunk_observation_findings.txt) for scope.

When installing a fresh trial, after verified staging, safe unmount and transfer exit, use the previously tested
physical [update procedure](../01-usb-name/README.md) and reboot normally. Connect the official Editor,
then obtain the baseline with a fresh log:

```sh
python tools/device/l6_sd_completion_probe.py --output deployment/09_sd_completion/baseline-01.jsonl
```

Verify backing in the USB master before the next recording; the previous take
did not independently establish pad playback. The official Editor currently
shows pad 1 One-shot, MIDI note 60/channel 1 and MIDI control enabled. Zoom's
[manual](https://zoomcorp.com/manuals/l6-en/) documents note-triggered pad playback
on the L6 Mixer Control Port. The playback preflight sends only that fixed note
on/off pair and captures USB input, without transport or level changes.

The playback-only preflight passed: an 18.005-second finite USB capture matches
the assigned source at correlation 0.9923, with three separated one-second
windows at 0.9859–0.9978. The host reported no input-buffer errors. Its stopped
counter interval adds 1,163 bounce-read waits, zero omitted chunk observations
and zero new detections; broad reads add 54, with no writes or omissions. Heap
and assignment remain unchanged. This verifies USB backing playback, not SD
recording or physical completion. Local evidence: `detail/pad-playback-01/`.

The subsequent recording passed its audio/file checks: all seven files contain
8,601,408 finite frames at 48 kHz, aligned at 179.196 seconds. The 12.972-second
one-shot backing is identified in MASTER at about 25.244 seconds, with source
correlation 0.99999987 and no backing detected in the input stems. Live inputs
were mostly noise, so this does not establish a substantial new live layer.
The user heard the backing and reported no audio problems. All 65 prior saved
audio hashes, 121 prior metadata entries and settings are preserved. Normal
Eject and transfer exit succeeded; the Editor and original pad queries respond.
Local evidence: `detail/recording-playback-01/`.

The stopped recording interval adds 4,896 waits, zero omitted chunk observations
and 948 detections: 934 direct-write and 14 bounce-write detections. Every
direct-write wait on this recording boot had a detection. All reason unions
contain only data inhibit and data-line activity; no wait-error, fault, reset,
unexpected-mode/argument or transfer-active category is observed. Retained
write samples have DAT0 low, consistent with trailing card busy; NXP documents
[card busy after a write returns](https://mcuxpresso.nxp.com/api_doc/dev/3151/a00063.html).
This is a candidate-driver explanation, not a proven memory-completion contract.
Broader SD observations add 396 reads, 1,504 writes and one omitted call. Heap
current/minimum remains 163,104 at the stopped recording checkpoint.
The later transfer interval is retained separately. No extra capture is enabled.

For a future recording trial, press Record and report that recording is active.
The computer can then trigger the same pad and capture USB audio automatically;
make an ordinary multitrack recording with some live notes. Stop with Record
after the playback check completes, and obtain another stopped sample. Live
pages may change or be busy and are not stopped baselines. Compare counter progress, omitted
observations, all reached call sites, anomalies and retained first anomaly. A
busy snapshot is incomplete; query again after stopping. Inspect all seven
ordinary files and preserve their evidence before attempting a longer take.
Do not deliberately remove the card or inject transfer faults for this trial.

Quiet controller samples are evidence about the exercised paths. They do not
prove physical completion, cache visibility, stale-IRQ identity or failure
recovery, and do not authorize installing the extra recorder.
