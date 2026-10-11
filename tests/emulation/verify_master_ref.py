#!/usr/bin/env python3
"""Master reference: pad 1 plays the last take's stock MASTER.WAV in place.

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
from verify_record_catalogue import putstr,getstr,BASE
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
        'handoff_state handoff_result handoff_serial handoff_posts handoff_posted_at handoff_revoked').split()
OFF={n:4*i for i,n in enumerate(FIELDS)};STOP_PATH=4*len(FIELDS);PATH=STOP_PATH+160;POSTED=PATH+160;ASSIGNED=POSTED+160
OK,REVOKED,MISSING,SPLIT,IO,FORMAT=range(6)
NONE,H_POSTED,H_ASSIGNED,H_SKIPPED,H_FAILED,H_LOST,H_SUPERSEDED=range(7)
MAGIC=0x4c364d52;REC_STOP=0x8004ba4d;PLAY_STOP=0x8004b91d
TAKE_DIR=0x8060ff80;RECORDER_BUSY=0x80578ec0;PACKET=0x23001900
FOLDER='A:\\RECORDER\\261011_130947';MASTER=FOLDER+'\\MASTER.WAV'
NOT_FOUND,EXISTS=0xffffd75a,0xffffd75b

def stock_master(data_bytes,rate=48000,channels=2,tag=3,stale=False):
    """Header as stock postprocess leaves it: fmt at 12, PAD to 902, data."""
    h=bytearray(b'RIFF')+struct.pack('<I',902+data_bytes)+b'WAVEfmt '
    h+=struct.pack('<IHHIIHH',16,tag,channels,rate,rate*channels*4,channels*4,32)
    h+=b'PAD '+struct.pack('<I',858)+bytes(858)+b'data'+struct.pack('<I',0 if stale else data_bytes)
    assert len(h)==910;return (910+data_bytes,bytes(h)+bytes(1024))

def load(m):
    """Place the packed build's code and zeroed globals as the scatter would."""
    j=PACK['jumps'];m.uc.mem_write(j['candidate_code_start'],PACK['code'])
    m.uc.mem_write(j['globals_start'],bytes(j['globals_end']-j['globals_start']))
    layout=struct.unpack('<8I',bytes(m.uc.mem_read(N['mr_layout'],32)))
    assert layout[1:]==(OFF['revoked'],OFF['task'],OFF['handoff_state'],STOP_PATH,PATH,POSTED,ASSIGNED),layout
    return layout[0]
def normal_recording_state(m):
    m.uc.mem_write(0x801f5f00,b'\xff');put32(m,0x8077ce70,0x557)
    for ch in (0,1,2,4,6,8,10):put32(m,0x8077e87c+ch*4,0x1000+ch)

