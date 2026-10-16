#!/usr/bin/env python3
"""Copy a firmware image onto a mounted L6 microSD card.

The card can be mounted with a card reader or with the L6's own USB file
transfer mode (ZOOM L6 Editor: File Transfer Mode, or l6_transfer_mode.py).
Then update the mixer as Zoom's guide describes: with the card in, hold
PLAY/STOP while pressing POWER until the power indicator lights.

  install_release.py                     the built release (release/<version>/)
  install_release.py --stock             Zoom's v1.10 L6.BIN: back to stock
  install_release.py --card /Volumes/X   when the card is not found by itself

What it does, checking each step:
- checks the image against SHA256SUMS and the release's published image
  hash (its manifest), or the stock hash;
- checks the card looks like an L6 card (SOUND_PAD/PAD1..PAD4);
- backs up an existing L6.BIN and ZOOM_L6.SYS from the card (never modified);
- writes L6.BIN through a temporary file, flushed to the card (F_FULLFSYNC on
  macOS), then renamed, then read back (the read may come from the
  computer's cache: eject properly, e.g. with --eject);
- a release folder with MASTER.WAV (0.1.0; from 0.2.0 the firmware writes it
  itself): puts it in each pad folder that lacks one (an existing different
  MASTER.WAV stops it: rename that file first);
- removes macOS ._ metadata files next to the files it wrote;
- with --eject, ejects the card (macOS).
Pad sounds, recordings and settings are not touched. Stock firmware ignores
the anchors and the take histories, so they can stay on the card.
"""
import argparse,fcntl,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
STOCK=ROOT/'Reference/L6_v1.10_E/L6.BIN'
STOCK_SHA='64f1f36b8383176b5d841911fbf3c16205139a313ee88be906f313b1a98a33fb'
PADS=[f'PAD{n}' for n in range(1,5)]

def digest(b):return hashlib.sha256(b).hexdigest()
def fail(message):sys.exit('Stopped: '+message)

def find_card():
    volumes=[v for v in Path('/Volumes').glob('*') if all((v/'SOUND_PAD'/p).is_dir() for p in PADS)] if Path('/Volumes').is_dir() else []
    if len(volumes)!=1:fail(f'found {len(volumes)} mounted L6 cards {[str(v) for v in volumes]}; name one with --card')
    return volumes[0]

def release_files(folder):
    sums=folder/'SHA256SUMS'
    if not sums.exists():fail(f'{sums} is missing: run tools/firmware/build_release.py first')
    files={}
    for line in sums.read_text().splitlines():
        sha,name=line.split(None,1);data=(folder/name).read_bytes()
        if digest(data)!=sha:fail(f'{folder/name} does not match SHA256SUMS')
        files[name]=data
    if set(files) not in ({'L6.BIN'},{'L6.BIN','MASTER.WAV'}):fail(f'unexpected files in {sums}')
    return files

def published(folder,image):
    """A release image must be the one its version publishes (the manifest's
    expected hash, from the builder), not just match its own SHA256SUMS."""
    try:expected=json.loads((folder/'manifest.json').read_text()).get('expected_sha256')
    except (OSError,ValueError):expected=None
    if not expected:fail(f'{folder} has no published image hash (an unpinned build): add --any-image to install it anyway')
    if digest(image)!=expected:fail(f'{folder}/L6.BIN is not the published image {expected}: rebuild with build_release.py')

def flush(f):
    f.flush();os.fsync(f.fileno())
    if hasattr(fcntl,'F_FULLFSYNC'):
        try:fcntl.fcntl(f.fileno(),fcntl.F_FULLFSYNC)   # macOS: also flush the device's cache
        except OSError:pass

def new_folder(base):
    """A backup folder no earlier run used."""
    for n in range(1000):
        path=base.with_name(base.name+(f'-{n}' if n else ''))
        try:path.mkdir(parents=True);return path
        except FileExistsError:continue
    fail(f'no free backup folder next to {base}')
