#!/usr/bin/env python3
"""Compare a captured pre-master .TMP with its stock take; local copies only.

Checks the extra file's format and header, that it has exactly as many frames as
the take's MASTER.WAV, and the lag and correlation against MASTER. The stock
master body adds a 48-frame delay at 48 kHz, so the expected lag is 48 frames;
master gain and dynamics lower the correlation but not the lag.
"""
import argparse,json,struct
from pathlib import Path
import numpy as np

def read_wav(path):
    """Float32 PCM WAV reader that tolerates extra chunks (JUNK, bext, ...)."""
    data=Path(path).read_bytes()
    if data[:4]!=b'RIFF' or data[8:12]!=b'WAVE':raise ValueError(f'{path}: not a RIFF/WAVE file')
    if struct.unpack_from('<I',data,4)[0]!=len(data)-8:raise ValueError(f'{path}: RIFF size does not match file')
    offset=12;fmt=None;payload=None
    while offset+8<=len(data):
        tag=data[offset:offset+4];n=struct.unpack_from('<I',data,offset+4)[0];body=offset+8
        if body+n>len(data):raise ValueError(f'{path}: truncated {tag!r} chunk')
        if tag==b'fmt ':fmt=struct.unpack_from('<HHIIHH',data,body)
        elif tag==b'data':payload=(body,n)
        offset=body+n+(n&1)
    if fmt is None or payload is None:raise ValueError(f'{path}: missing fmt or data chunk')
    kind,channels,rate,byte_rate,align,bits=fmt
    if (kind,rate,bits)!=(3,48000,32) or align!=channels*4 or byte_rate!=rate*align:
        raise ValueError(f'{path}: expected 48-kHz 32-bit float, got {fmt}')
    body,n=payload
    if n%align:raise ValueError(f'{path}: data is not whole frames')
    return np.frombuffer(data,dtype='<f4',count=n//4,offset=body).reshape(-1,channels),dict(header_bytes=body)

def loudest(frames,seconds):
    """Start frame of the most energetic window, in whole seconds."""
    energy=np.square(frames[:len(frames)//48000*48000].astype(np.float64)).sum(axis=1).reshape(-1,48000).sum(axis=1)
    if len(energy)<=seconds:return 0
    totals=np.convolve(energy,np.ones(seconds),'valid')
    return int(np.argmax(totals))*48000

def lag(reference,signal,limit=480,seconds=20):
    """Lag of signal behind reference (frames) maximizing normalized correlation,
    estimated over the reference's loudest window."""
    start=loudest(reference,seconds);reference=reference[start:];signal=signal[start:]
    n=min(len(reference),len(signal),seconds*48000)
    x=reference[:n].astype(np.float64).sum(axis=1);y=signal[:n].astype(np.float64).sum(axis=1)
    x-=x.mean();y-=y.mean()
    size=1<<(2*n-1).bit_length()
    cross=np.fft.irfft(np.fft.rfft(y,size)*np.conj(np.fft.rfft(x,size)),size)
    lags=np.r_[np.arange(0,limit+1),np.arange(-limit,0)];values=cross[lags]
    best=int(np.argmax(np.abs(values)));k=int(lags[best])
    a=x[:n-k] if k>=0 else x[-k:];b=y[k:] if k>=0 else y[:n+k]
    norm=np.sqrt(np.sum(a*a)*np.sum(b*b))
    return k,float(np.sum(a*b)/norm) if norm else 0.0

def analyze(extra_path,take_dir,expected_lag=48,tolerance=2,minimum_correlation=.5):
    extra,info=read_wav(extra_path);master,_=read_wav(Path(take_dir)/'MASTER.WAV')
    if info['header_bytes']!=512 or extra.shape[1]!=2:raise ValueError('extra file is not the 512-byte stereo layout')
    result=dict(extra=str(extra_path),take=str(take_dir),extra_frames=len(extra),master_frames=len(master),
        frames_equal=len(extra)==len(master),all_finite=bool(np.isfinite(extra).all()),
        extra_peak=float(np.max(np.abs(extra))) if len(extra) else 0.0)
    stems=sorted(p.name for p in Path(take_dir).glob('*.WAV') if p.name!='MASTER.WAV')
    result['stem_frames']={name:len(read_wav(Path(take_dir)/name)[0]) for name in stems}
    if result['extra_peak']>0:
        k,c=lag(extra,master)
        result.update(lag_frames=k,correlation=c,lag_as_expected=abs(k-expected_lag)<=tolerance,
                      correlated=abs(c)>=minimum_correlation)
    result['passed']=result['frames_equal'] and result['all_finite'] and result.get('lag_as_expected',False) \
        and result.get('correlated',False) \
        and all(n==len(master) for n in result['stem_frames'].values())
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('extra',type=Path,help='Local copy of SOUND_PAD/PAD1/OD_<serial>.TMP')
    p.add_argument('take',type=Path,help='Local copy of the take folder containing MASTER.WAV')
    p.add_argument('--expected-lag',type=int,default=48)
    a=p.parse_args();print(json.dumps(analyze(a.extra,a.take,a.expected_lag),indent=2))
if __name__=='__main__':main()
