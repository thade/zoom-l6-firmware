# Research notes

Working notes from static reading of the stock v1.10 firmware, emulation of
its original instructions, and hardware results, written 2–16 October 2026.
Each note is dated; statements about the "current design" or what is
"installed" are as of that date. Addresses are stock v1.10.

## Basis of the release

Read these to understand the release ([architecture](../architecture.md)):

| Note | Covers |
|---|---|
| [master_reference_findings.txt](master_reference_findings.txt) | The take chain: playing the stock master in place, the anchor rule, the take check, the handoff, the history |
| [stereo_aux_findings.txt](stereo_aux_findings.txt) | The AUX gain rows, pan factors and gain-ramp path the stereo send uses (written as a feasibility study; built in experiments 30–34) |
| [aux_switch_findings.txt](aux_switch_findings.txt) | The mode bytes, settings flash, keys, LEDs and MIDI options for the switch |
| [panel_keys_findings.txt](panel_keys_findings.txt) | Every panel key and LED index, which two-button holds are free, the chain switch's storage |
| [capture_source_reuse_findings.txt](capture_source_reuse_findings.txt) | The image layout: code placed in the consumed DSP source span |
| [startup_sites_findings.txt](startup_sites_findings.txt) | The two startup hook sites |
| [pad_dispatch_findings.txt](pad_dispatch_findings.txt) | Main's event receive, which the five receive hooks wrap |
| [stock_pad_adapter_findings.txt](stock_pad_adapter_findings.txt) | Saved pad paths and the stock assignment |
| [record_events_findings.txt](record_events_findings.txt), [scheduler_exclusion_findings.txt](scheduler_exclusion_findings.txt) | The recorder's state byte and RecPlayCtl busy word |
| [firmware_integration_findings.txt](firmware_integration_findings.txt) | The firmware container and update format (written before any image was built) |
| [bootloader_findings.txt](bootloader_findings.txt) | The bootloader from the flash backup: the PLAY/STOP decision, loading MAIN, the SD update and its marker (the basis of experiment 18's recovery test) |

## Reviews

`astra_*_review*.txt`: independent reviews of the capture designs (7–9
October), which led to the simplified capture and then the master reference.

## Archived research

Everything else is research toward the earlier designs and the hardware
diagnostics of experiments 4–23, grouped by file prefix: `capture_*`,
`simple_capture`, `extra_*`, `handoff_*`, `history_capture`, `segmented_history`
(capture designs); `sd_*`, `storage_*`, `native_*`, `usb_*`, `session_*`,
`read_*`, `reload_*`, `playback_*`, `pad_*`, `control_*` (stock storage, USB,
pad and playback internals); `*_probe_*` and `ram_*` (hardware diagnostics).
[remaining_device_gates.txt](remaining_device_gates.txt) lists the gates for
the capture designs, not for 0.1.0. Notes that describe a superseded plan
carry a header saying so.
