#!/usr/bin/env python3
"""Build the release firmware image from the stock L6 v1.10 L6.BIN. No device access.

Writes release/<version>/:
  L6.BIN        the firmware image, copied to the card root to update the L6
  SHA256SUMS    its hash (check with: shasum -a 256 -c SHA256SUMS)
  manifest.json what was built, from which sources and stock image
  recipe.json   the release as a recipe for the browser patcher (no stock
                data; tools/firmware/recipe.py). A pinned release (one whose
                image was installed and checked) is also written to
                patcher/recipes/<version>.json and made current in
                patcher/recipes/index.json: the hosted patcher only ever
                offers pinned releases.

Needs Reference/L6_v1.10_E/L6.BIN (see docs/setup.md). Once a release is
pinned, a build that does not reproduce its published hash stops with an error.
"""
import argparse,json
from build_deployment_probe import ROOT,SOURCE,digest,write_manifest
from build_master_trial import trial,MODES
import recipe as recipes

def main():
    a=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--out',default=str(ROOT/'release'),help='parent folder (default: release/)')
    args=a.parse_args()
    data,wav,report,t=trial('release')
    out=(ROOT/args.out)/MODES['release']['version'];out.mkdir(parents=True,exist_ok=True)
    # From 0.2.0 the firmware writes the pad anchors itself.
    files={'L6.BIN':data} if MODES['release'].get('anchors') else {'L6.BIN':data,'MASTER.WAV':wav}
    for name,content in files.items():
        path=out/name
        if path.exists() and path.read_bytes()!=content:raise SystemExit(f'Refusing to overwrite a different {path}')
        path.write_bytes(content)
    (out/'SHA256SUMS').write_text(''.join(f'{digest(c)}  {n}\n' for n,c in files.items()))
    write_manifest(out/'manifest.json',report)
    recipe=recipes.make(SOURCE.read_bytes(),data,t['pack'],report['version'])
    text=json.dumps(recipe,indent=1)+'\n'
    (out/'recipe.json').write_text(text)
    pinned='sha' in MODES['release']
    if not pinned:
        print(json.dumps(dict(version=report['version'],folder=str(out),l6_bin_sha256=digest(data),
                              files=sorted(files),pinned=False,patcher='not updated (unpinned)')))
        return
    shelf=ROOT/'patcher/recipes';shelf.mkdir(parents=True,exist_ok=True)
    (shelf/f"{report['version']}.json").write_text(text)
    index=shelf/'index.json'
    versions=sorted({*json.loads(index.read_text()).get('versions',[]),report['version']} if index.exists() else {report['version']},
                    key=lambda v:tuple(int(x) for x in v.split('.')))
    index.write_text(json.dumps(dict(current=report['version'],versions=versions),indent=1)+'\n')
    print(json.dumps(dict(version=report['version'],folder=str(out),l6_bin_sha256=digest(data),
                          files=sorted(files),pinned='sha' in MODES['release'])))
if __name__=='__main__':main()
