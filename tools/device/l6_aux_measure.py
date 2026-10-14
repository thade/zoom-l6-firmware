#!/usr/bin/env python3
"""Record the two AUX jacks through a 2-input audio interface and measure them.

Connect AUX 1 to the interface's input 1 and AUX 2 to input 2. Records with
ffmpeg (avfoundation) from the named input device, then reports per side:
RMS and peak level (dBFS), left/right balance, the correlation between the
sides, and the delay of AUX 2 relative to AUX 1 (samples, from the
cross-correlation peak). Read-only: it sends nothing to the mixer.

  l6_aux_measure.py --list
  l6_aux_measure.py --device "My Interface" --seconds 5 --output take.wav
  l6_aux_measure.py --analyze take.wav
"""
import argparse,json,re,subprocess,sys,wave
from pathlib import Path
import numpy as np

def devices():
    out=subprocess.run(['ffmpeg','-hide_banner','-f','avfoundation','-list_devices','true','-i',''],
                       capture_output=True,text=True).stderr
    audio=out.split('AVFoundation audio devices:')[-1]
    return {m.group(2).strip():int(m.group(1)) for m in re.finditer(r'\[(\d+)\] (.+)',audio)}

def record(device,seconds,output,rate):
    index=devices().get(device)
    if index is None:raise SystemExit(f'No audio input named {device!r}; see --list')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','avfoundation','-i',f':{index}',
                    '-t',str(seconds),'-ac','2','-ar',str(rate),'-c:a','pcm_s24le',str(output)],check=True)

def load(path):
    with wave.open(str(path)) as w:
        n,ch,width,rate=w.getnframes(),w.getnchannels(),w.getsampwidth(),w.getframerate()
        raw=w.readframes(n)
    if ch!=2:raise SystemExit('expected a 2-channel recording (AUX 1, AUX 2)')
    if width==3:
        b=np.frombuffer(raw,np.uint8).reshape(-1,3)
        x=(b[:,0].astype(np.int32)|b[:,1].astype(np.int32)<<8|b[:,2].astype(np.int32)<<16)
        x=np.where(x&0x800000,x-0x1000000,x)/float(1<<23)
    elif width==2:x=np.frombuffer(raw,'<i2')/32768.0
    else:x=np.frombuffer(raw,'<i4')/float(1<<31)
    return x.reshape(-1,2),rate

def db(v):return float(20*np.log10(v)) if v>0 else float('-inf')

def analyze(path,max_lag=480):
    x,rate=load(path);a,b=x[:,0]-x[:,0].mean(),x[:,1]-x[:,1].mean()
    rms=[float(np.sqrt(np.mean(s*s))) for s in (a,b)];peak=[float(np.max(np.abs(s))) for s in (a,b)]
    result=dict(file=str(path),rate=rate,seconds=len(x)/rate,
                aux1=dict(rms_dbfs=db(rms[0]),peak_dbfs=db(peak[0])),
                aux2=dict(rms_dbfs=db(rms[1]),peak_dbfs=db(peak[1])),
                balance_db=(db(rms[0])-db(rms[1])) if rms[0]>0 and rms[1]>0 else None)
    if rms[0]>1e-5 and rms[1]>1e-5:
        n=min(len(a),rate*4);u,v=a[:n],b[:n]
        lags=range(-max_lag,max_lag+1)
        c=[float(np.dot(u[max(0,-k):n-max(0,k)],v[max(0,k):n-max(0,-k)])) for k in lags]
        best=int(np.argmax(np.abs(c)));norm=float(np.sqrt(np.dot(u,u)*np.dot(v,v)))
        result.update(delay_samples=list(lags)[best],correlation=c[best]/norm if norm else None,
                      correlation_at_zero=c[max_lag]/norm if norm else None)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--list',action='store_true');p.add_argument('--device')
    p.add_argument('--seconds',type=float,default=5);p.add_argument('--rate',type=int,default=48000)
    p.add_argument('--output',type=Path);p.add_argument('--analyze',type=Path)
    a=p.parse_args()
    if a.list:print(json.dumps(devices(),indent=1,ensure_ascii=False));return
    path=a.analyze
    if not path:
        if not (a.device and a.output):raise SystemExit('--device and --output are needed to record')
        a.output.parent.mkdir(parents=True,exist_ok=True);record(a.device,a.seconds,a.output,a.rate);path=a.output
    print(json.dumps(analyze(path),indent=1))
if __name__=='__main__':main()
