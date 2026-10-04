# USB name: stored-data change

**Result, 4 October 2026:** stock L6 → modified T6 → restored L6, observed over USB after each user-reported update and normal reboot. VID/PID remained `1686:089e` in the tested mode.

The trial changed the stored product-name character at file offset `0xa1d55` from L to T, plus the additive checksum byte at `0x1ff`. Image length and version fields were unchanged.

This proved acceptance and use of modified application data, and restoration from that working modified image. It did not prove executable-code changes or recovery from a broken image.

Prepare and check locally:

```sh
python tools/firmware/build_deployment_probe.py
python tests/emulation/verify_deployment_probe.py
```

See [setup](../../docs/setup.md) for the vendor input and dependencies. Output goes to ignored `deployment/01_usb_marker/`. Verification executes the original startup decompressor for six USB configurations; it does not emulate the updater.

The hardware procedure was: copy one image as card-root `L6.BIN`, verify its hash, safely unmount, then follow [Zoom's update guide](https://zoomcorp.com/documents/3579/L6_Firmware_Update_Guide_EN.pdf). With stable power, hold PLAY/STOP while powering on. Slow green means updating; rapid green means complete. Do not interrupt power while updating. Reboot normally and inspect USB identification. Repeat with stock to verify restoration.

No firmware images, recordings or device backups are published here.
