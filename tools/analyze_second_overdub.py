"""Offline comparison of the two second-pass candidate takes; NumPy only."""
from pathlib import Path
import json,struct
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def read(p):
 b=Path(p).read_bytes();pos=12;fmt=None;data=None
 while pos+8<=len(b):
  tag=b[pos:pos+4];n=struct.unpack_from('<I',b,pos+4)[0];v=b[pos+8:pos+8+n]
  if tag==b'fmt ':fmt=struct.unpack_from('<HHIIHH',v)
  if tag==b'data':data=v
  pos+=8+n+(n%2)
 assert fmt[0]==3 and fmt[2]==48000 and fmt[5]==32,fmt
 return np.frombuffer(data,dtype='<f4').reshape(-1,fmt[1]).astype('float64')
def rms(x):return float(np.sqrt(np.mean(x*x)))
def db(x):return float(20*np.log10(max(abs(float(x)),1e-20)))
def align(m,b):
 k=16;x=m[:len(m)//k*k,0].reshape(-1,k).mean(axis=1);y=b[:len(b)//k*k,0].reshape(-1,k).mean(axis=1)
 n=1<<(len(x)+len(y)-1).bit_length();c=np.fft.irfft(np.fft.rfft(x,n)*np.conj(np.fft.rfft(y,n)),n)
 lags=np.arange(-len(y)+3*48000//k,len(x)-3*48000//k)
 d=int(lags[np.argmax(c[lags%n])])*k
 scores=[]
 for lag in range(d-32,d+33):
  start=max(0,lag);bs=max(0,-lag);t=min(len(m)-start,len(b)-bs)
  scores.append((float(np.sum(m[start:start+t,0]*b[bs:bs+t,0])),lag))
 d=max(scores)[1];out=np.zeros_like(m);start=max(0,d);bs=max(0,-d);t=min(len(m)-start,len(b)-bs);out[start:start+t]=b[bs:bs+t]
 return out,d
refs={'pass1_master':read(ROOT/'analysis/overdub_test/261002_175819/MASTER.WAV'),
      'original_backing':read(ROOT/'analysis/backing_track/GLORY_BOX.WAV')}
def main():
 report={'method':'Waveform alignment and least-squares stereo reconstruction; no listening-based claim','takes':[]}
 for take in ('261002_180953','261002_181142'):
  root=ROOT/'analysis/overdub_test/pass2'/take
  tracks={p.name:read(p) for p in root.glob('*.WAV')};m=tracks['MASTER.WAV'];s=tracks['TRACK03_ST.WAV']
  assert all(len(x)==len(m) for x in tracks.values())
  result={'take':take,'duration_seconds':len(m)/48000,'tracks':{},'models':{}}
  for name,x in tracks.items():
   result['tracks'][name]={'channels':x.shape[1],'frames':len(x),'rms_dbfs':db(rms(x)) if np.any(x) else None,'peak_dbfs':db(np.max(np.abs(x))) if np.any(x) else None}
  for name,b in refs.items():
   bb,d=align(m,b);X=np.column_stack([bb,s,np.ones(len(m))]);coef=np.linalg.lstsq(X,m,rcond=None)[0];e=m-X@coef
   corr=np.corrcoef(np.column_stack([bb,s]).T)[:2,2:]
   mono_coef=np.linalg.lstsq(np.column_stack([bb,np.ones(len(m))]),m,rcond=None)[0]
   alone=m-np.column_stack([bb,np.ones(len(m))])@mono_coef
   windows=[]
   for sec in (1,4,7):
    start=sec*48000;end=min(start+2*48000,len(m))
    cx=np.linalg.lstsq(X[start:end],m[start:end],rcond=None)[0]
    windows.append({'recording_second':sec,'backing_diagonal_gains':[float(cx[0,0]),float(cx[1,1])]})
   result['models'][name]={'offset_samples':d,'offset_seconds':d/48000,'coefficient_rows':['backingL','backingR','new_input3_L','new_input3_R','DC'],'coefficients':coef.tolist(),'backing_gains_db':[db(coef[0,0]),db(coef[1,1])],'residual_relative_db':db(rms(e)/rms(m)),'energy_explained_percent':100*(1-(rms(e)/rms(m))**2),'backing_only_energy_explained_percent':100*(1-(rms(alone)/rms(m))**2),'input3_backing_correlations':corr.tolist(),'gain_windows':windows}
  report['takes'].append(result)
 report['limits']=['Only these short takes and current settings were tested.','Offset includes manual trigger timing and is not hardware latency.','Low waveform correlation supports absence of a coherent backing copy, not absolute zero leakage.','Stereo input channels can be highly correlated: individual cross-feed coefficients should not be overinterpreted.']
 out=ROOT/'analysis/overdub_test/pass2/audio_analysis.json';out.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2))

if __name__ == '__main__':
 main()
