#!/usr/bin/env python3
"""Exercise five native L6 effects using USB audio and experiment-08 guards.

macOS, connected official L6 Editor, armed experiment-08 guards, and verified
CH1 / EFX TYPE CC117 mapping are prerequisites. Sends only fixed effect choices
to Mixer Control Port. No gains, routing, numeric effect parameters, transport,
pad assignments, guard initialization, card writes or firmware updates.
Requires numpy, sounddevice and soundfile. Saves all evidence on the computer.
"""
import argparse
import contextlib
import ctypes as C
import datetime
import json
from pathlib import Path
import queue
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

import l6_midi_probe as midi
import l6_ring_probe as ring
from l6_health_probe import sample

EFFECT_VALUES = dict(hall=12, room=38, spring=64, delay=89, echo=115)
RATE = 48000
DURATION = 24
BURSTS = (1, 5, 9, 13)
ENERGY_BIN_FRAMES = RATE // 50  # 20 ms: keep repeat timing, tolerate reverb phase.


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def require(condition, explanation):
    if not condition:
        raise RuntimeError(explanation)


def audio_fixture():
    """Four repeatable, low-level broadband bursts; no input-to-output loop."""
    audio = np.zeros((DURATION * RATE, 4), dtype=np.float32)
    n = RATE // 10
    t = np.arange(n) / RATE
    # Known seed and window permit effect-response comparison across passes.
    rng = np.random.default_rng(600117)
    burst = (rng.standard_normal(n) * .25
             + np.sin(2 * np.pi * 523 * t)
             + np.sin(2 * np.pi * 787 * t)
             + np.sin(2 * np.pi * 1201 * t))
    burst *= np.sin(np.pi * np.arange(n) / (n - 1)) ** 2
    burst *= .01 / np.max(np.abs(burst))
    for second in BURSTS:
        audio[second * RATE:second * RATE + n, :2] = burst[:, None]
    return audio


@contextlib.contextmanager
def effect_port(log_path):
    """No generic send API: only the five vetted CC117/channel-1 packets."""
    client = midi.REF()
    with log_path.open('x') as log:
        def write(row):
            log.write(json.dumps(row) + '\n')
            log.flush()

        title = midi.cfstr(None, b'L6 bounded USB effect test', 0x08000100)
        try:
            midi.check(midi.client_new(title, None, None, C.byref(client)))
        finally:
            midi.release(title)
        try:
            sources = [e for e in midi.endpoints('Source') if e['display_name'] == 'L6 Mixer Control Port']
            destinations = [e for e in midi.endpoints('Destination') if e['display_name'] == 'L6 Mixer Control Port']
            require(len(sources) == len(destinations) == 1, 'Exact L6 Mixer Control Port pair is required')
            write(dict(kind='inventory', source=sources[0], destination=destinations[0]))
            events = queue.Queue()

            def receive(ptr, refcon, connection):
                try:
                    count = C.c_uint32.from_address(ptr).value
                    require(count <= 4096, 'Unexpected MIDI packet count')
                    pos = ptr + 4
                    for _ in range(count):
                        size = C.c_uint16.from_address(pos + 8).value
                        events.put(dict(direction='device_to_host', timestamp=time.time(),
                                        hex=C.string_at(pos + 10, size).hex(' ')))
                        pos = (pos + 10 + size + 3) & ~3
                except Exception as exc:
                    events.put(exc)

            callback = midi.READ(receive)  # Keep callback alive through client disposal.
            inp = midi.REF()
            out = midi.REF()
            title = midi.cfstr(None, b'L6 effect response listener', 0x08000100)
            try:
                midi.check(midi.port_new(client, title, callback, None, C.byref(inp)))
                midi.check(midi.out_new(client, title, C.byref(out)))
            finally:
                midi.release(title)
            midi.check(midi.connect(inp, sources[0]['ref'], None))

            def drain():
                while True:
                    try:
                        row = events.get_nowait()
                    except queue.Empty:
                        break
                    if isinstance(row, Exception):
                        raise row
                    write(row)

            def select(effect):
                require(effect in EFFECT_VALUES, 'Unsupported effect')
                data = bytes((0xb0, 117, EFFECT_VALUES[effect]))
                storage = C.create_string_buffer(1024)
                raw = C.create_string_buffer(data)
                first = midi.packet_init(storage)
                require(bool(midi.packet_add(storage, len(storage), first, 0, len(data), raw)),
                        'Could not construct fixed effect packet')
                midi.check(midi.send(out, destinations[0]['ref'], storage))
                write(dict(direction='test_to_device', timestamp=time.time(), effect=effect, hex=data.hex(' ')))
                time.sleep(.3)
                drain()

            yield select, drain
        finally:
            midi.client_free(client)


