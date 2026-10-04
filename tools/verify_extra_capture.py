#!/usr/bin/env python3
"""Additional stereo capture beside all stock streams, entirely offline.

Runs compiled new buffer code plus original DSP/recording/WAV functions.
Filesystem, scheduling, capture hook location and lifecycle fencing are modeled.
"""
import hashlib,json,struct
from elftools.elf.elffile import ELFFile
from unicorn.arm_const import UC_ARM_REG_R11
from verify_recording_writer import WriterRig,C
from verify_uncompressed_tap import B,MIX,STAGING,RING,STRIDE,packed
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE

ELF=ROOT/'prototype/extra_capture/capture.elf'
STATE=0x22000000
STREAMS=((0,1),(1,1),(2,2),(4,2),(6,2),(8,2),(10,2))

class ExtraRig(WriterRig):
    def __init__(self):
        super().__init__();m=self.m
        m.uc.mem_map(0x10010000,0x10000);m.uc.mem_map(STATE,0x20000)
        with ELF.open('rb') as f:
            elf=ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type']=='PT_LOAD' and seg['p_filesz']:m.uc.mem_write(seg['p_vaddr'],seg.data())
            self.syms={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
        self.layout=struct.unpack('<6I',self.raw(self.syms['extra_layout'],24))
        self.call('extra_init',8)
        self.handles={index:i+1 for i,(index,channels) in enumerate(STREAMS)}
        self.channels_by_handle={i+1:ch for i,(index,ch) in enumerate(STREAMS)}
        self.channels_by_handle[8]=2
        self.files={h:bytearray() for h in range(1,9)};self.cursor={h:0 for h in range(1,9)}
        self.failure_by_handle={};self.payload_writes=[]
        m.hooks[0x800374f0]=lambda a:self.handles[a[0]]
        mask=0
        for index,channels in STREAMS:
            if channels==2:mask|=1<<index
            m.uc.mem_write(C+0x448+index,bytes([32]))
            for a in (C+0x440+index*4+0xd4,C+index*4+0x4e4,C+index*4+0x4b4):put32(m,a,100000)
            put32(m,C+0x1e4c+index*4,self.handles[index])
        put32(m,C+0x444,mask)
    def call(self,name,*args):return self.m.invoke(self.syms[name],[STATE,*args])
    def write(self,a):
        old=self.fail_write;self.fail_write=self.failure_by_handle.get(a[0])
        try:
            self.payload_writes.append((a[0],a[2]))
            return super().write(a)
        finally:self.fail_write=old
    def headers(self):
        for handle,channels in self.channels_by_handle.items():
            self.m.invoke(0x8000fb68,[0,48000,channels,32])
            put32(self.m,0x21031000,512)
            self.m.uc.mem_write(self.m.stack,struct.pack('<3I',0,0x21031000,512))
            assert self.m.invoke(0x8000fc68,[handle,0,0,0x801f8ee0])==0
            assert len(self.files[handle])==512
    def finish_file(self,handle):
        assert self.m.invoke(0x8000ea08,[handle,len(self.files[handle])-512,0])==0
        f=self.files[handle];assert f[:4]==b'RIFF' and f[8:12]==b'WAVE'
        assert struct.unpack_from('<I',f,4)[0]==len(f)-8
        offset=12;chunks={}
        while offset+8<=len(f):
            name=bytes(f[offset:offset+4]);n=struct.unpack_from('<I',f,offset+4)[0]
            assert offset+8+n<=len(f)
            chunks[name]=bytes(f[offset+8:offset+8+n]);offset+=8+n+(n&1)
        channels=self.channels_by_handle[handle]
        assert struct.unpack('<HHIIHH',chunks[b'fmt '])==(3,channels,48000,48000*channels*4,channels*4,32)
        assert offset==len(f)
        return chunks[b'data']
    def capture(self,left=None,right=None):
        if left is not None:self.floats(MIX,left+right)
        return self.call('extra_capture',MIX,MIX+256)
    def all_stock(self,position):
        self.position=position
        for index,channels in STREAMS:
            self.index=index;self.channels=channels;self.produce();self.drain()
    def pump_extra(self):
        while True:
            status=self.call('extra_drain')
            if status:return status


def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=ExtraRig();m=r.m
    before=r.raw(C,0x4000)
    m.uc.mem_write(m.stack,bytes(8))
    m.invoke(0x80037ca0,[12,0xabcdef,1,32])
    assert r.raw(C,0x4000)==before
    # Existing test fixture stubs the handle getter; remove it for this test.
    del m.hooks[0x800374f0]
    assert m.invoke(0x800374f0,[12])==0
    m.uc.mem_write(0x21030000,b'\xa5'*512)
    assert r.read_stream(12)==bytes(512)
    passed('stock_stream_12_registration_and_handle_lookup_reject_index_and_reader_returns_silence')

    r=ExtraRig();r.headers();m=r.m;expected={h:[] for h in range(1,9)}
    for block in range(18):
        inputs=[[(i-32+c+block)/256 for i in range(64)] for c in range(10)]
        pad_l=[(i+block)/512 for i in range(64)]
        pad_r=[(63-i-block)/512 for i in range(64)]
        r.pad(0,[v*2**31 for v in pad_l],[v*2**31 for v in pad_r])
        for c in range(10):r.floats(B+0x10+c*256,[v*2**31 for v in inputs[c]])
        r.floats(B+0x5e34,[1]+[0]*9+[0,1]+[0]*8)
        clean=r.raw(B+0x10,2560);r.mix();pre=r.raw(MIX)
        writes=len(r.payload_writes)
        assert r.capture()==0 and len(r.payload_writes)==writes
        assert r.raw(MIX)==pre and r.raw(B+0x10,2560)==clean
        left=[a+b for a,b in zip(inputs[0],pad_l)]
        right=[a+b for a,b in zip(inputs[1],pad_r)]
        expected[8].extend(v for pair in zip(left,right) for v in pair)
        r.gain(.5);r.stock_staging()
        # Input staging is supplied by this fixture; actual producer copies all
        # 12 staged channels, including the original master, into stock rings.
        for c in range(10):r.floats(B+0xc10+c*256,[v*2**31 for v in inputs[c]])
        r.window(0x20227622,0x20227626);put32(m,B+0x53e4,(block%2)*64)
        m.uc.reg_write(UC_ARM_REG_R11,B);r.window(0x20229b82,0x2022a77a)
        for index,channels in STREAMS:
            values=([v*.5 for v in left],[v*.5 for v in right]) if index==10 else inputs[index:index+channels]
            expected[r.handles[index]].extend(v for pair in zip(*values) for v in pair)
        r.all_stock((block%2)*64)
        # Deliberately retain the extra snapshot across later audio mutation.
        r.floats(MIX,[12345.0]*128)
        if block%6==5:assert r.pump_extra()==1
    assert not r.call('extra_ready')
    r.call('extra_stop_quiesced');assert r.call('extra_ready')
    for handle in range(1,9):assert r.finish_file(handle)==packed(expected[handle])
    passed('all_seven_stock_files_and_additional_stereo_WAV_have_independent_exact_payloads',
           frames_per_file=1152,stock_files=7,additional_files=1,
           limitation='Normal master gain executed; compressor/effects excluded; input staging and tap hook supplied by fixture')
    assert r.files[7]!=r.files[8]
    passed('ordinary_master_retains_gain_while_extra_file_has_pre_gain_mix')
    assert all(h!=8 or n<=4096 for h,n in r.payload_writes)
    passed('compiled_capture_owns_snapshots_without_IO_and_worker_batches_writes_up_to_4KiB')

    r=ExtraRig();r.headers();samples=[2**30]*64
    slots=r.layout[2]
    for i in range(slots):assert r.capture(samples,[-2**29]*64)==0
    owned=r.raw(STATE+r.layout[1],slots*512)
    assert r.capture([0]*64,[0]*64)==3
    assert r.raw(STATE+r.layout[1],slots*512)==owned
    assert r.call('extra_drain')==3
    r.call('extra_stop_quiesced');assert not r.call('extra_ready')
    passed('buffer_exhaustion_faults_extra_capture_without_overwriting_owned_audio',
           capacity_blocks=slots,capacity_bytes=slots*512,nominal_stall_ms=slots*64/48000*1000)
    # A stock master can still be produced after the optional capture has failed.
    r.master_block(samples,[-2**29]*64);r.index=10;r.channels=2;r.produce();r.drain()
    assert r.finish_file(7)==packed([v for _ in range(64) for v in (.5,-.25)])
    passed('ordinary_master_writer_still_operates_after_extra_capture_overflow',
           limitation='Harness deliberately keeps calling ordinary path; device hook must do the same')

    # Ring reuse across wraps with bursts that do not divide 128 slots.
    r=ExtraRig();r.headers();wanted=[]
    for i in range(300):
        value=(i-150)/256
        assert r.capture([value*2**31]*64,[-value*2**31]*64)==0
        wanted.extend([value,-value]*64)
        if i%11==10:assert r.pump_extra()==1
    r.call('extra_stop_quiesced');assert not r.call('extra_ready')
    assert r.pump_extra()==1 and r.call('extra_ready')
    assert r.finish_file(8)==packed(wanted)
    passed('extra_ring_wrap_and_partial_final_batch_preserve_every_sample_in_order')

    for failure,label in (((0,256),'short_write'),((0xffffd825,0),'io_error')):
        r=ExtraRig();r.headers();assert r.capture(samples,samples)==0
        old_read=r.raw(STATE+4,4);r.failure_by_handle[8]=failure
        assert r.call('extra_drain')==4 and r.raw(STATE+4,4)==old_read
        assert r.capture(samples,samples)==4
        r.call('extra_stop_quiesced');assert not r.call('extra_ready')
        assert struct.unpack('<I',r.raw(C+0x1e48,4))[0]==0
        passed('extra_'+label+'_prevents_success_without_altering_stock_error_state')
    r=ExtraRig();r.headers();r.call('extra_stop_quiesced')
    assert not r.call('extra_ready') and r.capture(samples,samples)==2
    passed('empty_or_stopped_capture_cannot_be_exposed_as_completed_audio')
    r=ExtraRig();r.headers();assert r.capture(samples,samples)==0
    put32(r.m,STATE+20,r.layout[5]);before=len(r.files[8])
    assert r.call('extra_drain')==5 and len(r.files[8])==before
    r.call('extra_stop_quiesced');assert not r.call('extra_ready')
    passed('prototype_size_limit_faults_instead_of_wrapping_WAV_length',
           limitation='Split files not implemented; limit is conservative and synthetic')

    report=dict(passed_groups=len(results),results=results,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        prototype_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        layout=dict(state_bytes=r.layout[0],buffer_offset=r.layout[1],slots=r.layout[2]),
        bandwidth=dict(stock_bytes_per_second=12*48000*4,extra_bytes_per_second=2*48000*4,
                       combined_bytes_per_second=14*48000*4,increase_percent=100*2/12),
        limitations=['Offline serially scheduled original functions and separately compiled new code',
          'Synthetic file handles and memory; no actual exclusive creation or pad-folder routing',
          'WAV headers/finalizers run separately with stock shared format state; metadata options omitted',
          'Single producer/consumer contract; quiescent start/stop fence and installed hook unbound',
          'No performance, SD throughput/stall, memory availability, real concurrency or power-loss validation',
          'Original compressor/effects and input ADC/staging production excluded',
          'Pad assignment, unique filenames, checked close, verification and split-file lifecycle not implemented'])
    target=ROOT/'analysis/extra_capture_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(target)),indent=2))

if __name__=='__main__':main()
