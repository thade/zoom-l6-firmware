#!/usr/bin/env python3
"""Play test tones into the L6 over USB and measure the two AUX jacks.

USB playback from the computer reaches the mixer's USB-assigned input (input 5
on the test setup); AUX 1 and AUX 2 go to a two-input interface. The tool
plays a stereo signal with a distinct tone on each side (left 1 kHz, right
1.5 kHz; or the same 1 kHz on both with --mono), records the interface at the
same time, and reports for each jack the level of each tone (dBFS), plus the
analysis of l6_aux_measure (balance, correlation, delay). Sends nothing to
the mixer but audio.

  l6_aux_tone_test.py --output deployment/30_stereo_aux/tones-centre.wav
"""
import argparse,json,subprocess,tempfile,time,wave
from pathlib import Path
import numpy as np
from l6_aux_measure import devices,analyze,load

LEFT,RIGHT=1000.0,1500.0   # above the input low cut

def play_devices():
    out=subprocess.run(['ffmpeg','-hide_banner','-f','lavfi','-i','anullsrc','-t','0.1','-f','audiotoolbox',
                        '-list_devices','true','-'],capture_output=True,text=True).stderr
    found={}
    for line in out.splitlines():
        if '] [' in line and 'AppleUSBAudioEngine' in line or 'BuiltIn' in line:
            idx=line.split('] [',1)[1].split(']',1)[0]
            if idx.isdigit():found[line.split(']',2)[-1].strip()]=int(idx)
    return found

def tone_file(path,seconds,mono,level_db,rate=48000):
    t=np.arange(int(seconds*rate))/rate;a=10**(level_db/20)
    fade=np.minimum(1,np.minimum(t,seconds-t)/0.05)
    l=a*np.sin(2*np.pi*LEFT*t)*fade;r=a*np.sin(2*np.pi*(LEFT if mono else RIGHT)*t)*fade
    pcm=(np.stack([l,r],1)*32767).astype('<i2')
    with wave.open(str(path),'wb') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(rate);w.writeframes(pcm.tobytes())

def tone_levels(path,band=25.0):
    """RMS level (dBFS) of each tone per jack: the energy within +/-band Hz of
    it (robust to a tone arriving slightly spread or shifted)."""
    x,rate=load(path);seg=x[int(0.5*rate):len(x)-int(0.5*rate)]
    spec=np.fft.rfft(seg,axis=0);freq=np.fft.rfftfreq(len(seg),1/rate)
    out={}
    for side,name in ((0,'aux1'),(1,'aux2')):
        out[name]={}
        for f in (LEFT,RIGHT):
            mask=np.abs(freq-f)<=band
            rms=float(np.sqrt(2*np.sum(np.abs(spec[mask,side])**2))/len(seg))
            out[name][f'{int(f)}_hz_dbfs']=round(float(20*np.log10(rms)),1) if rms>0 else None
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--mono',action='store_true')
    p.add_argument('--seconds',type=float,default=4);p.add_argument('--level',type=float,default=-12)
    p.add_argument('--interface',default='Elektron Syntakt');p.add_argument('--mixer',default='L6')
    a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
    targets=play_devices();mixer=[i for name,i in targets.items() if a.mixer in name]
    if len(mixer)!=1:raise SystemExit(f'cannot identify the mixer output among {targets}')
    source=devices().get(a.interface)
    if source is None:raise SystemExit(f'no input named {a.interface!r}')
    with tempfile.TemporaryDirectory() as tmp:
        tones=Path(tmp)/'tones.wav';tone_file(tones,a.seconds,a.mono,a.level)
        rec=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','avfoundation','-i',f':{source}',
                              '-t',str(a.seconds+1),'-ac','2','-ar','48000','-c:a','pcm_s24le',str(a.output)])
        time.sleep(0.3)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-re','-i',str(tones),'-f','audiotoolbox',
                        '-audio_device_index',str(mixer[0]),'-'],check=True)
        rec.wait()
    print(json.dumps(dict(signal='mono 1 kHz' if a.mono else 'left 1 kHz, right 1.5 kHz',level_dbfs=a.level,
                          tones=tone_levels(a.output),analysis=analyze(a.output)),indent=1))
if __name__=='__main__':main()
