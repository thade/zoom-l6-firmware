# Browser patcher

A static page that makes the release `L6.BIN` from Zoom's own L6 v1.10
download, in the browser: no Python, git or compiler, and it works on
Windows. Nothing is uploaded, and the page contains none of Zoom's firmware.

- `index.html`: the page (get Zoom's file, accept the risks, drop the zip or
  `L6.BIN`, download the result or send it to the mixer, then the install
  guide).
- `mixer.js`: send to the mixer, in Chrome and Edge on a computer. Over USB
  MIDI (Web MIDI, SysEx) it puts the L6 into File Transfer Mode with the same
  fixed messages and timing as
  [tools/device/l6_transfer_mode.py](../tools/device/l6_transfer_mode.py),
  writes `L6.BIN` to the card the user picks (File System Access API; it
  must hold `SOUND_PAD/PAD1`–`PAD4`) and reads it back, and after the user
  ejects the card leaves File Transfer Mode. The update itself still needs
  the PLAY/STOP power-on: the bootloader only updates from the card then.
  Other browsers get the download only.
- `patcher.js`: the build, a JavaScript copy of `rebuild()` in
  [tools/firmware/recipe.py](../tools/firmware/recipe.py). It refuses any
  input that is not the stock v1.10 `L6.BIN` (SHA-256 `64f1f36b…`) and any
  result that is not the release's published image.
- `recipes/<version>.json`: what turns stock into that release, written by
  `tools/firmware/build_release.py`: the token skeleton of the compressed DSP
  record (its literal bytes come from the user's file), our packed code, the
  patch bytes, copies of stock bytes the new scatter table moves, and both
  hashes. No stock byte is in it (checked by `verify_master_everyday.py`).
  `recipes/index.json` names the current release; `?version=` picks another.

Checks: `tests/emulation/verify_master_everyday.py` (the committed recipe is
current and rebuilds the image) and `tests/emulation/verify_patcher.py`
(`patcher.js` under Node rebuilds the image and refuses other input;
`mixer.js` against a modelled L6 Editor port and card folders). Real Web MIDI
and folder access are checked by hand in Chrome. The
page's zip handling uses [fflate](https://github.com/101arrowz/fflate) 0.8.2
from jsDelivr.

To try it locally, serve this folder (`python -m http.server -d patcher`)
and open http://localhost:8000; opening `index.html` as a file cannot load
the recipe.
