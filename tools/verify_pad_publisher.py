#!/usr/bin/env python3
"""Manager-to-pad boundary test, entirely offline; two explicit CPU fixtures.

Capture CPU executes the manager through its post-verification RESET boundary.
Copy its ELF globals, manager RAM and bytearray files to the stock-pad CPU, which
executes the locked visitor, publisher and original pad control flow. This is a
state-transfer integration test, NOT a shared RTOS/audio scheduler or real fence.
"""
import hashlib,json
from verify_session_manager import ManagerRig,MAN,RESET,LIVE
from verify_stock_pad_adapter import StockRig,SETTINGS,CONFIG
from verify_overdub_prototype import STATE,PORT,STATUS,ELF as PAD_ELF
from verify_extra_capture import ELF
from verify_record_scheduler import word
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32

class PublisherRig(StockRig):
    def __init__(self,capture):
        super().__init__()
        self.m.uc.mem_map(0x10010000,0x10000)
        self.m.uc.mem_map(0x22000000,0x20000)
        self.capture=capture;self.syms=capture.syms
        self.playing=False;self.readers=0;self.fenced=False
        self.reentry=False;self.checked_reentry=False
        self.sync_boundary()
    def sync_boundary(self):
        c=self.capture
        self.m.uc.mem_write(0x10010000,c.raw(0x10010000,0x10000))
        self.m.uc.mem_write(MAN,c.raw(MAN,c.mlayout[0]))
        self.m.uc.ctl_remove_cache(0x10010000,0x10020000)
        for path,data in c.disk.items():self.files[path]=bytearray(data)
    def enter(self,a):
        # Explicit modeled contract. The unbound default never asserts a fence.
        if self.playing or self.readers or not self.fenced:return 1
        return super().enter(a)
    def checkpoint(self,a):
        assert word(self.m,MAN+12)==1 # manager latch held throughout worker I/O
        if self.reentry and not self.checked_reentry:
            self.checked_reentry=True
            peer=ManagerRig()
            peer.m.uc.mem_write(0x10010000,bytes(self.m.uc.mem_read(0x10010000,0x10000)))
            peer.m.uc.mem_write(MAN,bytes(self.m.uc.mem_read(MAN,peer.mlayout[0])))
            assert peer.m.invoke(peer.syms['manager_step'],[MAN])==11
            assert peer.m.invoke(peer.syms['manager_copy_result'],[MAN,0,0x21035000])==11
        return super().checkpoint(a)
    def publish(self):
        sources={p:bytes(b) for p,b in self.files.items() if p in self.capture.disk or p.startswith('A:\\RECORDER')}
        before=bytes(self.m.uc.mem_read(MAN,self.capture.mlayout[0]))
        code=self.m.invoke(self.syms['manager_publish_pads'],[MAN,STATE,PORT])
        assert before==bytes(self.m.uc.mem_read(MAN,self.capture.mlayout[0]))
        assert all(bytes(self.files[p])==b for p,b in sources.items())
        assert not self.locked
        active={word(self.m,0x807348d0+pad*0x22c+4) for pad in range(4)}-{0}
        assert set(self.handles)==active
        return STATUS[code]

def boundary(c,blocks=2):
    assert c.mstate()==LIVE
    c.request();c.dispatch_all()
    for _ in range(blocks):c.audio_call();c.tick()
    c.request(1);c.dispatch_all();c.drive(lambda:c.mstate()==RESET,with_audio=False)
    assert not c.opened
    c.assert_ordinary()
    return c.result()

