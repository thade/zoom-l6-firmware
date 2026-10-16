#!/usr/bin/env python3
"""The browser patcher's own JavaScript (patcher/patcher.js) run under Node
with the committed release recipe: it rebuilds the published image from the
stock L6 v1.10 file, refuses any other input, and refuses a damaged recipe
by its output hash. The page's zip handling (fflate) is not covered here.
Skipped without Node. No device access.
"""
import json,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
STOCK=ROOT/'Reference/L6_v1.10_E/L6.BIN'
SCRIPT='''
import { readFileSync } from 'node:fs';
import { build } from %s;
const [stockPath, recipePath] = process.argv.slice(2);
const stock = new Uint8Array(readFileSync(stockPath));
const recipe = JSON.parse(readFileSync(recipePath, 'utf8'));
const out = {};
const ok = await build(stock, recipe); out.hash = ok.hash; out.bytes = ok.image.length; out.stock = ok.stockHash;
const wrong = Uint8Array.from(stock); wrong[0x300] ^= 1;
try { await build(wrong, recipe); out.wrong = 'built'; } catch (e) { out.wrong = e.kind; }
const damaged = structuredClone(recipe); const code = damaged.span.code;
damaged.span.code = (code.startsWith('AAAA') ? 'BBBB' : 'AAAA') + code.slice(4);   // valid base64, wrong bytes
try { await build(stock, damaged); out.damaged = 'built'; } catch (e) { out.damaged = e.kind; }
try { await build(stock.subarray(0, 1000), recipe); out.short = 'built'; } catch (e) { out.short = e.kind; }
console.log(JSON.stringify(out));
'''

def main():
    node=shutil.which('node')
    if not node:print(json.dumps(dict(passed=True,groups=0,skipped='no node'))) ;return
    index=json.loads((ROOT/'patcher/recipes/index.json').read_text())
    recipe=json.loads((ROOT/f"patcher/recipes/{index['current']}.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        script=Path(tmp)/'run.mjs';script.write_text(SCRIPT%json.dumps((ROOT/'patcher/patcher.js').as_uri()))
        r=subprocess.run([node,str(script),str(STOCK),str(ROOT/f"patcher/recipes/{index['current']}.json")],capture_output=True,text=True)
    if r.returncode:sys.exit(r.stdout+r.stderr)
    out=json.loads(r.stdout)
    assert out['hash']==recipe['image_sha256'] and out['bytes']==recipe['image_bytes'] and out['stock']==recipe['stock_sha256'],out
    assert (out['wrong'],out['damaged'],out['short'])==('stock','result','stock'),out
    cases=[dict(case='node_rebuilds_the_published_image_and_refuses_other_input_and_damage',version=recipe['version'],**out)]
    (ROOT/'analysis/patcher_verification.json').write_text(json.dumps(dict(passed=True,groups=1,results=cases),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=1)))
if __name__=='__main__':main()
