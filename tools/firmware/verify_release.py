#!/usr/bin/env python3
"""Build and check the release from a fresh clone. No device access.

Needs only the stock image at Reference/L6_v1.10_E/L6.BIN. Builds the
emulator fixtures the release suites run on, builds the release image (which
must reproduce its published hash once pinned), then runs:
  verify_master_everyday       the exact image: sites, boot, earlier images rebuilt
  verify_master_ref_everyday   take chain and history groups on the release link
  verify_stereo_aux_hooks_everyday  stereo AUX and switch groups on the release link
Takes about a minute.
"""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ENV=dict(os.environ,PYTHONPATH=os.pathsep.join(filter(None,[str(ROOT/'tools/firmware'),str(ROOT/'tools/device'),
                                                              os.environ.get('PYTHONPATH')])))
FIXTURES=(['tools/firmware/build_overdub_prototype.py'],['tools/firmware/build_extra_capture.py'],
          ['tools/firmware/build_extra_capture.py','--layout','placement'],
          ['tools/firmware/build_extra_capture.py','--layout','placement','--startup-fixture'])
SUITES=('verify_master_everyday.py','verify_master_ref_everyday.py','verify_stereo_aux_hooks_everyday.py')

def run(args,cwd=ROOT):
    r=subprocess.run([sys.executable,*args],cwd=cwd,env=ENV,text=True,capture_output=True)
    if r.returncode:sys.exit(f'FAILED: {" ".join(args)}\n{r.stdout[-2000:]}{r.stderr[-4000:]}')
    return r.stdout

def main():
    if not (ROOT/'Reference/L6_v1.10_E/L6.BIN').exists():
        sys.exit('Missing Reference/L6_v1.10_E/L6.BIN: download Zoom L6 v1.10 first (docs/setup.md)')
    start=time.time()
    for args in FIXTURES:run(args)
    built=json.loads(run(['tools/firmware/build_release.py']).strip().splitlines()[-1])
    results={}
    for suite in SUITES:
        results[suite]=json.loads(run([suite],cwd=ROOT/'tests/emulation').strip().splitlines()[-1])
    print(json.dumps(dict(passed=all(r.get('passed') for r in results.values()),release=built,
        groups={k:v.get('groups') for k,v in results.items()},seconds=round(time.time()-start)),indent=1))
if __name__=='__main__':main()
