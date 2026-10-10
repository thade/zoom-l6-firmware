# RAM configuration diagnostic

**Status: running on hardware; three consistent configuration reads verified.**

Read the L6's external-memory controller and internal-memory configuration
without opening the device. This extends diagnostic 11 with one fixed query,
preserving its existing hooks, state and 223104-frame ordinary buffer capacity.
It adds no extra recording, worker, RAM allocation or controller writes.

All 42 offline groups pass: seven new checks plus 35 retained checks against the
exact new image. The previous diagnostic 11 rebuilds byte-identically. Full
capture regression counts remain separate. Firmware and evidence stay private.

The exact image is staged on the identified L6 card and its readback matches.
All 149 recording/pad files (4,566,329,838 bytes), their metadata and the global
settings file are unchanged. The previous image/settings are backed up locally.
Normal Eject and official Editor transfer exit completed; original pad names,
counts, MIDI ports and prior diagnostic replies pass. The user completed the
physical update and normal reboot. The new query responds, all retained
diagnostics give consistent snapshots, and original pad names/counts and MIDI
ports pass. Current/minimum free heap is 163,104 bytes; extra capture is disabled.

All three queries agree, including both register snapshots within each query.
The enabled external SDRAM window is **32 MiB at 0x80000000..0x82000000**, on
chip select 0, with a 16-bit bus, nine column bits, four banks and refresh enabled.
The other three SDRAM windows are disabled. Core mappings report 128 KiB DTCM
and 32 KiB ITCM. GPR16 selects the fuse configuration, so GPR17 is not treated
as an active full bank map. This strengthens the 32-MiB hypothesis without
detecting physical chip density or proving either apparent external gap unused.

Private evidence: `deployment/12_memory_capacity/installed_startup_verification.json`,
`startup-memory.jsonl` and `capacity_interpretation.json`. Installed diagnostic
execution is verified through replies; installed flash bytes are not read back.

```sh
python tools/firmware/build_memory_capacity_probe.py
python tools/firmware/build_sd_command_fixture.py
python tests/emulation/verify_memory_capacity_probe.py
```

Image: `deployment/12_memory_capacity/trial_memory_capacity/L6.BIN`.
SHA256: `d458a67180ded0d8f5c86fada4a9eca1bdf1b5857b9446b1f13b39ed82859120`.
Code/state: 6812 bytes, including the unchanged 1052 state bytes. The query
adds 288 bytes over diagnostic 11 and uses 432 traced software stack bytes
before the modeled sender. Physical stack headroom/timing are unmeasured.

Stage the exact verified image on the identified card, back up the previous
update/settings, preserve recordings/pads and verify readback. Use normal Eject
and exit transfer, then follow the tested
[physical update procedure](../01-usb-name/README.md). After normal reboot and
official Editor connection, collect three fixed snapshots:

```sh
python tools/device/l6_memory_capacity_probe.py --output deployment/12_memory_capacity/startup-01.jsonl
```

The page reports SDRAM decode windows, width/geometry, refresh/module enable,
FlexRAM selection and core TCM/ID registers. Two sequential reads must agree;
disagreement is marked without retry. No host-selected address is accepted.

Configured size is **evidence, not physical density detection or proof of spare
RAM**. A larger chip can have a smaller configured window. No patterns or alias
tests are performed. Exact silicon and all proposed RAM ownership remain open.
See [findings](../../docs/research/physical_ram_capacity_findings.txt).

The computer-side width decoder uses the documented one-bit PS field, ignoring
reserved bit 1. All 42 groups pass after that correction, including both widths
with the reserved bit set or clear. The staged firmware bytes are unchanged.
