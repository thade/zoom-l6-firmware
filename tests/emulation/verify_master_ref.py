#!/usr/bin/env python3
"""Take chain: pads 1-4 play the last four takes' stock MASTER.WAV in place.

Original take naming, stock record request/stop callbacks and the seven stock
writers execute through the patched admission and stop sites; original
catalogue, reload, assignment, settings save/load and startup code execute.
Probed files, WAV validation of the queued call, pad play/stop and the
assignment queue are recorded models. No device or card access.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_capture_placement import PlacementRig
from verify_capture_integration import IntegrationRig,record
from verify_capture_startup import Boot
from verify_pad_protocol import ROOT,IMAGE,Machine
from verify_record_catalogue import putstr,getstr,BASE,STRIDE
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_stock_pad_adapter import CONFIG,SETTINGS
import verify_pad_reload as V
from capture_jump_patches import symbols
from build_master_ref import build
from plan_master_ref import plan,TRIAL_ELF

build(trial=True);PLAN=plan(trial=True);PACK=PLAN['pack'];N=symbols(TRIAL_ELF)
FIELDS=('admitted stopped stock_recording open_take stop_faults stop_revoked admit_revoked revoked revoke_packet main_timed_out handled '
        'task polls seen pending file_open take_revoked checked refused last_status master_bytes '
        'handoff_state handoff_result handoff_serial handoff_posts handoff_posted_at handoff_revoked chain_mask').split()
OFF={n:4*i for i,n in enumerate(FIELDS)};STOP_PATH=4*len(FIELDS);PATH=STOP_PATH+160;POSTED=PATH+160
NEXT=POSTED+160;ASSIGNED=NEXT+4*160
STATE=0x23010000   # stands in for the heap allocation made at startup
OK,REVOKED,MISSING,SPLIT,IO,FORMAT,SHORT=range(7)
NONE,H_POSTED,H_ASSIGNED,H_SKIPPED,H_FAILED,H_LOST,H_SUPERSEDED=range(7)
MAGIC=0x4c364d52;REC_STOP=0x8004ba4d;PLAY_STOP=0x8004b91d
TAKE_DIR=0x8060ff80;RECORDER_BUSY=0x80578ec0;PACKET=0x23001900
FOLDER='A:\\RECORDER\\261011_130947';MASTER=FOLDER+'\\MASTER.WAV'
def take_master(n):return f'A:\\RECORDER\\261011_14{n:04d}\\MASTER.WAV'
def config(p):return CONFIG+0x798+p*0x20a
NOT_FOUND,EXISTS=0xffffd75a,0xffffd75b

def stock_master(data_bytes,rate=48000,channels=2,tag=3,stale=False,bits=32):
    """Header as stock postprocess leaves it: fmt at 12, PAD to 902, data."""
    h=bytearray(b'RIFF')+struct.pack('<I',902+data_bytes)+b'WAVEfmt '
    h+=struct.pack('<IHHIIHH',16,tag,channels,rate,rate*channels*bits//8,channels*bits//8,bits)
    h+=b'PAD '+struct.pack('<I',858)+bytes(858)+b'data'+struct.pack('<I',0 if stale else data_bytes)
    assert len(h)==910;return (910+data_bytes,bytes(h)+bytes(1024))

def load(m,state=STATE):
    """Place the packed build's code and zeroed globals as the scatter would,
    and publish a zeroed state as startup_register does."""
    j=PACK['jumps'];m.uc.mem_write(j['candidate_code_start'],PACK['code'])
    m.uc.mem_write(j['globals_start'],bytes(j['globals_end']-j['globals_start']))
    layout=struct.unpack('<9I',bytes(m.uc.mem_read(N['mr_layout'],36)))
    assert layout[1:]==(OFF['revoked'],OFF['task'],OFF['handoff_state'],STOP_PATH,PATH,POSTED,NEXT,ASSIGNED),layout
    m.uc.mem_write(state,bytes(layout[0]));put32(m,N['mr_state'],state)
    return layout[0]
def normal_recording_state(m):
    m.uc.mem_write(0x801f5f00,b'\xff');put32(m,0x8077ce70,0x557)
    for ch in (0,1,2,4,6,8,10):put32(m,0x8077e87c+ch*4,0x1000+ch)

class MasterRig(PlacementRig):
    """Stock-only integration harness plus the master-reference build."""
    def __init__(self,catalogue=('BACKING.WAV','MASTER.WAV'),card=None,anchors=(1,2,3)):
        self.posts=[];self.delays=0;self.packet=(0,0,0,0);self.probes=[];self.faults={}
        self.card={MASTER:stock_master(20_000_000)} if card is None else card
        self.finalizing=[]
        PlacementRig.__init__(self,patched=False,enabled=False)
        m=self.m;m.uc.mem_map(0x23000000,0x100000);self.size=load(m)
        for p in PLAN['patches']:
            if p.get('adapter') in ('mr_admit_hook','mr_stop_hook'):m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
        putstr(m,TAKE_DIR,FOLDER)
        self.open_probes={};self.next_probe=900
        m.hooks.update({0x80074158:self.delay,0x80020690:self.receive_packet,
            0x80020ca0:lambda a:self.posts.append(tuple(a[:5])) or 0})
        open_stock,info_stock,close_stock=m.hooks[0x8005ffe8],m.hooks[0x8005ef40],m.hooks[0x8005c1f8]
        def open_(a):
            path=getstr(m,a[1])
            if not path.startswith('A:\\RECORDER\\'):return open_stock(a)
            assert (a[2],a[3])==(0,0x100),'read-only probe expected';self.probes.append(path)
            put32(m,a[0],0)
            if path in self.faults:return self.faults[path]
            if path not in self.card:return NOT_FOUND
            h=self.next_probe;self.next_probe+=1;self.open_probes[h]=path;put32(m,a[0],h);return 0
        def info(a):
            if a[0] not in self.open_probes:return info_stock(a)
            m.uc.mem_write(a[1],struct.pack('<4I',self.card[self.open_probes[a[0]]][0],0,0,0));return 0
        read_stock=m.hooks[0x80060620]
        def read(a):
            if a[0] not in self.open_probes:return read_stock(a)
            size,content=self.card[self.open_probes[a[0]]];data=content[:min(a[2],size)]
            m.uc.mem_write(a[1],data);put32(m,a[3],len(data));return 0
        # Stock finalize/postprocess (0x8000b698) is a modeled stub here; note
        # what the worker would see while it runs inside RecStop's callback.
        def finalize(a):self.finalizing.append((word(m,RECORDER_BUSY),self.field('stopped')));return 0
        m.hooks.update({0x80060620:read,0x8000b698:finalize})
        def close(a):
            if a[0] not in self.open_probes:return close_stock(a)
            del self.open_probes[a[0]];return 0
        m.hooks.update({0x8005ffe8:open_,0x8005ef40:info,0x8005c1f8:close})
        # Main side: original catalogue code for PAD1-4; models for the rest.
        # Pad 1 lists `catalogue`; pads in `anchors` (0-based) list the anchor.
        self.assigned=[];self.stopped=[];self.validated=[];self.validate_result={};self.playing=set()
        m.hooks[0x80008f00]=lambda a:0
        for pad in range(4):
            for fn in (0x8002a2e0,0x8002a428,0x8002a2c8):m.invoke(fn,[BASE+pad*STRIDE])
            putstr(m,BASE+pad*STRIDE+0x14,f'A:\\SOUND_PAD\\PAD{pad+1}')
            for name in catalogue if pad==0 else ('MASTER.WAV',) if pad in anchors else ():
                putstr(m,0x23001a00,name);assert m.invoke(0x80008dd8,[pad,0x23001a00,0])==0
            putstr(m,config(pad),'NO ASSIGN')
        self.pad_before=self.raw(BASE,0xb10) # takes must still leave the catalogue alone
        def validate(a):self.validated.append((getstr(m,a[0]),a[1],a[2]));return self.validate_result.get(a[1],0)
        # The stock loader saves the path later, on its task; by default the
        # load completes at once. With deferred loads the pending flag stays set
        # until complete_loads(), as Main's completion handler clears it.
        self.deferred=None
        def assign(a):
            self.assigned.append(dict(mode=a[0],path=getstr(m,a[1]),pointer=a[1],pad=a[2],index=a[3],count=a[4],option=a[5]))
            if self.deferred is None:putstr(m,config(a[2]),getstr(m,a[1]))
            else:self.deferred.append((a[2],getstr(m,a[1])));m.uc.mem_write(0x8044337f+a[2],b'\x01')
            return 0
        m.hooks.update({0x80009568:validate,0x80002440:lambda a:int(a[0] in self.playing),
                        0x80002d08:lambda a:self.stopped.append(a[0]) or 0,0x80008c68:assign})
    def redirect(self,address,name,always=False):
        # Deep stream registration is modeled; its checkpoint calls mr_admit,
        # the C entry of the 0x8000b158 adapter.
        if name=='ct_emulator_admit':
            def hook(uc,a,size,u):self.entries.append('mr_admit');uc.reg_write(A.UC_ARM_REG_PC,N['mr_admit'])
            self.m.uc.hook_add(UC_HOOK_CODE,hook,begin=address,end=address)
    def delay(self,a):self.delays+=1;return 0
    def receive_packet(self,a):self.m.uc.mem_write(a[0],struct.pack('<4I',*self.packet));return 0
    def field(self,name):return word(self.m,STATE+OFF[name])
    def set(self,name,value):put32(self.m,STATE+OFF[name],value)
    def text(self,offset):return getstr(self.m,STATE+offset)
    def pads(self):return [getstr(self.m,config(p)) for p in range(4)]
    def complete_loads(self):
        for pad,path in self.deferred:putstr(self.m,config(pad),path);self.m.uc.mem_write(0x8044337f+pad,b'\x00')
        self.deferred=[]
    def chain_take(self,path):
        """One later take with its master on the card, checked and delivered."""
        self.card[path]=stock_master(10**6);self.quick_take(path[:-len('\\MASTER.WAV')])
        self.settle();self.deliver();assert self.field('handoff_state')==H_ASSIGNED
    def step(self):return self.m.invoke(N['mr_worker_step'],[])
    def main_receive(self,*packet):
        self.packet=packet;self.delays=0
        return self.m.invoke(N['mr_main_receive'],[PACKET])
    def deliver(self,serial=None):
        _,magic,posted,_,_=self.posts[-1]
        self.main_receive(3,magic,posted if serial is None else serial,0)
    def count(self,pad=0):return self.m.invoke(0x80008ee8,[pad])
    def take(self,folder=FOLDER,blocks=6,busy_after=False):
        """One ordinary stock take; the worker polls during it."""
        putstr(self.m,TAKE_DIR,folder)
        self.audio_call();self.begin_recording(2);probes=len(self.probes)
        for _ in range(blocks):
            self.audio_call();assert self.step() in (0,10) and len(self.probes)==probes
        data=self.stop_recording()
        if busy_after:put32(self.m,RECORDER_BUSY,1)
        self.assert_ordinary();return {h:bytes(self.files[h]) for h in range(1,8)}
    def quick_take(self,folder):
        """A later take through the adapter C entries (the stock rig records once)."""
        normal_recording_state(self.m);putstr(self.m,TAKE_DIR,folder)
        self.m.invoke(N['mr_admit'],[]);assert self.field('stock_recording')==1
        self.m.invoke(N['mr_stop'],[0,REC_STOP])
    def settle(self,limit=4):
        for _ in range(limit):
            if self.step()!=10:return
        raise AssertionError('worker still waiting')

class MasterBoot(Boot):
    """Original reset/scatter/startup with the packed build and native heap."""
    def __init__(self):
        j=PACK['jumps']
        super().__init__(pack=PACK,names=dict(N,native_worker_entry=0),patches=PLAN['patches'])
        m=self.m;m.hooks.pop(0x8006de78)
        m.hooks[0x80074780]=lambda a:0;m.hooks[0x80077540]=lambda a:0
        original=m.hooks[0x80076c60];self.created=[];self.added_writes=[]
        def create(a):
            if a[0]!=N['mr_worker_entry']:return original(a)
            self.created.append((bytes(m.uc.mem_read(a[1],9)),a[2],a[4]));put32(m,a[5],0x7f00);return 1
        m.hooks[0x80076c60]=create
        code=(j['candidate_code_start'],j['candidate_load_end'])
        def added(uc,access,address,size,value,u):
            if code[0]<=uc.reg_read(A.UC_ARM_REG_PC)<code[1]:self.added_writes.append((address,size))
        m.uc.hook_add(UC_HOOK_MEM_WRITE,added,begin=0x80000000,end=0x81ffffff)

def reload_rig(pad1_names,assigned):
    """Original reload/assignment/save/load harness; pad 1 configured to a path."""
    r=V.ReloadRig();m=r.m;m.hooks[0x80002b00]=lambda a:0
    for fn in (0x8002a2e0,0x8002a428,0x8002a2c8):m.invoke(fn,[BASE])
    putstr(m,BASE+0x14,'A:\\SOUND_PAD\\PAD1')
    template=r.files[r.take(800)];r.files[MASTER]=bytearray(template)
    for name in pad1_names:
        r.files['A:\\SOUND_PAD\\PAD1\\'+name]=bytearray(template)
        putstr(m,0x21005000,name);assert m.invoke(0x80008dd8,[0,0x21005000,0])==0
    putstr(m,CONFIG+0x798,assigned);return r
def sampler(r):return getstr(r.m,0x807348d0+0x20),r.m.uc.mem_read(0x807348d0,1)[0]

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))

    # Original take naming (collision bump included) fills 0x8060ff80; at
    # RecStop our path equals the stock recorder's own master path.
    m=Machine();CAT=0x806b3954;m.invoke(0x800088d0,[]);putstr(m,CAT+0x14,'A:\\RECORDER')
    def clock(a):m.uc.mem_write(a[0],struct.pack('<HBBBBB',2026,10,11,13,9,46));return 0
    made=[]
    def mkdir(a):made.append(getstr(m,a[0]));return EXISTS if made[-1]=='261011_130946' else 0
    m.hooks.update({0x80008a88:clock,0x8005e718:lambda a:32768,0x8005e708:lambda a:0,0x8005f3d0:mkdir,
        0x8000be30:lambda a:(m.uc.mem_write(a[0]+6,bytes([47])),0)[1],0x80008939:lambda a:0})
    m.invoke(0x800485b0,[0x2003f000]);assert m.invoke(0x80008848,[0x2003f000,1])==0
    index=m.invoke(0x80008880,[]);m.invoke(0x80022de0,[m.invoke(0x800088a8,[index&0xffff])])
    assert made==['261011_130946','261011_130947'] and getstr(m,TAKE_DIR)==FOLDER
    recorder_master=getstr(m,m.invoke(0x80022c80,[10,1]));stock_second=getstr(m,m.invoke(0x80022c80,[10,2]))
    # This machine is not M-profile (no IPSR), so admission is set directly.
    state=0x80f00000;load(m,state);put32(m,state+OFF['open_take'],1)
    m.invoke(N['mr_stop'],[0,REC_STOP])
    assert getstr(m,state+STOP_PATH)==recorder_master==MASTER and word(m,state+OFF['stopped'])==1
    assert stock_second==FOLDER+'\\MASTER_01.WAV'
    passed('take_folder_from_original_naming_gives_the_stock_master_path_at_RecStop',
           master=recorder_master,second_part=stock_second)

    # A real stock take: stock files unchanged; the worker waits for RecStop's
    # callback to end, probes read-only, posts; Main assigns via the anchor.
    ordinary=record(IntegrationRig(enabled=False),delay=2,blocks=6)
    r=MasterRig();before=r.count()
    assert r.take(busy_after=True)==ordinary
    # Inside the original RecPlayCtl dispatch, finalize runs after the stop
    # was published and while the stock busy word is set; it is clear after.
    assert r.finalizing==[(1,1)],r.finalizing
    assert r.field('admitted')==1 and r.field('stopped')==1 and r.field('stock_recording')==0
    assert r.text(STOP_PATH)==MASTER
    for _ in range(3):assert r.step()==10
    assert not r.probes and not r.posts
    put32(r.m,RECORDER_BUSY,0);assert r.step()==0
    assert r.probes==[MASTER,FOLDER+'\\MASTER_01.WAV'] and not r.open_probes
    assert r.field('last_status')==OK and r.field('master_bytes')==20_000_910 and r.field('file_open')==0
    assert r.field('handoff_state')==H_POSTED and r.posts==[(3,MAGIC,1,0,0)]
    r.deliver()
    assert r.field('handoff_state')==H_ASSIGNED and r.field('handoff_result')==0 and r.count()==before
    a=r.assigned[0];assert (a['mode'],a['path'],a['pad'],a['index'],a['count'],a['option'])==(0,MASTER,0,1,2,1)
    assert a['pointer']==STATE+ASSIGNED and r.validated==[(MASTER,0,1)] and not r.stopped and len(r.assigned)==1
    assert r.field('chain_mask')==1 and r.pads()==[MASTER,'NO ASSIGN','NO ASSIGN','NO ASSIGN']
    passed('ordinary_take_assigns_its_stock_master_to_pad_1_through_the_anchor_entry',assignment=dict(a,pointer=hex(a['pointer'])))

    # Repeats and stale serials do nothing; a second take replaces the first.
    r.deliver();r.deliver(serial=0);assert len(r.assigned)==1
    second='A:\\RECORDER\\261011_131500';r.card[second+'\\MASTER.WAV']=stock_master(5_000_000)
    r.quick_take(second);r.settle();r.deliver()
    assert [(x['pad'],x['path'],x['index'],x['count']) for x in r.assigned[1:]]==[(1,MASTER,0,1),(0,second+'\\MASTER.WAV',1,2)]
    assert r.assigned[1]['pointer']==STATE+ASSIGNED+160 and r.field('handoff_serial')==2 and r.field('chain_mask')==3
    passed('repeated_events_are_ignored_and_a_new_take_moves_the_previous_one_to_pad_2')

    # The chain over five takes from hand-picked pads: each take moves one pad
    # along; a hand-picked sound is overwritten, never carried; the oldest
    # take drops off pad 4.
    r=MasterRig();hand=['A:\\SOUND_PAD\\PAD1\\GLORY_BOX.WAV','A:\\SOUND_PAD\\PAD2\\OD_X.WAV','A:\\SOUND_PAD\\PAD3\\OD_Y.WAV','NO ASSIGN']
    for p,path in enumerate(hand):putstr(r.m,config(p),path)
    t=[take_master(n) for n in range(1,6)];history=[]
    for n in range(5):
        r.chain_take(t[n]);history.append((r.pads(),r.field('chain_mask')))
    assert history==[([t[0],hand[1],hand[2],hand[3]],1),([t[1],t[0],hand[2],hand[3]],3),
                     ([t[2],t[1],t[0],hand[3]],7),([t[3],t[2],t[1],t[0]],15),([t[4],t[3],t[2],t[1]],15)],history
    assert [x['pad'] for x in r.assigned[-4:]]==[3,2,1,0]   # oldest first
    # A hand-picked pad between takes is overwritten; no take repeats or is
    # lost. Repeated takes collapse; pads already right are left alone.
    cases_after={}
    for label,before,new,after,mask in (
            ('hand_on_pad_1',['A:\\SOUND_PAD\\PAD1\\H.WAV',t[2],t[1],t[0]],t[4],[t[4],t[2],t[1],t[0]],0b1),
            ('hand_on_pad_2',[t[3],'A:\\SOUND_PAD\\PAD2\\H.WAV',t[1],t[0]],t[4],[t[4],t[3],t[1],t[0]],0b11),
            ('repeat',[t[0],t[0],'NO ASSIGN','NO ASSIGN'],t[1],[t[1],t[0],'NO ASSIGN','NO ASSIGN'],0b1)):
        r=MasterRig()
        for p,path in enumerate(before):putstr(r.m,config(p),path)
        r.chain_take(new);assert r.pads()==after and r.field('chain_mask')==mask,(label,r.pads())
        cases_after[label]=r.pads()
    passed('takes_move_one_pad_along_per_take_overwriting_hand_picked_pads_and_dropping_the_oldest',
           pads_after_each_take=[h[0] for h in history],other_cases=cases_after)

    # An earlier shift still loading (its paths not yet saved) defers the next
    # one until Main has handled every completion.
    r=MasterRig();r.deferred=[];r.card[t[0]]=stock_master(10**6);r.quick_take(t[0][:-11]);r.settle();r.deliver()
    assert r.pads()[0]=='NO ASSIGN' and len(r.assigned)==1
    r.card[t[1]]=stock_master(10**6);r.quick_take(t[1][:-11]);r.settle();r.deliver()
    assert r.field('handoff_state')==H_POSTED and len(r.assigned)==1
    r.complete_loads();r.deliver()
    assert r.field('handoff_state')==H_ASSIGNED and [(x['pad'],x['path']) for x in r.assigned[1:]]==[(1,t[0]),(0,t[1])]
    passed('a_shift_waits_while_earlier_assignments_are_still_loading')

    # PlayStop and pad-record takes are not ordinary takes.
    r=MasterRig();r.audio_call();r.begin_recording(2);r.audio_call()
    r.m.invoke(N['mr_stop'],[0,PLAY_STOP]);assert r.field('stock_recording')==1 and r.field('stopped')==0
    r.stop_recording();assert r.field('stopped')==1
    r=MasterRig();normal_recording_state(r.m);r.m.uc.mem_write(0x801f5f00,b'\x00') # pad record target
    r.m.invoke(N['mr_admit'],[]);r.m.invoke(N['mr_stop'],[0,REC_STOP])
    assert r.field('admitted')==0 and r.field('stopped')==0;r.settle();assert not r.posts and not r.probes
    # A take cut off without a setter call (card cleanup) leaves open_take;
    # the next admission, ordinary or not, closes it.
    r=MasterRig();normal_recording_state(r.m);r.m.invoke(N['mr_admit'],[])
    r.m.uc.mem_write(0x801f5f00,b'\x00');r.m.invoke(N['mr_admit'],[])
    assert r.field('open_take')==0 and r.field('stock_recording')==0
    r.m.invoke(N['mr_stop'],[0,REC_STOP]);assert r.field('stopped')==0
    # A storage change during the take refuses it at RecStop.
    r=MasterRig();normal_recording_state(r.m);r.m.invoke(N['mr_admit'],[]);r.main_receive(0,0,0x32,0)
    r.m.invoke(N['mr_stop'],[0,REC_STOP]);assert r.field('stopped')==0 and r.field('stop_faults')==1
    passed('only_RecStop_ends_an_ordinary_take_and_cut_off_or_revoked_takes_are_not_published')

    # The worker refuses anything but one complete, unsplit master in the
    # same folder, and never posts for it.
    refusals={}
    for label,card,faults,status in (('missing',{},{},MISSING),
            ('split',{MASTER:stock_master(2**31-4096),FOLDER+'\\MASTER_01.WAV':stock_master(10**6)},{},SPLIT),
            ('io',{MASTER:stock_master(10**6)},{MASTER:0xffffd825},IO),
            ('44.1_kHz',{MASTER:stock_master(10**6,rate=44100)},{},FORMAT),
            ('mono',{MASTER:stock_master(10**6,channels=1)},{},FORMAT),
            ('stale_header',{MASTER:stock_master(10**6,stale=True)},{},FORMAT),
            ('truncated',{MASTER:(500,stock_master(10**6)[1])},{},FORMAT),
            ('not_wav',{MASTER:(10**6,bytes(1024))},{},FORMAT),
            ('under_2_s_float',{MASTER:stock_master(96000*8-8)},{},SHORT),
            ('under_2_s_16_bit',{MASTER:stock_master(96000*4-4,tag=1,bits=16)},{},SHORT)):
        r=MasterRig(card=card);r.faults=faults;r.take();r.settle()
        assert r.field('last_status')==status and r.field('refused')==1 and not r.posts and not r.open_probes,label
        refusals[label]=status
    # Exactly 2 s (96,000 frames) is enough, in either format.
    for size,tag,bits in ((96000*8,3,32),(96000*4,1,16)):
        r=MasterRig(card={MASTER:stock_master(size,tag=tag,bits=bits)});r.take();r.settle()
        assert r.field('last_status')==OK and r.posts,bits
    r=MasterRig();r.take();r.main_receive(0,0,0x33,0);r.settle()
    assert r.field('last_status')==REVOKED and not r.probes and not r.posts
    passed('missing_split_unreadable_wrong_format_stale_short_or_revoked_masters_are_refused',refusals=refusals)

    # Folder text that is not a RECORDER take, or too long, is never published.
    r=MasterRig();folder='A:\\RECORDER\\'+'X'*51;assert len(folder)==63   # longest accepted
    r.card[folder+'\\MASTER.WAV']=stock_master(10**6);r.take(folder=folder);r.settle()
    assert r.field('stopped')==1 and r.field('last_status')==OK and r.probes[-1]==folder+'\\MASTER_01.WAV'
    for folder in ('A:\\SOUND_PAD\\PAD2','A:\\RECORDER\\'+'X'*52,''):
        r=MasterRig();r.take(folder=folder)
        assert r.field('stopped')==0 and r.field('stop_faults')==1;r.settle();assert not r.posts
    passed('only_bounded_RECORDER_take_folders_are_published_at_RecStop')

    # Main: anchor checks, busy/recording waits, record target, revocation,
    # validation and a playing pad, as the Editor select does.
    r=MasterRig(catalogue=('BACKING.WAV',));r.take();r.settle();r.deliver()
    assert r.field('handoff_state')==H_FAILED and r.field('handoff_result')==3 and not r.assigned and r.count()==1
    r=MasterRig();putstr(r.m,BASE+0x14,'A:\\SOUND_PAD\\PAD2');r.pad_before=r.raw(BASE,0xb10);r.take();r.settle();r.deliver()
    assert r.field('handoff_result')==4 and not r.assigned
    r=MasterRig();r.validate_result={0:4};r.take();r.settle();r.deliver()
    assert r.field('handoff_state')==H_FAILED and r.field('handoff_result')==0x104 and not r.assigned
    # The chain ends at the first pad without an anchor (only PAD1's: pad 1
    # alone, as experiment 24). A format problem on any pad refuses the shift.
    r=MasterRig(anchors=(1,2));putstr(r.m,config(0),MASTER);putstr(r.m,config(1),take_master(9));putstr(r.m,config(2),take_master(8))
    r.chain_take(take_master(1));assert r.pads()==[take_master(1),MASTER,take_master(9),'NO ASSIGN']
    r=MasterRig(anchors=());putstr(r.m,config(0),MASTER);r.chain_take(take_master(1))
    assert r.pads()==[take_master(1),'NO ASSIGN','NO ASSIGN','NO ASSIGN'] and r.field('chain_mask')==1
    r=MasterRig();putstr(r.m,config(0),MASTER);putstr(r.m,config(1),take_master(9));r.validate_result={2:4}
    r.card[take_master(1)]=stock_master(10**6);r.quick_take(take_master(1)[:-11]);r.settle();r.deliver()
    assert r.field('handoff_result')==0x2104 and not r.assigned and r.pads()[:3]==[MASTER,take_master(9),'NO ASSIGN']
    passed('the_chain_ends_at_the_first_pad_without_an_anchor_and_any_format_problem_refuses_the_shift')
    r=MasterRig();r.take();r.settle()
    r.set('stock_recording',1);r.deliver();assert r.field('handoff_state')==H_POSTED
    r.set('stock_recording',0);put32(r.m,RECORDER_BUSY,1);r.deliver();assert r.field('handoff_state')==H_POSTED
    put32(r.m,RECORDER_BUSY,0);r.playing={0,3};r.deliver()
    assert r.field('handoff_state')==H_ASSIGNED and r.stopped==[0] and len(r.assigned)==1  # pad 4 is not reassigned
    r=MasterRig();putstr(r.m,config(0),take_master(9));r.playing={0,1,2};r.take();r.settle();r.deliver()
    assert r.stopped==[0,1] and [x['pad'] for x in r.assigned]==[1,0]
    for target in (b'\x00',b'\x03'):
        r=MasterRig();r.take();r.settle();r.m.uc.mem_write(0x801f5f00,target);r.deliver()
        assert r.field('handoff_state')==H_SKIPPED and r.field('handoff_result')==2 and not r.assigned
    r=MasterRig();r.take();r.settle();r.main_receive(1,0,3,0);r.deliver()
    assert r.field('handoff_state')==H_SKIPPED and r.field('handoff_result')==5 and not r.assigned
    passed('handoff_waits_for_the_recorder_stops_reassigned_playing_pads_and_skips_target_or_storage_change')
    # Main blocks in the validator (it reads the anchor); meanwhile the worker
    # supersedes and posts serial 2. Serial 1 is dropped without touching 2.
    r=MasterRig();r.take();r.settle()
    def validate(a):
        r.set('handoff_serial',2);putstr(r.m,STATE+POSTED,'A:\\RECORDER\\261011_131500\\MASTER.WAV');return 0
    r.m.hooks[0x80009568]=validate;r.main_receive(3,MAGIC,1,0)
    assert not r.assigned and r.field('handoff_state')==H_POSTED and r.field('handled')==1
    r.m.hooks[0x80009568]=lambda a:0;r.main_receive(3,MAGIC,2,0)
    assert [x['path'] for x in r.assigned]==['A:\\RECORDER\\261011_131500\\MASTER.WAV'] and r.field('handoff_state')==H_ASSIGNED
    passed('a_serial_superseded_while_Main_is_blocked_is_dropped_without_affecting_the_newer_one')

    # A newer take supersedes an unhandled post; reposts, then LOST.
    r=MasterRig();r.take();r.settle();assert r.field('handoff_state')==H_POSTED
    r.set('stock_recording',1);r.deliver()            # Main defers while the next take records
    r.set('stock_recording',0);second='A:\\RECORDER\\261011_131500';r.card[second+'\\MASTER.WAV']=stock_master(10**6)
    r.quick_take(second);put32(r.m,RECORDER_BUSY,1)   # RecStop still finalizing
    assert r.step()==10 and r.field('handoff_state')==H_SUPERSEDED
    r.main_receive(3,MAGIC,1,0);assert not r.assigned  # the old serial is never assigned
    put32(r.m,RECORDER_BUSY,0);r.settle();assert r.field('handoff_serial')==2;r.deliver();assert [x['path'] for x in r.assigned]==[second+'\\MASTER.WAV']
    r=MasterRig();r.take();r.settle()
    for _ in range(29*40):r.step()
    assert len(r.posts)==30 and r.field('handoff_state')==H_POSTED
    for _ in range(40):r.step()
    assert r.field('handoff_state')==H_LOST;r.deliver();assert not r.assigned
    passed('newer_takes_supersede_unhandled_posts_and_unhandled_posts_end_lost',posts=30)

    # Storage packets wait (bounded, once per stuck probe) for an open probe.
    r=MasterRig();r.set('file_open',1);r.main_receive(0,0,0x34,0)
    assert r.delays==500 and r.field('main_timed_out')==1;r.main_receive(0,0,0x35,0);assert r.delays==0
    r.set('file_open',0);r.main_receive(2,0,0xa2,0);assert r.delays==0 and r.field('main_timed_out')==0
    assert r.field('revoked')==3 and r.field('revoke_packet')==0x200a2
    passed('storage_packets_revoke_and_wait_boundedly_for_an_open_probe')

    # Original reload, assignment and settings code: with the anchor the
    # reference survives the queued assignment, a save, a cold-boot load and
    # the reload rescan; without it, any other PAD1 file replaces it.
    r=reload_rig(['BACKING.WAV','MASTER.WAV'],'NO ASSIGN');putstr(r.m,0x21006000,MASTER)
    r.m.uc.mem_write(0x21007000,struct.pack('<6I',0,0x21006000,0,1,2,1))  # as 0x80008c68 queues it
    r.m.invoke(0x80049d60,[0x21007000])
    assert r.paths()[0]==MASTER and sampler(r)==(MASTER,1)
    outcomes={}
    for names in (['MASTER.WAV'],['BACKING.WAV','MASTER.WAV'],['BACKING.WAV']):
        r=reload_rig(names,MASTER);m=r.m
        m.uc.mem_write(0x80445524,bytes(0xc34));assert m.invoke(0x80006b18,[])==0
        saved=bytes(r.files[SETTINGS][96:96+0x20a]).decode('utf-16le').split('\0')[0];assert saved==MASTER
        for p in range(4):putstr(m,CONFIG+0x798+p*0x20a,'NO ASSIGN')
        m.uc.mem_write(0x807348d0,bytes(0x22c));del m.hooks[0x80006410]
        r.run();r.consume();outcomes['+'.join(names)]=r.paths()[0]
    assert outcomes=={'MASTER.WAV':MASTER,'BACKING.WAV+MASTER.WAV':MASTER,
                      'BACKING.WAV':'A:\\SOUND_PAD\\PAD1\\BACKING.WAV'}
    # All four pads referencing takes, with an anchor in each folder.
    r=reload_rig(['BACKING.WAV','MASTER.WAV'],t[3]);m=r.m
    for p in range(1,4):
        putstr(m,0x21005000,'MASTER.WAV');assert m.invoke(0x80008dd8,[p,0x21005000,0])==0
        r.files[f'A:\\SOUND_PAD\\PAD{p+1}\\MASTER.WAV']=bytearray(r.files[MASTER])
    for p in range(4):r.files[t[3-p]]=bytearray(r.files[MASTER]);putstr(m,config(p),t[3-p])
    m.uc.mem_write(0x80445524,bytes(0xc34));assert m.invoke(0x80006b18,[])==0
    saved=[bytes(r.files[SETTINGS][96+p*0x20a:96+(p+1)*0x20a]).decode('utf-16le').split('\0')[0] for p in range(4)]
    for p in range(4):putstr(m,config(p),'NO ASSIGN')
    m.uc.mem_write(0x807348d0,bytes(0x22c*4));del m.hooks[0x80006410]
    r.run();r.consume()
    assert saved==[t[3],t[2],t[1],t[0]]==r.paths()[:4],(saved,r.paths())
    passed('anchors_keep_the_references_through_assignment_save_cold_boot_and_reload',after_reload=outcomes,chain=r.paths()[:4])

    b=MasterBoot();b.boot();j=PACK['jumps'];size=MasterRig().size
    g=b.word(N['mr_state']);assert b.created==[(b'L6PadRef\0',2048,1)] and b.word(N['mr_startup_status'])==4
    assert 0x808e2fe0<=g<0x8095ffd8 and bytes(b.m.uc.mem_read(g,size))==bytes(OFF['task'])+struct.pack('<I',0x7f00)+bytes(size-OFF['task']-4)
    assert b.added_writes and all(j['globals_start']<=a and a+n<=j['globals_end'] or g<=a and a+n<=g+size for a,n in b.added_writes)
    passed('original_startup_allocates_zeroed_state_on_the_native_heap_and_registers_the_worker',
           state=hex(g),state_bytes=size)

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=PLAN['elf_sha256'],limitations=PLAN['limitations']+[
            'Take start is modeled at the checkpoint; naming runs separately with a modeled clock and mkdir',
            'Probed files, the queued call validator, pad play/stop and the assignment queue are models in the take groups',
            'Worker steps and task preemption are explicit test actions, not RTOS scheduling',
            'The loader, RIFF parsing of a real master and pad playback are not executed'])
    (ROOT/'analysis/master_ref_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