def write_checked(path,data,exclusive=False):
    """Write through a temporary name, flush to the card, rename, read back."""
    tmp=path.with_name('.'+path.name+'.tmp')
    if tmp.exists():
        print(f'Removing {tmp}, left by an interrupted install',file=sys.stderr);tmp.unlink()
    with open(tmp,'xb') as f:
        f.write(data);flush(f)
    if exclusive and path.exists():tmp.unlink();fail(f'{path} appeared while writing')
    os.replace(tmp,path)
    if path.read_bytes()!=data:fail(f'{path} reads back differently: do not update; check the card')
    for meta in (path.with_name('._'+path.name),tmp.with_name('._'+tmp.name)):
        if meta.exists():meta.unlink()

def main():
    a=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--card',type=Path,help='mounted card root (default: the one mounted L6 card)')
    a.add_argument('--release',type=Path,help='release folder (default: the newest under release/)')
    a.add_argument('--stock',action='store_true',help="install Zoom's v1.10 L6.BIN instead")
    a.add_argument('--backup',type=Path,default=ROOT/'release/backups',help='where card files are backed up')
    a.add_argument('--eject',action='store_true',help='eject the card afterwards (macOS)')
    a.add_argument('--any-image',action='store_true',help='install a folder without a published hash (experiment builds)')
    args=a.parse_args()
    if args.stock:
        image=STOCK.read_bytes() if STOCK.exists() else fail(f'{STOCK} is missing (docs/setup.md)')
        if digest(image)!=STOCK_SHA:fail(f'{STOCK} is not Zoom L6 v1.10')
        anchor=None;label='stock v1.10'
    else:
        folder=args.release or max((ROOT/'release').glob('[0-9]*.[0-9]*.[0-9]*'),default=None,
                                   key=lambda p:tuple(int(x) for x in p.name.split('.')))
        if not folder:fail('no release built: run tools/firmware/build_release.py first')
        files=release_files(folder);image,anchor=files['L6.BIN'],files.get('MASTER.WAV');label=f'release {folder.name}'
        if not args.any_image:published(folder,image)
    card=args.card or find_card()
    if not all((card/'SOUND_PAD'/p).is_dir() for p in PADS):fail(f'{card} has no SOUND_PAD/PAD1..PAD4: not an L6 card')
    if anchor:
        for p in PADS:
            existing=card/'SOUND_PAD'/p/'MASTER.WAV'
            if existing.exists() and existing.read_bytes()!=anchor:
                fail(f'{existing} is a different file; rename it before installing')
    target=card/'L6.BIN';backed=[];saved=None
    for name in ('L6.BIN','ZOOM_L6.SYS'):
        if (card/name).exists() and not (name=='L6.BIN' and (card/name).read_bytes()==image):
            if not saved:saved=new_folder(args.backup/time.strftime('%Y%m%d-%H%M%S'))
            shutil.copyfile(card/name,saved/name)   # data only: card file flags need not copy
            if (saved/name).read_bytes()!=(card/name).read_bytes():fail(f'backup of {name} failed')
            backed.append(str(saved/name))
    if not target.exists() or target.read_bytes()!=image:write_checked(target,image)
    placed=[]
    if anchor:
        for p in PADS:
            path=card/'SOUND_PAD'/p/'MASTER.WAV'
            if not path.exists():write_checked(path,anchor,exclusive=True);placed.append(str(path))
    if args.eject:subprocess.run(['diskutil','eject',str(card)],check=True)
    print(json.dumps(dict(installed=label,card=str(card),l6_bin_sha256=digest(image),anchors_added=placed,
                          backups=backed,ejected=args.eject),indent=1))
    print('Next: '+('eject the card, then ' if not args.eject else '')+
          'with the card in the L6, hold PLAY/STOP and press POWER until the power indicator lights. '
          'It blinks green slowly while updating (about 30 s) and quickly when done; then switch off and on.',file=sys.stderr)
if __name__=='__main__':main()
