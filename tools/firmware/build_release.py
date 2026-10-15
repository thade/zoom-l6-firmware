#!/usr/bin/env python3
"""Build the release firmware image from the stock L6 v1.10 L6.BIN. No device access.

Writes release/<version>/:
  L6.BIN        the firmware image, copied to the card root to update the L6
  MASTER.WAV    the anchor file, copied into each SOUND_PAD/PAD1..PAD4 folder
  SHA256SUMS    their hashes (check with: shasum -a 256 -c SHA256SUMS)
  manifest.json what was built, from which sources and stock image

Needs Reference/L6_v1.10_E/L6.BIN (see docs/setup.md). Once a release is
pinned, a build that does not reproduce its published hash stops with an error.
"""
import argparse,json
from build_deployment_probe import ROOT,digest,write_manifest
from build_master_trial import trial,MODES

def main():
    a=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--out',default=str(ROOT/'release'),help='parent folder (default: release/)')
    args=a.parse_args()
    data,wav,report,_=trial('release')
    out=(ROOT/args.out)/MODES['release']['version'];out.mkdir(parents=True,exist_ok=True)
    files={'L6.BIN':data,'MASTER.WAV':wav}
    for name,content in files.items():
        path=out/name
        if path.exists() and path.read_bytes()!=content:raise SystemExit(f'Refusing to overwrite a different {path}')
        path.write_bytes(content)
    (out/'SHA256SUMS').write_text(''.join(f'{digest(c)}  {n}\n' for n,c in files.items()))
    write_manifest(out/'manifest.json',report)
    print(json.dumps(dict(version=report['version'],folder=str(out),l6_bin_sha256=digest(data),
                          master_wav_sha256=digest(wav),pinned='sha' in MODES['release'])))
if __name__=='__main__':main()
