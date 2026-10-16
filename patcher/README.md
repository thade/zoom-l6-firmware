# Browser patcher

A static page that makes the release `L6.BIN` from Zoom's own L6 v1.10
download, in the browser: no Python, git or compiler, and it works on
Windows. Nothing is uploaded, and the page contains none of Zoom's firmware.

- `index.html`: the page (get Zoom's file, accept the risks, drop the zip or
  `L6.BIN`, download the result, then the install guide).
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
(`patcher.js` under Node rebuilds the image and refuses other input). The
page's zip handling uses [fflate](https://github.com/101arrowz/fflate) 0.8.2
from jsDelivr.

To try it locally, serve this folder (`python -m http.server -d patcher`)
and open http://localhost:8000; opening `index.html` as a file cannot load
the recipe.
