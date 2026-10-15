# Firmware source

## Release (0.1.0)

- `capture/master/`: the code in the release image.
  - `master_ref.c`, `master_ref.h`: the take chain (pads 1–4 play the last
    four takes) and `HISTORY.TXT`, with the recorder, worker and Main hooks.
  - `stereo_aux.c`, `stereo_aux.h`: the stereo AUX send and the AUX 1 + AUX 2
    mono/stereo switch.
  - `master_hooks.S`: entry adapters for the patched stock sites.
  - `master_query.c`: the read-only status query, in diagnostic (trial)
    builds only.
- `capture/hook_macros.inc`, `capture/retention.h`: shared hook conventions.
- The link layout is `tests/fixtures/capture_source_reuse.ld`.

`tools/firmware/build_release.py` builds the image; see
[docs/architecture.md](../docs/architecture.md) for how the pieces fit.

## Research (not in the release)

- `capture/simple*`: the pre-compressor capture installed in experiments
  19–23.
- `capture/` (other files): the earlier capture-first designs and their
  emulator fixtures.
- `overdub/`: the first overdub prototype (pad management, publication).
- `diagnostics/`: hardware probes from experiments 4–18; `health_hooks.S`
  also carries the trial builds' status query.

Most research ELFs use emulator addresses and must not be installed. The
installable images are built only by `tools/firmware/build_release.py` and
`build_master_trial.py`.
