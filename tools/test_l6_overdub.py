"""File integrity and recovery tests; no physical MIDI or SD-card access."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import l6_overdub as workflow


def wav(path, value=0.25):
    fmt = struct.pack('<HHIIHH', 3, 2, 48000, 384000, 8, 32)
    data = struct.pack('<ff', value, -value) * 128
    body = b'WAVEfmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', len(data)) + data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'RIFF' + struct.pack('<I', len(body)) + body)


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.card = root / 'card'
        self.state = root / 'state.json'
        (self.card / 'RECORDER').mkdir(parents=True)
        for p in range(1, 5):
            (self.card / 'SOUND_PAD' / f'PAD{p}').mkdir(parents=True)
        self.take('260925_203532')
        workflow.initialize(self.card, self.state, [])

    def take(self, name, value=0.25):
        path = self.card / 'RECORDER' / name / 'MASTER.WAV'
        wav(path, value)
        wav(path.with_name('TRACK03_ST.WAV'), 0.1)
        return path

    def test_rotation_and_retry_preserve_sources_and_user_files(self):
        user_file = self.card / 'SOUND_PAD/PAD1/MY_SONG.WAV'
        wav(user_file)
        original = workflow.digest(user_file)
        for i in range(1, 6):
            self.take(f'261002_18000{i}', i / 10)
            plan = workflow.prepare(self.state)
            self.assertEqual(plan[0]['take'], f'261002_18000{i}')
            self.assertEqual(len(plan), min(4, i))
            for item in plan:
                self.assertEqual(workflow.digest(Path(item['source'])), workflow.digest(Path(item['target'])))
        self.assertEqual([x['take'] for x in plan], [f'261002_18000{i}' for i in (5, 4, 3, 2)])
        snapshots = {str(p): (p.stat().st_mtime_ns, workflow.digest(p)) for p in self.card.rglob('*.WAV')}
        self.assertEqual(workflow.prepare(self.state), plan)
        self.assertEqual(snapshots, {str(p): (p.stat().st_mtime_ns, workflow.digest(p)) for p in self.card.rglob('*.WAV')})
        self.assertEqual(workflow.digest(user_file), original)
        self.assertNotIn('260925_203532', [x['take'] for x in json.loads(self.state.read_text())['history']])

    def test_interrupted_copy_resumes_without_false_ready(self):
        self.take('261002_180001')
        self.take('261002_180002', 0.5)
        copy = workflow.copy_verified
        calls = []
        def fail_second(*args):
            calls.append(args)
            if len(calls) == 2:
                raise OSError('simulated unplug')
            return copy(*args)
        with patch.object(workflow, 'copy_verified', side_effect=fail_second):
            with self.assertRaises(OSError):
                workflow.prepare(self.state)
        self.assertEqual(json.loads(self.state.read_text())['phase'], 'copying')
        self.assertEqual(len(workflow.prepare(self.state)), 2)
        self.assertEqual(json.loads(self.state.read_text())['phase'], 'prepared')

    def test_truncated_and_split_master_rejected_before_copying(self):
        master = self.take('261002_180001')
        good = master.read_bytes()
        master.write_bytes(good[:-8])
        with self.assertRaises(ValueError):
            workflow.prepare(self.state)
        master.write_bytes(good)
        master.with_name('MASTER_0001.WAV').write_bytes(good)
        with self.assertRaises(RuntimeError):
            workflow.prepare(self.state)
        self.assertFalse(list((self.card / 'SOUND_PAD').rglob('*.WAV')))

    def test_conflict_and_changed_original_stop(self):
        master = self.take('261002_180001')
        plan = workflow.prepare(self.state)
        target = Path(plan[0]['target'])
        target.write_bytes(b'user replacement')
        with self.assertRaises(RuntimeError):
            workflow.prepare(self.state)
        self.assertEqual(target.read_bytes(), b'user replacement')
        target.write_bytes(master.read_bytes())
        wav(master, 0.75)
        with self.assertRaises(RuntimeError):
            workflow.prepare(self.state)

    def test_preview_does_not_change_state_or_card(self):
        self.take('261002_180001')
        before = self.state.read_bytes()
        self.assertEqual(len(workflow.prepare(self.state, preview=True)), 1)
        self.assertEqual(before, self.state.read_bytes())
        self.assertFalse(list((self.card / 'SOUND_PAD').rglob('*.WAV')))


if __name__ == '__main__':
    unittest.main()
