"""Segmented gain/lag checks for the second-pass recordings; local analysis only."""
import analyze_second_overdub as a
import numpy as np,json
r={}
old=a.read(a.ROOT/'analysis/overdub_test/261002_175819/TRACK03_ST.WAV')
power=np.sqrt(np.mean(old[:len(old)//480*480].reshape(-1,480,2)**2,axis=(1,2)))
print('first performance above -60dBFS at',int(np.where(power>0.001)[0][0])/100)
for take in ('261002_180953','261002_181142'):
 root=a.ROOT/'analysis/overdub_test/pass2'/take;m=a.read(root/'MASTER.WAV');s=a.read(root/'TRACK03_ST.WAV');models={}
 for name,b in a.refs.items():
  bb,d=a.align(m,b);variants=[]
  for shift in range(-3,4):
   lag=d+shift;start=max(0,lag);bs=max(0,-lag);t=min(len(m)-start,len(b)-bs);z=np.zeros_like(m);z[start:start+t]=b[bs:bs+t]
   e2=0;wins=[]
   for i in range(0,len(m),24000):
    end=min(i+24000,len(m));X=np.column_stack([z[i:end],s[i:end],np.ones(end-i)])
    co=np.linalg.lstsq(X,m[i:end],rcond=None)[0];err=m[i:end]-X@co;e2+=float(np.sum(err**2))
    wins.append({'second':i/48000,'gain_L':float(co[0,0]),'gain_R':float(co[1,1]),'residual_rms_dbfs':a.db(a.rms(err))})
   variants.append((e2,lag,wins))
  e2,lag,wins=min(variants,key=lambda v:v[0]);models[name]={'lag':lag,'variable_gain_model_residual_db':10*np.log10(e2/np.sum(m*m)),'windows':wins}
 r[take]=models
print(json.dumps(r,indent=2))
(a.ROOT/'analysis/overdub_test/pass2/window_analysis.json').write_text(json.dumps({'first_performance_onset_seconds':int(np.where(power>0.001)[0][0])/100,'takes':r},indent=2)+'\n')
