#!/usr/bin/env python3
"""Simplified pre-compressor capture: real DSP/recorder windows, offline only.

Original DSP tap/commit, stock record request/stop callbacks and the seven
stock writers execute. Files, queues and task scheduling are the existing
models; the worker is stepped explicitly. No device or card access.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_capture_placement import PlacementRig
from verify_capture_integration import IntegrationRig,record
from verify_capture_startup import Boot
from verify_uncompressed_tap import B,packed
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_record_catalogue import getstr
from verify_pad_protocol import ROOT,IMAGE
from capture_jump_patches import SCATTER,BIAS,symbols
from build_simple_capture import build
from plan_simple_capture import plan,ELF
from plan_capture_packing import packing

build();PLAN=plan();PACK=packing(ELF);N=symbols(ELF)
STATE=0x23000000;DESC=0x23001800;PACKET=0x23001900;HISTORY=0x23100000
FIELDS=('expected capacity staged frames epoch published_cursor age published_capacity '
        'take open_take stop_take abort_take start stop take_epoch take_revoked skipped event_faults '
        'revoked file_open state done cursor fifo_used bytes handle serial limit named '
        'completed failed last_status mask shift').split()
OFF={name:4*i for i,name in enumerate(FIELDS)};HIST=4*len(FIELDS)
PATH,HEADER,FIFO=176,256,768
REC_STOP=0x8004ba4d;PLAY_STOP=0x8004b91d
OK,REVOKED,TIMELINE,OVERRUN,ORDER,IO,NAME,EVENT,VERIFY=range(9)

class SimpleRig(PlacementRig):
    """Stock-only integration harness plus the simplified capture build."""
    def __init__(self,segments=8,per_segment=128,init=True):
        self.stream=[];self.extra_writes=[];self.delays=0;self.packet=(0,0,0,0)
        PlacementRig.__init__(self,patched=False,enabled=False)
        m=self.m;j=PACK['jumps']
        # The earlier composition is loaded by the base harness but never entered.
        m.uc.mem_write(j['candidate_code_start'],PACK['code'])
        m.uc.mem_write(j['globals_start'],bytes(j['globals_end']-j['globals_start']))
        source,dest,length,_=SCATTER;dsp=bytearray(IMAGE[source-BIAS:source-BIAS+length])
        for p in PLAN['DSP_patches']:dsp[p['site']-dest:p['site']-dest+p['bytes']]=bytes.fromhex(p['patch'])
        m.uc.mem_write(dest,bytes(dsp))
        for p in PLAN['patches']:
            if p.get('adapter') in ('sc_admit_hook','sc_stop_hook'):m.uc.mem_write(p['site'],bytes.fromhex(p['patch']))
        m.uc.mem_map(STATE,0x200000)
        m.hooks[0x80074158]=self.delay
        m.hooks[0x80020690]=self.receive_packet
        layout=struct.unpack('<11I',self.raw(N['sc_layout'],44))
        assert layout[1:]==(OFF['frames'],OFF['take'],OFF['revoked'],OFF['state'],OFF['completed'],
                            PATH,HEADER,FIFO,OFF['limit'],OFF['skipped']),layout
        self.size=layout[0]
        if init:
            m.uc.mem_write(DESC,struct.pack('<10I',*[HISTORY+i*per_segment*512 for i in range(segments)],
                                            *[0]*(8-segments),segments,per_segment))
            assert m.invoke(N['sc_init'],[STATE,DESC,1])==0 and word(m,N['sc_state'])==STATE
    def redirect(self,address,name,always=False):
        # Deep stream registration is modeled; its checkpoint calls sc_admit,
        # the C entry of the 0x8000b158 adapter. Earlier capture hooks stay off.
        if name=='ct_emulator_admit':
            def hook(uc,a,size,u):self.entries.append('sc_admit');uc.reg_write(A.UC_ARM_REG_PC,N['sc_admit'])
            self.m.uc.hook_add(UC_HOOK_CODE,hook,begin=address,end=address)
    def delay(self,a):self.delays+=1;return 0
    def receive_packet(self,a):
        self.m.uc.mem_write(a[0],struct.pack('<4I',*self.packet));return 0
    def io_write(self,a):
        if a[0] in self.opened:self.extra_writes.append((self.opened[a[0]][1],a[2]))
        return super().io_write(a)
    def audio_call(self):
        s=self.sequence
        left=[(s+i-32)/2048+(s+i)/4096 for i in range(64)]
        right=[(s+i+1-32)/2048-(s+i+16)/4096 for i in range(64)]
        super().audio_call()
        self.stream.extend(v for pair in zip(left,right) for v in pair)
    def field(self,name):return word(self.m,STATE+OFF[name])
    def set(self,name,value):put32(self.m,STATE+OFF[name],value)
    def step(self):return self.m.invoke(N['sc_worker_step'],[])
    def stop(self,cursor,caller=REC_STOP):self.m.invoke(N['sc_stop'],[cursor,caller])
    def admit(self):self.m.invoke(N['sc_admit'],[])
    def opens(self):return sum(1 for c in self.calls if c in ('create','reopen'))
    def settle(self,limit=200):
        for _ in range(limit):
            if self.step()!=10:break
        assert self.field('state')==0
    def main_receive(self,*packet):
        self.packet=packet;self.delays=0
        return self.m.invoke(N['sc_main_receive'],[PACKET])
    def path(self):return getstr(self.m,STATE+PATH)
    def extra(self):return bytes(self.disk[self.path()])
    def premaster(self,start,stop):return packed(self.stream[2*start:2*stop])

def take(r,delay=2,blocks=22,every=1):
    r.audio_call();r.begin_recording(delay)
    for i in range(blocks):
        r.audio_call()
        if i%every==every-1:r.step()
    data=r.stop_recording()
    for h in range(1,8):assert data[h]==packed(r.expected[h])
    r.assert_ordinary();r.settle()
    return {h:bytes(r.files[h]) for h in range(1,8)}

def valid_wav(data,frames):
    assert data[:4]==b'RIFF' and data[8:12]==b'WAVE' and struct.unpack_from('<I',data,4)[0]==len(data)-8
    assert struct.unpack_from('<HHIIHH',data,20)==(3,2,48000,384000,8,32)
    assert data[504:508]==b'data' and struct.unpack_from('<I',data,508)[0]==frames*8==len(data)-512

def sector_writes(r):
    """Every payload write is 4 KiB at a 512-aligned offset, except the last."""
    payload=[(pos,n) for pos,n in r.extra_writes if pos>=512]
    assert all(pos%512==0 and n==4096 for pos,n in payload[:-1]),payload
    assert payload[-1][0]%512==0
    return payload

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))

    assert PLAN['patch_sites']==12 and PLAN['packing']['spare_bytes']>0 and PLAN['globals_bytes']<=96
    assert not any(n.startswith(('ct_','rr_','bridge_','manager_','storage_','life_','sdp_')) for n in N)
    passed('twelve_byte_checked_sites_and_stock_decoder_packing_without_LZ4_or_source_reuse',
           code_bytes=PLAN['code_bytes'],globals_bytes=PLAN['globals_bytes'],
           spare_bytes=PLAN['packing']['spare_bytes'],sites=sorted(hex(p['site']) for p in PLAN['patches']+PLAN['DSP_patches']))

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2)
    r=SimpleRig();r.sequence=0
    assert take(r,delay=2)==ordinary
    start,stop=r.field('start'),r.field('stop');data=r.extra()
    assert stop-start==24*64 and data[512:]==packed(r.expected_extra)==r.premaster(start,stop)
    valid_wav(data,stop-start);writes=sector_writes(r)
    assert r.field('completed')==1 and r.field('last_status')==OK and not r.opened and r.field('file_open')==0
    assert r.path().startswith('A:\\SOUND_PAD\\PAD1\\OD_') and r.path().endswith('.TMP')
    passed('stock_start_and_stop_cursors_give_exact_extra_file_beside_seven_byte_identical_stock_files',
           frames=stop-start,payload_writes=writes,extra_sha256=hashlib.sha256(data).hexdigest())

    # Finding: a partial first block misaligned every later write. The FIFO
    # writes whole 4-KiB chunks whatever the start and stop offsets are.
    r=SimpleRig();r.sequence=0
    for _ in range(6):r.audio_call()
    put32(r.m,0x80443154,(word(r.m,B+0x53e4)-100)%256)
    r.m.invoke(N['sc_admit'],[]);assert r.field('take')==1
    for i in range(40):
        r.audio_call()
        if i%3==2:r.step()
    r.stop((word(r.m,B+0x53e4)-37)%256);r.settle()
    start,stop=r.field('start'),r.field('stop');assert start%64 and stop%64
    data=r.extra();assert data[512:]==r.premaster(start,stop);valid_wav(data,stop-start)
    writes=sector_writes(r);assert len(writes)>=3
    passed('unaligned_start_and_stop_keep_every_payload_write_4KiB_and_sector_aligned',
           start_offset=start%64,stop_offset=stop%64,payload_writes=writes)

    # Finding: a stop arriving after the worker read "no stop" but before it
    # truncated cancelled valid takes. Preempt exactly after the block copy.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.m.invoke(N['sc_admit'],[])
    for _ in range(4):r.audio_call()
    assert r.step()==10 and r.field('state')==1
    cursor=r.field('cursor');target=cursor+10;reads=[0]
    def preempt(uc,access,address,size,value,u):
        reads[0]+=1
        if reads[0]==2: # sc_stop runs here, after the copy, before the stop re-read
            uc.mem_write(STATE+OFF['stop'],struct.pack('<I',target))
            uc.mem_write(STATE+OFF['stop_take'],struct.pack('<I',1))
    h=r.m.uc.hook_add(UC_HOOK_MEM_READ,preempt,begin=STATE+OFF['frames'],end=STATE+OFF['frames']+3)
    try:r.step()
    finally:r.m.uc.hook_del(h)
    assert reads[0]>=2;r.settle()
    assert r.field('last_status')==OK and r.extra()[512:]==r.premaster(cursor,target)
    passed('stop_published_after_block_copy_truncates_instead_of_cancelling',frames=10)

    # Finding: the mailbox try-lock latched failures. Events are single-writer
    # fields; a second start while busy is skipped, never an error in the take.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.m.invoke(N['sc_admit'],[])
    for _ in range(4):r.audio_call()
    r.step();r.m.invoke(N['sc_admit'],[]) # missing stop: abort take 1, skip this start
    assert r.field('abort_take')==1 and r.field('skipped')==1 and r.field('take')==1
    r.settle();assert r.field('last_status')==EVENT and not r.opened
    r.m.invoke(N['sc_admit'],[]);assert r.field('take')==2
    for _ in range(3):r.audio_call()
    r.stop(word(r.m,B+0x53e4));r.settle()
    assert r.field('last_status')==OK and r.field('completed')==1
    r.stop(word(r.m,B+0x53e4)) # second stop callback: ignored
    assert r.field('event_faults')==0
    passed('missing_stop_aborts_only_that_take_and_next_take_completes_without_locks')

    # Lost history: worker held off past the history length.
    r=SimpleRig(segments=4,per_segment=1);r.sequence=0
    for _ in range(2):r.audio_call()
    r.m.invoke(N['sc_admit'],[]);assert r.step()==10
    for _ in range(6):r.audio_call()
    assert r.step()==1 and r.field('last_status')==OVERRUN and not r.opened and r.field('file_open')==0
    r.m.invoke(N['sc_admit'],[]);assert r.field('take')==2
    for _ in range(2):
        r.audio_call();r.step()
    r.stop(word(r.m,B+0x53e4));r.settle()
    assert r.field('last_status')==OK and r.extra()[512:]==r.premaster(r.field('start'),r.field('stop'))
    passed('overwritten_history_abandons_the_take_and_the_next_take_is_exact')

    # Finding: Main could wait forever after a failed close. Now one bounded
    # wait, one close attempt, and the file is forgotten.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.m.invoke(N['sc_admit'],[]);r.step();r.audio_call();r.step()
    r.inject=('close_write',1,'error') # e.g. the card was removed
    r.main_receive(0,0,0x33,0)
    assert r.delays==500 and r.field('revoked')==1 # worker cannot run in this model
    assert r.step()==1 and r.field('last_status')==REVOKED and r.field('file_open')==0 and not r.opened
    assert r.calls.count('close_write')==1 # attempted once, failed, forgotten
    r.main_receive(0,0,0x33,0);assert r.delays==0
    r.main_receive(3,0,0x33,0);assert r.delays==0 and r.field('revoked')==2
    for packet in ((0,0,0x31,0),(1,1,0,0),(2,0,0xa1,0)):r.main_receive(*packet)
    assert r.field('revoked')==2
    passed('storage_packet_waits_at_most_500_ticks_and_failed_close_never_blocks_Main',
           wait_ticks=500,classified=['0/x/32..35','1/0/0..5','2/x/a2,a3'])

    # Revocation between admission and file creation: no file is created.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.m.invoke(N['sc_admit'],[]);r.main_receive(1,0,2,0)
    assert r.step()==1 and r.field('last_status')==REVOKED and not r.disk
    passed('revocation_before_open_creates_no_file')

    # Timeline break: a skipped callback changes the epoch; the take is dropped.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.m.invoke(N['sc_admit'],[]);r.step()
    cursor=(word(r.m,B+0x53e4)+64)%256;put32(r.m,B+0x53e4,cursor);r.audio_cursor=cursor
    r.audio_call();assert r.step()==1 and r.field('last_status')==TIMELINE and not r.opened
    passed('audio_continuity_break_abandons_the_take')

    # Only an ordinary seven-stream recording starts a take.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.m.uc.mem_write(0x801f5f00,b'\x00');r.m.invoke(N['sc_admit'],[])
    r.m.uc.mem_write(0x801f5f00,b'\xff');put32(r.m,0x8077e87c+8*4,0);r.m.invoke(N['sc_admit'],[])
    assert r.field('take')==0
    passed('pad_recording_or_missing_stream_starts_no_take')

    # Write failure and verification failures end the take with closed files.
    for inject,corruption,status in ((('audio',1,'error'),None,IO),(None,'header',VERIFY),(None,'truncate',VERIFY)):
        r=SimpleRig();r.sequence=0;r.inject=inject;r.corruption=corruption
        for _ in range(3):r.audio_call()
        r.m.invoke(N['sc_admit'],[])
        for _ in range(12):
            r.audio_call();r.step()
        r.stop(word(r.m,B+0x53e4));r.settle()
        assert r.field('last_status')==status and r.field('failed')==1 and not r.opened and r.field('file_open')==0
    passed('write_and_verification_failures_close_the_file_and_report_status')

    # Finding: readback could be satisfied from cache. Lines are cleaned and
    # invalidated after the header read, covering exactly the read buffer.
    r=SimpleRig();r.sequence=0;lines=[]
    r.m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda uc,acc,a,s,v,u:lines.append(v),begin=0xe000ef70,end=0xe000ef73)
    for _ in range(3):r.audio_call()
    r.m.invoke(N['sc_admit'],[])
    for _ in range(3):
        r.audio_call();r.step()
    r.stop(word(r.m,B+0x53e4));r.settle()
    assert r.field('last_status')==OK and lines==list(range(STATE+FIFO,STATE+FIFO+512,32))
    passed('header_readback_cleans_and_invalidates_its_own_buffer_lines',lines=len(lines))

    # Reaching the size limit finishes a valid, shorter file instead of failing.
    r=SimpleRig();r.sequence=0;r.set('limit',8192)
    for _ in range(3):r.audio_call()
    r.m.invoke(N['sc_admit'],[])
    for _ in range(40):
        r.audio_call();r.step()
    r.settle();data=r.extra()
    assert r.field('last_status')==OK and len(data)==512+8192 and data[512:]==r.premaster(r.field('start'),r.field('start')+1024)
    passed('size_limit_finishes_a_valid_truncated_file')

    # Review follow-up: PlayStop also calls the stop setter; only RecStop counts.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.admit()
    for _ in range(3):
        r.audio_call();r.step()
    r.stop(word(r.m,B+0x53e4),PLAY_STOP)
    assert r.field('stop_take')==0 and r.field('open_take')==1 and r.field('state')==1
    r.stop(word(r.m,B+0x53e4));r.settle();assert r.field('last_status')==OK
    passed('playback_stop_through_the_shared_setter_does_not_end_a_take')

    # Review follow-up: names persist on the card across reboots. The first take
    # after boot finds a free serial in O(log n) probes; later takes probe once.
    r=SimpleRig();r.sequence=0
    for i in range(1,46):r.disk['A:\\SOUND_PAD\\PAD1\\OD_%08X.%s'%(i,'WAV' if i%3 else 'TMP')]=bytearray(b'x')
    def short_take():
        for _ in range(3):r.audio_call()
        r.admit();before=r.opens()
        for _ in range(2):
            r.audio_call();r.step()
        r.stop(word(r.m,B+0x53e4));r.settle()
        assert r.field('last_status')==OK
        return r.opens()-before
    first=short_take();assert r.path().endswith('OD_0000002E.TMP')
    second=short_take();assert r.path().endswith('OD_0000002F.TMP')
    assert first<=30 and second==4,(first,second)
    passed('existing_WAV_and_TMP_names_are_skipped_with_logarithmic_probing_after_boot',
           existing=45,first_take_opens=first,next_take_opens=second)

    # Review follow-up: the after-copy overwrite check, and its exact boundary.
    for lap,status in ((0,None),(64,OVERRUN)):
        r=SimpleRig();r.sequence=0
        for _ in range(3):r.audio_call()
        r.admit();r.step();r.audio_call()
        base=r.field('cursor')&~63;history=r.field('mask')*64;reads=[0]
        def lapped(uc,acc,a,size,v,u,lap=lap,base=base,history=history):
            reads[0]+=1
            if reads[0]==2:uc.mem_write(STATE+OFF['frames'],struct.pack('<I',base+history+lap))
        h=r.m.uc.hook_add(UC_HOOK_MEM_READ,lapped,begin=STATE+OFF['frames'],end=STATE+OFF['frames']+3)
        try:result=r.step()
        finally:r.m.uc.hook_del(h)
        if status:assert result==1 and r.field('last_status')==status and not r.opened
        else:assert r.field('state')==1 and r.field('failed')==0
    passed('slot_reused_during_copy_is_detected_and_the_last_safe_frame_is_accepted')

    # Review follow-up: 32-bit frame counters wrap after 24.85 hours of audio.
    r=SimpleRig();F0=(1<<32)-5*64;r.set('frames',F0);r.sequence=0
    for _ in range(3):r.audio_call()
    r.set('age',0x7fffffc0) # long uptime: age saturates instead of wrapping
    r.admit()
    for _ in range(12):
        r.audio_call();r.step()
    r.stop(word(r.m,B+0x53e4));r.settle()
    start,stop=r.field('start'),r.field('stop')
    assert r.field('age')==0x80000000 and stop<start and r.field('last_status')==OK
    assert r.extra()[512:]==r.premaster((start-F0)%2**32,(stop-F0)%2**32)
    passed('take_spanning_the_32_bit_frame_wrap_after_long_uptime_is_exact')

    # Review follow-up: a continuity break after the stop no longer drops the take.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.admit();r.step()
    for _ in range(6):r.audio_call()
    r.stop(word(r.m,B+0x53e4))
    cursor=(word(r.m,B+0x53e4)+64)%256;put32(r.m,B+0x53e4,cursor);r.audio_cursor=cursor
    for _ in range(2):r.audio_call()
    r.settle();assert r.field('last_status')==OK and r.extra()[512:]==r.premaster(r.field('start'),r.field('stop'))
    passed('continuity_break_while_draining_after_stop_keeps_the_take')

    # Review follow-up: revocation during name probing creates no file.
    r=SimpleRig();r.sequence=0
    for _ in range(3):r.audio_call()
    r.admit();original=r.m.hooks[0x8005ffe8]
    def open_then_revoke(a):
        result=original(a);put32(r.m,STATE+OFF['revoked'],r.field('revoked')+1);return result
    r.m.hooks[0x8005ffe8]=open_then_revoke
    assert r.step()==1 and r.field('last_status')==REVOKED and not r.disk and 'create' not in r.calls
    passed('revocation_during_name_probing_stops_before_creating_a_file')

    # Startup: one allocation, worker created before publication.
    for create,status in ((1,4),(0,3)):
        r=SimpleRig(init=False);m=r.m;made=[]
        m.hooks[0x8006de78]=lambda a:STATE+4
        def created(a,create=create):
            made.append((a[0],bytes(m.uc.mem_read(a[1],10)),a[2],a[4]))
            put32(m,a[5],0x7f00);return create
        m.hooks[0x80076c60]=created
        m.invoke(N['startup_register'],[]);assert word(m,N['sc_state'])==0 and not made
        m.invoke(N['startup_observe'],[0,0]);m.invoke(N['startup_register'],[])
        assert made==[(N['sc_worker_entry'],b'L6Capture\0',4096,1)] and word(m,N['sc_startup_status'])==status
        assert word(m,N['sc_state'])==(STATE+32 if create else 0)
        if create:
            tails=struct.unpack('<8I',r.raw(STATE+32+HIST,32))
            assert tails==tuple(0x81429800+i*960000+223104*4 for i in range(8))
    passed('startup_allocates_once_and_publishes_only_after_worker_creation')

    class SimpleBoot(Boot):
        def __init__(self):
            names=dict(N,native_worker_entry=0)
            super().__init__(pack=PACK,names=names,patches=PLAN['patches'])
            m=self.m;m.hooks.pop(0x8006de78) # original native heap allocator
            m.hooks[0x80074780]=lambda a:0;m.hooks[0x80077540]=lambda a:0
            original=m.hooks[0x80076c60];self.created=[]
            def create(a):
                if a[0]!=N['sc_worker_entry']:return original(a)
                self.created.append(bytes(m.uc.mem_read(a[1],10)));put32(m,a[5],0x7f00);return 1
            m.hooks[0x80076c60]=create
    b=SimpleBoot();b.boot()
    g=b.word(N['sc_state']);j=PACK['jumps']
    assert b.created==[b'L6Capture\0'] and b.word(N['sc_startup_status'])==4 and g and g%32==0
    assert all(j['globals_start']<=a and a+n<=j['globals_end'] for a,n in b.writes)
    assert struct.unpack('<2I',bytes(b.m.uc.mem_read(g+HIST+32,8)))==(8,128)
    passed('original_reset_scatter_and_startup_expand_the_build_and_register_the_worker',
           state=hex(g),state_bytes=r.size)

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=PLAN['elf_sha256'],limitations=PLAN['limitations']+[
            'Worker steps and task preemption are explicit test actions, not RTOS scheduling',
            'Deep stream registration is modeled; its checkpoint calls the 0x8000b158 adapter C entry',
            'Files are the synchronous in-memory model; SD timing, DMA and card removal are not physical'])
    (ROOT/'analysis/simple_capture_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
