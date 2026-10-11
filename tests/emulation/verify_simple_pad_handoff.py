#!/usr/bin/env python3
"""Pad handoff of the simplified capture: seal on the worker, assign on Main.

Original catalogue initialization, lookup, insert and path construction run.
WAV validation, pad play/stop and the assignment queue are recorded models;
rename is the in-memory filesystem model. No device or card access.
"""
import json,struct
from verify_simple_capture import SimpleRig,STATE,OFF,B,PATH,FIFO,take,build,plan,symbols
from verify_capture_integration import IntegrationRig,record
from verify_record_catalogue import putstr,getstr,BASE
from verify_record_scheduler import word
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE
import hashlib

ELF=build(trial='handoff');PLAN=plan(trial='handoff');PACK=PLAN['pack'];N=symbols(ELF)
MAGIC=0x4c364f44
NONE,POSTED,ASSIGNED,SKIPPED,FAILED,LOST=range(6)
H_STATE,H_RESULT,H_SERIAL=PATH+88,PATH+92,PATH+96   # padding words after path
H_NAME=FIFO+4096+512;H_PATH=H_NAME+32;H_POSTS=H_PATH+80;H_AT=H_POSTS+4;STOCK_REC=H_AT+4;H_HANDLED=STOCK_REC+4
RECORDER_BUSY=0x80578ec0

