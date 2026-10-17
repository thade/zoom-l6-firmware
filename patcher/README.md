# Browser patcher

A static page that makes the release `L6.BIN` from Zoom's own L6 v1.10
download, in the browser: no Python, git or compiler, and it works on
Windows. Nothing is uploaded, and the page contains none of Zoom's firmware.
Hosted at https://thade.github.io/zoom-l6-firmware/.

- `index.html` and `page.js`: the page (what the firmware does, get Zoom's file, accept the risks,
  drop the zip or `L6.BIN`, then send the result to the mixer or download and
  copy it, and update). `zip.js` reads Zoom's zip with the browser's own
  deflate decoder. The page loads no third-party code: its Content Security
  Policy allows only this site's scripts (and Google Fonts for the type).
- `patcher.js`: the build, a JavaScript copy of `rebuild()` in
  [tools/firmware/recipe.py](../tools/firmware/recipe.py). It refuses any
  input that is not the stock v1.10 `L6.BIN` (SHA-256 `64f1f36b…`) and any
  result that is not the release's published image.
- `mixer.js`: send to the mixer, in Chrome and Edge on a computer. Over USB
  MIDI (Web MIDI, SysEx) it puts the L6 into File Transfer Mode with the same
  fixed messages and timing as
  [tools/device/l6_transfer_mode.py](../tools/device/l6_transfer_mode.py),
  writes `L6.BIN` to the card the user picks (File System Access API; it
  must hold `SOUND_PAD/PAD1`–`PAD4`) and reads it back, and after the user
  ejects the card leaves File Transfer Mode. It uses only the L6's Editor
  port (an input and output of the same name, never the Mixer Control or
  MIDI I/O port) and refuses when more than one L6 is connected. The update
  itself still needs the PLAY/STOP power-on: the bootloader only updates
  from the card then. Other browsers get the download only.
- `recipes/<version>.json`: what turns stock into that release, written by
  `tools/firmware/build_release.py`: the token skeleton of the compressed DSP
  record (its literal bytes come from the user's file), our packed code, the
  patch bytes, copies of stock bytes the new scatter table moves, and both
  hashes. No stock byte is in it (checked by `verify_master_everyday.py`).
  `recipes/index.json` names the current release; `?version=` picks another.

Checks: `tests/emulation/verify_master_everyday.py` (the committed recipe is
current and rebuilds the image) and `tests/emulation/verify_patcher.py`
(`patcher.js` under Node rebuilds the image and refuses other input;
`mixer.js` against a modelled L6 with its three ports, two L6s and a busy
port; `zip.js` on deflated and stored zips of the stock file). Real Web MIDI
and folder access are checked by hand in Chrome.

To try it locally, serve this folder (`python -m http.server -d patcher`)
and open http://localhost:8000; opening `index.html` as a file cannot load
the recipe.
