# Progress

Goal: Allow for an overdubbing workflow using just the L6 hardware.

1. **Workflow defined.** Keep clean input recordings and the ordinary master; make an additional stereo recording for reuse on a sound pad.
2. **Firmware investigation substantially complete.** Recording, audio routing, file handling and pad assignment have been traced. Detailed findings are in [research/](research/).
3. **Offline prototype substantially complete.** Capture, file completion, session management and pad publication have emulator coverage. Real scheduling, memory placement and hardware integration remain open.
4. **Modified data deployed and restored.** The USB name changed from L6 to T6, then returned to L6 after reinstalling stock firmware.
5. **Modified instruction executed on hardware.** The USB name changed to ZOOM L6 through a one-instruction patch. Stock restoration has been staged; its completion has not yet been verified.
6. **Next: integrate the prototype.** Resolve buffer ownership, scheduling, memory placement and the remaining native interfaces.
7. **Test progressively on hardware.** Additional stereo capture, automatic pad assignment, then repeated overdubs.
8. **Validate the complete workflow.** Timing, audio integrity, clean stems, preserved masters and failure handling.
9. **Package the finished firmware.** A tested image and installation/restoration instructions, once the preceding steps pass.

The dated [experiments](../experiments/) record hardware evidence. Emulation uses original instructions and compiled prototype code with synthetic memory, files and selected scheduling/driver responses. It is not a full mixer simulator. Restoring a working modified image does not establish recovery from broken firmware.

Historical research notes describe intermediate states. Earlier statements that no modified firmware has been deployed predate the successful marker trials.
