#!/usr/bin/env python3
"""Open a take, and everything it contains, in REAPER.

  import_take.py /Volumes/L6_SD/RECORDER/261015_204724
  import_take.py /Volumes/L6_SD/RECORDER/261015_204724 --out ~/Music/song
  import_take.py /Volumes/L6_SD 261015_204724 --link
  import_take.py /Volumes/L6_SD --list 5              the last five takes, nothing else

import.sh, next to this script, asks which take and what to call the project.

Reads the take's HISTORY.TXT, follows it to every earlier take and pad sound
it lists, and theirs, and makes a project folder named after the take. The
folder gets a copy of every file (with --link, REAPER plays them from the
card instead) and a project <take>.RPP (--name picks another name) with:
- on top, the take's own MASTER.WAV, muted: the mix as you heard it;
- then a folder for each take, newest first, with its track files, its
  MASTER.WAV (muted) and any pad sound it played that is not a take;
- every file placed where it sounded in the final take.

The placement is measured, not assumed. A pad starts some time after REC, so
each earlier take's master is looked for in the master of the take that
played it (cross-correlation, to the sample; needs NumPy). Without NumPy, or
when no clear match is found, the files start at 0 and the report says so.
The report is printed and kept in the project's notes (REAPER: View, Project
Notes).

What it cannot do. A take recorded before this firmware has no HISTORY.TXT,
so what it played is unknown. A take folder that was deleted cannot be
imported. Both are reported. The levels you heard are not recovered: the
track files are the dry inputs, and the mixer does not record fader, knob or
pad levels. A take that was played twice at different times is placed once.
Only the first file of a take long enough to be split is searched, so what
sounded later in such a take is reported as not found.
"""
import argparse,math,re,shutil,struct,sys,time
from pathlib import Path
try:import numpy as np
except ImportError:np=None

FILE_RE=re.compile(r'^(MASTER|TRACK0[1-6](?:_ST|_L|_R)?)(?:_(\d\d))?\.WAV$',re.I)
COARSE=64            # samples per step of the coarse search
REFINE=30            # seconds of audio compared at full rate around the coarse match
SEGMENT=0.5          # seconds per segment of that comparison
QUIET=0.01           # a segment under 1% of the loudest segment's energy (-20 dB) is not compared
MIN_AGREE=3          # segments that must agree on the lag, to the sample, and the share of the
MIN_SHARE=0.3        # compared segments they must be (2 October 2026 recordings: a copy 12 of 25
                     # and 20 of 23 with a loud new performance over it; unrelated files 3 of 27 at most)
MAX_CHILD_LOAD=48000*60*20  # a pad sound at another rate is resampled in memory: 20 minutes at most

def fail(message):sys.exit('Stopped: '+message)

# --- the card -----------------------------------------------------------------

class History:
    """One HISTORY.TXT (docs/history-format.md), versions 1 and 2."""
    def __init__(self,path):
        self.entries=[];self.version=None;self.omitted=False;self.truncated=False;self.problems=[]
        lines=path.read_text('utf-8',errors='replace').replace('\r','').split('\n')
        while lines and lines[-1]=='':lines.pop()
        if not lines or not lines[0].startswith('L6 HISTORY '):self.problems.append('HISTORY.TXT is not a history file');return
        try:self.version=int(lines[0][11:])
        except ValueError:self.problems.append('HISTORY.TXT has an unknown version line')
        else:
            if self.version not in (1,2):self.problems.append(f'HISTORY.TXT version {self.version} is unknown, so it was read as version 1')
        count=None
        for line in lines[1:]:
            if line=='OMITTED':self.omitted=True
            elif line=='TRUNCATED':self.truncated=True
            elif line.startswith('END '):
                try:count=int(line[4:])
                except ValueError:self.problems.append('HISTORY.TXT has a bad END line')
            elif line.startswith('SOUND '):self.entries.append(('sound',line[6:]))
            elif line.startswith('RECORDER/'):self.entries.append(('take',line[9:]))
            else:self.problems.append(f'HISTORY.TXT has an unknown line {line!r}')
        if count is None:self.problems.append('HISTORY.TXT has no END line, so it was cut off')
        elif count!=len(self.entries):self.problems.append(f'HISTORY.TXT says {count} entries but lists {len(self.entries)}')
        if self.truncated:self.problems.append('HISTORY.TXT is marked TRUNCATED: the list is incomplete')

