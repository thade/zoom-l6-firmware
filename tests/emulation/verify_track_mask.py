#!/usr/bin/env python3
"""No track files for muted channels with no sends (experiment 43).

The build with TRACK_MASK replaces the record prepare's one call of the
stock stream mask selector with tm_select. This suite runs the original
prepare with the setting off and on over mixer states, then each resulting
mask through the original record-start callback (file creation per stream),
RecStop's callback (the stop cursor setter hook, finalize, postprocess, the
take loader and playback preparation) on an in-memory card, the admission
change on takes with fewer streams feeding the chain and the history, the
AUX 2 + EFX hold through the stock key parser, the MUTE LED show, and the
build. Original code executes; the card, the producer registration, the
player, the folder naming and the kernel are models. No device access.
"""
import fnmatch,hashlib,json,struct,sys
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_PC,UC_ARM_REG_LR
from verify_pad_protocol import ROOT,IMAGE,BIAS
from verify_uncompressed_tap import TapRig
from verify_recording_writer import C
from verify_stem_completion import calls
from verify_firmware_workflow import put32,get32
from verify_record_catalogue import getstr,putstr
from build_master_ref import build
from plan_master_ref import plan,MASK_SPEC
from capture_jump_patches import symbols
from build_deployment_probe import SOURCE,digest
from build_master_trial import trial,trial_elf,assemble,MODES

ELF=build(trial=False,stereo=True,link=True,skip=True);PLAN=plan(ELF,trial=False);PACK=PLAN['pack'];N=PACK['names']
CONFIG=0x80440dc8;REC=0x801f8c48;SCRATCH=0x8060fd80;BUF=0x21020000;STATE=0x21010000
TICK=0x801f9050;RECORDING,RECORDER_BUSY=0x80578ebc,0x80578ec0
SKIP=CONFIG+0x311;AUX_MODE=CONFIG+0x30d;RECORDER_MODE=CONFIG+0x31d
MUTE_LED=lambda ch:0x8062939c+2*ch;SELECT_LED=lambda sel:0x8062939c+2*(sel+0xc)
TM_MAGIC=0x4c36544d;SA_MAGIC=0x4c364158;CHAIN_MAGIC=0x4c364348
HEAD=(0,1,2,4,6,8)                           # channel 1-6 to its head lane
LANES=lambda ch:[HEAD[ch]] if ch<2 else [HEAD[ch],HEAD[ch]+1]
FOLDER='A:\\RECORDER\\261011_130947'
MASTER_ONLY=0xc00;ALL=0xfff
NOT_FOUND=0xffffd75a
FS={0x8005ffe8,0x800622b0,0x80060620,0x8005f168,0x8005ef40,0x8005ec30,0x8005c1f8,0x8005e718,0x800227e8}

def lane(l,off):return CONFIG+0x15*l+off

class Card:
    """In-memory card: final and Work paths to bytes; handles for open files.
    The stock calls it through the public open/read/write/seek/info/close
    and, in the take loader, the per-stream file probe 0x800227e8 (a folder
    search for the stream's names), modeled as a pattern match."""
    def __init__(self,m):
        self.m=m;self.files={};self.opened={};self.next=1;self.events=[]
        m.hooks.update({0x8005ffe8:self.open,0x800622b0:self.write,0x80060620:self.read,0x8005f168:self.seek,
                        0x8005ef40:self.info,0x8005ec30:self.size,0x8005c1f8:self.close,0x8005e718:lambda a:512,
                        0x800227e8:self.count})
    def open(self,a):
        path=getstr(self.m,a[1]);mode=a[2];put32(self.m,a[0],0)
        self.events.append(('open',path,mode))
        if mode&0x100:self.files[path]=bytearray()
        elif path not in self.files:return NOT_FOUND
        h=self.next;self.next+=1;self.opened[h]=[path,0];put32(self.m,a[0],h);return 0
    def write(self,a):
        h,p,n,out=a[:4];path,cur=self.opened[h];f=self.files[path];data=bytes(self.m.uc.mem_read(p,n))
        f.extend(bytes(max(0,cur+n-len(f))));f[cur:cur+n]=data;self.opened[h][1]=cur+n;put32(self.m,out,n);return 0
    def read(self,a):
        h,p,n,out=a[:4];path,cur=self.opened[h];d=self.files[path][cur:cur+n]
        if d:self.m.uc.mem_write(p,bytes(d))
        self.opened[h][1]=cur+len(d);put32(self.m,out,len(d));return 0 if len(d)==n else 0xffffd759
    def seek(self,a):
        h,offset,mode=a[:3];offset=offset if offset<2**31 else offset-2**32;path,cur=self.opened[h]
        base=cur if mode==0 else len(self.files[path]) if mode==1 else 0;self.opened[h][1]=base+offset;return 0
    def info(self,a):
        path,cur=self.opened[a[0]];self.m.uc.mem_write(a[1],struct.pack('<4I',len(self.files[path]),cur,0,0));return 0
    def size(self,a):
        path,cur=self.opened[a[0]];put32(self.m,a[1],len(self.files[path]));return 0
    def close(self,a):
        self.events.append(('close',self.opened[a[0]][0]));del self.opened[a[0]];return 0
    def count(self,a):
        pattern=getstr(self.m,a[0]).upper()
        return sum(1 for path in self.files if fnmatch.fnmatchcase(path.upper(),pattern))

