# Raw SD interrupt diagnostic

**Status: running on hardware; startup, playback and the restarted ordinary recording are verified.**

The exact image is on the identified L6 card. All 128 recording/pad files
(3181674312 bytes) match their pre-transfer hashes and metadata; settings also
match. The previous update and settings have local backups. Normal Eject and
transfer exit succeeded. The Editor reconnects, all original pad names/counts
respond unchanged, and the existing diagnostic still responds with 163104
current free heap bytes. After the user completed the update/reboot, all four
new raw pages and the retained detail/health pages respond. This confirms
diagnostic 10's execution; installed flash has not been read back. Local evidence is under
`deployment/10_sd_raw/`.

Two stopped startup sets agree on 3024 interrupts and 1206 TC indications,
1200 sampled with DMA enabled, with no raw errors or missed samples. The retained
detail sees 1200 read waits without detections. The core reports enabled 128-KiB
DTCM and 32-KiB ITCM, plus enabled instruction/data caches. Both native bounce
areas fit in DTCM, whose CPU accesses bypass cache. The peripheral bus path and
exact chip remain unproved; see the findings for the architectural interpretation.

An automated one-shot pad check captures 18.005 seconds of finite USB audio,
matching the source at correlation 0.99186 and three separated windows above
0.9857. No host audio-buffer error is reported. It adds 1163 bounce-read waits
and DMA-mode TC indications, with no raw/detail errors, omissions or detections.
Original pad names/counts and current/minimum heap (163104 bytes) are unchanged.
The subsequent two takes are 136.905 and 201.279 seconds; all fourteen WAVs
are valid, finite and aligned within each take. The first was interrupted before
the first pad trigger and has no identified complete backing. The restarted
take includes the 12.972-second backing at 39.046 seconds plus substantial
input-3 notes. After accounting for live stems, source correlation is 0.95724;
the separate stems have maximum absolute source correlation 0.00515. Its aligned
backing window matches the USB master and stems within 4.657e-10 per sample.
The user's initial listening report was corrected to uncertain.

The stopped interval adds 12776 TC/DMA-mode TC and native wait observations,
with zero raw errors, raw omissions or detailed omissions. Ninety-six consistent
live latest-TC pages have sampled DMA-write configuration, raw status 0x02/0x0a/
0x12 and no error flags. Both sampling windows belong to the restarted take, before the
second trigger and just after backing ends; these stored writes have no proven
command generation. Detailed writes still show trailing inhibit/line activity
without transfer-active bits. The broad observer omits eight calls and reaches
648 ticks; its coverage and an added-capture service budget are not qualified.
Stopped current/minimum heap remains 163104 bytes. Inspection copies 784170834
bytes with matching local hashes; all 128 prior metadata entries, settings and
the pad source are preserved. Normal Eject, transfer exit, original pad replies
and restored current heap pass. Prior audio byte hashes were not repeated.

Next bind concrete completion/generation and exclusive buffer ownership beneath
both audio and metadata IO, then qualify storage transitions and memory before
enabling a capture-only trial. Actual IRQ/worker stack and added-capture service
capacity remain open. Keep busy/changing live pages incomplete; quiet snapshots
do not grant buffer reuse. No settings or card faults were injected.

This diagnostic records the SD controller's completion and error bits before
the existing interrupt handler clears them. It also records the active cache
and tightly coupled memory settings. These answer specific remaining questions
before enabling an extra overdub recording.

It retains diagnostic 09's detailed wait observations and health queries,
ordinary recording, pad assignments and the 223104-frame native buffer capacity.
It adds one interrupt observer. The existing handler still acknowledges status
and posts the same events. There is no extra recorder, new task/allocation,
cache change, controller reset, retry or buffer protection.

Prepare and verify locally:

```sh
python tools/firmware/build_sd_raw_probe.py
python tests/emulation/verify_sd_raw_probe.py
```

All 23 offline groups pass: thirteen existing detail groups run against this
exact image, plus ten new raw-observer groups. The complete redesigned capture
regression separately passes 730 groups across 64 suites. Original diagnostic
09 builds remain byte-identical.

Private image: `deployment/10_sd_raw/trial_sd_raw/L6.BIN`.
SHA256: `d67c6e7fd0b8fbcda61497ebb28805b462c9ebf3a15c38b3a82e48a50043f091`.
Code/state uses 3964 bytes, including 636 aligned state bytes. The new IRQ
adapter has a 132-byte traced software stack in the modeled test; actual
exception stack, latency and headroom require device validation.

Stage only this verified image on the identified card, preserve the previous
update file and verify settings/audio before and after. After matching readback,
normal Eject and transfer exit, use the previously tested physical
[update procedure](../01-usb-name/README.md) and reboot normally. Staged file
identity is not installed flash readback.

With the official Editor connected, collect four fixed read-only pages into a
fresh log:

```sh
python tools/device/l6_sd_raw_probe.py --output deployment/10_sd_raw/startup-01.jsonl
```

The pages are latest transfer-complete interrupt, first transfer-complete
interrupt, latest raw error and counters. Querying returns stored observations
and never clears them. Existing detail and health helpers still work. Start with
stopped startup samples. Inspect the TCM/cache settings and any omitted/raw-error
observations before choosing the next ordinary recording with audible pad backing.

Raw snapshots are sequential. The interrupted task is not a demonstrated
transfer owner, and the DMA address may have advanced. A completion bit has no
proven transfer generation. Missing/skipped or changing snapshots are incomplete.
These observations do not establish physical transfer joining or safe cache/
buffer reuse. See [findings](../../docs/research/sd_raw_observation_findings.txt).
