# Synthetic fixtures

`audio_fixture.c` and `control_fixture.c` supply artificial callback bodies for the emulator builds. They are not Zoom DSP code or hardware drivers.

The Python harnesses also construct WAV bytes, filesystem responses and scheduled events in memory. Real recordings are excluded from the repository.
