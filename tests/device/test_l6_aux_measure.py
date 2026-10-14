"""Offline checks of the AUX jack analysis on synthetic two-channel recordings."""
import sys,tempfile,unittest,wave
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/device'))
from l6_aux_measure import analyze

def write(path,left,right,rate=48000):
    x=np.stack([left,right],1);pcm=(np.clip(x,-1,1-2**-23)*(1<<23)).astype(np.int32)
    b=np.zeros((len(pcm)*2,3),np.uint8);flat=pcm.reshape(-1)
    for k in range(3):b[:,k]=(flat>>(8*k))&255
    with wave.open(str(path),'wb') as w:
        w.setnchannels(2);w.setsampwidth(3);w.setframerate(rate);w.writeframes(b.tobytes())

class AuxMeasure(unittest.TestCase):
    def setUp(self):
        self.dir=Path(tempfile.mkdtemp());rng=np.random.default_rng(1)
        self.noise=rng.standard_normal(48000*2)*0.1
    def test_balance_and_delay(self):
        p=self.dir/'a.wav';right=np.concatenate([np.zeros(5),self.noise[:-5]])*0.5
        write(p,self.noise,right);r=analyze(p)
        self.assertAlmostEqual(r['balance_db'],6.02,delta=0.05)
        self.assertEqual(r['delay_samples'],5);self.assertGreater(r['correlation'],0.99)
    def test_separated_sides(self):
        p=self.dir/'b.wav';other=np.random.default_rng(2).standard_normal(len(self.noise))*0.1
        write(p,self.noise,other);r=analyze(p)
        self.assertLess(abs(r['correlation_at_zero']),0.05)
    def test_one_side_silent(self):
        p=self.dir/'c.wav';write(p,self.noise,np.zeros(len(self.noise)));r=analyze(p)
        self.assertEqual(r['aux2']['rms_dbfs'],float('-inf'));self.assertIsNone(r['balance_db'])
        self.assertNotIn('delay_samples',r)
if __name__=='__main__':unittest.main()
