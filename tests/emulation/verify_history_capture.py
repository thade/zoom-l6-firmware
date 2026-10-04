#!/usr/bin/env python3
"""Compiled history/range code plus extra-file lifecycle, entirely offline.

All access is deliberately serialized. Original range getters are tested in
separate suites; monotonic sample labels here are explicit harness inputs.
"""
import hashlib,json,struct
from verify_extra_lifecycle import LifeRig
from verify_extra_capture import STATE,ELF
from verify_uncompressed_tap import MIX,packed
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
from verify_recording_writer import WriterRig,C
from verify_record_events import STOP_SAVED
from verify_uncompressed_tap import STAGING

H=0x22014000
STAMP=0x22015000
STORAGE=0x23000000

def values(i):return ((i%4096)-2048)/4096,((i*3%2048)-1024)/2048
def payload(first,end,origin=0):return packed([v for i in range(first-origin,end-origin) for v in values(i)])

class HistoryRig(LifeRig):
    def __init__(self,capacity=256,origin=0):
        super().__init__();self.m.uc.mem_map(STORAGE,0x200000)
        self.origin=origin;self.next=origin
        self.hlayout=struct.unpack('<7I',self.raw(self.syms['history_layout'],28))
        self.stamp(origin)
        assert self.hcall('history_init',STORAGE,capacity,STAMP)==0
    def stamp(self,value):self.m.uc.mem_write(STAMP,struct.pack('<Q',value))
    def hcall(self,name,*args):return self.m.invoke(self.syms[name],[H,*args])
    def push(self,label=None):
        first=self.next if label is None else label
        samples=[values(i-self.origin) for i in range(first,first+64)]
        self.floats(MIX,[x[0]*2**31 for x in samples]+[x[1]*2**31 for x in samples])
        self.stamp(first);before=len(self.calls)
        status=self.hcall('history_push',MIX,MIX+256,STAMP)
        assert len(self.calls)==before,'Audio push must not perform filesystem IO'
        if status==0:self.next=first+64
        return status
    def begin(self,start):
        assert self.life('life_prepare',0,1)==0
        assert self.life('life_start_quiesced')==0
        self.stamp(start);return self.hcall('history_begin',STATE,STAMP)
    def end(self,end):self.stamp(end);return self.hcall('history_end',STAMP)
    def pump(self,drain=True):
        while True:
            before=len(self.calls);status=self.hcall('history_pump')
            assert len(self.calls)==before,'Range selection must not perform filesystem IO'
            if drain:
                while self.call('extra_drain')==0:pass
            if status!=10:return status
    def complete(self,end):
        assert self.end(end)==0 and self.pump()==0
        assert self.finish()==0
    def finish(self):
        assert self.life('life_stop_quiesced')==0
        # Large-history fixtures require more 4-KiB verification steps than
        # the earlier short-file lifecycle fixture's limit of 100 calls.
        for _ in range(2048):
            status=self.life('life_step')
            if status!=10:return status
        raise AssertionError('History fixture exceeded bounded finalization steps')

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    # Retain a historical start, then catch up as live audio continues. Both
    # selection and final endpoint fall inside ordinary 64-frame blocks.
    r=HistoryRig(512)
    for _ in range(8):assert r.push()==0
    assert r.begin(63)==0 and r.pump()==11
    for _ in range(12):assert r.push()==0;assert r.pump()==11
    # Pumped through frame 1279 exclusive: cursor 1279. End at 1297, after one
    # further audio block, with the stop delivered before draining that block.
    assert r.push()==0;r.complete(1297);r.validate(payload(63,1297))
    passed('delayed_unaligned_start_and_partial_stop_survive_continuous_history_wraps',frames=1234)

    # Large history tests use the existing conditional stock history lengths,
    # without claiming those branches are active settings on an actual L6.
    for lookback in (24000,96000):
        r=HistoryRig(240000)
        for _ in range((lookback+1024)//64):assert r.push()==0
        start=r.next-lookback
        assert r.begin(start)==0 and r.pump()==11
        r.complete(r.next);r.validate(payload(start,r.next))
    passed('half_second_and_two_second_historical_ranges_produce_exact_WAV_payloads',
           limitation='Synthetic mode/range requests and externally supplied 1.92-MB history storage')

    # Crossing 32-bit frame count must not alias an earlier lap.
    origin=2**32-128;r=HistoryRig(256,origin)
    for _ in range(3):assert r.push()==0
    assert r.begin(origin+1)==0
    r.complete(origin+191);r.validate(payload(origin+1,origin+191,origin))
    passed('64_bit_sample_labels_cross_low_word_wrap_without_truncation')

    # Endpoint may arrive before its audio; wait without synthesizing samples.
    r=HistoryRig();assert r.begin(0)==0 and r.end(81)==0
    assert r.pump()==11 and not r.life('life_verified_path')
    assert r.push()==0 and r.pump()==11
    assert r.push()==0 and r.pump()==0
    assert r.finish()==0;r.validate(payload(0,81))
    passed('future_endpoint_waits_for_real_audio_and_excludes_later_samples')

    for start in (0,257):
        r=HistoryRig(128)
        for _ in range(4):assert r.push()==0
        assert r.begin(start)==17 and r.finish()!=0
        assert not r.life('life_verified_path');r.assert_ordinary()
    passed('overwritten_and_not_yet_captured_start_positions_invalidate_optional_file')

    # Once a range is selected, losing unread audio must fault before overwrite.
    r=HistoryRig(128)
    for _ in range(2):assert r.push()==0
    assert r.begin(0)==0;snapshot=r.raw(STORAGE,1024)
    assert r.push()==17 and r.raw(STORAGE,1024)==snapshot
    assert r.finish()!=0 and not r.life('life_verified_path');r.assert_ordinary()
    passed('unread_selected_history_cannot_be_overwritten_silently')

    for label in (0,128):
        r=HistoryRig();assert r.push()==0 and r.begin(0)==0
        assert r.push(label)==18 and r.finish()!=0
        assert not r.life('life_verified_path')
    r=HistoryRig(origin=2**64-64)
    assert r.push()==18
    passed('duplicate_missing_and_overflowing_sample_labels_fail_without_guessing_timeline')

    r=HistoryRig();assert r.push()==0 and r.push()==0 and r.begin(0)==0
    assert r.pump()==11
    assert r.end(81)==12 and r.finish()!=0 and not r.life('life_verified_path')
    passed('late_stop_behind_already_queued_audio_invalidates_file_instead_of_keeping_excess')

    r=HistoryRig();assert r.push()==0 and r.begin(0)==0 and r.pump()==11
    assert r.finish()!=0 and not r.life('life_verified_path')
    passed('premature_file_finalization_cannot_bypass_pending_range_completion')

    r=HistoryRig(16384)
    for _ in range(129):assert r.push()==0
    assert r.begin(0)==0 and r.end(r.next)==0
    assert r.pump(drain=False)==12 and r.finish()!=0
    assert not r.life('life_verified_path');r.assert_ordinary()
    passed('writer_queue_exhaustion_faults_extra_file_without_ordinary_state_mutation')

    for failure in ('short','error'):
        r=HistoryRig();assert r.push()==0 and r.begin(0)==0 and r.end(17)==0
        assert r.pump(drain=False)==0
        r.inject=('audio',1,failure)
        assert r.finish()!=0 and not r.life('life_verified_path');r.assert_ordinary()
    passed('partial_final_block_write_failures_prevent_file_eligibility')

    r=HistoryRig(128)
    for _ in range(2):assert r.push()==0
    assert r.begin(0)==0;r.complete(65);r.validate(payload(0,65))
    first=bytes(r.disk[r.path()])
    for _ in range(8):assert r.push()==0
    assert bytes(r.disk[r.path()])==first
    assert r.hcall('history_rearm')==0
    # Reuse history, but supply a fresh lifecycle/capture instance after checked
    # completion. The modeled disk remains, so exclusive creation skips serial1.
    r.m.uc.mem_write(0x22011000,bytes(r.life_layout[0]))
    assert r.begin(r.next-65)==0;start=r.next-65
    r.complete(r.next);r.validate(payload(start,r.next))
    assert r.path().endswith('00000002.WAV')
    passed('completed_range_detaches_and_continuous_history_supports_a_second_unique_take')

    # Non-power-of-two capacity exercises actual cursor arithmetic.
    r=HistoryRig(193)
    for _ in range(7):assert r.push()==0
    start=r.next-193;assert r.begin(start)==0
    r.complete(r.next);r.validate(payload(start,r.next))
    passed('non_power_of_two_history_and_oldest_retained_sample_are_supported')

    r=HistoryRig(256)
    for _ in range(4):assert r.push()==0
    assert r.begin(0)==0 and r.end(130)==0 and r.pump(drain=False)==0
    assert r.finish()==0;r.validate(payload(0,130))
    passed('queued_full_blocks_and_short_tail_finalize_without_padding_samples')

    # Independent original master pipeline and new extra pipeline see the same
    # frame labels. Execute actual stock master gain, staging, scaling, reader,
    # producer, worker and finalizer. The new history starts two blocks later,
    # while retaining the original start. Compressor/effects remain excluded.
    r=HistoryRig(256);stock=WriterRig();stock.header();sm=stock.m
    put32(sm,C+8,1<<10);put32(sm,C+0x50,128)
    for block in range(17):
        assert r.push()==0
        stock.position=(block%2)*64
        samples=[values(block*64+i) for i in range(64)]
        stock.floats(MIX,[v[0]*2**31 for v in samples]+[v[1]*2**31 for v in samples])
        stock.gain(.5);stock.stock_staging()
        staged=struct.unpack('<128f',stock.raw(STAGING))
        stock.master_block(list(staged[:64]),list(staged[64:]))
        if block==1:assert r.begin(0)==0
        if block==16:
            put32(sm,C+0x20+40,stock.position)
            put32(sm,STOP_SAVED,(stock.position+17)%128)
            stock.window(0x8000b732,0x8000b73a)
            assert r.end(1041)==0
        stock.produce();stock.drain()
        if block>=1:assert r.pump()==(0 if block==16 else 11)
    assert r.finish()==0;r.validate(payload(0,1041))
    master=stock.finish();extra=bytes(r.disk[r.path()][512:])
    assert len(master)==len(extra)==1041*8
    extra_values=struct.unpack('<2082f',extra)
    assert master==packed([v*.5 for v in extra_values])
    passed('original_processed_master_and_delayed_extra_history_have_identical_frame_ranges',
           frames=1041,master_gain=.5,
           limitation='Separate emulator CPUs, synthetic input and serial scheduling; original compressor/effects excluded')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        capture_state_bytes=r.layout[0],history_state_bytes=r.hlayout[0],
        limitations=['All history/control/capture operations externally serialized; not a concurrent audio fence',
          'History memory and monotonic sample labels supplied by harness; no stock hook or allocation binding',
          'Original compressor/effects excluded; sample ranges contain deterministic fixture audio',
          'No device timing, cache coherency, SD throughput or power-loss validation',
          'Late endpoints behind transferred audio fail; no rollback/truncation protocol',
          'Pad assignment and playback-reader exclusion remain unbound'])
    target=ROOT/'analysis/history_capture_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(target)),indent=2))

if __name__=='__main__':main()
