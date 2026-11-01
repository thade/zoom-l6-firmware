#!/usr/bin/env python3
"""tools/reaper/import_take.py on a made-up card: three generations of takes
with known offsets (one pad already playing when REC was pressed, so a
negative one), a pad sound at 44.1 kHz 16-bit, a split root take, a version 1
history, a take recorded before the firmware (no HISTORY.TXT) and a take
whose folder is gone. Checks the project's tracks, items and positions, the
copied files, --link, --no-align and the refusal to overwrite. With the
2 October 2026 recordings present (analysis/overdub_test, not in git) also
checks the three offsets measured then, to the sample. Needs NumPy.
"""
import os,re,struct,subprocess,sys,tempfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];TOOL=ROOT/'tools/reaper/import_take.py';RATE=48000
sys.path.insert(0,str(TOOL.parent));import import_take as it

def wav(path,x,rate=RATE,pcm16=False):
    """x: frames x channels float32."""
    x=np.asarray(x,np.float32);x=x.reshape(len(x),-1);ch=x.shape[1]
    if pcm16:data=(np.clip(x,-1,1)*32767).astype('<i2').tobytes();tag,bits=1,16
    else:data=x.astype('<f4').tobytes();tag,bits=3,32
    fmt=struct.pack('<HHIIHH',tag,ch,rate,rate*ch*bits//8,ch*bits//8,bits)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'RIFF'+struct.pack('<I',4+8+len(fmt)+8+len(data))+b'WAVE'+b'fmt '+struct.pack('<I',len(fmt))+fmt+b'data'+struct.pack('<I',len(data))+data)

def mix(base,part,lag,gain):
    """Add part*gain into base starting at frame lag (negative: part started earlier)."""
    out=base.copy();s=max(0,lag);ps=max(0,-lag);n=min(len(out)-s,len(part)-ps)
    if n>0:out[s:s+n]+=gain*part[ps:ps+n]
    return out

def parse(rpp):
    """[(track name, isbus, mute, [(item name, position, length, soffs, file)])]"""
    tracks=[];cur=None;itm=None
    for line in rpp.read_text().splitlines():
        t=line.strip()
        if t=='<TRACK':cur={'items':[]};tracks.append(cur)
        elif t=='<ITEM':itm={};cur['items'].append(itm)
        elif t.startswith('NAME '):(itm if itm is not None else cur)['name']=t[5:].strip('"')
        elif t.startswith('ISBUS '):cur['isbus']=t[6:]
        elif t.startswith('MUTESOLO '):cur['mute']=t.split()[1]=='1'
        elif t.startswith('POSITION '):itm['pos']=float(t[9:])
        elif t.startswith('LENGTH '):itm['len']=float(t[7:])
        elif t.startswith('SOFFS '):itm['soffs']=float(t[6:])
        elif t.startswith('FILE '):itm['file']=t[5:].strip('"');itm=None
    return tracks

def run(*args,ok=True):
    r=subprocess.run([sys.executable,str(TOOL),*map(str,args)],capture_output=True,text=True)
    assert (r.returncode==0)==ok,(args,r.stdout,r.stderr)
    return r.stdout+r.stderr

def close(a,b,tol=1e-6):assert abs(a-b)<=tol,(a,b)

def made_up_card(card):
    rng=np.random.default_rng(1);noise=lambda n,ch=2:rng.standard_normal((n,ch)).astype(np.float32)*0.1
    rec=card/'RECORDER'
    for n in range(1,5):(card/'SOUND_PAD'/f'PAD{n}').mkdir(parents=True)   # an L6 card has the four pad folders
    # T0: recorded before the firmware, 5 s, no history.
    t0=noise(5*RATE);wav(rec/'261001_100000/MASTER.WAV',t0);wav(rec/'261001_100000/TRACK01.WAV',t0[:,:1])
    # A pad sound at 44.1 kHz, 16-bit, mono, 2 s.
    s=rng.standard_normal(2*44100).astype(np.float32)*0.3;wav(card/'SOUND_PAD/PAD2/LOOP.WAV',s[:,None],44100,pcm16=True)
    s48=np.interp(np.arange(int(round(len(s)*RATE/44100)))*(44100/RATE),np.arange(len(s)),s).astype(np.float32)[:,None]*[1,1]
    # T1: 8 s, played T0 at +12345 and the pad at +30000; version 1 history.
    t1=mix(mix(noise(8*RATE),t0,12345,0.5),s48,30000,0.3)
    wav(rec/'261001_110000/MASTER.WAV',t1);wav(rec/'261001_110000/TRACK01.WAV',t1[:,:1]);wav(rec/'261001_110000/TRACK03_ST.WAV',noise(8*RATE))
    (rec/'261001_110000/HISTORY.TXT').write_text('L6 HISTORY 1\nRECORDER/261001_100000\nSOUND SOUND_PAD/PAD2/LOOP.WAV\nEND 2\n')
    # T2, the root: 8 s split 6 + 2, played T1 which was already 4000 frames in when REC was pressed; version 2 history
    # listing a take whose folder is gone, then T1, then T1's inherited entries.
    t2=mix(noise(8*RATE),t1,-4000,0.7)
    wav(rec/'261001_120000/MASTER.WAV',t2[:6*RATE]);wav(rec/'261001_120000/MASTER_01.WAV',t2[6*RATE:])
    wav(rec/'261001_120000/TRACK01.WAV',t2[:6*RATE,:1]);wav(rec/'261001_120000/TRACK01_01.WAV',t2[6*RATE:,:1])
    (rec/'261001_120000/HISTORY.TXT').write_text('L6 HISTORY 2\nRECORDER/261001_090000\nRECORDER/261001_110000\nRECORDER/261001_100000\nSOUND SOUND_PAD/PAD2/LOOP.WAV\nEND 4\n')

def check_made_up(tmp):
    card=tmp/'card';made_up_card(card);out=tmp/'song'
    text=run(card/'RECORDER/261001_120000','--out',out)
    assert '261001_090000: folder not on the card' in text,text
    assert '261001_100000: no HISTORY.TXT' in text,text
    assert '261001_110000: starts -0.083 s into 261001_120000 (-4000 samples' in text,text
    assert '261001_100000: starts +0.257 s into 261001_110000 (+12345 samples' in text,text
    assert 'LOOP.WAV: starts +0.625 s into 261001_110000 (+30000 samples' in text,text
    rpp=out/'261001_120000.RPP';tracks=parse(rpp);names=[t['name'] for t in tracks]
    assert names==['261001_120000 MASTER: the mix as heard','261001_120000','TRACK01','MASTER',
        '261001_090000 (folder not on the card)','261001_110000','TRACK01','TRACK03_ST','MASTER','LOOP.WAV',
        '261001_100000','TRACK01','MASTER'],names
    assert [t['isbus'] for t in tracks]==['0 0','1 1','0 0','2 -1','0 0','1 1','0 0','0 0','0 0','2 -1','1 1','0 0','2 -1']
    assert [t['mute'] for t in tracks]==[True,False,False,True,False,False,False,False,True,False,False,False,True]
    top=tracks[0]['items'];assert [i['file'] for i in top]==['RECORDER/261001_120000/MASTER.WAV','RECORDER/261001_120000/MASTER_01.WAV']
    close(top[0]['pos'],0);close(top[0]['len'],6);close(top[1]['pos'],6);close(top[1]['len'],2)
    seg=tracks[2]['items'];assert [i['name'] for i in seg]==['TRACK01.WAV','TRACK01_01.WAV'];close(seg[1]['pos'],6)
    for t in tracks[6:9]:   # T1 started 4000 frames before the root: trimmed at 0
        i=t['items'][0];close(i['pos'],0);close(i['soffs'],4000/RATE);close(i['len'],8-4000/RATE)
    loop=tracks[9]['items'][0];close(loop['pos'],(30000-4000)/RATE);close(loop['len'],2);assert loop['file']=='SOUND_PAD/PAD2/LOOP.WAV'
    for t in tracks[11:13]:close(t['items'][0]['pos'],(12345-4000)/RATE)
    notes=[l.strip()[1:] for l in rpp.read_text().splitlines() if l.strip().startswith('|')]
    assert any('folder not on the card' in n for n in notes) and any('+12345 samples' in n for n in notes),notes
    copied=sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.suffix!='.RPP')
    assert copied==['RECORDER/261001_100000/MASTER.WAV','RECORDER/261001_100000/TRACK01.WAV','RECORDER/261001_110000/HISTORY.TXT',
        'RECORDER/261001_110000/MASTER.WAV','RECORDER/261001_110000/TRACK01.WAV','RECORDER/261001_110000/TRACK03_ST.WAV',
        'RECORDER/261001_120000/HISTORY.TXT','RECORDER/261001_120000/MASTER.WAV','RECORDER/261001_120000/MASTER_01.WAV',
        'RECORDER/261001_120000/TRACK01.WAV','RECORDER/261001_120000/TRACK01_01.WAV','SOUND_PAD/PAD2/LOOP.WAV'],copied
    for rel in copied:assert (out/rel).read_bytes()==(card/rel).read_bytes()
    # Refuses to overwrite; --force replaces; --link and --no-align; the card and the take name as two arguments.
    assert 'exists; add --force' in run(card/'RECORDER/261001_120000','--out',out,ok=False)
    run(card/'RECORDER/261001_120000','--out',out,'--force')
    text=run(card,'261001_120000','--out',tmp/'linked','--link','--no-align')
    assert 'placed every file at 0 (--no-align)' in text
    linked=parse(tmp/'linked/261001_120000.RPP')
    assert all(i['soffs']==0 and i['pos']==(6 if i['name'].endswith('_01.WAV') else 0) for t in linked for i in t['items'])
    assert all(i['file'].startswith(str(card.resolve())) for t in linked for i in t['items'])   # --link: absolute card paths
    assert not any(p.suffix=='.WAV' for p in (tmp/'linked').rglob('*'))
    # Not a take folder.
    assert 'not inside a RECORDER folder' in run(card/'SOUND_PAD/PAD2',ok=False)
    # --list: newest first, with date, length, files and history; --name.
    listed=run(card,'--list','2').splitlines()
    assert listed==['261001_120000  2026-10-01 12:00    0:08  4 files  history: 4 entries','261001_110000  2026-10-01 11:00    0:08  3 files  history: 2 entries'],listed
    run(card,'261001_120000','--out',tmp/'named','--name','My song')
    assert (tmp/'named/My song.RPP').exists() and parse(tmp/'named/My song.RPP')[0]['name']=='261001_120000 MASTER: the mix as heard'
    assert 'cannot be empty or contain /' in run(card,'261001_120000','--out',tmp/'named','--name','a/b',ok=False)
    assert '  TEMPO 120 4 4\n' in (tmp/'named/My song.RPP').read_text()
    run(card,'261001_120000','--out',tmp/'named','--name','My song','--force','--bpm','93.5');assert '  TEMPO 93.5 4 4\n' in (tmp/'named/My song.RPP').read_text()
    assert 'between 1 and 960' in run(card,'261001_120000','--out',tmp/'named','--force','--bpm','0',ok=False)
    print('made-up card: 3 generations placed to the sample, split root, 44.1 kHz pad, version 1 history, missing folder and history, copy/link/no-align/force, list, name')
    # A second card for what must be reported rather than guessed: a played take whose master is silent, a take
    # without MASTER.WAV holding another, damaged and empty files, a short fmt chunk, an unknown history version.
    card2=tmp/'card2';rec2=card2/'RECORDER';rng=np.random.default_rng(2);noise=lambda n:rng.standard_normal((n,2)).astype(np.float32)*0.1
    for n in range(1,5):(card2/'SOUND_PAD'/f'PAD{n}').mkdir(parents=True)
    p0=noise(6*RATE);wav(rec2/'261002_100000/MASTER.WAV',p0);wav(rec2/'261002_100000/TRACK01.WAV',p0[:,:1])
    wav(rec2/'261002_090000/TRACK01.WAV',noise(6*RATE)[:,:1])   # no MASTER.WAV; played P
    (rec2/'261002_090000/HISTORY.TXT').write_text('L6 HISTORY 1\nRECORDER/261002_100000\nEND 1\n')
    wav(rec2/'261002_110000/MASTER.WAV',np.zeros((6*RATE,2),np.float32));wav(rec2/'261002_110000/TRACK01.WAV',noise(6*RATE)[:,:1])   # silent master
    (rec2/'261002_110000/HISTORY.TXT').write_text('L6 HISTORY 3\nEND 0\n')
    r2=mix(noise(8*RATE),p0,9000,0.5);wav(rec2/'261002_120000/MASTER.WAV',r2)
    (rec2/'261002_120000/TRACK01.WAV').write_bytes(b'RIFF\x00\x00\x00')   # damaged first segment
    wav(rec2/'261002_120000/TRACK01_01.WAV',r2[:,:1])
    (rec2/'261002_120000/TRACK02.WAV').write_bytes((rec2/'261002_100000/TRACK01.WAV').read_bytes()[:44])   # header only: no audio
    fmt14=struct.pack('<HHIIH',1,1,RATE,RATE*2,2);(rec2/'261002_120000/TRACK03_ST.WAV').write_bytes(b'RIFF'+struct.pack('<I',4+8+14+8)+b'WAVE'+b'fmt '+struct.pack('<I',14)+fmt14+b'data'+struct.pack('<I',0))
    (rec2/'261002_120000/HISTORY.TXT').write_text('L6 HISTORY 2\nRECORDER/261002_110000\nRECORDER/261002_090000\nRECORDER/261002_100000\nEND 3\n')
    text=run(card2,'261002_120000','--out',tmp/'song2')
    assert '261002_110000: placed at 0 in 261002_120000 (no clear match: 0 of 0 segments agree' in text,text   # silence is no evidence
    assert '261002_090000: no MASTER.WAV, so what sounded in it cannot be placed' in text,text
    assert '261002_100000: placed at 0 in 261002_090000 (261002_090000 has no MASTER.WAV to measure against)' in text,text
    assert '261002_110000: HISTORY.TXT version 3 is unknown, so it was read as version 1' in text,text
    assert '261002_120000/TRACK01.WAV: left out (not a WAV file)' in text and '261002_120000/TRACK02.WAV: left out (no audio in the file)' in text,text
    assert '261002_120000/TRACK03_ST.WAV: left out (bad fmt chunk)' in text and 'Traceback' not in text,text
    tracks2=parse(tmp/'song2/261002_120000.RPP');assert [t['name'] for t in tracks2[1:6]]==['261002_120000','TRACK01','TRACK02','TRACK03_ST','MASTER'],[t['name'] for t in tracks2]
    assert [i['name'] for i in tracks2[2]['items']]==['TRACK01_01.WAV'] and tracks2[3]['items']==[] and tracks2[4]['items']==[],tracks2[2:5]
    notes2=[l.strip()[1:] for l in (tmp/'song2/261002_120000.RPP').read_text().splitlines() if l.strip().startswith('|')]
    assert any('TRACK01.WAV: left out' in n for n in notes2) and any('no MASTER.WAV to measure' in n for n in notes2),notes2
    listed2=run(card2,'--list','5');assert listed2.startswith('261002_120000  2026-10-02 12:00    0:08  5 files  history: 3 entries\n'),listed2   # the bad files do not stop the listing
    assert it.item(card/'RECORDER/261001_100000/MASTER.WAV','x',-10.0,RATE,'n',lambda _:None)==(None,-5.0)   # a segment ending before 0 still takes its time
    print('second card: silent master, no master, damaged, empty and short-fmt files, unknown history version: all reported, none guessed')
    # import.sh: the folder and the card as arguments, the answers on stdin (a bad answer first, then take 2, a name).
    r=subprocess.run(['bash',str(TOOL.parent/'import.sh'),str(tmp/'projects'),str(card)],input='x\n2\nTake two\nabc\n88\n',capture_output=True,text=True)
    assert r.returncode==0,(r.stdout,r.stderr)
    assert '  1) 261001_120000 ' in r.stdout and '  2) 261001_110000 ' in r.stdout and '  3) 261001_100000 ' in r.stdout,r.stdout
    assert (tmp/'projects/Take two/Take two.RPP').exists() and (tmp/'projects/Take two/RECORDER/261001_110000/MASTER.WAV').exists()
    assert parse(tmp/'projects/Take two/Take two.RPP')[0]['name']=='261001_110000 MASTER: the mix as heard'
    assert '  TEMPO 88 4 4\n' in (tmp/'projects/Take two/Take two.RPP').read_text()
    r=subprocess.run(['bash',str(TOOL.parent/'import.sh'),str(tmp/'projects'),str(card)],input='1\n\n\n',capture_output=True,text=True)   # the default name and tempo
    assert r.returncode==0 and '  TEMPO 120 4 4\n' in (tmp/'projects/261001_120000/261001_120000.RPP').read_text(),(r.stdout,r.stderr)
    print('import.sh: lists the takes, takes the answers, names the project, sets the tempo')
    # No card mounted: the script enters File Transfer Mode through the helper (a stand-in here, which
    # "mounts" the card), imports, ejects and leaves the mode, in that order. A helper that finds no mixer stops it.
    # The disk query is a stand-in too: in_mode names the card's disk as the mixer does.
    volumes=tmp/'volumes';volumes.mkdir();log=tmp/'transfer.log';helper=tmp/'transfer.py';eject=tmp/'eject.sh';diskinfo=tmp/'diskinfo.sh'
    helper.write_text(f'''import os,sys;log=open({str(log)!r},'a');log.write(sys.argv[1]+'\\n')
if sys.argv[1]=='enter':
    if os.path.exists({str(tmp/'no_answer')!r}):print('{{"mode": "enter", "session": false, "card_mounted": false}}');sys.exit(1)
    os.symlink({str(card)!r},{str(volumes/'L6_SD')!r})
    print('{{"mode": "enter", "already": true, "card_mounted": true}}' if os.path.exists({str(tmp/'enter_already')!r}) else '{{"mode": "enter", "session": true, "card_mounted": true}}')
else:
    print('{{"mode": "exit", "transfer_mode": %s}}'%('null' if os.path.exists({str(tmp/'exit_fails')!r}) else '0'))
    if os.path.exists({str(tmp/'exit_fails')!r}):sys.exit(1)
''')
    eject.write_text(f'#!/bin/sh\necho "eject $1" >> {log}\nrm "{volumes/"L6_SD"}"\n');eject.chmod(0o755)
    diskinfo.write_text(f'''#!/bin/sh
case "$1" in
  disk9) if [ -e "{tmp/'in_mode'}" ]; then echo "   Device / Media Name:       L6 SD R&W"; else echo "   Device / Media Name:       Card Reader"; fi ;;
  *) echo "   Part of Whole:             disk9" ;;
esac
''');diskinfo.chmod(0o755)
    env=dict(os.environ,L6_VOLUMES=str(volumes),L6_TRANSFER_MODE=str(helper),L6_EJECT=str(eject),L6_DISKINFO=str(diskinfo))
    r=subprocess.run(['bash',str(TOOL.parent/'import.sh'),str(tmp/'projects')],input='3\n\n\n',capture_output=True,text=True,env=env)
    assert r.returncode==0 and 'Putting the mixer into File Transfer Mode' in r.stdout and 'Ejecting the card' in r.stdout,(r.stdout,r.stderr)
    assert (tmp/'projects/261001_100000/261001_100000.RPP').exists()
    assert log.read_text()==f'enter\neject {volumes}/L6_SD\nexit\n',log.read_text()
    # Stopped at the first prompt (stdin ends, as Ctrl-C would): the mode is still left.
    log.write_text('');(volumes/'L6_SD').unlink(missing_ok=True)
    r=subprocess.run(['bash',str(TOOL.parent/'import.sh'),str(tmp/'projects')],input='',capture_output=True,text=True,env=env)
    assert r.returncode!=0 and 'Ejecting the card' in r.stdout and log.read_text()==f'enter\neject {volumes}/L6_SD\nexit\n',(r.stdout,r.stderr,log.read_text())
    # The card already mounted from the mixer (its disk named as the mixer names it): the script offers to eject the
    # card and leave the mode when done. Declined, or stopped at the question: left as found. A card in a reader, or
    # the mixer reporting it was in the mode before the script entered it: the same question, or none for the reader.
    told='so this card is mounted from it'   # the question itself is a read prompt, which bash prints only on a terminal
    def mounted(answers,dest,in_mode=True,mount=True,flags=()):
        log.write_text('');(volumes/'L6_SD').unlink(missing_ok=True)
        if mount:os.symlink(card,volumes/'L6_SD')
        for f in ('in_mode','enter_already','exit_fails','no_answer'):(tmp/f).unlink(missing_ok=True)
        for f in (('in_mode',) if in_mode else ())+tuple(flags):(tmp/f).touch()
        return subprocess.run(['bash',str(TOOL.parent/'import.sh'),str(tmp/dest)],input=answers,capture_output=True,text=True,env=env)
    r=mounted('\n3\n\n\n','p_yes')
    assert r.returncode==0 and told in r.stdout and 'Ejecting the card' in r.stdout and not r.stderr,(r.stdout,r.stderr)
    assert (tmp/'p_yes/261001_100000/261001_100000.RPP').exists() and log.read_text()==f'eject {volumes}/L6_SD\nexit\n',log.read_text()
    r=mounted('n\n3\n\n\n','p_no')
    assert r.returncode==0 and 'The card stays mounted' in r.stdout and 'Ejecting the card' not in r.stdout and (tmp/'p_no/261001_100000/261001_100000.RPP').exists(),(r.stdout,r.stderr)
    assert log.read_text()=='' and (volumes/'L6_SD').exists(),log.read_text()
    r=mounted('','p_eof')
    assert r.returncode!=0 and told in r.stdout and 'Ejecting the card' not in r.stdout and log.read_text()=='',(r.stdout,r.stderr)
    r=mounted('3\n\n\n','p_reader',in_mode=False)
    assert r.returncode==0 and told not in r.stdout and log.read_text()=='' and (tmp/'p_reader/261001_100000/261001_100000.RPP').exists(),(r.stdout,r.stderr)
    r=mounted('\n3\n\n\n','p_already',mount=False,flags=('enter_already',))   # entered from the Editor just before: not the script's to leave unasked
    assert r.returncode==0 and 'Putting the mixer' in r.stdout and told in r.stdout and log.read_text()==f'enter\neject {volumes}/L6_SD\nexit\n',(r.stdout,r.stderr,log.read_text())
    r=mounted('n\n3\n\n\n','p_already_no',mount=False,flags=('enter_already',))
    assert r.returncode==0 and 'The card stays mounted' in r.stdout and log.read_text()=='enter\n',(r.stdout,r.stderr,log.read_text())
    r=mounted('\n3\n\n\n','p_exit_fails',flags=('exit_fails',))   # the mixer never confirmed leaving the mode: said so
    assert r.returncode==0 and 'Could not leave File Transfer Mode' in r.stderr and log.read_text()==f'eject {volumes}/L6_SD\nexit\n',(r.stdout,r.stderr)
    r=mounted('','p_no_answer',mount=False,flags=('no_answer',))   # the mixer on USB but silent (the Editor open)
    assert r.returncode==1 and 'The mixer did not answer. Quit ZOOM L6 Editor' in r.stderr and log.read_text()=='enter\n',(r.stdout,r.stderr)
    helper.write_text("import sys;sys.exit('Cannot identify the unique L6 Editor port')")
    r=mounted('','p_no_mixer',mount=False)
    assert r.returncode==1 and 'No mixer found: Cannot identify the unique L6 Editor port' in r.stderr,(r.stdout,r.stderr)
    # A project name starting with a dash reaches the tool as a name.
    r=subprocess.run(['bash',str(TOOL.parent/'import.sh'),str(tmp/'dashed'),str(card)],input='1\n-mix\n\n',capture_output=True,text=True)
    assert r.returncode==0 and (tmp/'dashed/-mix/-mix.RPP').exists(),(r.stdout,r.stderr)
    print('import.sh: enters File Transfer Mode when no card is mounted, ejects and leaves it after; asks when the mixer was in it already; reports a mixer that stays in it; stops without a mixer')

