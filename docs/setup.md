# Build from source

Everything here runs offline on your computer; nothing talks to the mixer
until you install (see the [README](../README.md#install)). On Windows, or
without Python, use the [browser patcher](https://thade.github.io/zoom-l6-firmware/)
instead.

## 1. Requirements

- macOS or Linux, **git** and **Python 3.12 or newer** (macOS's built-in
  Python 3.9 is too old: rebuilding earlier experiments needs 3.12's archive
  extraction). The compiler comes as a Python package (zig 0.13).
- A **full clone**: `git clone https://github.com/thade/zoom-l6-firmware.git`,
  then `cd zoom-l6-firmware`. A ZIP download or `--depth 1` clone builds the
  release but cannot rebuild the earlier experiments the checks compare
  against (0.1.0 and 0.2.0 build from the `v0.1.0` and `v0.2.0` tags).

## 2. Python environment

Run commands from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-research.txt
```

## 3. Zoom's v1.10 firmware

Download **L6 v1.10** from Zoom's
[L6 support page](https://zoomcorp.com/en/us/digital-mixer-multi-track-recorders/digital-mixer-recorder/livetrak-l6-final/l6-support/)
(the LiveTrak **L6**, not the L6max, which has its own v1.10). In October
2026 the file was `L6_v1.10_E.zip` (2,901,772 bytes, SHA256
`a02888a0d03f06d314e5625c14866f5c5f0e32ea778406751d50ee6848a72f1c`), at
https://zoomcorp.com/documents/3581/L6_v1.10_E.zip. Unzip it and copy
`L6_v1.10_E/L6.BIN` to `Reference/L6_v1.10_E/L6.BIN`, then check it:

```sh
shasum -a 256 Reference/L6_v1.10_E/L6.BIN
```

```text
64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb
```

The tools refuse any other file. `Reference/` is ignored by git: Zoom's
firmware is never committed.

## 4. Build and check the release

```sh
python tools/firmware/verify_release.py
```

This builds the emulator fixtures, builds the release, and runs its offline
checks (a few minutes). It prints the release folder and image hash. The
image alone:

```sh
python tools/firmware/build_release.py
```

Both write `release/0.3.0/`: `L6.BIN`, `SHA256SUMS`, `manifest.json` and
`recipe.json` (the same release for the browser patcher).
The 0.3.0 image is reproducible: the build stops if the image differs from
its published hash:

```text
34df789bc9eabf0b6060a12700cbd889d39ef4b8833f2c34db05b3bf72f3e90b  L6.BIN
```

Then [install](../README.md#install).

## Rebuilding earlier experiments

`tools/firmware/build_master_trial.py <mode>` rebuilds any installed
experiment image from 24 on, byte for byte, from the commit it was built from
(modes are listed in its docstring); `deployment/` holds the output and is
ignored by git. The experiment READMEs in `experiments/` describe each one.

## Full research regression

```sh
python tools/firmware/verify_redesign.py
```

Runs every offline suite in the repository (about 100, including the
research toward 0.1.0: the overdub prototype, the capture designs and the
hardware probes). Some research suites need local images from earlier
experiments or private recordings that are not included, so this is a
development tool, not part of the release checks. The live device helpers in
`tools/device/` use macOS frameworks (CoreMIDI, `/Volumes`); the emulator
checks need no mixer.

## Local files

- `Reference/`: Zoom's firmware download and manuals.
- `release/`: built release images and card backups made by the installer.
- `deployment/`: experiment images, manifests and device evidence.
- `analysis/`: generated reports and private recordings.
- `.zig-cache/`, `src/**/*.elf`: build output.

All are ignored by git. Public experiment summaries live in `experiments/`
and written research in `docs/research/`.