def check_snapshot(rows, baseline):
    guards = (rows[0], rows[-1])
    span, backlog = rows[1:3]
    for g in guards:
        require(g['observer_consistent'] and g['guards_armed'] and g['layout_matches'],
                'Guards/layout are not armed and coherent; preserve logs')
        require(not g['bad_words'] and not g['layout_faults'], 'Latched guard/layout fault; preserve logs')
        require(g['play_cursor'] == baseline['play_cursor'], 'Native song playback advanced; stop test')
    require(span['observer_consistent'] and not span['overlaps'] and not span['invalid_spans'],
            'Requested source observer conflict; preserve logs')
    require(span['claim_skips'] == baseline['source_omissions'] and span['requests'] >= baseline['source_requests'],
            'New source omission or counter regression; preserve logs')
    require(backlog['observer_consistent'] and not backlog['invalid_cursors'] and not backlog['active_mask'],
            'Native recording active or backlog snapshot invalid; stop test')


def snapshot(path, baseline):
    rows = sample(path, query_builder=ring.request, reply_decoder=ring.decode, kinds=(1, 4, 5, 1))
    check_snapshot(rows, baseline)
    return rows


def full_scan(path, baseline=None):
    last = {}

    def receive(packet):
        row = ring.decode(packet)
        if row:
            last['guard' if row['kind'] <= 3 else 'span' if row['kind'] == 4 else 'backlog'] = row
        return row

    rows = sample(path, query_builder=ring.request, reply_decoder=receive,
                  kinds=ring.sequence(last, scan=True))
    first, end = rows[0], last['guard']
    misses = end['claim_skips'] - first['claim_skips']
    checks = dict(guards_intact=end['guards_armed'] and not end['bad_words'] and not end['layout_faults'],
                  coherent_layout=end['observer_consistent'] and end['layout_matches'],
                  full_cycle=sum(r['kind'] == 3 for r in rows) - misses == ring.CHUNKS
                  and end['scan_word'] == first['scan_word'] and end['sweeps'] == first['sweeps'] + 1,
                  no_new_source_omissions=last['source_window']['checked_interval_has_no_new_omissions'],
                  native_recording_stopped=not last['backlog']['active_mask'],
                  native_playback_stopped=first['play_cursor'] == end['play_cursor'])
    result = dict(checks=checks, passed=all(checks.values()), latest=last, successful_chunks=ring.CHUNKS,
                  retried_guard_claims=misses)
    save(path.with_suffix('.summary.json'), result)
    require(result['passed'], 'Stopped full guard scan failed; preserve logs')
    if baseline is not None:
        check_snapshot((end, last['span'], last['backlog'], end), baseline)
    return result