def fresh():
    c=ManagerRig();c.audio_call();boundary(c)
    r=PublisherRig(c);return c,r

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    c,r=fresh();r.fenced=True;ordinary=r.take(900)
    params=[bytes(r.m.uc.mem_read(CONFIG+x,4)) for x in (0xfc4,0xfc8,0x329)]
    history=[]
    for n in range(6):
        if n:
            c.drive(lambda:c.mstate()==LIVE);boundary(c,n%3+1);r.sync_boundary()
        history.insert(0,c.result()[1])
        assert r.publish()=='ok' and r.history()==history[:4]
        for pad,path in enumerate(history[:4]):
            assert bytes(r.files[r.paths()[pad]])==bytes(c.disk[path])
            assert r.snapshot(pad)[0]==0
        assert [bytes(r.m.uc.mem_read(CONFIG+x,4)) for x in (0xfc4,0xfc8,0x329)]==params
        assert r.files[SETTINGS][96:96+0xc34]==r.m.uc.mem_read(CONFIG+0x798,0xc34)
        assert all(path in r.files for path in history)
    assert ordinary not in r.history() and r.counts.get('qualify',0)==0
    passed('six_compiled_manager_results_publish_latest_four_extra_WAVs_through_stock_assignment_and_settings',takes=6)

    before=dict(r.counts);files={p:bytes(b) for p,b in r.files.items()};paths=r.paths()
    assert r.publish()=='skipped' and r.paths()==paths
    assert files=={p:bytes(b) for p,b in r.files.items()}
    assert all(r.counts.get(op,0)==before.get(op,0) for op in ('open','read','write','settings_write'))
    passed('duplicate_snapshot_is_idempotent_without_file_or_settings_IO')

    c,r=fresh();before=bytes(r.m.uc.mem_read(STATE,r.state_size));paths=r.paths();files=dict(r.files)
    for playing,readers,fenced in ((False,0,False),(True,0,True),(False,1,True)):
        r.playing=playing;r.readers=readers;r.fenced=fenced
        for _ in range(3):assert r.publish()=='busy'
        assert bytes(r.m.uc.mem_read(STATE,r.state_size))==before and r.paths()==paths and r.files==files
    r.playing=False;r.readers=0;r.fenced=True
    assert r.publish()=='ok'
    passed('unbound_fence_playing_pad_and_outstanding_reader_defer_without_IO_assignment_or_auto_stop')

    c,r=fresh();r.fenced=True;r.reentry=True;assert r.publish()=='ok' and r.checked_reentry
    passed('manager_reset_and_result_reads_cannot_reenter_during_publication_IO')

    c,r=fresh();r.fenced=True;assert r.publish()=='ok';old=r.paths();old_history=r.history()
    c.drive(lambda:c.mstate()==LIVE);boundary(c);r.sync_boundary();r.reject_once_pad=2
    assert r.publish()=='assign' and r.paths()==old and r.history()==old_history
    assert r.publish()=='ok' and r.history()==[c.result(i)[1] for i in range(2)]
    passed('late_loader_failure_rolls_back_then_explicit_retry_publishes_same_manager_snapshot')

    for kind in ('short','error'):
        c,r=fresh();r.fenced=True;assert r.publish()=='ok';old=r.paths();history=r.history()
        c.drive(lambda:c.mstate()==LIVE);boundary(c);r.sync_boundary();r.counts={};r.fail=('settings_write',2,kind)
        assert r.publish()=='persist' and r.paths()==old and r.history()==history
        r.fail=None;assert r.publish()=='ok'
    passed('settings_write_failures_restore_previous_assignments_and_do_not_consume_result')

    c,r=fresh();r.fenced=True;r.fail=('close',1,'error')
    assert r.publish()=='fault';events=len(r.events);assert r.publish()=='fault' and len(r.events)==events
    assert r.paths()==['NO ASSIGN']*4
    passed('uncertain_file_close_latches_fault_and_prevents_retries')

    c,r=fresh();r.fenced=True;p=c.result()[1];r.files[p][0]=0
    assert r.publish()=='wav' and r.paths()==['NO ASSIGN']*4 and r.history()==[]
    passed('manager_provenance_does_not_bypass_container_revalidation')

    c,r=fresh();r.fenced=True;r.fail=('checkpoint',1,'error')
    assert r.publish()=='cancelled' and r.paths()==['NO ASSIGN']*4 and r.history()==[]
    r.fail=None;assert r.publish()=='ok'
    passed('cooperative_cancel_leaves_verified_result_available_for_explicit_retry')

    c,r=fresh();r.fenced=True
    c.drive(lambda:c.mstate()==LIVE);r.sync_boundary();before=dict(r.counts)
    assert r.publish()=='busy' and r.counts==before
    c.cancel();c.drive(lambda:c.mstate()==9);r.sync_boundary()
    assert r.publish()=='busy' and r.counts==before
    put32(r.m,MAN+12,1);assert r.publish()=='busy'
    passed('armed_cancelled_or_busy_manager_cannot_publish_outside_completed_take_boundary')

    c,r=fresh();r.fenced=True
    for _ in range(5):c.drive(lambda:c.mstate()==LIVE);boundary(c)
    r.sync_boundary();assert r.publish()=='ok'
    assert r.history()==[c.result(i)[1] for i in range(4)]
    passed('delayed_publication_uses_full_latest_four_snapshot_and_preserves_older_source_files')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      pad_prototype_sha256=hashlib.sha256(PAD_ELF.read_bytes()).hexdigest(),
      limitations=['Two CPU fixtures exchange actual compiled manager state and files at the boundary; not a shared running RTOS',
        'Playback, renderer fence, reader drain, ordinary recorder/card exclusion remain modeled port contracts',
        'Harness invokes publisher before manager reset; production task scheduling and retry/error UI are not wired',
        'Full verified copies into pad-specific folders cost storage and time; no power-loss atomicity',
        'No hardware writes, audible playback, timing/SD throughput or firmware installation proof'])
    path=ROOT/'analysis/pad_publisher_verification.json';path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(path)),indent=2))
if __name__=='__main__':main()
