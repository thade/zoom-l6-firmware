# Research setup

Run commands from the repository root. Use Python 3 and a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-research.txt
```

Obtain official **L6 v1.10** firmware from [Zoom's support page](https://zoomcorp.com/en/us/digital-mixer-multi-track-recorders/digital-mixer-recorder/livetrak-l6-final/l6-support/). Place its `L6.BIN` at `Reference/L6_v1.10_E/L6.BIN`. The tools check this SHA256:

```text
64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb
```

Build and verify the code-marker experiment offline:

```sh
python tools/firmware/build_code_probe.py
python tests/emulation/verify_code_probe.py
```

Build and verify the current redesign (all offline):

```sh
python tools/firmware/verify_redesign.py
```

Build only the capture-first candidate:

```sh
python tools/firmware/build_extra_capture.py
```

Build the smaller offline hook fixture and run its native capture checks:

```sh
python tools/firmware/build_extra_capture.py --layout placement --hooks-fixture --minimal-link
python tests/emulation/verify_capture_minimal.py
```

This variant retains all proposed hook targets while dropping unreachable
research entry points. It is still an emulator artifact. The
[remaining device gates](research/remaining_device_gates.txt) explain the
hardware evidence needed before creating an installable capture image.

Build the historical emulator prototypes before running their individual tests:

```sh
python tools/firmware/build_overdub_prototype.py
python tools/firmware/build_extra_capture.py --profile research
python tests/emulation/verify_extra_capture.py
python tests/emulation/verify_recorder_file_worker.py
```

The ELF files use emulator addresses and must not be installed on the mixer. These build and verification commands do not access the device.

File-workflow tests use synthetic recordings and do not access MIDI or a card:

```sh
python -m unittest discover -s tests/device -p 'test_*.py'
```

## Local files

- `Reference/`: downloaded vendor firmware and manuals.
- `deployment/`: generated probe images, manifests and local device evidence.
- `analysis/`: generated reports, disassembly, private recordings and session state.
- `src/**/*.elf`: generated emulator executables.

These files stay ignored. Public experiment summaries live in `experiments/`, and written research lives in `docs/research/`.

Some older tests require private recording fixtures that are intentionally not included. In particular, `verify_overdub_prototype.py` uses a historical recording for its full-file test; many other suites reuse its harness with synthetic files. The `analyze_*` scripts additionally require those recordings and NumPy. This is not yet a fully portable test package. Live device helpers use macOS frameworks; emulator checks do not require a connected mixer.