def metrics(sent, received):
    require(np.isfinite(received).all(), 'Nonfinite USB audio')
    dry = received[:, 8:10].astype(np.float64)
    master = received[:, :2].astype(np.float64)
    template = sent[:, :2].astype(np.float64)
    rms = lambda x: float(np.sqrt(np.mean(x * x)))
    # Find stream latency from the first dry burst, then align the known windows.
    first = dry[:3 * RATE, 0]
    onset = int(np.argmax(np.abs(first) > 1e-5))
    require(abs(onset - RATE) < RATE // 2, 'Expected USB dry burst not found within latency bound')
    # Use peak location rather than window onset, which changes with amplitude.
    input_peak = int(np.argmax(np.abs(template[:3 * RATE, 0])))
    dry_peak = int(np.argmax(np.abs(first)))
    latency = dry_peak - input_peak
    require(abs(latency) < RATE // 2, 'Unexpected USB stream alignment')
    src = slice(max(0, -latency), min(len(template), len(template) - latency))
    dst = slice(src.start + latency, src.stop + latency)
    x, y = template[src].ravel(), dry[dst].ravel()
    correlation = float(np.dot(x, y) / np.sqrt(np.dot(x, x) * np.dot(y, y)))
    tail_windows = [master[(s * RATE + latency + RATE // 5):(s * RATE + latency + 3 * RATE)] for s in BURSTS]
    dry_tail_windows = [dry[(s * RATE + latency + RATE // 5):(s * RATE + latency + 3 * RATE)] for s in BURSTS]
    quiet = master[int(.2 * RATE):int(.8 * RATE)]
    fingerprint = np.mean(tail_windows, axis=0)
    result = dict(finite=True, latency_frames=latency, dry_input_correlation=correlation,
                  master_peak=float(np.max(np.abs(master))), master_rms=rms(master),
                  master_tail_rms=rms(np.concatenate(tail_windows)),
                  coherent_mean_tail_rms=rms(fingerprint), dry_tail_rms=rms(np.concatenate(dry_tail_windows)),
                  quiet_master_rms=rms(quiet))
    result['checks'] = dict(dry_matches_fixture=correlation > .99,
        master_below_quiet_bound=result['master_peak'] < .9,
        effect_tail_above_background=result['master_tail_rms'] > max(1e-6, result['quiet_master_rms'] * 3),
        dry_tail_silent=result['dry_tail_rms'] < 1e-6)
    return result, fingerprint


def energy_fingerprint(received, latency):
    """Background-corrected decay/repeat envelope, without averaging tail phase."""
    tails = np.asarray([received[(s * RATE + latency + RATE // 5):(s * RATE + latency + 3 * RATE), :2]
                        for s in BURSTS], dtype=np.float64)
    blocks = tails.reshape(len(BURSTS), -1, ENERGY_BIN_FRAMES, 2)
    background = np.mean(received[int(.2 * RATE):int(.8 * RATE), :2].astype(np.float64) ** 2, axis=0)
    return np.sqrt(np.maximum(np.mean(blocks ** 2, axis=(0, 2)) - background, 0))


def compare_responses(references, restored, original_effect):
    """Require the restored envelope to match its reference and reject other types."""
    norms = {name: float(np.linalg.norm(ref)) for name, ref in references.items()}
    require(all(np.isfinite(ref).all() and norms[name] > 0 for name, ref in references.items()),
            'Missing or nonfinite reference effect response')
    require(np.isfinite(restored).all(), 'Nonfinite restored effect response')
    differences = {}
    for i, left in enumerate(EFFECT_VALUES):
        for right in tuple(EFFECT_VALUES)[i + 1:]:
            a, b = references[left], references[right]
            differences[left + '/' + right] = float(np.linalg.norm(a - b) / max(norms[left], norms[right]))
    restoration_distances = {name: float(np.linalg.norm(restored - ref) / norms[name])
                             for name, ref in references.items()}
    original = references[original_effect]
    restored_norm = float(np.linalg.norm(restored))
    correlation = float(np.sum(restored * original) / (restored_norm * norms[original_effect])) if restored_norm else 0.0
    difference = restoration_distances[original_effect]
    other_distance = min(value for name, value in restoration_distances.items() if name != original_effect)
    return dict(comparison_method='20ms stereo RMS tail envelope; mean energy across four bursts; silent background subtracted.',
                pairwise_tail_energy_differences=differences,
                restored_energy_relative_difference=difference,
                restored_energy_correlation=correlation,
                restored_distances_by_effect=restoration_distances,
                restored_audio_matches_original=difference < .1 and correlation > .98
                and other_distance > max(.1, 2 * difference),
                five_distinct_effect_responses=all(v > .05 for v in differences.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-effect', choices=tuple(EFFECT_VALUES), required=True)
    parser.add_argument('--verified-cc117-channel1', action='store_true', required=True,
                        help='Confirm official Editor mapping has been inspected')
    parser.add_argument('--output', type=Path, required=True, help='New computer-only evidence directory')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report_path = args.output / 'report.json'
    report = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  original_effect=args.original_effect, capture_enabled=False, cases=[],
                  guard_initialization_sent=False, allowed_mixer_control_change='effect_type',
                  effect_commands=[],
                  effect_numeric_parameters_changed=False, native_transport_commands_sent=False,
                  status='preflight', passed=False,
                  limitations=['Guard scans qualify checked writes, not reads, DMA/cache ownership or all modes.',
                               'USB master observations establish an effect response; effect labels rely on verified MIDI mapping/value decoder.',
                               'No additional recording stream, SD-storage or overdub synchronization is exercised.'])
    save(report_path, report)
    devices = [dict(d) for d in sd.query_devices() if d['name'] == 'ZOOM L6']
    require(len(devices) == 1, 'Exactly one ZOOM L6 audio device required')
    device = devices[0]
    require(device['max_input_channels'] == 12 and device['max_output_channels'] == 4,
            'Expected L6 12-input/4-output USB audio interface')
    sd.check_input_settings(device=device['index'], channels=12, dtype='float32', samplerate=RATE)
    sd.check_output_settings(device=device['index'], channels=4, dtype='float32', samplerate=RATE)
    report['audio_device'] = device
    preflight = full_scan(args.output / 'preflight.jsonl')
    report['preflight'] = preflight
    g, span = preflight['latest']['guard'], preflight['latest']['span']
    baseline = dict(play_cursor=g['play_cursor'], source_requests=span['requests'], source_omissions=span['claim_skips'])
    report.update(status='running', baseline=baseline, samplerate=RATE, seconds_per_effect=DURATION)
    save(report_path, report)
    sent = audio_fixture()
    sf.write(args.output / 'sent.wav', sent, RATE, subtype='FLOAT')
    fingerprints = {}

    def run_audio(name):
        folder = args.output / name
        folder.mkdir()
        report['current_case'] = name
        save(report_path, report)
        received = sd.playrec(sent, RATE, channels=12, device=(device['index'], device['index']),
                              dtype='float32', latency='high', blocking=False)
        snapshots = []
        started = time.monotonic()
        try:
            for i, at in enumerate((5, 10, 15, 20)):
                time.sleep(max(0, started + at - time.monotonic()))
                snapshots.append(snapshot(folder / f'live-{i}.jsonl', baseline))
            status = sd.wait()
        finally:
            sd.stop()  # Close host audio stream even if a diagnostic query fails.
            sf.write(folder / 'returned.wav', received, RATE, subtype='FLOAT')
        scan = full_scan(folder / 'stopped-scan.jsonl', baseline)
        measured, _ = metrics(sent, received)
        row = dict(name=name, metrics=measured, host_stream_status=str(status),
                   live_snapshots=snapshots, stopped_scan=scan,
                   passed=not status and all(measured['checks'].values()))
        report['cases'].append(row)
        save(report_path, report)
        require(not status, f'Host audio stream failure: {status}')
        require(all(measured['checks'].values()), f'Audio qualification failed: {measured["checks"]}')
        print(json.dumps(dict(completed=name, master_tail_rms=measured['master_tail_rms'],
                              sweeps=scan['latest']['guard']['sweeps'], guard_bad_words=0)), flush=True)
        return energy_fingerprint(received, measured['latency_frames'])

    try:
        with effect_port(args.output / 'effect-midi.jsonl') as (select, drain):
            def send_effect(effect):
                command = dict(effect=effect, timestamp=time.time(), sent_to_coremidi=False)
                report['effect_commands'].append(command)
                save(report_path, report)
                select(effect)
                command['sent_to_coremidi'] = True
                save(report_path, report)

            changed = False
            try:
                # Establish original Room response before any type change.
                fingerprints[args.original_effect] = run_audio(args.original_effect)
                for effect in EFFECT_VALUES:
                    if effect == args.original_effect:
                        continue
                    changed = True  # Restore even if sending succeeds then logging fails.
                    send_effect(effect)
                    fingerprints[effect] = run_audio(effect)
                    drain()
            finally:
                sd.stop()
                if changed:
                    report['restoration_attempted'] = True
                    save(report_path, report)
                    send_effect(args.original_effect)
                    report['restoration_cc_sent'] = True
                    save(report_path, report)
            restored = run_audio('restored-' + args.original_effect)
            drain()
        report.update(compare_responses(fingerprints, restored, args.original_effect))
        require(report['restored_audio_matches_original'], 'Restored effect response differs from original')
        require(report['five_distinct_effect_responses'], 'Five distinct effect responses were not established')
        report.update(status='complete', passed=True)
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save(report_path, report)
    print(json.dumps(dict(passed=report['passed'], report=str(report_path), restored_effect=args.original_effect)), flush=True)


if __name__ == '__main__':
    main()
