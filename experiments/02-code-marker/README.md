# USB name: executable-instruction change

**Result, 4 October 2026:** the device reported **ZOOM L6** after installation and normal reboot, with VID/PID `1686:089e` and revision 1. The editor connected, displayed existing pad assignments and entered/exited File Transfer Mode. Stock restoration was prepared; its completion is not yet verified.

At runtime address `0x800737f6`, the instruction changes from `ldr r0, [r5, #0xc]` to `ldr r0, [r5, #0x1c]`. It selects the existing full label instead of the short product name. Every stored string remains unchanged. Only file byte `0x729f7` and checksum byte `0x1ff` differ from stock.

Prepare and check locally:

```sh
python tools/firmware/build_code_probe.py
python tests/emulation/verify_code_probe.py
```

See [setup](../../docs/setup.md) for the vendor input and dependencies. Output goes to ignored `deployment/02_code_marker/`.

Offline verification passed 12 paired cases: six USB profiles with two power-flag fixtures each. Original code constructs L6 for stock and ZOOM L6 for the trial; the other intermediate configuration bytes match. USB controller setup and full boot are outside the simulation.

The editor's File Transfer Mode exposed the card without removing it. The trial was copied as root `L6.BIN`, read back and checked, then safely unmounted before exiting transfer mode. Installation used the same [physical update sequence](../01-usb-name/README.md) as the first trial. Stock restoration must use the untouched stock image and verify the name returns to L6.

This confirms one changed instruction executed on hardware. It does not prove new code placement, the overdub prototype, or recovery from broken firmware.
