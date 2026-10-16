# Early-hang recovery check

Can the PLAY/STOP SD updater recover a mixer whose application hangs at reset?
Every earlier restoration started from an image that booted. Experiment 17 and
any capture image add code that runs before Main, so this question should be
answered before they are installed.

**Passed on the mixer (16 October 2026).** The hang image left the mixer dark
and absent from USB; holding PLAY/STOP at power-on installed Zoom's v1.10 from
the card, and the mixer started normally. See Results.

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

This was indirect. The bootloader, read from the experiment 39 flash backup
([bootloader findings](../../docs/research/bootloader_findings.txt)), now shows
it directly (16 October 2026, static reading):

- PLAY/STOP is read from an MCU GPIO pin, not the panel controller, before MAIN
  is copied to RAM; held, the bootloader enters update mode and never runs MAIN.
- MAIN is started with no check at all, so this image's hang is never seen by
  the bootloader; there is no handshake.
- The update checks the package (name, checksum) before erasing, erases the
  update-complete marker first and writes it last after verifying the rest, so
  a failed update leaves the mixer in update mode at the next power-on.
- BOOT is never written by a package with the stock header, which every image
  we build keeps.

The bootloader's own instructions, emulated over modelled flash, card and GPIO
(`tests/emulation/verify_bootloader.py`), reproduce this: with this image
installed, PLAY/STOP held reaches update mode and a stock update restores the
flash, and a power cut at any point of an update leaves the mixer in update
mode at the next power-on.

## Risk (before the test)

The test passed (see Results); this was the worst case planned for.

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

## Results (16 October 2026)

Run after the bootloader was read and emulated
([bootloader findings](../../docs/research/bootloader_findings.txt)).

1. Staged `d5254eba…` through File Transfer Mode (read back), then the
   PLAY/STOP update: slow green, then rapid green.
2. Power-on: no lights at all and no USB device. The image hangs before the
   application turns on any LED.
3. With the card in a computer card reader, staged Zoom's v1.10 `L6.BIN`
   (`64f1f36b…`, read back).
4. Card back in, the mixer fully powered off, PLAY/STOP held at power-on:
   the update ran, and the next power-on started stock v1.10. USB product
   `L6` (ZOOM Corporation), an Editor session opened, and the diagnostic
   status query got no reply, as expected on stock.

**Power it fully off first.** The L6 can be powered from either USB port or
from batteries. A hung mixer shows no lights, so it looks dead or switched
off while it is in fact still powered and stuck. Unplug both USB cables and
take out the batteries before the PLAY/STOP power-on, or the button press
does nothing and the mixer can seem bricked.
