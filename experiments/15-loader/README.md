# Isolated startup loader diagnostic

**Status: installed; startup identity and automated pad playback verified.**

Test the 512-byte LZ4 decoder needed to fit the combined capture and storage code.
This trial loads the unchanged stock DSP into its existing destination. It keeps
expanded diagnostic14 and introduces no capture worker, extra recording, new
memory reservation, or storage guard.

The exact image passes 71 offline groups: five loader/query checks and all 66
retained checks. Original scatter outputs match, malformed input stops before
Main, and the fixed read-only query executes through the original USB sender.
Code is 9,812 bytes; persistent state remains 1,780 bytes. The compressed stock
DSP uses 31,605 bytes. Normal capture profiles remain separate from this builder.

Image: `deployment/15_loader/trial_loader/L6.BIN`.
SHA256: `05586375a6945f9034dfdee7f8c0ecd9829104fa5538651b374079a8daabe9dd`.

Staging verified the card file and preserved settings and 156 recording/pad
metadata entries without scanning audio. Normal Eject and transfer exit passed.
After the user's physical update and normal reboot, the new query reported:

| Field | Value |
|---|---|
| Compressed source | `0x800a9608` |
| Original DSP destination | `0x20220000` |
| Expanded bytes | 55,004 |
| New loader | `0x800a9408` |

Original pad names/counts, MIDI ports and retained health checks pass. Free heap
remains 163,104 bytes. This is new-code execution evidence and an application-RAM
record; installed flash bytes have not been read back.

One automated pad1 play produced 18.005333 seconds of finite USB audio, with
0.992265 whole-source correlation, three separated windows above 0.985, and no
host callback errors. There were 1,162 native data waits and no new detail
conditions or omitted observations. Pad settings were unchanged. The preceding
attempt failed whole-source matching during a substantial gain change; its
original result is preserved. The user subsequently confirmed changing volume for comfort.
No SD recording transport command or level/effect change was sent.

```sh
python tools/firmware/build_loader_probe.py
python tests/emulation/verify_loader_probe.py
python tools/device/l6_loader_probe.py --output deployment/15_loader/loader-query.jsonl
```

Private evidence: `deployment/15_loader/installed_loader_verification.json`,
`hardware-summary.json`, and the two `pad-playback-*` directories.

This qualifies the new decoder on the exercised original DSP path. It does not
qualify capture's new executable/global destinations, physical memory ownership,
storage-source exclusion, extra recording, or a finished combined image.