class TakeRig(TapRig):
    """The stock recorder on Main and RecPlayCtl with the build's code placed
    and the prepare, admission and stop sites patched. Folder naming, the
    catalogue, the recorder locks and the kernel are models."""
    def __init__(self,patched=True):
        super().__init__();m=self.m;j=PACK['jumps']
        m.uc.mem_write(j['candidate_code_start'],PACK['code']);m.uc.mem_write(j['globals_start'],bytes(j['globals_end']-j['globals_start']))
        for p in PLAN['patches']:
            if p['adapter'] in ('tm_select','mr_admit_hook','mr_stop_hook'):
                assert bytes(m.uc.mem_read(p['site'],4))==bytes.fromhex(p['original'])
                if patched:m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
        put32(m,N['mr_state'],STATE);m.uc.mem_write(STATE,bytes(0x6000))   # the worker is published; zeroed state
        self.events=[];self.registered=[];self.player=[];self.watched=[];self.posts=[];self.saves=0
        m.hooks.update({0x800088c0:lambda a:1,0x80008880:lambda a:0,0x800088a8:lambda a:BUF,0x80006528:lambda a:0,
            0x80006538:lambda a:0,0x8000b2a8:lambda a:0,0x80008848:lambda a:0,0x80076950:lambda a:1,0x800763d8:lambda a:1,
            0x80006150:lambda a:48000,0x80006178:lambda a:32,0x8000ae00:lambda a:0,0x80020360:lambda a:0,0x8000ec20:lambda a:0,
            0x800485b0:lambda a:(putstr(m,a[0],'261011_130947'),0)[1],   # the take name
            0x80020ca0:lambda a:self.posts.append(tuple(a[:5])) or 0,0x80006ab8:self.save,0x80020690:lambda a:0})
        # The mixer: unmuted, sends at zero, AUX send points post-fader (the
        # stock default), the 3/4 and 5/6 strips stereo (input mode -1).
        for l in range(10):m.uc.mem_write(lane(l,0x13),bytes([1,1]))
        for l in range(2,6):m.uc.mem_write(CONFIG+0x25ad+l,b'\xff')
        for addr,name in ((0x80022d20,'status'),(0x80022d80,'record'),(0x8000ea08,'finalize'),(0x8000b090,'start_backend')):self.watch(addr,name)
        self.card=Card(m)
    def save(self,a):self.saves+=1;return 0
    def watch(self,addr,name):
        def f(uc,address,size,u):self.watched.append((name,)+tuple(uc.reg_read(x) for x in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)))
        self.m.uc.hook_add(UC_HOOK_CODE,f,begin=addr,end=addr)
    def event(self,name,value=0):
        def f(a):self.events.append((name,tuple(a[:4])));return value
        return f
    # Mixer state (the bytes the stock getters read).
    def setting(self,on):self.m.uc.mem_write(SKIP,bytes([0x96,0x69]) if on else bytes(2))
    def stereo(self,on):self.m.uc.mem_write(AUX_MODE,bytes([0xa5,0x5a]) if on else bytes(2))
    def mute(self,ch,on=1):
        for l in LANES(ch):self.m.uc.mem_write(lane(l,0),bytes([on]))
    def efx(self,l,level,muted=0):self.m.uc.mem_write(lane(l,9),bytes([level,muted]))
    def aux(self,l,aux,level,muted=0,post=1):
        self.m.uc.mem_write(lane(l,0xc+aux),bytes([level&255]));self.m.uc.mem_write(lane(l,0xe+aux),bytes([muted]))
        self.m.uc.mem_write(lane(l,0x13+aux),bytes([post]))
    def mono_x2(self,ch):
        for l in LANES(ch):self.m.uc.mem_write(lane(l,0x12),b'\x01')
    def field(self,off):return get32(self.m,STATE+off)
    # The take.
    def prepare(self,target=-1):
        """The original prepare 0x80002df8: the selector call (patched), then
        0x8000b540 -> 0x80004738 set the per-stream has-file flags and the
        selected bytes. Returns (mask, selected bytes, has-file flags)."""
        m=self.m;m.invoke(0x800043f8,[])                    # recorder file state: Work name, stereo lane pairs
        assert m.invoke(0x80002df8,[target&0xffffffff])==0
        return get32(m,REC+0x1c),list(m.uc.mem_read(REC+0x20,12)),[m.invoke(0x80022c78,[s]) for s in range(12)]
    def start(self):
        """The original record-start callback 0x8000b168 -> 0x8000b090: a Work
        file per flagged stream (0x800042e0: open, WAV header), ZOOM_L6.SYS
        for the first, producer registration (modeled: handle and active bit),
        then our admission hook. Returns each stream's (Work name, final name)."""
        m=self.m
        for fn in (0x80002908,0x8001aaa0,0x80002cb0,0x8001aab8,0x80002a98,0x80002d28,0x80002ad8,0x80002a90,0x80006158,0x800381e0,
                   0x80037f60,0x80037fc0,0x80004060,0x80004068,0x8000bbc0,0x8000bbe8,0x80038530):m.hooks[fn]=self.event(hex(fn))
        m.hooks[0x8000bf48]=self.event('system_file')
        def register(a):
            self.registered.append(tuple(a[:4]));put32(m,0x8077e87c+a[0]*4,a[1]);put32(m,0x8077ce70,get32(m,0x8077ce70)|1<<a[0]);return 0
        m.hooks[0x80037ca0]=register
        m.hooks[0x80008a88]=lambda a:m.uc.mem_write(a[0],struct.pack('<HBBBBB',2026,10,11,13,9,46)) or 0
        putstr(m,BUF,FOLDER);m.invoke(0x80022de0,[BUF]);m.invoke(0x80022dc8,[48000,32])
        m.uc.mem_write(REC+0xa,b'\x01');m.uc.mem_write(REC+0xb,b'\x01');m.uc.mem_write(0x801f5f00,b'\xff')
        m.invoke(0x8000b168,[0])
        self.names={s:(getstr(m,m.invoke(0x80022bb8,[s])) if m.invoke(0x80022c78,[s]) else None,getstr(m,m.invoke(0x80022c80,[s,1]))) for s in range(12)}
        return self.names
    def stop(self,frames=64):
        """RecStop's callback 0x8004ba40: the stop cursor setter (our hook),
        then 0x8000b698: finalize and close each registered stream, reset,
        postprocess (per-file pass modeled, rename and Work removal modeled
        on the card), the take loader over the card, the mask again, and the
        playback preparation handed to the stream task; then StreamPreLoad
        itself with the player calls recorded."""
        m=self.m;card=self.card
        for s,h,ch,_ in self.registered:   # the producer state the finalizers read; a payload of `frames`
            channels=2 if ch else 1;card.files[self.names[s][0]]+=struct.pack('<%df'%(frames*channels),*([h/16]*(frames*channels)))
            put32(m,C+0x1e4c+s*4,h);put32(m,C+0x454+s*4,frames);m.uc.mem_write(C+0x448+s,b'\x20')
        mask=sum(1<<s for s,_,_,_ in self.registered)
        put32(m,C+8,mask);put32(m,C+0x444,sum(1<<s for s,_,ch,_ in self.registered if ch));put32(m,C+0x440,0)
        m.uc.mem_write(REC+0x2c,b'\x01')
        for fn in calls(0x8000b698,0x8000b9b4):
            if fn not in FS:m.hooks[fn]=self.event('stop:'+hex(fn))
        for fn in (0x80037dc0,0x80037d68,0x80037d98,0x80037df0,0x80037e98,0x80037e58,0x8000ea08,0x800380d0,0x800032b0,0x8000b540,0x8000ae48):
            m.hooks.pop(fn,None)
        m.hooks[0x80002360]=lambda a:1
        m.hooks[0x80002418]=lambda a:(m.uc.reg_write(UC_ARM_REG_R1,0),frames)[1]   # the stop position (64-bit): the take's length
        def delay(a):
            if get32(m,C+0x440):put32(m,C+0x440,0);m.uc.mem_write(C+0xe8,b'\x01')
            else:m.uc.mem_write(C+0xe8,b'\0')
            return 0
        m.hooks[0x80077686]=delay
        for fn in calls(0x800032b0,0x800035c8)|calls(0x800035d0,0x80003850):
            if fn not in FS:m.hooks.pop(fn,None)
        for fn in (0x80005e48,0x80008868,0x80008880,0x800088c0,0x80008bd0,0x80022950):m.hooks[fn]=self.event('post:'+hex(fn))
        m.hooks[0x80004868]=self.event('process_stream')
        def rename(a):
            work,final=self.names[a[0]];self.events.append(('rename',a[0]))
            if work in card.files:card.files[final]=card.files.pop(work)
            return 0
        m.hooks[0x80022938]=rename;m.hooks[0x80022958]=self.event('remove_work')
        m.hooks[0x8005b7e0]=lambda a:m.uc.mem_write(a[1],b'\0') or 0
        def player(name):
            def f(a):self.player.append((name,)+tuple(a[:4]));return 0
            return f
        for fn,name in ((0x80037c38,'set'),(0x800384b8,'range'),(0x80038070,'done'),(0x800385c0,'length')):m.hooks[fn]=player(name)
        for fn in (0x8001aaa0,0x8001aab8,0x80002fd0,0x80037c30,0x800044f8,0x800042d8,0x80002958,0x8000a5d8,0x80038080,0x80002a60,0x80002b40,0x800381c0,0x80038078):
            m.hooks[fn]=self.event('tail:'+hex(fn))
        for fn in (0x8001e4d8,0x80007c20,0x8000acf0,0x8000b9b8,0x80008a80,0x80008880,0x80008890,0x800068c8,0x8000bab8,0x8000bbe8,0x80020360,0x80008a60,0x80006968,0x80006740):
            m.hooks[fn]=self.event('recstop:'+hex(fn))
        m.hooks[0x80002460]=lambda a:54321
        m.uc.mem_write(RECORDING,b'\x01');put32(m,BUF+0x100,0)
        m.invoke(0x8004ba40,[BUF+0x100])
        # StreamPreLoad on the stream task: first where RecStop left the position
        # (the take's end: the stock preload opens nothing there), then from the
        # take's start, as a seek to the beginning positions it.
        self.player.clear();m.invoke(0x8000aec0,[]);self.player_at_end=list(self.player)
        m.hooks[0x80061770]=lambda a:0   # the player's positioning call on the opened file (not modeled further)
        self.player.clear();m.uc.mem_write(REC+0x10,bytes(8));m.invoke(0x8000aec0,[])
        return mask
    def receive(self,*packet):
        self.m.uc.mem_write(BUF+0x180,struct.pack('<4I',*packet));return self.m.invoke(N['mr_main_receive'],[BUF+0x180])
    def leds(self):return [list(self.m.uc.mem_read(MUTE_LED(ch),2)) for ch in range(6)]

