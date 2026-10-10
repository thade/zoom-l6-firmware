# Passive upper-gap activity diagnostic

**Status: running on hardware; idle, recording, playback, effects and transfer comparisons collected.**

Read small sections of the apparent upper RAM gap without reserving or writing
that space. This extends diagnostic 12, retains its earlier observers and keeps
the existing 223104-frame ordinary recording buffers. Extra capture, its worker,
allocation and storage guards remain disabled. Ordinary recording stays enabled.

All 53 offline groups pass against the exact prepared image: 11 new groups and
all 42 earlier diagnostic groups. The diagnostic 12 builder still produces its
original image. These checks are separate from the 774-group capture regression.
Firmware binaries, card backups and raw device evidence stay private.

The exact image is on the identified L6 card. Previous firmware/settings are
backed up; settings and metadata for all 149 recording/pad files remain unchanged.
Normal Eject, Editor transfer exit and reconnection completed, with original pad
names/counts, MIDI ports and retained diagnostic replies checked. After the
user's update/reboot, the new query confirms diagnostic 13 execution. Installed
flash bytes have not been read back.

Two complete idle sweeps agree across all 872 pages. Two automated one-shot
pad-1 plays cover 436 disjoint pages each; their combined fingerprints also
match the idle baseline. USB source matching confirms both backing plays, with
finite samples and no host callback errors. This is coverage across two plays,
not one continuous playback. Each page query spans zero or one timer ticks;
free/minimum heap remains 163104 bytes during recording and playback.

A 165.251-second multitrack take adds two recording observation windows covering
all 872 pages, again matching idle. The first backing is identified in USB audio
and the saved MASTER. The master becomes silent at 34.956 seconds; the user
confirmed changing a level or mute. The second backing is therefore unconfirmed,
not a demonstrated firmware dropout. All seven WAV headers have matching frame
counts; only MASTER audio and small headers were read from the card. Full RAM
sweeps after stop and after normal card transfer also match. The Editor and pads
reconnect normally. Current free heap returns to 163104 bytes; its low-water mark
after transfer is 160664. Stable fingerprints do not establish unused memory.

A further full sweep during user-reported song playback matches idle, with SD
reads advancing and no writes. Its USB MASTER is silent, so song audio is not
verified. After the user enabled the effect send/return, six automated 24-second
USB tests cover all five effects and restored Room. Each effect has a measurable,
distinct response, and every full RAM sweep matches idle. Restored Room matches
its starting response. No host audio errors or additional SD reads/writes occur
during those effects tests. Free/minimum heap remains 163104/160664 bytes.

The user identified the recordings as disposable tests and asked to stop routine
full audio scans. The pre-write audio scan completed; the post-write scan was
stopped. Full byte preservation is therefore not claimed. Future staging checks
firmware hash/readback, settings and basic file metadata; read audio only when
needed for a particular audio test.

Image: `deployment/13_ram_activity/trial_ram_activity/L6.BIN`.
SHA256: `178533646790e4859c486af6b4d43a9a54505ec0a5870369435067a9e2d90157`.
Code/state: 7324 bytes, including the unchanged 1052 persistent state bytes.
The new query adds 512 bytes and no persistent state. Traced software stack use
is 248 bytes for the query path and 280 bytes with the original reply sender;
physical stack headroom, exception frames and precise timing remain unmeasured.

```sh
python tools/firmware/build_ram_activity_probe.py
python tools/firmware/build_sd_command_fixture.py
python tests/emulation/verify_ram_activity_probe.py
```

After verified card staging, normal Eject and Editor transfer exit, follow the
[tested physical update procedure](../01-usb-name/README.md). Keep stable power,
hold PLAY/STOP while powering on, wait for rapid green blinking, then reboot
normally. A card-file readback does not verify installed flash bytes.

With diagnostic 13 installed and the official Editor connected, start with
three pages, then collect two complete idle snapshots:

```sh
python tools/device/l6_ram_activity_probe.py --quick --output deployment/13_ram_activity/startup-quick.jsonl
python tools/device/l6_ram_activity_probe.py --output deployment/13_ram_activity/idle-01.jsonl
python tools/device/l6_ram_activity_probe.py --output deployment/13_ram_activity/idle-02.jsonl --baseline deployment/13_ram_activity/idle-01.jsonl
```

Each query reads one fixed 1024-byte page twice. There are 872 pages covering
`[0x81f26000,0x82000000)`. The host pauses at least 20 ms between queries by
default and matches both page and token in replies. Malformed packets, changed
fingerprints, inconsistent controller readings and missing pages cannot yield
a complete unchanged comparison. Quick checks never claim full coverage.

Next trace remaining memory users and address/cache aliases; repeating unchanged
snapshots cannot establish ownership. The transfer comparison covers before/after one
normal Editor transfer, not activity inside that mode or every card/USB path.
Collect only while the Editor query path is reachable, and keep physical mode
changes separate from observation logs.

**Unchanged fingerprints do not prove unused RAM.** CPU reads can see cached
data and miss DMA writes, transient activity or read-only consumers. The digests
also have collision limits. This adds activity evidence; ownership and physical
address independence must still be established before using this gap for audio.
See [findings](../../docs/research/ram_activity_probe_findings.txt).
