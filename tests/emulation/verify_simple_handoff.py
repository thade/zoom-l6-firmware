#!/usr/bin/env python3
"""Small compiled handoff, real manager/stock assignment, modeled fence/seal.
No device, filesystem rename or power-loss claim is made by this fixture.
"""
import json, struct
import verify_extra_capture as capture
from verify_pad_protocol import ROOT
capture.ELF=ROOT/'src/capture/handoff-test.elf'
from verify_extra_lifecycle import LifeRig, LIFE
from verify_session_manager import ManagerRig, MAN, LIVE
from verify_pad_publisher import PublisherRig, boundary
from verify_overdub_prototype import PORT
from verify_record_catalogue import getstr
from verify_firmware_workflow import put32
from verify_native_worker import WorkerRig, WORKER, CONFIG, SCHEDULER
from verify_session_handover import DESC
from verify_history_capture import payload

H=0x2201e000; HP=0x2102b500; SEAL=0x2102b600
NATIVE=0x2201f000; GATE=0x2102b700; CONVERT=0x2102b800

class Simple(PublisherRig):
    def __init__(self):
        c=ManagerRig();c.audio_call();boundary(c,10)
        super().__init__(c)
        self.seals=0;self.seal_status=0;self.fenced=True
        self.prefetch_reads=[];self.converted=[];self.read_failures=[]
        m=self.m
        for fn in (0x800368a8,0x800367b8,0x80036818,0x800367e8,0x800368d8,
                   0x80036800,0x80036938,0x80036950,0x800368f0,0x80036908,
                   0x80036920,0x800366f8,0x80036860,0x800368c0,0x800369a8):
            del m.hooks[fn]
        m.hooks[0x80074440]=lambda a:0
        m.invoke(0x80036688,[])
        for pad in range(4):m.invoke(0x800367d0,[pad,CONVERT|1])
        m.hooks[CONVERT]=self.convert
        for fn in (0x8001aaa0,0x8001aab8):m.hooks[fn]=lambda a:0
        # Install only in this synthetic CPU. No vendor image is written.
        m.uc.mem_write(0x8005c1f8,struct.pack('<2I',0xf000f8df,self.syms['bn_close_hook']|1))
        m.uc.ctl_remove_cache(0x8005c1f8,0x8005c208)
        m.hooks[SEAL]=lambda a:self.seal(a[1:])
        m.hooks[SEAL+4]=lambda a:self.enter([])
        m.hooks[SEAL+8]=lambda a:self.leave([])
        m.uc.mem_write(GATE,struct.pack('<4I',NATIVE,SEAL+5,SEAL+9,SEAL|1))
        self.nlayout=struct.unpack('<4I',m.uc.mem_read(self.syms['bn_layout'],16))
        assert m.invoke(self.syms['bn_init'],[NATIVE,GATE,HP])==0
        self.layout=struct.unpack('<4I',self.m.uc.mem_read(self.syms['backing_layout'],16))
        assert self.m.invoke(self.syms['backing_init'],[H,MAN,HP,0])==0
    def parse_wav(self,a):
        result=super().parse_wav(a)
        if result==0 and a[4]:
            data=self.files[self.handles[a[0]][0]];fmt=data.find(b'fmt ');offset=data.find(b'data')+8
            channels=struct.unpack_from('<H',data,fmt+10)[0];bits=struct.unpack_from('<H',data,fmt+22)[0]
            self.m.uc.mem_write(a[4],struct.pack('<Q',(len(data)-offset)//(channels*bits//8)))
        return result
    def read(self,a):
        h,buffer,size,out=a[:4]
        if 0x80735b80<=buffer<0x8077c580:
            self.prefetch_reads.append((self.handles[h][0],size))
            failure=self.read_failures.pop(0) if self.read_failures else None
            if failure=='error':put32(self.m,out,0);return 0xffffd825
            if failure=='short':
                a=list(a);a[2]-=1
        return super().read(a)
    def convert(self,a):
        buffer,frames,dest,pad,channels,width=a[:6]
        self.converted.append((pad,bytes(self.m.uc.mem_read(buffer,frames*channels*width))))
        return frames*channels*width
    def seal(self,a):
        assert self.locked
        self.seals+=1
        if self.seal_status:return self.seal_status
        src,dst=map(lambda p:getstr(self.m,p),a[:2])
        assert src.endswith('.TMP') and dst==src[:-3]+'WAV'
        if dst in self.files:return 2 # BP_SAFE: positively unchanged
        data=bytes(self.files[src]);assert data[:4]==b'RIFF'
        assert struct.unpack_from('<I',data,4)[0]==len(data)-8
        assert struct.unpack_from('<I',data,508)[0]==len(data)-512
        self.files[dst]=self.files.pop(src)
        assert bytes(self.files[dst])==data
        return 0
    def step(self):return self.m.invoke(self.syms['backing_step'],[H])
    def next(self):
        c=self.capture
        c.m.uc.mem_write(MAN,bytes(self.m.uc.mem_read(MAN,c.mlayout[0])))
        c.disk={p:bytearray(b) for p,b in self.files.items() if '\\OD_' in p}
        c.drive(lambda:c.mstate()==LIVE);boundary(c,3);self.sync_boundary()

def main():
    groups=[]
    def passed(s):groups.append(s)
    r=Simple();assert r.layout[0]<2048
    originals=[];untouched=r.paths()[1:]
    for _ in range(6):
        tmp=r.capture.result()[1];data=bytes(r.files[tmp]);originals.append((tmp[:-3]+'WAV',data))
        assert r.step()==0 and not r.locked
        assert r.paths()[0]==originals[-1][0] and r.paths()[1:]==untouched
        assert all(bytes(r.files[p])==b for p,b in originals)
        assert not r.counts.get('write',0) # no audio copies, only settings writes
        before=r.seals;assert r.step()==2 and r.seals==before
        r.next()
    passed('six_passes_change_only_one_pad_without_audio_copy_or_old_take_deletion')

    for playing,readers,fenced in ((True,0,True),(False,1,True),(False,0,False)):
        r=Simple();r.playing=playing;r.readers=readers;r.fenced=fenced
        files={p:bytes(b) for p,b in r.files.items()};old=r.paths()
        assert r.step()==2 and not r.seals and r.paths()==old and r.files==files
        r.playing=False;r.readers=0;r.fenced=True;assert r.step()==0
    passed('playing_or_unjoined_or_unfenced_state_cannot_seal_or_assign')

    for failure in ('seal','assign','save'):
        r=Simple();assert r.step()==0;r.next();old=r.paths()
        if failure=='seal':r.seal_status=2
        if failure=='assign':r.reject_once_pad=1
        if failure=='save':r.counts={};r.fail=('settings_write',2,'short')
        assert r.step() in (4,7,8) and r.paths()==old and not r.locked
        assert r.m.invoke(r.syms['manager_step'],[MAN])==10
        assert not r.m.uc.mem_read(H+r.layout[2],4).strip(b'\0')
    passed('safe_seal_load_and_settings_failures_preserve_previous_backing_and_release_capture')

    r=Simple()
    from unicorn import UC_HOOK_CODE
    from verify_pad_protocol import REGS
    # The optimized ELF calls the common publication body directly. Contend
    # its actual manager latch only at release (action 2), after mutation.
    def contend(uc,a,n,u):
        if uc.reg_read(REGS[2])==2:put32(r.m,MAN+12,1)
    release=r.syms['publication']&~1
    token=r.m.uc.hook_add(UC_HOOK_CODE,contend,begin=release,end=release)
    assert r.step()==2 and r.seals==1 and not r.locked
    counts=dict(r.counts);paths=r.paths()
    r.m.uc.hook_del(token);put32(r.m,MAN+12,0)
    assert r.step()==0 and r.seals==1 and r.counts==counts and r.paths()==paths
    passed('release_contention_does_not_repeat_seal_assignment_or_settings_write')

    r=Simple();assert r.step()==0;r.next();r.reject_once_pad=1
    bad_restore=SEAL+0x10;r.m.hooks[bad_restore]=lambda a:2
    put32(r.m,H+4+7*4,bad_restore|1)
    assert r.step()==10 and r.locked
    assert r.m.invoke(r.syms['manager_step'],[MAN])==11
    seals=r.seals;assert r.step()==10 and r.seals==seals
    passed('unverified_rollback_keeps_hold_and_cannot_be_mistaken_for_safe_failure')

    r=Simple();r.seal_status=10
    assert r.step()==10 and r.locked
    assert r.m.invoke(r.syms['manager_step'],[MAN])==11
    before=r.seals;assert r.step()==10 and r.seals==before
    passed('uncertain_seal_quarantines_optional_handoff_without_retry_or_shared_Main_hooks')

    for held in (False,True):
        r=Simple();r.fenced=False
        if held:assert r.step()==2
        assert r.m.invoke(r.syms['manager_cancel'],[MAN]) is not None
        assert r.step()==9 and not r.seals and not r.locked
        assert r.m.invoke(r.syms['manager_step'],[MAN])==16
    passed('cancellation_before_or_while_waiting_for_fence_releases_completed_boundary')

    # Reboot-like fresh state, with more collisions than one worker slice.
    r=LifeRig()
    for i in range(1,81):
        ext='WAV' if i%2 else 'TMP'
        r.disk[f'A:\\SOUND_PAD\\PAD1\\OD_{i:08X}.{ext}']=bytearray(b'old')
    old={p:bytes(b) for p,b in r.disk.items()}
    assert r.life('life_prepare',0,1)==10
    assert r.life('life_prepare',0,1)==10
    assert r.life('life_prepare',0,1)==0 and r.path().endswith('00000051.TMP')
    assert all(bytes(r.disk[p])==b for p,b in old.items())
    r.life('life_start_quiesced');data=r.feed(5);assert r.finish()==0;r.validate(data)
    assert r.path().endswith('.TMP') # final WAV visibility belongs to seal
    passed('restart_skips_completed_and_partial_names_in_bounded_slices_without_overwrite')

    r=LifeRig();r.life('life_prepare',0,1);r.life('life_start_quiesced')
    r.feed(1);r.inject=('audio',1,'short');assert r.finish()==13
    assert all(p.endswith('.TMP') for p in r.disk) and not r.life('life_verified_path')
    r.assert_ordinary()
    passed('partial_write_remains_private_and_does_not_change_normal_recordings')

    r=ManagerRig();r.audio_call();writes=[];original=r.write_file
    def write(a):
        if r.opened[a[0]][1]:writes.append(a[2])
        return original(a)
    r.m.hooks[0x800622b0]=write
    boundary(r,21)
    assert writes==[4096,4096,2560],writes
    passed('active_writer_batches_21_blocks_into_two_4KiB_writes_and_exact_final_remainder')

    # Drive handoff from the real compiled worker, not the test's stepping loop.
    r=WorkerRig();pad=['NO ASSIGN'];held=[False];count=[0]
    def enter(a):held[0]=True;return 0
    def leave(a):held[0]=False;return 0
    def snapshot(a):
        r.m.uc.mem_write(a[1],bytes(548))
        r.m.uc.mem_write(a[1],(pad[0]+'\0').encode('utf-16le'));return 0
    def assign(a):pad[0]=getstr(r.m,a[1]);return 0
    def restore(a):pad[0]=getstr(r.m,a[1]);return 0
    def seal(a):
        assert held[0];src,dst=[getstr(r.m,p) for p in a[:2]]
        assert dst not in r.disk;r.disk[dst]=r.disk.pop(src);count[0]+=1;return 0
    ports=[enter,leave,seal,snapshot,lambda a:0,assign,restore,lambda a:0]
    for i,fn in enumerate(ports):r.m.hooks[0x21038000+i*4]=lambda a,fn=fn:fn(a[1:])
    r.m.uc.mem_write(HP,struct.pack('<9I',H,*[0x21038001+i*4 for i in range(8)]))
    r.m.uc.mem_write(r.m.stack,struct.pack('<2I',0,1))
    assert r.m.invoke(r.syms['native_worker_register'],[WORKER,MAN,DESC,CONFIG])==0
    assert r.m.invoke(r.syms['backing_init'],[H,MAN,HP,0])==0
    assert r.m.invoke(r.syms['backing_attach_worker'],[H,WORKER])==0
    assert r.m.invoke(r.syms['backing_attach_worker'],[H,WORKER])==3
    put32(r.m,SCHEDULER,1);assert r.release()==0;r.ready()
    for _ in range(3):
        session=r.session;start=r.sequence;r.request();r.dispatch_all()
        for _ in range(3):r.audio_call();r.tick()
        r.request(1);r.dispatch_all()
        r.drive(lambda:r.mstate()==LIVE and r.session>session)
        assert bytes(r.disk[pad[0]])[512:]==payload(start,start+192)
        assert not held[0]
    assert count[0]==3
    passed('one_serialized_worker_drives_three_capture_finalize_handoff_and_rearm_cycles')
    r.cancel();r.drive(lambda:r.mstate()==9)
    assert r.resume()==0;r.drive(lambda:r.mstate()==LIVE)
    assert count[0]==3 # A cancelled session has no new completed result.
    session=r.session;r.request();r.dispatch_all();r.audio_call();r.tick()
    r.request(1);r.dispatch_all();r.drive(lambda:r.mstate()==LIVE and r.session>session)
    assert count[0]==4 and not held[0]
    passed('worker_resumes_cancelled_session_without_waiting_for_nonexistent_publication')
    print(json.dumps(dict(passed_groups=len(groups),cases=groups),indent=2))

if __name__=='__main__':main()
