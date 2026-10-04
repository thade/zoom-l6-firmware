#!/usr/bin/env python3
"""Offline block ownership and stock-cursor publication experiments.

Actual stock gain/copy/ring windows execute. Hook invocation and scheduling are
explicit fixtures; coherent emulator memory is not a device cache/fence proof.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from verify_history_capture import HistoryRig,H,STAMP,values,payload
from verify_extra_capture import ELF
from verify_uncompressed_tap import B,MIX,STAGING,packed
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

P=0x22016000;OBS=0x22017000;KEY=OBS+32;OUT=OBS+64;SLOTS=0x23200000

class ExchangeRig(HistoryRig):
    def __init__(self,count=4,capacity=256):
        super().__init__(512);m=self.m;m.uc.mem_map(SLOTS,0x20000)
        self.xlayout=struct.unpack('<7I',self.raw(self.syms['exchange_layout'],28))
        self.capacity=capacity;self.cursor=0;self.sequence=0
        put32(m,B,48000);put32(m,B+0x53e8,capacity)
        self.observe()
        assert self.xcall('exchange_init',SLOTS,count,OBS)==0
    def xcall(self,name,*args):return self.m.invoke(self.syms[name],[P,*args])
    def observe(self,cursor=None,callback=0x2022a791,copy_state=0,selected=0):
        self.m.uc.mem_write(OBS,struct.pack('<5I',self.cursor if cursor is None else cursor,
            self.capacity,callback,copy_state,selected))
    def key(self,value):self.m.uc.mem_write(KEY,struct.pack('<Q',value))
    def stage(self):
        samples=[values(self.sequence+i) for i in range(64)]
        self.floats(MIX,[v[0]*2**31 for v in samples]+[v[1]*2**31 for v in samples])
        self.observe();before=len(self.calls)
        status=self.xcall('exchange_stage',MIX,MIX+256,OBS)
        assert len(self.calls)==before
        return status
    def stock_advance(self):
        self.gain(.5);self.stock_staging()
        samples=struct.unpack('<128f',self.raw(STAGING));self.position=self.cursor
        self.master_block(list(samples[:64]),list(samples[64:]))
        self.cursor=struct.unpack('<I',self.raw(B+0x53e4,4))[0]
        self.observe()
    def commit(self):
        status=self.xcall('exchange_commit',OBS)
        if status==0:self.sequence+=64
        return status
    def block(self):
        status=self.stage();self.stock_advance();assert self.commit()==0;return status
    def claim(self,first):
        self.key(first);status=self.xcall('exchange_claim',KEY,OUT)
        return status,struct.unpack('<I',self.raw(OUT,4))[0]
    def release(self,first):self.key(first);return self.xcall('exchange_release',KEY)
    def resolve(self,selected):
        self.observe(selected=selected);status=self.xcall('exchange_resolve',OBS,OUT)
        return status,struct.unpack('<Q',self.raw(OUT,8))[0]
    def transfer(self,first):
        status,slot=self.claim(first);assert status==0
        self.m.uc.mem_write(STAMP,struct.pack('<Q',first))
        assert self.hcall('history_push',slot+self.xlayout[2],slot+self.xlayout[3],STAMP)==0
        self.next=first+64
        assert self.release(first)==0

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=ExchangeRig();assert r.stage()==0
    assert r.claim(0)[0]==11
    r.stock_advance()
    # Stock cursor has moved, but exchange hasn't published this block yet.
    assert r.resolve(r.cursor)[0]==11 and r.claim(0)[0]==11
    assert r.commit()==0
    assert r.resolve(r.cursor)==(0,64)
    status,slot=r.claim(0);assert status==0
    raw=struct.unpack('<128f',r.raw(slot+r.xlayout[2]))
    wanted=[values(i) for i in range(64)]
    assert raw==tuple([v[0]*2**31 for v in wanted]+[v[1]*2**31 for v in wanted])
    assert r.read_stream(10,position=0)==packed([v*.5 for pair in wanted for v in pair])
    assert r.release(0)==0
    passed('pre_master_snapshot_publishes_only_after_original_ring_advance_and_retains_pre_gain_samples')

    r=ExchangeRig(count=2)
    assert r.block()==0;status,slot=r.claim(0);assert status==0
    owned=r.raw(slot+r.xlayout[2])
    assert r.block()==0
    assert r.block()==11 # Producer reaches held slot; ordinary audio still runs.
    assert r.sequence==192 and r.raw(slot+r.xlayout[2])==owned
    assert r.claim(128)[0]==11
    assert r.release(128)==12 and r.release(0)==0
    assert r.claim(128)[0]==17
    assert r.block()==0 and r.block()==0
    assert r.claim(0)[0]==17
    status,new=r.claim(256);assert status==0 and new==slot
    assert r.release(256)==0
    passed('held_reader_prevents_overwrite_without_blocking_audio_and_missing_generation_is_detected')

    r=ExchangeRig();assert r.block()==0
    assert r.claim(0)[0]==0 and r.claim(0)[0]==11
    assert r.release(0)==0 and r.release(0)==12
    assert r.claim(1)[0]==12
    passed('duplicate_claim_wrong_release_and_unaligned_block_request_are_rejected')

    for change in ('callback','copy_disabled','cursor_jump','capacity'):
        r=ExchangeRig();assert r.block()==0
        r.observe(callback=0x80010961 if change=='callback' else 0x2022a791,
                  copy_state=2 if change=='copy_disabled' else 0,
                  cursor=128 if change=='cursor_jump' else None)
        if change=='capacity':put32(r.m,OBS+4,512)
        assert r.xcall('exchange_stage',MIX,MIX+256,OBS)==18
        assert r.resolve(r.cursor)[0]==18
    r=ExchangeRig();assert r.stage()==0
    assert r.commit()==18 # No stock advancement.
    r=ExchangeRig();assert r.stage()==0 and r.stage()==18
    passed('mode_copy_state_cursor_capacity_and_unpaired_callback_changes_latch_timeline_failure')

    r=ExchangeRig();assert r.block()==0
    version=P+r.xlayout[4];put32(r.m,version,3)
    assert r.resolve(64)[0]==11
    put32(r.m,version,2);reads=[]
    # Interrupt between the first version load and payload loads. An instruction
    # hook gives an explicit scheduling point instead of relying on emulator
    # memory-hook behavior for repeated reads within one translated block.
    address=r.syms['snapshot']&~1
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    point=next(a for a,n,m,o in md.disasm_lite(r.raw(address,100),address)
               if m.startswith('ldr') and '[r0, #0x2c]' in o)
    def interleave(uc,address,size,user):
        reads.append(1);put32(r.m,version,4)
    hook=r.m.uc.hook_add(UC_HOOK_CODE,interleave,begin=point,end=point)
    changed=r.resolve(64);r.m.uc.hook_del(hook)
    assert changed[0]==11,(changed,len(reads),r.raw(version,4).hex())
    assert len(reads)==1
    r=ExchangeRig();assert r.stage()==0;r.stock_advance()
    put32(r.m,P+r.xlayout[4],0xfffffffc)
    assert r.commit()==18
    passed('odd_changed_and_exhausted_publication_versions_cannot_yield_a_torn_timestamp')

    # Resolve at the real stock selector's return, before delayed start work.
    r=ExchangeRig();assert r.block()==0
    selected=r.m.invoke(0x80018f10,[])
    status,start=r.resolve(selected);assert (status,start)==(0,64)
    for _ in range(4):assert r.block()==0
    assert r.cursor==selected and r.sequence==320
    # Deliberately demonstrates why re-resolving a cached modulo cursor is wrong.
    assert r.resolve(selected)==(0,320) and start==64
    stop=r.m.invoke(0x80002460,[])
    assert r.resolve(stop)==(0,320)
    passed('original_start_and_stop_cursors_resolve_at_event_time_and_cached_cursor_alias_is_demonstrated',
           obligation='Resolve synchronously at event capture; delayed modulo cursors cannot identify their original lap')

    r=ExchangeRig(count=4,capacity=240000)
    for _ in range(4):assert r.block()==0
    r.m.uc.mem_write(0x80570c14,b'\1')
    selected=r.m.invoke(0x80018f10,[]) # 0.5-second branch clamped to 256 available.
    assert selected==0 and r.resolve(selected)==(0,0)
    assert r.resolve(239936)[0]==17 # Before the exchange's initial observation.
    passed('stock_history_selector_maps_available_retained_audio_and_rejects_before_origin')

    # Positive bridge: worker owns each slot while copying it into the existing
    # serialized history prototype; then that existing lifecycle makes a WAV.
    r=ExchangeRig(count=4,capacity=256)
    for i in range(12):
        assert r.block()==0;r.transfer(i*64)
        if i==1:assert r.begin(64)==0
        if i>=1:assert r.pump()==11
    assert r.block()==0;r.transfer(768)
    r.complete(785);r.validate(payload(64,785))
    passed('claimed_blocks_feed_existing_range_and_verified_pad_file_with_exact_721_frame_payload',
           limitation='Two buffers in this experiment; bridge scheduling remains harness-controlled')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        exchange_state_bytes=r.xlayout[0],slot_bytes=r.xlayout[1],
        limitations=['Emulated original windows; no installed pre-master or post-cursor hooks',
          'One producer/worker and coherent memory; device cache/interrupt/DMA/RTOS coverage unverified',
          'Synchronous event capture required; modulo positions cannot detect an entire unobserved ring lap',
          'No automatic exchange-error-to-file cancellation bridge or complete concurrent lifecycle yet',
          'Existing history remains serialized; this is a separate block ownership primitive',
          'Memory ownership, CPU overhead, pad-reader fence and deployment remain unverified'])
    target=ROOT/'analysis/block_exchange_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(target)),indent=2))

if __name__=='__main__':main()