class HandoffRig(SimpleRig):
    plan,pack,names=PLAN,PACK,N
    def __init__(self,catalogue=('PASS_001.WAV',),**kw):
        super().__init__(**kw);m=self.m
        self.assigned=[];self.stopped=[];self.validated=[];self.validate_result=0;self.playing=0
        for fn in (0x8002a2e0,0x8002a428,0x8002a2c8):m.invoke(fn,[BASE])
        putstr(m,BASE+0x14,'A:\\SOUND_PAD\\PAD1');m.hooks[0x80008f00]=lambda a:0
        for name in catalogue:
            putstr(m,0x23001a00,name);assert m.invoke(0x80008dd8,[0,0x23001a00,0])==0
        self.pad_before=self.raw(BASE,0xb10) # takes must still leave the catalogue alone
        def validate(a):self.validated.append((getstr(m,a[0]),a[1],a[2]));return self.validate_result
        def assign(a):
            self.assigned.append(dict(mode=a[0],path=getstr(m,a[1]),pad=a[2],index=a[3],count=a[4],option=a[5]))
            return 0
        m.hooks.update({0x80009568:validate,0x80002440:lambda a:self.playing,
                        0x80002d08:lambda a:self.stopped.append(a[0]) or 0,0x80008c68:assign})
    def h(self,offset):return word(self.m,STATE+offset)
    def deliver(self,serial=None):
        """Main receives the posted category-3 event (as the stock queue would)."""
        _,magic,posted,_,_=self.posts[-1]
        self.main_receive(3,magic,posted if serial is None else serial,0)
    def count(self):return self.m.invoke(0x80008ee8,[0])
    def short_take(self,blocks=3):
        for _ in range(3):self.audio_call()
        self.admit()
        for _ in range(blocks):
            self.audio_call();self.step()
        self.stop(word(self.m,B+0x53e4));self.settle()

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))

    # A real stock take: the worker seals OD_n.TMP -> .WAV and posts once;
    # Main inserts the name and queues the stock assignment for pad 1.
    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2)
    r=HandoffRig();r.sequence=0
    assert take(r,delay=2)==ordinary
    wav=r.sealed();assert wav in r.disk and r.path() not in r.disk and r.field('last_status')==0
    assert r.h(H_STATE)==POSTED and r.h(H_SERIAL)==1 and len(r.posts)==1 and r.posts[0][:3]==(3,MAGIC,1)
    assert getstr(r.m,STATE+H_PATH)==wav and getstr(r.m,STATE+H_NAME)==wav.rsplit('\\',1)[1]
    before=r.count();r.deliver()
    assert r.count()==before+1 and r.h(H_STATE)==ASSIGNED and r.h(H_RESULT)==0
    assert r.assigned==[dict(mode=0,path=wav,pad=0,index=1,count=2,option=1)] and r.validated==[(wav,0,1)]
    assert r.stopped==[] and r.delays==0
    passed('verified_take_is_renamed_and_assigned_to_pad_1_through_the_stock_assignment',
           path=wav,assignment=r.assigned[0])

    # Repeat delivery or a stale serial does nothing; an existing entry is reused.
    r.deliver();r.deliver(serial=0)
    assert len(r.assigned)==1 and r.count()==before+1 and r.h(H_HANDLED)==1
    # Review race: a repost of an already handled serial, even if the worker had
    # rewritten POSTED, is ignored; LOST never overwrites a final state.
    put32(r.m,STATE+H_STATE,POSTED);r.deliver();assert len(r.assigned)==1
    put32(r.m,STATE+H_STATE,ASSIGNED);put32(r.m,STATE+H_POSTS,30)
    for _ in range(45):r.step()
    assert r.h(H_STATE)==ASSIGNED
    r=HandoffRig(catalogue=('PASS_001.WAV','OD_00000001.WAV'));r.short_take()
    n=r.count();r.deliver()
    assert r.count()==n and r.assigned[-1]['index']==1 and r.h(H_STATE)==ASSIGNED
    passed('stale_or_repeated_events_are_ignored_and_catalogued_names_are_not_duplicated')

    # While a stock take records or RecStop finalizes, Main leaves the handoff
    # posted; a later repost assigns it. Pad-record target is skipped outright.
    r=HandoffRig();r.short_take()
    put32(r.m,STATE+STOCK_REC,1);r.deliver()
    assert r.h(H_STATE)==POSTED and not r.assigned
    put32(r.m,STATE+STOCK_REC,0);put32(r.m,RECORDER_BUSY,1);r.deliver()
    assert r.h(H_STATE)==POSTED and not r.assigned
    put32(r.m,RECORDER_BUSY,0);r.deliver()
    assert r.h(H_STATE)==ASSIGNED and len(r.assigned)==1
    r=HandoffRig();r.short_take();r.m.uc.mem_write(0x801f5f00,b'\x00');r.deliver()
    assert r.h(H_STATE)==SKIPPED and r.h(H_RESULT)==2 and not r.assigned
    passed('handoff_waits_while_recording_or_finalizing_and_skips_the_pad_record_target')

    # The real stock flag follows admission and RecStop, even for skipped takes.
    r=HandoffRig();r.sequence=0
    r.audio_call();r.begin_recording(2);assert r.h(STOCK_REC)==1
    r.audio_call();r.stop_recording();assert r.h(STOCK_REC)==0
    r.stop(word(r.m,B+0x53e4),caller=0x8004b91d);assert r.h(STOCK_REC)==0
    passed('stock_recording_flag_follows_admission_and_RecStop_only')

    # A playing pad 1 is stopped first, as the Editor select does.
    r=HandoffRig();r.short_take();r.playing=1;r.deliver()
    assert r.stopped==[0] and r.assigned and r.h(H_STATE)==ASSIGNED
    passed('playing_pad_1_is_stopped_before_assignment')

    # Validation failures and a catalogue that resolves elsewhere are refused.
    r=HandoffRig();r.short_take();r.validate_result=4;r.deliver()
    assert r.h(H_STATE)==FAILED and r.h(H_RESULT)==0x104 and not r.assigned
    r=HandoffRig();putstr(r.m,BASE+0x14,'A:\\SOUND_PAD\\PAD2');r.short_take();r.deliver()
    assert r.h(H_STATE)==FAILED and r.h(H_RESULT)==4 and not r.assigned
    passed('unsupported_format_or_mismatched_catalogue_path_is_refused_without_assigning')

    # Rename: any error ends the handoff, even if the new name is visible now
    # (a metadata error can leave only the cache changed).
    for when in ('after','before'):
        r=HandoffRig();r.rename_fault=(when,0xffffd827);r.short_take()
        assert r.h(H_STATE)==FAILED and r.h(H_RESULT)==0xffffd827 and not r.posts
        assert r.field('last_status')==0 # the take itself is still complete
    passed('any_rename_error_ends_the_handoff_without_posting')

    # A storage change after posting (before Main handles it) skips the handoff.
    r=HandoffRig();r.short_take();r.main_receive(0,0,0x33,0);r.deliver()
    assert r.h(H_STATE)==SKIPPED and r.h(H_RESULT)==5 and not r.assigned and r.count()==1
    passed('storage_change_after_posting_skips_without_touching_the_catalogue')

    # A storage change between verification and sealing leaves the .TMP and
    # posts nothing: revoke right after the header readback.
    r=HandoffRig();original=r.m.hooks[0x80060620]
    def read(a):
        result=original(a)
        if a[0] in r.opened:put32(r.m,STATE+OFF['revoked'],r.field('revoked')+1)
        return result
    r.m.hooks[0x80060620]=read;r.short_take()
    assert r.path() in r.disk and r.h(H_STATE)==SKIPPED and not r.posts and 'rename' not in r.calls
    passed('revocation_before_sealing_keeps_the_TMP_and_posts_nothing')

    # Unhandled events are reposted about once a second, 30 posts in all.
    r=HandoffRig();r.short_take();assert len(r.posts)==1
    for _ in range(29*41):r.step()
    assert len(r.posts)==30 and r.h(H_STATE)==POSTED and r.posts[-1][:3]==(3,MAGIC,1)
    for _ in range(41):r.step()
    assert r.h(H_STATE)==LOST and len(r.posts)==30
    r.deliver();assert not r.assigned # a late delivery after LOST does nothing
    passed('unhandled_events_are_reposted_from_idle_polls_then_marked_lost',posts=30)

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        elf_sha256=PLAN['elf_sha256'],limitations=[
            'Catalogue code is original; WAV validation, play/stop and the assignment queue are models',
            'SamplerFileAssign loading, settings save and the pad renderer are not executed here',
            'Main delivery is explicit; the stock event queue and scheduling are not modeled'])
    (ROOT/'analysis/simple_pad_handoff_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