class Take:
    def __init__(self,card,name):
        self.name=name;self.folder=card/'RECORDER'/name;self.history=None;self.files={};self.problems=[]
        if not self.folder.is_dir():self.folder=None;self.problems.append('folder not on the card');return
        hist=self.folder/'HISTORY.TXT'
        if hist.is_file():self.history=History(hist);self.problems+=self.history.problems
        else:self.problems.append('no HISTORY.TXT (recorded before this firmware), so what it played is unknown')
        for p in sorted(self.folder.iterdir()):
            m=FILE_RE.match(p.name)
            if m:self.files.setdefault(m.group(1).upper(),[]).append(p)
            elif p.suffix.upper()=='.WAV':self.problems.append(f'{p.name} is not a recorder file and was left out')
        if not self.files:self.problems.append('no recorder files in the folder')
        elif 'MASTER' not in self.files:self.problems.append('no MASTER.WAV, so what sounded in it cannot be placed')
    @property
    def master(self):return self.files.get('MASTER',[None])[0]
    @property
    def streams(self):return sorted(s for s in self.files if s!='MASTER')+(['MASTER'] if 'MASTER' in self.files else [])

class Sound:
    def __init__(self,card,rel):
        self.rel=rel;self.path=card/Path(*rel.split('/'));self.problems=[]
        if not self.path.is_file():self.path=None;self.problems.append('not on the card')

def collect(card,root):
    """Every take reachable from the root's history, newest first, and every pad sound."""
    takes={};order=[];sounds={};queue=[root]
    while queue:
        name=queue.pop(0)
        if name in takes:continue
        take=Take(card,name);takes[name]=take;order.append(name)
        for kind,ref in (take.history.entries if take.history else []):
            if kind=='take':queue.append(ref)
            elif ref not in sounds:sounds[ref]=Sound(card,ref)
    return takes,order,sounds

def assign_parents(takes,order):
    """For each entry, the take whose master it sounds in. In a version 2 list the
    pad files a take played come first and an earlier take's inherited entries
    follow that take; in version 1 the inherited entries precede it."""
    parent={}
    for x in order:
        hist=takes[x].history
        if not hist:continue
        ents=hist.entries
        for i,key in enumerate(ents):
            if key in parent or key==('take',x):continue
            holder=None
            for j,other in enumerate(ents):
                if other[0]!='take' or other==key or (hist.version==2 and j>i):continue
                y=takes.get(other[1])
                if y and y.history and key in y.history.entries:holder=other[1];break
            parent[key]=holder or x
    return parent

# --- audio ----------------------------------------------------------------------

class Info:
    def __init__(self,path):
        self.path=path;size=path.stat().st_size;fmt=None;pos=12
        with open(path,'rb') as f:
            head=f.read(12)
            if len(head)<12 or head[:4]!=b'RIFF' or head[8:12]!=b'WAVE':raise ValueError('not a WAV file')
            while True:
                f.seek(pos);h=f.read(8)
                if len(h)<8:break
                cid,n=h[:4],struct.unpack('<I',h[4:])[0]
                if cid==b'fmt ':
                    v=f.read(min(n,40))
                    if len(v)<16:raise ValueError('bad fmt chunk')
                    tag,ch,rate,_,align,bits=struct.unpack_from('<HHIIHH',v)
                    if tag==0xFFFE and len(v)>=26:tag=struct.unpack_from('<H',v,24)[0]
                    fmt=(tag,ch,rate,align,bits)
                elif cid==b'data':
                    if not fmt:raise ValueError('data chunk before fmt chunk')
                    self.tag,self.channels,self.rate,self.align,self.bits=fmt
                    if not self.align or not self.rate:raise ValueError('bad fmt chunk')
                    self.data=pos+8;self.frames=min(n,size-self.data)//self.align;return
                pos+=8+n+(n&1)
        raise ValueError('no data chunk')
    @property
    def seconds(self):return self.frames/self.rate

