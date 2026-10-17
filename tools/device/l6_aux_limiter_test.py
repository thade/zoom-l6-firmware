#!/usr/bin/env python3
"""Are the two AUX output limiters linked? Play a loud 1 kHz tone in bursts on
the left and a quiet, steady 1.5 kHz tone on the right into the L6 over USB
(input 5 on the test setup), record the two AUX jacks through a two-input
interface, and compare the right jack's level while the left bursts are on
and off. Independent limiters leave the right level alone; linked ones turn
it down by the left side's gain reduction for the length of each burst. The
left side must be loud enough to limit (input 5's AUX 1 send and level up;
the limiters act near full scale). Sends nothing to the mixer but audio.

  l6_aux_limiter_test.py --output deployment/41_linked/limiter-stereo.wav
"""
import argparse,json,subprocess,tempfile,time,wave
from pathlib import Path
import numpy as np
from l6_aux_measure import devices,load
from l6_aux_tone_test import play_devices,LEFT,RIGHT

def signal_file(path,seconds,left_db,right_db,burst,rate=48000):
    t=np.arange(int(seconds*rate))/rate
    gate=((t//burst)%2==1).astype(float)   # off first, then on/off every `burst` seconds
    edge=np.minimum(1,np.minimum(t%burst,burst-t%burst)/0.005)   # 5 ms fades at each edge
    l=10**(left_db/20)*np.sin(2*np.pi*LEFT*t)*gate*edge
    r=10**(right_db/20)*np.sin(2*np.pi*RIGHT*t)*np.minimum(1,np.minimum(t,seconds-t)/0.05)
    pcm=(np.stack([l,r],1)*32767).astype('<i2')
    with wave.open(str(path),'wb') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(rate);w.writeframes(pcm.tobytes())

def band_level(seg,rate,f,band=40.0):
    """RMS level (dBFS) of the tone at f within one window: a Hann window keeps a
    loud tone on the same jack from leaking into a quiet one's band."""
    w=np.hanning(len(seg));spec=np.fft.rfft(seg*w);freq=np.fft.rfftfreq(len(seg),1/rate)
    rms=float(np.sqrt(2*np.sum(np.abs(spec[np.abs(freq-f)<=band])**2))/np.sum(w))
    return round(float(20*np.log10(rms)),1) if rms>0 else None

def analyze(path,window=0.05):
    """Per window: the 1 kHz level on jack 1 and the 1.5 kHz level on jack 2;
    then the right level with the left bursts on versus off."""
    x,rate=load(path);n=int(window*rate);count=len(x)//n
    left=[band_level(x[k*n:(k+1)*n,0],rate,LEFT) for k in range(count)]
    right=[band_level(x[k*n:(k+1)*n,1],rate,RIGHT) for k in range(count)]
    valid=[k for k in range(count) if left[k] is not None and right[k] is not None]
    lo,hi=min(left[k] for k in valid),max(left[k] for k in valid)
    on=[k for k in valid if left[k]>(lo+hi)/2];off=[k for k in valid if left[k]<=(lo+hi)/2]
    # Skip the first and last window of each run (the fades); for the off
    # windows also the first half second after a burst (the limiter's release).
    on=[k for k in on if k-1 in on and k+1 in on]
    off=[k for k in off if min(on)<k<max(on) and k+1 in off and all(k-i in off for i in range(1,int(0.5/window)+1))]   # between bursts, settled
    med=lambda ks,s:round(float(np.median([s[k] for k in ks])),1) if ks else None
    r_on,r_off=med(on,right),med(off,right)
    return dict(window_seconds=window,windows=count,left_on_windows=len(on),left_off_windows=len(off),
                left_1khz_on_dbfs=med(on,left),left_1khz_off_dbfs=med(off,left),
                right_1500hz_with_left_on_dbfs=r_on,right_1500hz_with_left_off_dbfs=r_off,
                right_dip_db=round(r_off-r_on,1) if r_on is not None and r_off is not None else None,
                series=dict(left_1khz=left,right_1500hz=right))

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=10);p.add_argument('--burst',type=float,default=1.0)
    p.add_argument('--left-level',type=float,default=-6);p.add_argument('--right-level',type=float,default=-40)
    p.add_argument('--interface',default='Elektron Syntakt');p.add_argument('--mixer',default='L6')
    p.add_argument('--analyze',type=Path,help='only analyze this recording')
    a=p.parse_args()
    if a.analyze:print(json.dumps(analyze(a.analyze),indent=1));return
    a.output.parent.mkdir(parents=True,exist_ok=True)
    targets=play_devices();mixer=[i for name,i in targets.items() if a.mixer in name]
    if len(mixer)!=1:raise SystemExit(f'cannot identify the mixer output among {targets}')
    source=devices().get(a.interface)
    if source is None:raise SystemExit(f'no input named {a.interface!r}')
    with tempfile.TemporaryDirectory() as tmp:
        tones=Path(tmp)/'tones.wav';signal_file(tones,a.seconds,a.left_level,a.right_level,a.burst)
        rec=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','avfoundation','-i',f':{source}',
                              '-t',str(a.seconds+1),'-ac','2','-ar','48000','-c:a','pcm_s24le',str(a.output)])
        time.sleep(0.3)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-re','-i',str(tones),'-f','audiotoolbox',
                        '-audio_device_index',str(mixer[0]),'-'],check=True)
        rec.wait()
    result=analyze(a.output)
    print(json.dumps(dict(signal=f'left 1 kHz bursts of {a.burst} s at {a.left_level} dBFS, right steady 1.5 kHz at {a.right_level} dBFS',
                          recording=str(a.output),**{k:v for k,v in result.items() if k!='series'}),indent=1))
if __name__=='__main__':main()
