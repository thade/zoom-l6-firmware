# Early-hang recovery check

Can the PLAY/STOP SD updater recover a mixer whose application hangs at reset?
Every earlier restoration started from an image that booted. Experiment 17 and
any capture image add code that runs before Main, so this question should be
answered before they are installed.

**Parked (11 October 2026).** Prepared locally, not staged. Trials continue
without this check, so recovery from an image that fails before Main is unproven.

## Image

- Local image: `deployment/18_recovery_hang/trial_recovery_hang/L6.BIN`.
- SHA256: `d5254ebac55b719ffe8ae2d9d46a9405794cefb4f3df2685833668acac463376`.
- Builder: `tools/firmware/build_recovery_hang_probe.py`.
- Changes: the MAIN reset handler's first instruction (`cpsid i` at `0x80001414`,
  file offset `0x614`) becomes `b .`, plus the additive checksum. Three bytes in all.
  The BOOT descriptor stays empty, so the update never writes the bootloader.

The application never starts: no USB, MIDI, audio or card activity is expected
after a normal power-on.

## Evidence that the updater is outside MAIN

- Update packages carry an empty BOOT component; the flash map places a
  `0x65000`-byte BOOT region before MAIN ([firmware integration](../../docs/research/firmware_integration_findings.txt)).
- MAIN contains no `L6.BIN` file name (ASCII or UTF-16) and no reference to the
  `L6 System Data` container signature; both appear only in the package header.
- Zoom's update guide describes retrying an SD update after a failed startup.

This is indirect. A held-button check that depends on the front-panel controller,
or a bootloader that requires a MAIN handshake, would still defeat recovery.

## Risk

If recovery works, the mixer returns to stock with one more update. If it does
not, the mixer stays unbootable until a hardware route is used: the i.MX RT1040
serial downloader (boot-mode pins) or SWD, with a flash programmer. No
full-flash or BOOT backup exists, though BOOT is never written by these images.
An early failure in experiment 17 would carry the same risk without the
advantage of a known cause.

## Procedure

1. With the mixer idle and its card inside, stage this image, then read it back
   and check its hash. Eject normally and leave transfer mode.
2. Run the usual PLAY/STOP-held update, wait for rapid green, then power-cycle
   normally. Expect no startup: no USB device, no MIDI ports.
3. Stage the stock image (`deployment/01_usb_marker/stock_control/L6.BIN`) on the
   card with a computer card reader. The mixer cannot enter transfer mode while hung.
4. Hold PLAY/STOP at power-on. Rapid green followed by a normal stock boot passes.
   Check USB name `L6`, MIDI ports, Editor connection and existing pad assignments.