def check_history(tmp):
    def h(text):p=tmp/'H.TXT';p.write_text(text);return it.History(p)
    x=h('L6 HISTORY 2\nRECORDER/a\nSOUND SOUND_PAD/PAD1/X.WAV\nOMITTED\nEND 2\n')
    assert x.version==2 and x.entries==[('take','a'),('sound','SOUND_PAD/PAD1/X.WAV')] and x.omitted and not x.problems
    assert any('says 3' in p for p in h('L6 HISTORY 2\nRECORDER/a\nEND 3\n').problems)
    assert any('cut off' in p for p in h('L6 HISTORY 2\nRECORDER/a\n').problems)
    assert any('TRUNCATED' in p for p in h('L6 HISTORY 2\nTRUNCATED\nEND 0\n').problems)
    assert any('not a history' in p for p in h('hello\n').problems)
    assert h('L6 HISTORY 2\r\nRECORDER/a\r\nEND 1\r\n').entries==[('take','a')]
    print('history files: versions, OMITTED, TRUNCATED, END count, cut off, CRLF')

def check_real(tmp):
    """The 2 October 2026 stock-firmware overdub test: the pad backing was at +29168 in the
    first take, which played at +20528 and +23472 in the two second-generation takes
    (analysis/overdub_test/result.txt and audio_analysis.json). Histories are made up here
    (stock wrote none)."""
    a=ROOT/'analysis/overdub_test'
    if not (a/'pass2/261002_181142/MASTER.WAV').exists() or not (ROOT/'analysis/backing_track/GLORY_BOX.WAV').exists():print('2 October recordings: not present, skipped');return
    card=tmp/'real';rec=card/'RECORDER'
    for src in [a/'261002_175819',a/'pass2/261002_180953',a/'pass2/261002_181142']:
        (rec/src.name).mkdir(parents=True)
        for f in src.glob('*.WAV'):os.symlink(f,rec/src.name/f.name)
    (card/'SOUND_PAD/PAD1').mkdir(parents=True);os.symlink(ROOT/'analysis/backing_track/GLORY_BOX.WAV',card/'SOUND_PAD/PAD1/GLORY_BOX.WAV')
    (rec/'261002_175819/HISTORY.TXT').write_text('L6 HISTORY 2\nSOUND SOUND_PAD/PAD1/GLORY_BOX.WAV\nEND 1\n')
    for t in ['261002_180953','261002_181142']:(rec/t/'HISTORY.TXT').write_text('L6 HISTORY 2\nRECORDER/261002_175819\nSOUND SOUND_PAD/PAD1/GLORY_BOX.WAV\nEND 2\n')
    text=run(rec/'261002_180953','--out',tmp/'r1','--link')+run(rec/'261002_181142','--out',tmp/'r2','--link')
    for want in ['261002_175819: starts +0.428 s into 261002_180953 (+20528 samples','261002_175819: starts +0.489 s into 261002_181142 (+23472 samples','GLORY_BOX.WAV: starts +0.608 s into 261002_175819 (+29168 samples']:
        assert want in text,(want,text)
    print('2 October recordings: the three measured offsets found to the sample')

def main():
    with tempfile.TemporaryDirectory() as d:
        tmp=Path(d);check_history(tmp);check_made_up(tmp);check_real(tmp)
    print('PASS')

if __name__=='__main__':main()
