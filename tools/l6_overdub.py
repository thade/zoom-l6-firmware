#!/usr/bin/env python3
"""Promote completed L6 recordings to a rolling set of four sound pads.

Stock firmware; the official editor must handle file-transfer entry/exit and
remain connected for MIDI assignment. No audio processing or record/play command.
All state/logs stay on the Mac. Original recordings and pad files are retained.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

TAKE = re.compile(r'\d{6}_\d{6}\Z')
DEFAULT_STATE = Path(__file__).resolve().parents[1] / 'analysis/overdub_workflow/session.json'


def digest(path):
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f'File changed while reading: {path}')
    return h.hexdigest()


def wav_info(path):
    size = path.stat().st_size
    fmt = None
    data_size = None
    with path.open('rb') as f:
        header = f.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
            raise ValueError(f'Not a supported RIFF WAV: {path}')
        if struct.unpack_from('<I', header, 4)[0] + 8 != size:
            raise ValueError(f'WAV is incomplete or uses an unsupported large-file format: {path}')
        while f.tell() < size:
            chunk = f.read(8)
            if len(chunk) != 8:
                raise ValueError(f'Truncated WAV chunk: {path}')
            tag, length = struct.unpack('<4sI', chunk)
            end = f.tell() + length + (length & 1)
            if end > size:
                raise ValueError(f'Truncated WAV audio: {path}')
            if tag == b'fmt ':
                raw = f.read(min(length, 40))
                if len(raw) < 16:
                    raise ValueError('Short WAV format chunk')
                fmt = struct.unpack('<HHIIHH', raw[:16])
            elif tag == b'data':
                if data_size is not None:
                    raise ValueError('Multiple WAV data chunks are unsupported')
                data_size = length
            f.seek(end)
    if fmt is None or fmt[0] != 3 or fmt[1] != 2 or fmt[2] != 48000 or fmt[5] != 32 or fmt[4] != 8:
        raise ValueError(f'Expected the L6 stereo 48 kHz / float32 master: {path}')
    if not data_size or data_size % 8:
        raise ValueError(f'Empty or incomplete master: {path}')
    return {'bytes': size, 'seconds': data_size / 8 / 48000, 'sha256': digest(path)}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another workflow operation is already running') from None
        yield


def card_check(card):
    if not (card / 'RECORDER').is_dir() or not (card / 'SOUND_PAD').is_dir():
        raise RuntimeError('L6 card is not available in file-transfer mode')
    if str(card).startswith('/Volumes/') and not os.path.ismount(card):
        raise RuntimeError('Expected a mounted L6 card')
    for pad in range(1, 5):
        folder = card / 'SOUND_PAD' / f'PAD{pad}'
        if not folder.is_dir() or folder.is_symlink():
            raise RuntimeError(f'Missing or unsafe pad folder: {folder}')


def card_identity(card):
    if str(card).startswith('/Volumes/'):
        import plistlib
        info = plistlib.loads(subprocess.check_output(['diskutil', 'info', '-plist', str(card)]))
        if not info.get('VolumeUUID'):
            raise RuntimeError('Cannot identify this SD card')
        return info['VolumeUUID']
    return str(card.resolve())  # Local rehearsal only.


def takes(card):
    return sorted(p.name for p in (card / 'RECORDER').iterdir()
                  if p.is_dir() and not p.is_symlink() and TAKE.fullmatch(p.name))


def initialize(card, state_path, included):
    if state_path.exists():
        raise RuntimeError('Session already exists; use prepare or cycle')
    card_check(card)
    present = takes(card)
    if len(included) != len(set(included)) or any(x not in present for x in included):
        raise ValueError('Seed takes must be distinct recording folders on this card')
    state = {'version': 1, 'card': str(card.resolve()), 'card_id': card_identity(card),
             'ignored': [x for x in present if x not in included], 'history': [],
             'phase': 'initialized', 'assignments': []}
    save(state_path, state)
    return state


def copy_verified(source, target, expected):
    if target.exists():
        if target.is_symlink() or digest(target) != expected:
            raise RuntimeError(f'Existing file differs; refusing to replace it: {target}')
        return
    # Stage outside the pad directory; firmware never sees an incomplete WAV.
    fd, temporary = tempfile.mkstemp(prefix='.od-transfer-', dir=target.parent.parent)
    try:
        with os.fdopen(fd, 'wb') as out, source.open('rb') as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if digest(Path(temporary)) != expected:
            raise RuntimeError('Copy verification failed; pad file was not installed')
        # Our process lock prevents concurrent workflow runs. Recheck external edits.
        if target.exists():
            raise RuntimeError(f'Destination appeared during copying: {target}')
        os.rename(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(state_path, preview=False):
    state = json.loads(state_path.read_text())
    card = Path(state['card'])
    card_check(card)
    if card_identity(card) != state['card_id']:
        raise RuntimeError('This is a different SD card from the session')
    old = {x['take']: x for x in state['history']}
    candidates = [x for x in takes(card) if x not in state['ignored']]
    missing = set(old) - set(candidates)
    if missing:
        raise RuntimeError(f'Previously enrolled takes disappeared: {sorted(missing)}')
    history = []
    for take in candidates:
        folder = card / 'RECORDER' / take
        masters = sorted(p.name for p in folder.iterdir() if p.name.upper().startswith('MASTER') and p.suffix.upper() == '.WAV')
        if masters != ['MASTER.WAV']:
            raise RuntimeError(f'{take}: missing or split master; join/review this take before promotion')
        source = folder / 'MASTER.WAV'
        if source.is_symlink():
            raise RuntimeError('Symlinked master is unsupported')
        item = {'take': take, **wav_info(source)}
        if take in old and item != old[take]:
            raise RuntimeError(f'Original recording changed: {take}')
        history.append(item)
    # Preserve observed pass order even if the L6 clock is later adjusted backwards.
    ordered = [old[x['take']] for x in state['history']]
    ordered.extend(x for x in history if x['take'] not in old)
    plan = []
    needed = 0
    for pad, item in enumerate(reversed(ordered[-4:]), 1):
        name = f"OD_{item['take']}.WAV"
        target = card / 'SOUND_PAD' / f'PAD{pad}' / name
        if target.exists():
            if target.is_symlink() or digest(target) != item['sha256']:
                raise RuntimeError(f'Conflicting existing pad file: {target}')
        else:
            count = sum(p.suffix.upper() == '.WAV' for p in target.parent.iterdir())
            if count >= 1000:
                raise RuntimeError(f'Pad {pad} catalogue is full')
            needed += item['bytes']
        plan.append({'pad': pad, 'name': name, 'take': item['take'], 'sha256': item['sha256'],
                     'source': str(card / 'RECORDER' / item['take'] / 'MASTER.WAV'), 'target': str(target)})
    if shutil.disk_usage(card).free < needed + 1024 * 1024:
        raise RuntimeError('Not enough free space for all pad copies')
    if not preview:
        state.update(history=ordered, assignments=plan, phase='copying')
        save(state_path, state)
        for item in plan:
            copy_verified(Path(item['source']), Path(item['target']), item['sha256'])
        state['phase'] = 'prepared'
        save(state_path, state)
    return plan


def assign(state_path):
    state = json.loads(state_path.read_text())
    if state['phase'] not in ('prepared', 'assigning', 'ready'):
        raise RuntimeError('Prepare and verify the pad copies first')
    if Path(state['card']).exists():
        raise RuntimeError('Safely eject the card and exit file-transfer mode before assigning pads')
    if not state['assignments']:
        return []
    from l6_pad_control import PadSession
    log = state_path.parent / f'midi-{time.time_ns()}.jsonl'
    session = PadSession(log)
    try:
        before = {str(p + 1): session.query(p, 2).get('filename', '') for p in range(4)}
        selections = []
        # Resolve every destination before changing any pad.
        for item in state['assignments']:
            matches = [x for x in session.catalogue(item['pad'] - 1) if x.get('filename') == item['name']]
            if len(matches) != 1:
                raise RuntimeError(f"Pad {item['pad']} cannot find exactly one {item['name']}")
            selections.append((item, matches[0]['file_index']))
        state.update(phase='assigning', before_assignments=before, midi_log=str(log), confirmed=[])
        save(state_path, state)
        for item, index in reversed(selections):
            result = session.assign(item['pad'] - 1, index, item['name'])
            state['confirmed'].append({'pad': item['pad'], 'filename': result['filename']})
            save(state_path, state)
        for item, _ in selections:
            if session.query(item['pad'] - 1, 2).get('filename') != item['name']:
                raise RuntimeError('Pad assignment changed during verification')
        state['phase'] = 'ready'
        save(state_path, state)
        return state['confirmed']
    finally:
        session.close()


def describe(plan):
    if not plan:
        print('No new passes yet. Existing pad assignments are unchanged.', flush=True)
    for item in plan:
        print(f"Pad {item['pad']}: {item['take']} ({item['name']})", flush=True)


def cycle(state_path, timeout):
    state = json.loads(state_path.read_text())
    card = Path(state['card'])
    deadline = time.monotonic() + timeout
    print('After stopping your recording, enter File Transfer in the L6 Editor.', flush=True)
    while not (card / 'RECORDER').is_dir():
        if time.monotonic() >= deadline:
            raise TimeoutError('Timed out waiting for File Transfer; no recording was changed')
        time.sleep(1)
    plan = prepare(state_path)
    describe(plan)
    subprocess.run(['diskutil', 'unmount', str(card)], check=True)
    print('Copies verified and card safely unmounted. Click Exit File Transfer in the editor.', flush=True)
    print('Waiting for the editor to reconnect…', flush=True)
    last_error = 'No response before timeout'
    while time.monotonic() < deadline:
        try:
            # A fresh process avoids retaining CoreMIDI's endpoint cache across
            # the L6's USB disconnect/re-enumeration. The parent owns the lock.
            worker = subprocess.run([
                sys.executable, '-c',
                'import sys; sys.path.insert(0, sys.argv[1]); '
                'from pathlib import Path; from l6_overdub import assign; '
                'assign(Path(sys.argv[2]))',
                str(Path(__file__).resolve().parent), str(state_path.resolve())
            ], capture_output=True, text=True)
            if worker.returncode:
                raise RuntimeError(worker.stderr.strip().splitlines()[-1] if worker.stderr.strip()
                                   else f'MIDI worker exited with code {worker.returncode}')
            confirmed = json.loads(state_path.read_text()).get('confirmed', [])
            print('Pads verified. Ready for the next take. Use pad 1 for the latest master.', flush=True)
            return confirmed
        except (TimeoutError, RuntimeError) as exc:
            # Once assignment has begun, expose failures; do not hide a partial change.
            if json.loads(state_path.read_text())['phase'] == 'assigning':
                raise
            last_error = str(exc)
            time.sleep(2)
    raise TimeoutError(f'Editor did not reconnect: {last_error}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'preview', 'prepare', 'assign', 'cycle', 'status'])
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--card', type=Path, default=Path('/Volumes/L6_SD'))
    parser.add_argument('--include', nargs='*', default=[], help='Existing take folders to seed at initialization')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if args.timeout < 10:
        parser.error('--timeout must be at least 10 seconds')
    with locked(args.state):
        if args.action == 'init':
            initialize(args.card, args.state, args.include)
            print('Session created. Older recordings excluded except the explicitly included takes.')
        elif args.action in ('preview', 'prepare'):
            describe(prepare(args.state, preview=args.action == 'preview'))
        elif args.action == 'assign':
            print(json.dumps(assign(args.state), indent=2))
        elif args.action == 'cycle':
            cycle(args.state, args.timeout)
        else:
            print(args.state.read_text())


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'Workflow stopped: {exc}')
