#!/usr/bin/env python3
"""Native scan/read adapters and compiled audio observer join shutdown.

Two emulator CPUs exchange explicit snapshots at scheduled boundaries. Stop/fade,
drivers and control ingress are fixtures; this is not installed firmware.
"""
import json
import struct
from unicorn import UC_PROT_NONE
from verify_native_scan import NativeScan, SESSION, PORT, SQ, UID, LEDGER
from verify_native_audio import NativeAudio, C as AUDIO_CONTROL, TARGETS
from verify_control_coordinator import C
from verify_playback_shutdown import SD, SDP
from verify_pad_renderer_boundary import AUDIO
from verify_scheduling_boundaries import BASE
from verify_work_ownership import OK, BUSY, P, STALE
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT


class Rig(NativeScan):
    def __init__(self):
        super().__init__()
        self.audio_cpu=NativeAudio()
        self.csize=struct.unpack('<I',self.m.uc.mem_read(self.m.symbols['oc_layout'],4))[0]
        self.m.uc.mem_write(SD,struct.pack('<3I',SESSION,C,SDP))
        self.m.uc.mem_write(SDP,struct.pack('<2I',
            self.m.symbols['od_emulator_shutdown_disable_streams'],
            self.m.symbols['od_emulator_session_quiet']))
        put32(self.m,PORT+12,self.m.symbols['od_emulator_shutdown_fence'])
        put32(self.m,PORT+20,self.m.symbols['od_emulator_shutdown_rearm'])
        self.loaded()
    def shutdown(self):
        return self.scheduled(self.m.symbols['od_shutdown_poll'],[SD],None,UID)
    def finish(self,ticket):
        return self.scheduled(self.m.symbols['od_shutdown_finish'],[SD,ticket,0],None,UID)
    def audio(self,target=TARGETS[0],protect=False):
        a=self.audio_cpu
        a.m.uc.mem_write(AUDIO_CONTROL,bytes(self.m.uc.mem_read(C,self.csize)))
        a.m.uc.mem_write(AUDIO,bytes(self.m.uc.mem_read(AUDIO,240)))
        if protect:a.m.uc.mem_protect(0x21028000,0x2000,UC_PROT_NONE)
        a.full(target)
        self.m.uc.mem_write(C,a.raw(AUDIO_CONTROL,self.csize))
        self.m.uc.mem_write(AUDIO,a.raw(AUDIO,240))
        return a


def main():
    cases=[]
    def passed(case):cases.append(dict(case=case))

    r=Rig();assert r.session('start',0)==OK;old=r.owner()
    r.audio_cpu.seed(length=128,loop=1)
    r.m.uc.mem_write(AUDIO,r.audio_cpu.raw(AUDIO,240))
    assert len(r.audio().samples())==128 # Positive control for protected pages below.
    r.seed_scan();r.dispatch();assert len(r.q[SQ])==1
    assert r.shutdown()==BUSY and r.owner()==old
    r.audio();assert r.shutdown()==BUSY and r.owner()==old
    assert r.session('start',0)==BUSY
    count=r.scans;r.dispatch();assert r.scans==count
    r.stream();assert r.refills==1 and len(r.entries())==1
    assert r.shutdown()==OK and r.word(LEDGER)==P and r.owner()==0
    ticket=r.word(SD+32)
    for target in TARGETS*2:
        assert not r.audio(target,protect=True).samples()
        assert r.shutdown()==OK and r.word(SD+32)==ticket
        assert r.session('start',0)==BUSY
        r.dispatch();assert r.scans==count
    assert r.finish(ticket)==OK and r.word(LEDGER)==0
    assert r.finish(ticket)==STALE
    assert r.session('start',0)==OK and r.owner()!=old
    passed('native_scan_refill_and_full_audio_return_join_before_exclusive_hold_then_explicit_rearm')

    r=Rig();assert r.session('start',0)==OK
    r.seed_scan();r.send_mode='lost';r.dispatch()
    assert not r.q[SQ] and len(r.entries())==3
    assert r.shutdown()==BUSY
    r.m.uc.mem_write(BASE+0x1c,b'\x00')
    r.audio()
    for _ in range(3):assert r.shutdown()==BUSY and r.owner() and len(r.entries())==3
    assert r.word(LEDGER)==1 and r.session('start',0)==BUSY
    passed('unknown_refill_delivery_retains_ownership_despite_idle_flags_and_compiled_audio_ack')

    r=Rig();assert r.shutdown()==BUSY and not r.owner()
    assert r.session('start',0)==BUSY
    r.audio();assert r.shutdown()==OK
    first=r.word(SD+20);ticket=r.word(SD+32)
    assert r.finish(ticket)==OK
    assert r.shutdown()==BUSY and r.word(SD+20)>first
    assert r.finish(ticket)==STALE
    r.audio();assert r.shutdown()==OK and r.word(SD+32)>ticket
    passed('idle_session_and_each_later_cycle_require_new_compiled_audio_completion')

    out=ROOT/'analysis/native_renderer_fence_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,limitations=[
        'Persistent native-audio emulator executes begin/end observers with original DSP; no Python calls to completion begin/end',
        'Two emulator CPUs exchange explicit control and pad-state snapshots; not real concurrent scheduling',
        'Stop/fade, queues, file data, output continuation and ARM MAX IPSR probe are fixtures',
        'Shutdown ports explicitly bound by harness; complete native control admission and other direct callers remain unbound',
        'Protected buffers establish tested inactive paths only; no cache/DMA or physical timing proof',
        'No pad publication, capture observer composition, installed hooks or device access']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))


if __name__=='__main__':main()
