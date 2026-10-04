# Architecture

The intended workflow records a whole song, then reuses that take as a sound-pad backing track while recording the next layer.

```text
Live inputs ────────────────────────> clean channel files
     │
     └──> mixer <── previous take played from a sound pad
            │
            ├──> ordinary master processing ──> MASTER recording
            │
            └──> additional pre-compression stereo capture
                         │
                  finish and verify file
                         │
                  assign to a sound pad
                         │
                    next overdub pass
```

This is the target routing. Its additional capture and automatic pad workflow have not yet been installed on the device.

- [src/capture/](../src/capture/) contains capture, buffer ownership, file completion, request routing and session management.
- [src/overdub/](../src/overdub/) contains pad publication, reload coordination and resource-lifetime control. It retains the earlier master-copy prototype for comparison and regression tests.
- [tests/emulation/](../tests/emulation/) executes recovered firmware routines and compiled prototypes. Hardware, storage and scheduling boundaries are modeled.
- [tests/fixtures/](../tests/fixtures/) contains synthetic callback bodies.
- [tools/firmware/](../tools/firmware/) inspects the vendor image, builds emulator executables and prepares minimal deployment probes locally.
- [tools/device/](../tools/device/) contains macOS MIDI and file-transfer helpers, separate from the eventual hardware-only workflow.

The source and linker layouts are experimental. Emulator addresses are not safe device addresses. The hardware probes alter existing bytes in place; they do not establish where new code or capture buffers can safely live.
