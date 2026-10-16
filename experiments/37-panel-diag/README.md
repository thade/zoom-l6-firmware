# Panel switch diagnostics: why PAN + LEVEL failed

[Experiment 36](../36-release/README.md) with the status query and a record of
the two switch holds, to find why PAN + LEVEL often did not respond while
AUX 1 + AUX 2 always did. Trial build (diagnostic); not for everyday use.

**Installed 16 October 2026; found the cause.**

| | Experiment 36 | Experiment 37 |
|---|---|---|
| Code | 9,172 bytes | 11,168 bytes (with the query) |
| Image SHA256 | `c796f4e6…` | `b4c1c3c7fd99fa64627abdc52d9615be04e9bb3e8c3df5b37af637413d9985ae` |

## What it records

Built with `-DPANEL_DIAG` (diagnostic builds only; the release sources are
unchanged): per hold, polls with both keys or one, hold starts, restarts after
500 ms unseen, ignored misreads, releases, toggles, the longest hold and
unseen time; a 32-entry ring of key changes and hold events with their ticks;
the worker's poll intervals; and when Main first returned from a receive and
the mixer first issued a gain request. Status schema 6 carries them;
`tools/device/l6_panel_monitor.py` samples every 0.5 s and prints the merged
timeline.

## Results

- **Startup:** the worker's first poll 7 ms after the scheduler started, the
  first gain request at 31 ms, Main's first receive at **2,989 ms**.
- **Idle polling:** longest interval 40 ms over almost 10 minutes.
- **PAN + LEVEL**, about 10 attempts, the user reporting attempts 1, 2, 4, 7, 8
  and 9 as failed: in every failure the panel reported **LEVEL alone** for the
  whole attempt (4–10 s) and **PAN never appeared**; in the successes PAN
  arrived with LEVEL or within 25–50 ms. 4,596 polls saw one key against 746
  with both. Every hold the panel did report was timed and toggled correctly
  (9 starts, 7 toggles, no misreads or restarts); the longest poll interval
  during the session was 145 ms.
- **AUX 1 + AUX 2**, 4 attempts: both keys registered every time; 4 toggles.

The parser sets a key only on the panel controller's press message (or its
state dump), so the panel never reported PAN while LEVEL was held. PAN and
LEVEL are bit 7 of two different panel key groups; AUX 1 and AUX 2 are
adjacent bits of one ([panel keys findings](../../docs/research/panel_keys_findings.txt),
section 6). The chain switch moves to EFX + PAN, in the same group
([experiment 38](../38-release/README.md)), and the switches arm 1 s after
Main is ready instead of 10 s after power-on.

Evidence: `deployment/37_panel_diag/monitor-2.jsonl`. Rebuilt by
`tools/firmware/build_master_trial.py panel_diag` (pinned to f975842).