def take(configure,setting=True,target=-1,patched=True):
    """One take on a fresh rig: configure(rig) sets the mixer; returns the rig after the prepare."""
    r=TakeRig(patched);r.setting(setting);configure(r);r.mask,r.selected,r.flags=r.prepare(target);return r

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    # ---- The build ----
    image,_,manifest,_=trial('skip_muted')
    adapters=sorted(p['adapter'] for p in manifest['patches'])
    site=[p for p in manifest['patches'] if p['adapter']=='tm_select']
    assert manifest['experiment']==43 and len(adapters)==16 and adapters.count('mr_main_receive')==5 and 'health_parser' not in adapters
    assert len(site)==1 and site[0]['site']==MASK_SPEC['site']==0x80002e96 and site[0]['original_callee']==0x80008990 and site[0]['bytes']==4
    assert manifest['skip_muted_tracks'] and manifest['linked_aux_limiters'] and not manifest['diagnostics'] and len(manifest['DSP_patches'])==2
    assert IMAGE[0x80002e94-BIAS:0x80002e96-BIAS]==bytes.fromhex('2046')   # mov r0,r4: the target stays the selector's argument
    assert not any(p['site']<=0x80002d5e<p['site']+p['bytes'] for p in manifest['patches'])   # the project loader's selector call is stock
    everyday=dict(MODES['release']);del everyday['pin']   # the release sources are the same: the tree still builds 0.3.0
    with trial_elf(everyday) as release_elf:t=plan(release_elf,trial=False)
    assert digest(assemble(SOURCE.read_bytes(),t))==MODES['release']['sha']
    assert 'tm_select' not in symbols(release_elf)
    passed('the_skip_muted_build_patches_the_release_sites_plus_the_prepares_selector_call_and_the_tree_still_builds_0_3_0',
           trial_sha256=manifest['trial_sha256'],code_bytes=manifest['code_bytes'],release_code_bytes=t['code_bytes'],site=hex(site[0]['site']))

    # ---- The mask: the original prepare with the setting off and on ----
    def selected(mask,split=()):   # what 0x8000b540 derives: selected bytes (channels per head) and has-file flags
        sel=[0]*12;flags=[0]*12
        for s in range(12):
            if s in split:
                if mask>>s&1:sel[s]=flags[s]=1
            elif mask>>s&1 and s!=11 and not (s>=2 and s%2):sel[s]=2 if s>=2 else 1;flags[s]=1
        return sel,flags
    SPLIT={'mono_x2_3_4_muted':(2,3)}   # lanes MONO x2 makes separate streams
    def nothing(r):pass
    def all_muted(r):
        for ch in range(6):r.mute(ch)
    masks={}
    for label,configure,want in (
            ('nothing_muted',nothing,ALL),
            ('channel_1_muted',lambda r:r.mute(0),ALL&~1),
            ('channel_2_muted',lambda r:r.mute(1),ALL&~2),
            ('stereo_3_4_muted',lambda r:r.mute(2),ALL&~0xc),
            ('stereo_5_6_muted',lambda r:r.mute(3),ALL&~0x30),
            ('usb_muted',lambda r:r.mute(4),ALL&~0xc0),
            ('pad_channel_muted',lambda r:r.mute(5),ALL&~0x300),
            ('all_muted',all_muted,MASTER_ONLY),
            ('mono_x2_3_4_muted',lambda r:(r.mono_x2(2),r.mute(2)),ALL&~0xc),
            ('one_lane_of_a_pair_muted',lambda r:r.m.uc.mem_write(lane(2,0),b'\x01'),ALL),
            # The send escapes: an AUX send that carries something keeps the
            # channel; the EFX send is not looked at (a muted channel does not
            # reach the effect, found on the mixer).
            ('muted_efx_send_up',lambda r:(r.mute(0),r.efx(0,40)),ALL&~1),
            ('muted_efx_send_up_but_muted',lambda r:(r.mute(0),r.efx(0,40,muted=1)),ALL&~1),
            ('muted_aux1_pre',lambda r:(r.mute(0),r.aux(0,0,30,post=0)),ALL),
            ('muted_aux1_post',lambda r:(r.mute(0),r.aux(0,0,30,post=1)),ALL&~1),
            ('muted_aux1_pre_but_muted',lambda r:(r.mute(0),r.aux(0,0,30,muted=1,post=0)),ALL&~1),
            ('muted_aux1_pre_at_zero',lambda r:(r.mute(0),r.aux(0,0,0,post=0)),ALL&~1),
            ('muted_aux2_pre',lambda r:(r.mute(0),r.aux(0,1,30,post=0)),ALL),
            ('muted_aux2_pre_negative_level',lambda r:(r.mute(0),r.aux(0,1,-10,post=0)),ALL),
            ('muted_aux2_pre_in_stereo',lambda r:(r.stereo(1),r.mute(0),r.aux(0,1,30,post=0)),ALL&~1),
            ('muted_aux1_pre_in_stereo',lambda r:(r.stereo(1),r.mute(0),r.aux(0,0,30,post=0)),ALL),
            ('muted_efx_up_in_stereo',lambda r:(r.stereo(1),r.mute(0),r.efx(0,5)),ALL&~1),
            ('stereo_pair_one_lane_sends',lambda r:(r.mute(3),r.aux(5,0,30,post=0)),ALL),
            ('stereo_pair_both_lanes_silent',lambda r:(r.mute(3),r.aux(5,0,30,post=0),r.aux(5,0,30,muted=1,post=0)),ALL&~0x30),
            ('several_channels',lambda r:(r.mute(0),r.mute(2),r.mute(4),r.aux(7,1,20,post=0)),ALL&~0xd)):
        r=take(configure);split=SPLIT.get(label,())
        assert r.mask==want,(label,hex(r.mask),hex(want))
        assert (r.selected,r.flags)==selected(want,split),(label,r.selected,r.flags)
        masks[label]=hex(want)
        # The setting off: stock's answer whatever the mixer says; the unpatched prepare too.
        for setting,patched in ((False,True),(True,False)):
            q=take(configure,setting=setting,patched=patched);assert q.mask==ALL and (q.selected,q.flags)==selected(ALL,split),(label,setting,patched)
    # Counters: takes with the setting on, lanes dropped in all, the channels of the last take.
    r=take(lambda r:(r.mute(0),r.mute(2)))
    assert [get32(r.m,N[k]) for k in ('tm_takes','tm_dropped','tm_last')]==[1,3,0b101]
    r.mute(0,0);r.prepare();assert [get32(r.m,N[k]) for k in ('tm_takes','tm_dropped','tm_last')]==[2,5,0b100]
    passed('the_patched_prepare_leaves_out_both_lanes_of_each_muted_channel_whose_sends_carry_nothing',masks=masks)

    # Pad targets, Recorder Mode and the project loader keep stock's answer.
    for target in (0,1,2,3):
        r=take(all_muted,target=target);assert r.mask==MASTER_ONLY and (r.selected,r.flags)==selected(MASTER_ONLY)
        assert get32(r.m,N['tm_takes'])==0
    r=TakeRig();r.setting(1);all_muted(r);r.m.uc.mem_write(RECORDER_MODE,b'\x01')
    assert r.prepare()[0]==MASTER_ONLY and get32(r.m,N['tm_takes'])==1 and get32(r.m,N['tm_dropped'])==0
    r=TakeRig();r.setting(1);all_muted(r);r.m.invoke(0x800043f8,[])
    r.m.invoke(0x80002d30,[0]);assert get32(r.m,REC+0x1c)==ALL                      # the project loader's own call
    assert bytes(r.m.uc.mem_read(0x80002d5e,4))==bytes.fromhex('05f017fe')
    # Without the worker (startup gave up) the setting is off, as the stereo mode is.
    r=TakeRig();r.setting(1);all_muted(r);put32(r.m,N['mr_state'],0);assert r.prepare()[0]==ALL
    passed('pad_targets_master_only_the_project_loader_and_a_mixer_without_the_worker_keep_stocks_mask')

    # ---- The files: the original record start, stop, postprocess, loader and preload on each mask ----
    def track(s):return 'MASTER' if s==10 else f'TRACK0{s+1}' if s<2 else f'TRACK0{s//2+2}_ST'
    outcomes={}
    for label,configure,kept in (
            ('all_seven',nothing,[0,1,2,4,6,8,10]),
            ('mono_channel_out',lambda r:r.mute(0),[1,2,4,6,8,10]),
            ('stereo_pair_out',lambda r:r.mute(3),[0,1,2,6,8,10]),
            ('mono_x2_pair_out',lambda r:(r.mono_x2(2),r.mute(2)),[0,1,4,6,8,10]),
            ('mono_x2_pair_kept',lambda r:(r.mono_x2(2),r.mute(0)),[1,2,3,4,6,8,10]),
            ('several_out',lambda r:(r.mute(0),r.mute(2),r.mute(4)),[1,4,8,10]),
            ('master_only',all_muted,[10])):
        r=take(configure);names=r.start()
        work={s:w for s,(w,_) in names.items() if w};final={s:f for s,(_,f) in names.items()}
        # Work files for the kept streams only, named as stock names them; MONO x2 lanes get _L and _R.
        assert sorted(work)==kept,(label,sorted(work))
        for s in kept:
            name=('TRACK03_L','TRACK03_R')[s-2] if label.startswith('mono_x2') and s in (2,3) else track(s)
            assert work[s]==f'{FOLDER}\\Work\\{name}.WAV' and final[s]==f'{FOLDER}\\{name}.WAV',(label,s,work[s])
        assert sorted(r.card.files)==sorted(work.values()) and all(len(v)==910 for v in r.card.files.values()),label
        assert [e for e in r.card.events if e[0]=='open']==[('open',work[s],0x102) for s in kept]
        assert [x[0] for x in r.registered]==kept and [x[2] for x in r.registered]==[int(s>=2 and not (label.startswith('mono_x2') and s in (2,3))) for s in kept]
        assert [e for e in r.events if e[0]=='system_file']==[('system_file',(0x8077c81c,0,0,0))][:1] or len([e for e in r.events if e[0]=='system_file'])==1
        assert getstr(r.m,0x8077c81c)==work[kept[0]]                        # ZOOM_L6.SYS names the first created file's folder
        # Our admission hook, through its adapter at 0x8000b158: the take is ordinary with any subset.
        assert (r.field(0),r.field(8))==(1,1),(label,'admitted')
        # RecStop: the setter hook notes the take; finalize and close only the kept handles, in order.
        mask=r.stop()
        finalized=[x[1] for x in r.watched if x[0]=='finalize'];handles=[h for _,h,_,_ in r.registered]
        assert finalized==handles,(label,finalized)
        assert [e for e in r.card.events if e[0]=='close'][:len(kept)]==[('close',work[s]) for s in kept]
        assert r.field(4)==1 and getstr(r.m,STATE+4*27)==FOLDER+'\\MASTER.WAV'
        # Postprocess: the per-file pass and the rename for the kept streams, Work removed, then the loader.
        assert [e[1][0] for e in r.events if e[0]=='process_stream']==kept and [e[1] for e in r.events if e[0]=='rename']==kept
        assert len([e for e in r.events if e[0]=='remove_work'])==1
        assert sorted(r.card.files)==sorted(final[s] for s in kept)
        for s in kept:
            data=r.card.files[final[s]];channels=2 if s>=2 and not (label.startswith('mono_x2') and s in (2,3)) else 1
            assert struct.unpack_from('<I',data,4)[0]==len(data)-8 and struct.unpack_from('<I',data,906)[0]==64*channels*4,(label,s)   # the stock 910-byte header: data chunk at 902
        # The take loader: opened, read and recorded each kept stream's final
        # file (status 1 with its record index), left the others absent (0).
        # Stock as it is: the loader takes a mono file for streams 0-1 and a
        # stereo file for streams 2-9 only, so a MONO x2 lane's mono file is
        # opened and then refused (status 3), with or without the track mask.
        split=[s for s in kept if label.startswith('mono_x2') and s in (2,3)];loaded=[s for s in kept if s not in split]
        assert [e for e in r.card.events if e[0]=='open' and e[2]==2]==[('open',final[s],2) for s in kept]
        recorded=[x for x in r.watched if x[0]=='record'];status=[x for x in r.watched if x[0]=='status']
        assert len(recorded)==len(loaded),(label,recorded)
        assert [x[1:3] for x in status]==[(s,1 if s in loaded else 3 if s in split else 0) for s in range(12)],(label,status)
        assert [x[3] for x in status if x[2]==1]==list(range(len(loaded))) and all(x[3]==0xffffffff for x in status if x[2]!=1)
        # The mask applied again, then playback preparation (StreamPreLoad):
        # positioned at the take's end, as RecStop leaves it, every stream is set
        # off in the player (0x80037c38(s,0,0,0x10), 0x800384b8(s,0,-1,0)) and
        # nothing is opened; positioned at the start, the master pair gets its
        # file (opened read-only through the record the loader made) and the
        # streams without a file stay off. Track streams 0-9 are not this
        # preload's: it handles the master pair only.
        assert get32(r.m,REC+0x1c)==r.mask and mask==sum(1<<s for s in kept)   # the stream mask again; the producer mask had the head lanes
        OFF=lambda calls:[x[1] for x in calls if x[0]=='set' and x[2:]==(0,0,0x10)]
        assert OFF(r.player_at_end)==list(range(12)) and r.player_at_end[-2][0]=='done' and r.player_at_end[-1]==('length',64,0,0xffffffff,0)
        opened=[e for e in r.card.events if e[0]=='open' and e[2]==0]
        assert opened==[('open',final[s],0) for s in loaded],(label,opened)     # the player opens each loaded file, no other
        on=[x for x in r.player if x[0]=='set' and x[2:]!=(0,0,0x10)]
        assert [x[1] for x in on]==[10] and on[0][2]!=0 and on[0][3:]==(1,32),(label,r.player)   # the master: its handle, stereo, 32-bit
        assert ('range',10,0,64,len(r.card.files[final[10]])) in r.player
        assert OFF(r.player)==[s for s in range(12) if s!=10] and r.player[-2][0]=='done'
        outcomes[label]=dict(mask=hex(r.mask),files=[work[s].rsplit('\\',1)[1] for s in kept],loaded=[final[s].rsplit('\\',1)[1] for s in loaded])
    passed('the_original_start_stop_postprocess_loader_and_preload_handle_each_subset_as_they_handle_master_only',outcomes=outcomes)

    # ---- The MUTE LED show at the take start ----
    r=take(lambda r:(r.mute(0),r.mute(2),r.mute(5)))
    assert r.leds()==[[0x10,1],[0,0],[0x10,1],[0,0],[0,0],[0x10,1]]       # the dropped channels blink; others untouched
    put32(r.m,TICK,get32(r.m,TICK)+1999);r.receive(0,0,0x10,0);assert r.leds()[0]==[0x10,1]
    put32(r.m,TICK,get32(r.m,TICK)+1);r.receive(0,0,0x10,0)
    assert r.leds()==[[0x10,0],[0,0],[0x10,0],[0,0],[0,0],[0x10,0]]       # 2 s later: steady, from the channel mutes (stock's writer)
    r.mute(2,0);r.prepare();assert r.leds()[2]==[0x10,0]                  # unmuted now: kept, no show
    assert r.leds()[0]==[0x10,1]
    put32(r.m,TICK,get32(r.m,TICK)+2000);r.mute(0,0);r.receive(0,0,0x10,0);assert r.leds()[0]==[0,0]   # redrawn from the mute as it is then
    r=take(nothing);assert r.leds()==[[0,0]]*6                              # nothing dropped: the LEDs are left alone
    r=TakeRig();r.setting(1);r.mute(1);r.m.hooks[0x80076950]=lambda a:0     # the LED lock is busy: no show, the take still prepared
    assert r.prepare()[0]==ALL&~2 and r.leds()==[[0,0]]*6
    passed('dropped_channels_mute_leds_blink_for_2_s_and_are_redrawn_from_the_mutes_without_blocking_the_start')

    # ---- Admission: takes with fewer streams join the chain and get a history ----
    import verify_master_ref as V
    V.PLAN=PLAN;V.PACK=PACK;V.N=N
    def subset_state(m,streams):
        m.uc.mem_write(0x801f5f00,b'\xff');put32(m,0x8077ce70,sum(1<<s for s in streams))
        for s in range(12):put32(m,0x8077e87c+s*4,0x1000+s if s in streams else 0)
    rig=V.MasterRig();t=[V.take_master(n) for n in range(1,4)];histories={}
    for n,streams in enumerate(([0,1,10],[10],[1,2,3,4,10],[0,1,2,4,6,8,10])):
        rig.card[t[0] if n==0 else V.take_master(n+1)]=V.stock_master(10**6)
        path=V.take_master(n+1);subset_state(rig.m,streams);putstr(rig.m,V.TAKE_DIR,V.take_folder(path))
        rig.m.invoke(N['mr_admit'],[]);assert rig.field('stock_recording')==1,streams
        if n:rig.play(0)
        rig.m.invoke(N['mr_stop'],[0,V.REC_STOP]);rig.silence();rig.settle();rig.deliver()
        assert rig.field('handoff_state')==V.H_ASSIGNED and rig.pads()[0]==path,(streams,rig.pads())
        histories[str(streams)]=rig.history(path).decode()
    assert histories[str([0,1,10])]==V.history_text().decode() and histories[str([10])]==V.history_text(V.entry(t[0])).decode()
    # Still refused: a pad record target, no master stream, or the master's handle missing.
    for label,setup in (('pad_target',lambda m:m.uc.mem_write(0x801f5f00,b'\x00')),
                        ('no_master_bit',lambda m:put32(m,0x8077ce70,0x3)),
                        ('no_master_handle',lambda m:put32(m,0x8077e87c+40,0))):
        subset_state(rig.m,[0,1,10]);setup(rig.m);admitted=rig.field('admitted')
        rig.m.invoke(N['mr_admit'],[]);assert rig.field('stock_recording')==0 and rig.field('admitted')==admitted,label
    passed('subset_takes_are_admitted_join_the_chain_and_get_their_history_while_pad_and_masterless_takes_are_refused',histories=histories)

    # ---- The AUX 2 + EFX hold ----
    import verify_stereo_aux_hooks as S
    S.PACK=PACK;S.NAMES=N;S.SA={p['adapter']:p for p in PLAN['patches'] if p['adapter'].startswith('sa_')}
    assert [p[:2] for p in S.SOURCE_PAIRS]==[(16,17),(18,19),(17,18)] and S.SOURCE_PAIRS[2][2]=='TM_TOGGLE_MAGIC'
    p=S.Probe(True);saves=[];S.stub(p,0x80006ab8,calls=saves);S.stub(p,0x80076950,1);S.stub(p,0x800763d8,1)
    p.uc.mem_write(TICK,struct.pack('<I',30000))
    assert p.raw(SKIP,2)==bytes(2)
    p.run(N['tm_toggle']);assert p.raw(SKIP,2)==bytes([0x96,0x69]) and len(saves)==1
    assert p.raw(SELECT_LED(5),2)==bytes([0x10,1]) and p.raw(SELECT_LED(6),2)==bytes([0x10,1])   # AUX 2 and EFX blink: on
    p.run(N['tm_toggle']);assert p.raw(SKIP,2)==bytes(2) and len(saves)==2
    assert p.raw(SELECT_LED(5),2)==bytes([0x10,0]) and p.raw(SELECT_LED(6),2)==bytes([0x10,0])   # steady: off
    for at,value in ((RECORDING,1),(RECORDER_BUSY,1)):                                           # refused while recording or finalizing
        p.uc.mem_write(at,bytes([value]));p.run(N['tm_toggle']);p.uc.mem_write(at,bytes(1))
    assert p.raw(SKIP,2)==bytes(2) and len(saves)==2 and struct.unpack('<I',p.raw(N['tm_refused'],4))[0]==2
    # Through Main's receive hook: the category-3 event with our magic, and no other.
    packet=0x21020000;p.uc.mem_write(STATE,bytes(0x6000));S.stub(p,0x80020690)
    for magic,want in ((CHAIN_MAGIC,bytes(2)),(TM_MAGIC,bytes([0x96,0x69])),(SA_MAGIC,bytes([0x96,0x69])),(TM_MAGIC,bytes(2))):
        p.uc.mem_write(packet,struct.pack('<4I',3,magic,0,0));p.run(N['mr_main_receive'],[packet]);assert p.raw(SKIP,2)==want,hex(magic)
    assert struct.unpack('<I',p.raw(N['tm_toggles'],4))[0]==4
    # The stock save copies the global block, our bytes included, into the flash image.
    q=S.Probe(True);S.stub(q,0x800763d8,1);q.uc.mem_write(SKIP,bytes([0x96,0x69]));q.uc.mem_write(0x804439a0+0xf29,bytes(2));q.run(0x80006ab8)
    assert q.raw(0x804439a0+0xf29,2)==bytes([0x96,0x69])
    # The hold detector: AUX 2 + EFX (keys 17, 18) for 1.5 s posts once; the other holds stay quiet.
    keys={};posts=[]
    def key(uc,a,size,u):uc.reg_write(UC_ARM_REG_R0,keys.get(uc.reg_read(UC_ARM_REG_R0),0));uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    p.uc.hook_add(UC_HOOK_CODE,key,begin=0x80008478,end=0x80008478);S.stub(p,0x80020ca0,calls=posts)
    p.uc.mem_write(N['mr_main_ready'],struct.pack('<I',1001))
    def poll(t,a,b):keys[17],keys[18]=a,b;p.uc.mem_write(TICK,struct.pack('<I',t));p.run(N['panel_poll'])
    posted=lambda magic:[x for x in posts if x[1]==magic]
    for t in range(5000,6450,50):poll(t,1,1)
    assert not posted(TM_MAGIC)
    for t in range(6450,9000,50):poll(t,1,1)
    assert len(posted(TM_MAGIC))==1 and not posted(SA_MAGIC) and not posted(CHAIN_MAGIC)
    poll(9050,0,0);poll(9100,0,0);poll(9150,0,0)
    for t in range(9200,10750,50):poll(t,1,1)
    assert len(posted(TM_MAGIC))==2
    # Through the stock key parser with the panel's measured key reporting:
    # one toggle per hold, in either order, with the second key late or not.
    holds={}
    for order in (0,1):
        for stagger in (0,150,400):
            p=S.Probe(True);posts=[];S.stub(p,0x80020ca0,calls=posts);S.stub(p,0x8001fb80)
            p.uc.mem_write(N['mr_main_ready'],struct.pack('<I',1001));panel=S.Panel(p,True)
            first,second=((17,18),(18,17))[order]
            def at(ms):p.uc.mem_write(TICK,struct.pack('<I',ms));p.run(N['panel_poll'])
            for ms in range(5000,5200,25):at(ms)
            for n in range(3):
                start=6000+n*4000;panel.press(first)
                for ms in range(start,start+stagger,25):at(ms)
                panel.press(second)
                for ms in range(start+stagger,start+stagger+2000,25):at(ms)
                panel.release(first);panel.release(second)
                for ms in range(start+stagger+2000,start+4000,25):at(ms)
            got=[x[1] for x in posts if x[0]==3];holds[f'{order}/{stagger}']=got.count(TM_MAGIC)
            assert got==[TM_MAGIC]*3,(order,stagger,got)
    passed('holding_aux2_and_efx_for_1_5_s_toggles_the_setting_with_save_and_leds_refused_while_recording',holds=holds)

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=PLAN['elf_sha256'],trial_sha256=manifest['trial_sha256'],limitations=[
            'The take folder naming, the catalogue, the recorder locks, the producer registration, the deep per-file postprocess and the player are models',
            'The card is in-memory: the Work rename and the folder search are modeled; no FAT or exFAT structures',
            'One task at a time: Main, RecPlayCtl and the stream task run in sequence, not under the RTOS',
            'No hardware: the panel MCU, the LED task and the audio path are not run'])
    (ROOT/'analysis/track_mask_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
