# USB name: added-code detour

**Status, 4 October 2026:** prepared and verified offline. Not transferred to the card or installed. No hardware result yet.

This trial tests whether the mixer can branch to newly inserted instructions and return to the original code. The expected visible result is **L6 → ZOOM L6**. It uses the same existing string as trial 2, but a different execution path.

At `0x800737f6`, a four-byte branch replaces the original product-pointer load and store. Eight added bytes at `0x800360e4` load the full product label, perform the displaced store and branch back to `0x800737fa`. The detour preserves the stack pointer, link register and flags. It uses no extra stack or persistent RAM.

The routine occupies part of a 14-byte zero interval between a function return and the next function. It lies inside the existing main payload length. Package lengths, versions, stored strings, boot descriptor, panel and guide stay unchanged. Fourteen file bytes differ: the hook, the added routine and two checksum bytes.

Prepare and verify locally:

```sh
python tools/firmware/build_added_code_probe.py
python tests/emulation/verify_added_code_probe.py
```

See [setup](../../docs/setup.md) for dependencies and vendor input. Local output is under ignored `deployment/03_added_code/`, including a stock restoration image and verification report. Trial SHA256:

```text
ad963a9bcb7da7209030cdc8f9c851b3fdeb0926f160574210c3d3429144f7bc
```

Offline checks passed:

- Twelve paired USB cases execute the original constructors: six profiles and two power flags. Each trial takes the exact out-and-back path, reports ZOOM L6 and otherwise preserves the 1,024-byte configuration and registers at re-entry.
- All sixteen NZCV flag combinations preserve registers other than the intended output, preserve flags and make exactly the intended four-byte stack write.
- A reference audit decodes at every halfword in the main payload and copied RAM code. It also searches expanded initialized data for pointers. No direct branch/immediate, PC-relative access, bounded MOVW/MOVT construction or literal pointer into the selected interval was found.
- The audit correctly rejects a different zero interval at `0x800530c0`: the preceding function reads it as a floating-point constant. Empty-looking bytes alone are not sufficient evidence.

Static scans cannot exclude every computed pointer, indirect path or bootloader use. These tests do not simulate full boot, the updater, cache behavior or real scheduling. The routine is a candidate for a controlled hardware experiment, not an established general-purpose code area.

The next hardware procedure is to stage and read-back-verify this trial, safely leave transfer mode, then use the [previous physical update sequence](../01-usb-name/README.md). After reboot, check for ZOOM L6 and editor connectivity, then restore untouched stock and verify L6 again. The trial must be distinguished by its hash from trial 2, which produces the same label.

A successful trial would prove this specific code insertion and detour on hardware. It would not prove appended-payload loading, large-buffer ownership, the overdub prototype or recovery from broken firmware.
