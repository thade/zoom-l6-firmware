#!/usr/bin/env python3
"""The browser patcher's own JavaScript run under Node. patcher/patcher.js
with the committed release recipe: it rebuilds the published image from the
stock L6 v1.10 file, refuses any other input, and refuses a damaged recipe
by its output hash. patcher/mixer.js (send to the mixer) against a modelled
L6 Editor port and card folders (patcher_mixer.mjs), and zip.js on zips of
the stock file. Not covered: real Web MIDI and folder access. Skipped without
Node. No device access.
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
    import zipfile
    with tempfile.TemporaryDirectory() as tmp:
        zips=[]
        for name,method in (('deflated.zip',zipfile.ZIP_DEFLATED),('stored.zip',zipfile.ZIP_STORED)):
            z=Path(tmp)/name;zips.append(str(z))
            with zipfile.ZipFile(z,'w',method) as f:f.writestr('L6_v1.10_E/readme.txt','x');f.write(STOCK,'L6_v1.10_E/L6.BIN')
        r=subprocess.run([node,str(Path(__file__).with_name('patcher_mixer.mjs')),*zips],capture_output=True,text=True,timeout=300)
    if r.returncode:sys.exit(r.stdout+r.stderr)
    m=json.loads(r.stdout)
    assert (m['before'],m['enter'],m['during'],m['written'],m['exit']['state'],m['after'],m['only_fixed'])==(0,'acknowledged',1,True,0,0,True),m
    assert (m['enter_again'],m['exit_when_out']['state'],m['windows_names'],m['windows_key'])==('already',0,0,'MIDI2 (L6)'),m
    assert (m['other_ports_untouched'],m['first_state'],m['two'],m['two_silent'],m['busy'])==(True,0,'several',True,'busy'),m
    assert m['zip_deflated']==m['zip_stored']==recipe['stock_sha256'],m
    assert (m['denied'],m['absent'],m['not_card'],m['card_check'],m['supported'])==('permission','absent','not-card',True,[True,False,False]),m
    cases.append(dict(case='send_to_the_mixer_enters_writes_checks_and_leaves_transfer_mode_with_fixed_messages_on_the_editor_port_only',**m))
    (ROOT/'analysis/patcher_verification.json').write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
