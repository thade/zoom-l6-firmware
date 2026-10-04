"""Compare the user's 2026-10-02 stock-firmware overdub test with its backing.

Local WAV analysis only; requires NumPy. Regression detects coherent copies and
does not prove absolute absence of every possible form of bleed or distortion.
"""
import numpy as np,struct,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def read(p):
 b=Path(p).read_bytes();pos=12;fmt=None;data=None
 while pos+8<=len(b):
  tag=b[pos:pos+4];n=struct.unpack_from('<I',b,pos+4)[0];v=b[pos+8:pos+8+n]
  if tag==b'fmt ':fmt=struct.unpack_from('<HHIIHH',v)
  if tag==b'data':data=v
  pos+=8+n+(n%2)
 assert fmt[0]==3 and fmt[2]==48000 and fmt[5]==32,fmt
 return np.frombuffer(data,dtype='<f4').reshape(-1,fmt[1]).astype('float64')
def db(x):return float(20*np.log10(max(float(x),1e-20)))
def rms(x):return float(np.sqrt(np.mean(x*x)))
root=ROOT/'analysis/overdub_test/261002_175819'
a={p.name:read(p) for p in root.glob('*.WAV')}
stats={n:{'frames':len(x),'channels':x.shape[1],'digital_silence':bool(not np.any(x)),
          'rms_dbfs':db(rms(x)) if np.any(x) else None,
          'peak_dbfs':db(np.max(np.abs(x))) if np.any(x) else None} for n,x in a.items()}
m=a['MASTER.WAV'];b=read(ROOT/'analysis/backing_track/GLORY_BOX.WAV');s=a['TRACK03_ST.WAV']
assert all(len(z)==len(m) for z in a.values())
k=16
x=m[:len(m)//k*k,0].reshape(-1,k).mean(axis=1);y=b[:len(b)//k*k,0].reshape(-1,k).mean(axis=1)
n=1<<(len(x)+len(y)-1).bit_length()
c=np.fft.irfft(np.fft.rfft(x,n)*np.conj(np.fft.rfft(y,n)),n)
# Backing starts after record, within 10 seconds. Coarse peak then refine.
coarse=int(np.argmax(c[:48000*10//k]))*k
scores=[]
for d in range(max(0,coarse-32),coarse+33):
 t=min(len(m)-d,len(b),48000*20)
 scores.append((float(np.sum(m[d:d+t,0]*b[:t,0])),d))
d=max(scores)[1]
t=min(len(m)-d,len(b));bb=np.zeros_like(m);bb[d:d+t]=b[:t]
# Predict stereo master from backing stereo and recorded stereo input, plus DC.
X=np.column_stack([bb,s,np.ones(len(m))]);coef=np.linalg.lstsq(X,m,rcond=None)[0];pred=X@coef
residual=rms(m-pred)/rms(m)
track_comparisons={}
for name,z in a.items():
 co=np.linalg.lstsq(np.column_stack([bb,np.ones(len(m))]),z,rcond=None)[0]
 corr=np.corrcoef(np.column_stack([bb,z]).T)[:2,2:] if np.any(z) else np.zeros((2,z.shape[1]))
 track_comparisons[name]={'backing_coefficients':co[:2].tolist(),'backing_correlations':corr.tolist()}

# Check the alignment independently in separated sections of the recording.
offsets=[]
for sec in (3,13,23):
 start=sec*48000;size=3*48000
 vals=[(float(np.sum(m[start+lag:start+lag+size,0]*b[start:start+size,0])),lag)
       for lag in range(d-8,d+9)]
 offsets.append({'backing_start_seconds':sec,'best_offset_samples':max(vals)[1]})

report={'take':'261002_175819','duration_seconds':len(m)/48000,'format':'48 kHz float32 WAV',
        'files':stats,'backing_offset_samples':d,'backing_offset_seconds':d/48000,
        'alignment_windows':offsets,'master_model_coefficients':coef.tolist(),
        'coefficient_rows':['backing_left','backing_right','input3_left','input3_right','DC'],
        'coefficient_columns':['master_left','master_right'],
        'master_model_residual_relative_db':db(residual),
        'master_energy_explained_percent':100*(1-residual**2),
        'track_backing_comparisons':track_comparisons,
        'limits':['One 34-second take, not a repeated-overdub endurance or timing test.',
                  'Offset includes manual record/pad button timing; it is not device latency.',
                  'Low waveform correlation supports no coherent backing copy in stems, not absolute zero leakage.',
                  'No listening-based claim; conclusions use waveform alignment and linear regression.',
                  'Master reconstruction permits independent stereo gains and a DC term.']}
target=ROOT/'analysis/overdub_test/audio_analysis.json'
target.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'duration_seconds':report['duration_seconds'],'offset_seconds':d/48000,
                  'energy_explained_percent':report['master_energy_explained_percent'],
                  'alignment_windows':offsets,'report':str(target)},indent=2))