class MasterRig(PlacementRig):
    """Stock-only integration harness plus the master-reference build."""
    def __init__(self,catalogue=('BACKING.WAV','MASTER.WAV'),card=None):
        self.posts=[];self.delays=0;self.packet=(0,0,0,0);self.probes=[];self.faults={}
        self.card={MASTER:stock_master(20_000_000)} if card is None else card
        self.finalizing=[]
        PlacementRig.__init__(self,patched=False,enabled=False)
        m=self.m;self.size=load(m)
        for p in PLAN['patches']:
            if p.get('adapter') in ('mr_admit_hook','mr_stop_hook'):m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
        m.uc.mem_map(0x23000000,0x100000)
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
        # Main side: original catalogue code for PAD1; models for the rest.
        self.assigned=[];self.stopped=[];self.validated=[];self.validate_result=0;self.playing=0
        for fn in (0x8002a2e0,0x8002a428,0x8002a2c8):m.invoke(fn,[BASE])
        putstr(m,BASE+0x14,'A:\\SOUND_PAD\\PAD1');m.hooks[0x80008f00]=lambda a:0
        for name in catalogue:
            putstr(m,0x23001a00,name);assert m.invoke(0x80008dd8,[0,0x23001a00,0])==0
        self.pad_before=self.raw(BASE,0xb10) # takes must still leave the catalogue alone
        def validate(a):self.validated.append((getstr(m,a[0]),a[1],a[2]));return self.validate_result
        def assign(a):
            self.assigned.append(dict(mode=a[0],path=getstr(m,a[1]),pointer=a[1],pad=a[2],index=a[3],count=a[4],option=a[5]))
            return 0
        m.hooks.update({0x80009568:validate,0x80002440:lambda a:self.playing,
                        0x80002d08:lambda a:self.stopped.append(a[0]) or 0,0x80008c68:assign})
    def redirect(self,address,name,always=False):
        # Deep stream registration is modeled; its checkpoint calls mr_admit,
        # the C entry of the 0x8000b158 adapter.
        if name=='ct_emulator_admit':
            def hook(uc,a,size,u):self.entries.append('mr_admit');uc.reg_write(A.UC_ARM_REG_PC,N['mr_admit'])
            self.m.uc.hook_add(UC_HOOK_CODE,hook,begin=address,end=address)
    def delay(self,a):self.delays+=1;return 0
    def receive_packet(self,a):self.m.uc.mem_write(a[0],struct.pack('<4I',*self.packet));return 0
    def field(self,name):return word(self.m,N['mr_state']+OFF[name])
    def set(self,name,value):put32(self.m,N['mr_state']+OFF[name],value)
    def text(self,offset):return getstr(self.m,N['mr_state']+offset)
    def step(self):return self.m.invoke(N['mr_worker_step'],[])
    def main_receive(self,*packet):
        self.packet=packet;self.delays=0
        return self.m.invoke(N['mr_main_receive'],[PACKET])
    def deliver(self,serial=None):
        _,magic,posted,_,_=self.posts[-1]
        self.main_receive(3,magic,posted if serial is None else serial,0)
    def count(self):return self.m.invoke(0x80008ee8,[0])
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
    load(m);state=N['mr_state'];put32(m,state+OFF['open_take'],1)
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
    assert a['pointer']==N['mr_state']+ASSIGNED and r.validated==[(MASTER,0,1)] and not r.stopped
    passed('ordinary_take_assigns_its_stock_master_to_pad_1_through_the_anchor_entry',assignment=dict(a,pointer=hex(a['pointer'])))

    # Repeats and stale serials do nothing; a second take replaces the first.
    r.deliver();r.deliver(serial=0);assert len(r.assigned)==1
    second='A:\\RECORDER\\261011_131500';r.card[second+'\\MASTER.WAV']=stock_master(5_000_000)
    r.quick_take(second);r.settle();r.deliver()
    assert [x['path'] for x in r.assigned]==[MASTER,second+'\\MASTER.WAV'] and r.field('handoff_serial')==2
    passed('repeated_events_are_ignored_and_each_new_take_reassigns_pad_1')

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
            ('not_wav',{MASTER:(10**6,bytes(1024))},{},FORMAT)):
        r=MasterRig(card=card);r.faults=faults;r.take();r.settle()
        assert r.field('last_status')==status and r.field('refused')==1 and not r.posts and not r.open_probes,label
        refusals[label]=status
    r=MasterRig();r.take();r.main_receive(0,0,0x33,0);r.settle()
    assert r.field('last_status')==REVOKED and not r.probes and not r.posts
    passed('missing_split_unreadable_wrong_format_stale_or_revoked_masters_are_refused',refusals=refusals)

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
    r=MasterRig();r.validate_result=4;r.take();r.settle();r.deliver()
    assert r.field('handoff_state')==H_FAILED and r.field('handoff_result')==0x104 and not r.assigned
    passed('missing_or_misplaced_anchor_and_unsupported_format_are_refused_without_assigning')
    r=MasterRig();r.take();r.settle()
    r.set('stock_recording',1);r.deliver();assert r.field('handoff_state')==H_POSTED
    r.set('stock_recording',0);put32(r.m,RECORDER_BUSY,1);r.deliver();assert r.field('handoff_state')==H_POSTED
    put32(r.m,RECORDER_BUSY,0);r.playing=1;r.deliver()
    assert r.field('handoff_state')==H_ASSIGNED and r.stopped==[0] and len(r.assigned)==1
    r=MasterRig();r.take();r.settle();r.m.uc.mem_write(0x801f5f00,b'\x00');r.deliver()
    assert r.field('handoff_state')==H_SKIPPED and r.field('handoff_result')==2 and not r.assigned
    r=MasterRig();r.take();r.settle();r.main_receive(1,0,3,0);r.deliver()
    assert r.field('handoff_state')==H_SKIPPED and r.field('handoff_result')==5 and not r.assigned
    passed('handoff_waits_for_the_recorder_stops_a_playing_pad_and_skips_target_or_storage_change')
    # Main blocks in the validator (it reads the anchor); meanwhile the worker
    # supersedes and posts serial 2. Serial 1 is dropped without touching 2.
    r=MasterRig();r.take();r.settle()
    def validate(a):
        r.set('handoff_serial',2);putstr(r.m,N['mr_state']+POSTED,'A:\\RECORDER\\261011_131500\\MASTER.WAV');return 0
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
    passed('anchor_keeps_the_reference_through_assignment_save_cold_boot_and_reload',after_reload=outcomes)

    b=MasterBoot();b.boot();j=PACK['jumps']
    assert b.created==[(b'L6PadRef\0',2048,1)] and b.word(N['mr_startup_status'])==4
    assert b.added_writes and all(j['globals_start']<=a and a+n<=j['globals_end'] for a,n in b.added_writes)
    passed('original_reset_scatter_and_startup_expand_the_build_and_register_the_worker',
           state_bytes=MasterRig().size)

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=PLAN['elf_sha256'],limitations=PLAN['limitations']+[
            'Take start is modeled at the checkpoint; naming runs separately with a modeled clock and mkdir',
            'Probed files, the queued call validator, pad play/stop and the assignment queue are models in the take groups',
            'Worker steps and task preemption are explicit test actions, not RTOS scheduling',
            'The loader, RIFF parsing of a real master and pad playback are not executed'])
    (ROOT/'analysis/master_ref_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