def decode(raw,info):
    tag,ch,bits=info.tag,info.channels,info.bits
    if tag==3 and bits==32:a=np.frombuffer(raw,'<f4')
    elif tag==3 and bits==64:a=np.frombuffer(raw,'<f8')
    elif tag==1 and bits==16:a=np.frombuffer(raw,'<i2')/32768.0
    elif tag==1 and bits==24:
        b=np.frombuffer(raw,np.uint8).reshape(-1,3).astype(np.int32)
        a=(b[:,0]|(b[:,1]<<8)|(b[:,2].astype(np.int8).astype(np.int32)<<16))/8388608.0
    elif tag==1 and bits==32:a=np.frombuffer(raw,'<i4')/2147483648.0
    elif tag==1 and bits==8:a=(np.frombuffer(raw,np.uint8).astype(np.float32)-128)/128
    else:raise ValueError(f'WAV format {tag}, {bits}-bit, is not supported')
    if ch>1:a=a.reshape(-1,ch).mean(axis=1)
    return a.astype(np.float32)

class Audio:
    """Mono samples of a file at the project rate, read in pieces (a take can be
    an hour long) unless the file needs resampling, when it is read whole."""
    def __init__(self,info,rate):
        self.info=info;self.rate=rate;self.whole=None
        if info.rate!=rate:
            if info.frames>MAX_CHILD_LOAD:raise ValueError(f'{info.rate} Hz and too long to resample')
            x=self.read(0,info.frames);m=int(round(len(x)*rate/info.rate))
            self.whole=np.interp(np.arange(m)*(info.rate/rate),np.arange(len(x)),x).astype(np.float32)
        self.frames=len(self.whole) if self.whole is not None else info.frames
    def read(self,start,n):
        start=max(0,start);n=max(0,min(n,self.info.frames-start))
        with open(self.info.path,'rb') as f:f.seek(self.info.data+start*self.info.align);raw=f.read(n*self.info.align)
        return decode(raw[:len(raw)//self.info.align*self.info.align],self.info)
    def window(self,start,n):
        if self.whole is not None:start=max(0,start);return self.whole[start:start+n]
        return self.read(start,n)
    def coarse(self):
        if self.whole is not None:x=self.whole;return x[:len(x)//COARSE*COARSE].reshape(-1,COARSE).mean(axis=1)
        out=[];chunk=1<<20
        for start in range(0,self.frames,chunk):
            x=self.read(start,chunk);x=x[:len(x)//COARSE*COARSE]
            if len(x):out.append(x.reshape(-1,COARSE).mean(axis=1))
        return np.concatenate(out) if out else np.zeros(0,np.float32)

def find_lag(parent,child):
    """Where the child sounds in the parent: (lag in samples, score, segments that
    agree, segments compared). A negative lag means the child was already playing
    when the parent's recording began. The coarse search correlates both files at
    750 Hz and scores the peak against the correlation's RMS. The fine search then
    takes half-second segments of the first 30 s of overlap, and for each one the
    lag within two coarse steps that explains it best (least squares, a gain
    allowed). A copy makes the segments agree on one lag, to the sample; a note
    held at the same pitch in both files fits one segment well but at a lag of
    its own, so the segments' vote is the answer and their agreement the proof."""
    p,c=parent.coarse(),child.coarse()
    if len(p)<2 or len(c)<2:return None
    n=1<<(len(p)+len(c)-1).bit_length()
    corr=np.fft.irfft(np.fft.rfft(p,n)*np.conj(np.fft.rfft(c,n)),n)
    vals=np.concatenate([corr[:len(p)],corr[n-(len(c)-1):]]);lags=np.concatenate([np.arange(len(p)),np.arange(-(len(c)-1),0)])
    i=int(np.argmax(vals));rms=math.sqrt(float(np.mean(vals*vals)))
    score=float(vals[i])/rms if rms>0 else 0.0;d0=int(lags[i])*COARSE;span=2*COARSE
    seg=int(SEGMENT*parent.rate);cs=max(0,span-d0)
    m=min(REFINE*parent.rate,parent.frames-(cs+d0+span),child.frames-cs)//seg*seg
    if m<=0:return d0,score,0,0
    P=parent.window(cs+d0-span,m+2*span);C=child.window(cs,m)
    if len(P)<m+2*span or len(C)<m:return d0,score,0,0
    C2=C.reshape(-1,seg);C2=C2-C2.mean(axis=1,keepdims=True);cc=(C2*C2).sum(axis=1)
    loud=(cc>0)&(cc>=cc.max()*QUIET)   # a near-silent segment of the child says nothing; a silent one is no vote
    if not loud.any():return d0,score,0,0
    F=np.zeros((int(loud.sum()),2*span+1),np.float32);C2=C2[loud];cc=cc[loud]
    for k in range(2*span+1):
        Pk=P[k:k+m].reshape(-1,seg)[loud];Pk=Pk-Pk.mean(axis=1,keepdims=True);pp=(Pk*Pk).sum(axis=1);pc=(Pk*C2).sum(axis=1)
        ok=pp>0;F[:,k]=np.where(ok,pc*np.abs(pc)/np.where(ok,pp*cc,1),0.0)   # signed r-squared: a phase-inverted copy counts against
    F=F[F.max(axis=1)>0]   # a segment that fits nowhere (the parent silent there) is no vote either
    if not len(F):return d0,score,0,0
    best=F.argmax(axis=1);votes=np.bincount(best,minlength=F.shape[1]).astype(np.float64)
    votes+=np.array([F[best==k,k].sum() for k in range(F.shape[1])])/(len(F)+1)   # ties: the better fits
    k=int(np.argmax(votes))
    return d0-span+k,score,int(np.sum(best==k)),len(F)

# --- the project ----------------------------------------------------------------

def q(s):return '"'+s.replace('"',"'")+'"'

def item(path,ref,pos,rate,name,say=print):
    """An RPP item for one file at pos (seconds, may be negative). Returns (text, seconds it ends at).
    A file that does not open, or is empty, is left out and reported, and takes no time."""
    try:length=Info(path).seconds
    except (OSError,ValueError) as e:say(f'{name}: left out ({e})');return None,pos
    if length<=0:say(f'{name}: left out (no audio in the file)');return None,pos
    end=pos+length;soffs=0.0
    if pos<0:soffs=-pos;length=end;pos=0.0
    if length<=0:return None,end   # ends before the project starts
    text=f'    <ITEM\n      POSITION {pos:.9f}\n      LENGTH {length:.9f}\n      SOFFS {soffs:.9f}\n      NAME {q(name)}\n      <SOURCE WAVE\n        FILE {q(ref)}\n      >\n    >\n'
    return text,end

def stream_items(take,stream,pos,rate,ref_of,say=print):
    """The segments of one stream, end to end from pos."""
    items=[]
    for seg in take.files[stream]:
        t,pos=item(seg,ref_of(seg),pos,rate,seg.name,lambda line:say(f'{take.name}/{line}'))
        if t:items.append(t)
    return items

def track(name,items,isbus='0 0',mute=False):
    return f'  <TRACK\n    NAME {q(name)}\n    MUTESOLO {int(mute)} 0 0\n    ISBUS {isbus}\n'+''.join(items)+'  >\n'

def write_project(out,root,project,takes,order,sounds,parent,offsets,rate,notes,ref_of,bpm,say=print):
    """Writes <out>/<project>.RPP; say() takes each note about a file left out (also added to notes)."""
    tracks=[];rt=takes[root]
    if rt.master:tracks.append(track(f'{root} MASTER: the mix as heard',stream_items(rt,'MASTER',0.0,rate,ref_of,say),mute=True))
    played={}
    for key,p in parent.items():
        if key[0]=='sound':played.setdefault(p,[]).append(key[1])
    for name in order:
        take=takes[name];children=[]
        for stream in take.streams:children.append((stream,stream_items(take,stream,offsets.get(('take',name),0)/rate,rate,ref_of,say),stream=='MASTER'))
        for rel in played.get(name,[]):
            s=sounds[rel]
            if not s.path:continue
            t,_=item(s.path,ref_of(s.path),offsets.get(('sound',rel),0)/rate,rate,Path(rel).name,say)
            children.append((Path(rel).name,[t] if t else [],False))
        if not children:tracks.append(track(f'{name} ({"; ".join(take.problems) or "nothing to show"})',[]));continue
        tracks.append(track(name,[],isbus='1 1'))
        for i,(label,items,mute) in enumerate(children):
            tracks.append(track(label,items,isbus='2 -1' if i==len(children)-1 else '0 0',mute=mute))
    text=f'<REAPER_PROJECT 0.1 "7.0" {int(time.time())}\n  <NOTES 0 2\n'+''.join(f'    |{line}\n' for line in notes)+f'  >\n  RIPPLE 0\n  SAMPLERATE {rate} 0 0\n  TEMPO {bpm:g} 4 4\n'+''.join(tracks)+'>\n'
    (out/f'{project}.RPP').write_text(text)

# --- main -----------------------------------------------------------------------

def list_takes(card,n):
    """The last n takes on the card, newest first, one line each: the folder name,
    then its date and time, length, file count and whether it has a history."""
    rec=card/'RECORDER'
    if not rec.is_dir():fail(f'{card} has no RECORDER folder')
    names=sorted((p.name for p in rec.iterdir() if p.is_dir()),reverse=True)[:n]
    for name in names:
        take=Take(card,name);m=re.match(r'^(\d\d)(\d\d)(\d\d)_(\d\d)(\d\d)(\d\d)$',name)
        when=f'20{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}' if m else '' 
        try:secs=sum(Info(seg).seconds for seg in take.files['MASTER']) if take.master else None   # every segment of a split take
        except (OSError,ValueError):secs=None
        length=f'{int(secs//60)}:{int(secs%60):02d}' if secs is not None else '?:??'
        files=sum(len(v) for v in take.files.values())
        hist='no history' if not take.history else f'history: {len(take.history.entries)} entr'+('y' if len(take.history.entries)==1 else 'ies') if take.history.entries else 'history: nothing played'
        print(f'{name}  {when}  {length:>6}  {files} files  {hist}')

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('where',nargs='+',metavar='TAKE',help='the take folder on the card, or the card and the take name')
    ap.add_argument('--out',type=Path,help='the project folder (default: a folder named after the take, here)')
    ap.add_argument('--link',action='store_true',help='do not copy: the project plays the files from the card')
    ap.add_argument('--no-align',action='store_true',help='place every file at 0 instead of measuring')
    ap.add_argument('--force',action='store_true',help='replace an existing project file')
    ap.add_argument('--name',help='the project file name (default: the take name)')
    ap.add_argument('--bpm',type=float,default=120.0,help='the project tempo (default 120; the files are placed in seconds, so the tempo moves nothing)')
    ap.add_argument('--list',type=int,metavar='N',help='print the last N takes on the card (give the card alone) and stop')
    a=ap.parse_args()
    if a.list:
        if len(a.where)!=1:ap.error('--list takes the card alone')
        list_takes(Path(a.where[0]).resolve(),a.list);return
    if len(a.where)==1:folder=Path(a.where[0]).resolve();root=folder.name;card=folder.parent.parent
    elif len(a.where)==2:card=Path(a.where[0]).resolve();root=a.where[1];folder=card/'RECORDER'/root
    else:ap.error('give a take folder, or a card and a take name')
    if not folder.is_dir():fail(f'{folder} is not a folder')
    if folder.parent.name.upper()!='RECORDER':fail(f'{folder} is not inside a RECORDER folder')
    out=(a.out or Path(root)).resolve();project=a.name or root
    if '/' in project or not project:fail('the project name cannot be empty or contain /')
    if not 1<=a.bpm<=960:fail('the tempo must be between 1 and 960 BPM')
    if (out/f'{project}.RPP').exists() and not a.force:fail(f'{out/(project+".RPP")} exists; add --force to replace it')
    if a.link and out==card:fail('the project folder cannot be the card')

    takes,order,sounds=collect(card,root);parent=assign_parents(takes,order)
    rate=48000
    if takes[root].master:
        try:rate=Info(takes[root].master).rate
        except (OSError,ValueError):pass
    notes=[];offsets={('take',root):0}
    def say(line):notes.append(line);print(line)
    say(f'{root}: imported from {card} on {time.strftime("%Y-%m-%d %H:%M")} by import_take.py')
    for name in order:
        for p in takes[name].problems:say(f'{name}: {p}')
    for rel,s in sounds.items():
        for p in s.problems:say(f'{rel}: {p}')

    # Placement: each entry against the master of the take it sounds in, parents first.
    audio={};visiting=set()
    def get_audio(path):
        if path not in audio:audio[path]=Audio(Info(path),rate)
        return audio[path]
    def place(key):
        if key in offsets:return offsets[key]
        if key in visiting:say(f'{key[1]}: its history loops back on itself; placed at 0');return 0
        visiting.add(key);p=parent[key];base=place(('take',p));lag=0;kind,ref=key
        child=takes[ref].master if kind=='take' else sounds[ref].path
        pm=takes[p].master;label=ref if kind=='take' else Path(ref).name
        if child is None:pass
        elif pm is None:say(f'{label}: placed at 0 in {p} ({p} has no MASTER.WAV to measure against)')
        elif a.no_align:pass
        elif np is None:say(f'{label}: placed at 0 in {p} (NumPy is not installed, so nothing was measured)')
        else:
            try:found=find_lag(get_audio(pm),get_audio(child))
            except (OSError,ValueError) as e:found=None;say(f'{label}: placed at 0 in {p} ({e})')
            if found:
                d,score,agree,total=found
                if agree>=MIN_AGREE and agree>=total*MIN_SHARE:lag=d;say(f'{label}: starts {d/rate:+.3f} s into {p} ({d:+d} samples; {agree} of {total} segments agree, match {score:.0f}x)')
                else:say(f'{label}: placed at 0 in {p} (no clear match: {agree} of {total} segments agree, {score:.1f}x)')
        offsets[key]=base+lag;return offsets[key]
    for key in parent:place(key)
    if a.no_align:say('placed every file at 0 (--no-align)')
    elif np is None:say('NumPy is not installed, so every file starts at 0')

    out.mkdir(parents=True,exist_ok=True);copied=0;size=0
    def ref_of(path):
        nonlocal copied,size
        if a.link:return str(path)
        rel=path.relative_to(card);dest=out/rel
        if not dest.exists() or dest.stat().st_size!=path.stat().st_size:
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest);copied+=1;size+=path.stat().st_size
        return rel.as_posix()
    for name in order:
        take=takes[name]
        if take.history:ref_of(take.folder/'HISTORY.TXT')
    write_project(out,root,project,takes,order,sounds,parent,offsets,rate,notes,ref_of,a.bpm,say)
    present=[n for n in order if takes[n].folder];print(f'{len(present)} take(s), {sum(1 for s in sounds.values() if s.path)} pad sound(s)'+(f', {copied} file(s) copied ({size/1e6:.0f} MB)' if not a.link else ', played from the card'))
    print(f'project: {out/(project+".RPP")}')

if __name__=='__main__':main()
