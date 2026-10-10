"""Synthetic takes for the capture analysis tool; no device or card access."""
import struct,sys,tempfile,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/device'))
from analyze_capture_take import analyze,read_wav

def extra_wav(path,frames):
    """The firmware's 512-byte header (fmt + JUNK + data), float32 stereo."""
    payload=frames.astype('<f4').tobytes();h=bytearray(512)
    h[0:4]=b'RIFF';struct.pack_into('<I',h,4,len(payload)+504);h[8:16]=b'WAVEfmt '
    struct.pack_into('<IHHIIHH',h,16,16,3,2,48000,384000,8,32)
    h[36:40]=b'JUNK';struct.pack_into('<I',h,40,460);h[504:508]=b'data';struct.pack_into('<I',h,508,len(payload))
    Path(path).write_bytes(bytes(h)+payload)

def stock_wav(path,frames):
    """A plain stock-style header with an extra chunk before data."""
    payload=frames.astype('<f4').tobytes();ch=frames.shape[1]
    fmt=struct.pack('<HHIIHH',3,ch,48000,48000*ch*4,ch*4,32)
    body=b'WAVE'+b'fmt '+struct.pack('<I',16)+fmt+b'bext'+struct.pack('<I',6)+b'zoomL6'+b'data'+struct.pack('<I',len(payload))+payload
    Path(path).write_bytes(b'RIFF'+struct.pack('<I',len(body))+body)

class AnalyzeCaptureTake(unittest.TestCase):
    def take(self,directory,lag=48,master_frames=None,stem_frames=None):
        rng=np.random.default_rng(7);n=48000*6
        pre=(rng.standard_normal((n,2))*0.1).astype(np.float32)
        master=np.zeros_like(pre);master[lag:]=np.tanh(1.8*pre[:n-lag]) # gain, dynamics, delay
        d=Path(directory);extra_wav(d/'OD_00000001.TMP',pre)
        stock_wav(d/'MASTER.WAV',master[:master_frames or n])
        stock_wav(d/'TRACK01.WAV',pre[:stem_frames or n,:1])
        return d/'OD_00000001.TMP',d

    def test_matching_take_passes_with_the_stock_master_delay(self):
        with tempfile.TemporaryDirectory() as t:
            r=analyze(*self.take(t))
            self.assertTrue(r['passed']);self.assertEqual(r['lag_frames'],48);self.assertGreater(r['correlation'],.9)

    def test_length_lag_and_stem_mismatches_fail(self):
        for kwargs in (dict(master_frames=48000*6-64),dict(lag=0),dict(lag=52),dict(stem_frames=48000*5)):
            with tempfile.TemporaryDirectory() as t:
                self.assertFalse(analyze(*self.take(t,**kwargs))['passed'],kwargs)

    def test_small_lag_offsets_pass_and_silent_starts_do_not_hide_the_lag(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertTrue(analyze(*self.take(t,lag=50))['passed'])
        with tempfile.TemporaryDirectory() as t:
            extra,d=self.take(t);frames,_=read_wav(extra);quiet=np.array(frames);quiet[:48000*3]=0
            extra_wav(extra,quiet);r=analyze(extra,d)
            self.assertEqual(r['lag_frames'],48)

    def test_bad_headers_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            extra,_=self.take(t);data=bytearray(extra.read_bytes());data[20]=1 # PCM, not float
            extra.write_bytes(bytes(data))
            with self.assertRaises(ValueError):read_wav(extra)
            data[20]=3;extra.write_bytes(bytes(data[:-3])) # truncated payload
            with self.assertRaises(ValueError):read_wav(extra)

if __name__=='__main__':unittest.main()
