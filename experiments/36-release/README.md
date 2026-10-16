# Switch holds that tolerate a misread key

[Experiment 35](../35-release/README.md) with the two panel holds (PAN +
LEVEL for the take chain, AUX 1 + AUX 2 for the stereo AUX) made tolerant of
a briefly misread key. Everyday build.

**Installed 16 October 2026.** Long holds toggled once and holds were refused
while recording, but PAN + LEVEL still often failed; the diagnostic build
([experiment 37](../37-panel-diag/README.md)) found why, and
[experiment 38](../38-release/README.md), the 0.1.0 release, moves the chain
to EFX + PAN.
Recovery from an image that fails before Main remains unproven
([experiment 18](../18-recovery-hang/README.md) is parked).

| | Experiment 35 | Experiment 36 |
|---|---|---|
| Patch sites | 15 | 15 |
| Code | 9,144 bytes | 9,172 bytes |
| Image SHA256 | `824e37c6…` | `c796f4e6bd0f2b5f3d11b2594cdc882a40765af43e3d0b0b41eb4c2f6d08d5af` |

## Why

The PAN + LEVEL hold felt unreliable at first on the mixer (not reproduced
later). Running the release's own `panel_poll` in the emulator through key
sequences showed that the worker's 25 ms polls treated any poll seeing a key
up as a release: a single misread restarted the 1.5 s (the hold failed), a
misread after the toggle during a long hold toggled a second time 1.5 s
later, and a worker stall over 100 ms restarted the hold. Only the stock
panel-message handler writes the key states (press, release, and the panel
controller's state dump), so a misread on the mixer would need the panel
controller to report a brief release; whether it does is unknown.

## Change (`src/capture/master/panel.c`)

- A release ends a hold only when seen on three polls running (50–75 ms at
  25 ms polls): a one-off misread neither restarts the 1.5 s nor allows a
  second toggle. Only a real release re-arms a hold after it toggled.
- A hold restarts when both keys went unseen for over 500 ms (measured from
  when they were last seen pressed, not between polls), so a release hidden
  in a stall can merge into a hold only if under 500 ms, and never shortens
  it.

Reviewed by a separate agent, whose first review found the original
between-polls gap could let a long real release merge into a hold and toggle
instantly on re-press; the measured-from-last-seen version fixes that.

| Scenario (25 ms polls) | Experiment 35 | 0.1.0 |
|---|---|---|
| Clean 2.0 s hold | 1 toggle | 1 toggle |
| One misread at 1.0 s, released at 2.0 s | none | 1 toggle |
| One misread after the toggle, held 4 s | 2 toggles | 1 toggle |
| A misread every 0.5 s, held 4 s | none | 1 toggle |
| 150 ms worker stall, held 2.0 s | none | 1 toggle |
| Real 100 ms release, held to 2.0 s | none | none |
| 2 s stall hiding a release, re-pressed | (restart) | restart, no instant toggle |
| Two separate holds 0.3 s apart | 2 toggles | 2 toggles |

## Build and checks

- Rebuilt by `tools/firmware/build_master_trial.py tolerant` (pinned to
  2a2b910); its checks at the time ran through `tools/firmware/verify_release.py`
  (experiments 26–35 rebuilt; the master-reference groups, including the
  hold detector's misread, re-arm and stall cases, and the stereo groups on
  the release link).

## Procedure

Install with `tools/device/install_release.py`. After the update: hold PAN +
LEVEL several times (blink on, steady off) and AUX 1 + AUX 2 (blink stereo,
steady mono), including a long hold of 4 s or more (one toggle only); a hold
while recording still does nothing.
