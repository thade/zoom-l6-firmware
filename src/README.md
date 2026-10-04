# Experimental firmware source

The overdub code is an offline prototype. It has not run on the L6 hardware.

- `capture/`: additional stereo recording and session management.
- `overdub/`: pad management, publication and shared resource ownership.

The linker scripts describe emulator memory, not device placement. Do not install the generated ELF files. See [architecture](../docs/architecture.md) and [progress](../docs/progress.md) for the integration boundaries.
