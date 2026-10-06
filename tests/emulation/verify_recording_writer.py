#!/usr/bin/env python3
"""Original L6 sample-to-WAV pipeline with in-memory filesystem/RTOS models.

No device IO, firmware patch, or actual concurrent scheduling. Pad-tap snapshot
and replacement are explicitly host-modeled. Post-record processing is excluded.
"""
import hashlib,json,struct
from unicorn.arm_const import UC_ARM_REG_R4,UC_ARM_REG_R11,UC_ARM_REG_S18
from verify_uncompressed_tap import TapRig,B,MIX,STAGING,packed
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
from verify_record_catalogue import putstr,getstr
from verify_scheduling_boundaries import stop

C=0x8077ca30

class WriterRig(TapRig):
    cpu_options={}
    def __init__(self,index=10,channels=2):
        super().__init__(**self.cpu_options);m=self.m
        self.index=index;self.channels=channels;self.frames=64;self.position=0
        self.files={1:bytearray()};self.cursor={1:0};self.queue=[];self.messages=[]
        self.fail_write=None;self.write_calls=[];self.reader_args=[]
        m.hooks.update({0x800622b0:self.write,0x80060620:self.read,
          0x8005f168:self.seek,0x8005ef40:self.stat,
          0x800376a0:self.request,0x8005e718:lambda a:512,
          0x800374f0:lambda a:1,0x80037638:lambda a:0,
          0x800385e8:lambda a:0,0x80076950:lambda a:1,
          0x800483f8:self.send,0x800483a8:self.receive,0x800763d8:lambda a:1})
        # Original callback registration and stock producer queue callback.
        m.invoke(0x80038258,[0x80002831])
        put32(m,C+0x1de0,0x80037591)
        put32(m,C+0x1de8,100000)
        put32(m,C+0x444,(1<<index) if channels==2 else 0)
        m.uc.mem_write(C+0x448+index,bytes([32]))
        for address in (C+0x440+index*4+0xd4,C+index*4+0x4e4,C+index*4+0x4b4):
            put32(m,address,100000)
        put32(m,C+0x1e4c+index*4,1)
        # Observe real callback arguments without replacing its body.
        from unicorn import UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_SP
        from verify_pad_protocol import REGS
        def observe(uc,a,s,u):
            args=[uc.reg_read(v) for v in REGS]
            args+=list(struct.unpack('<2I',uc.mem_read(uc.reg_read(UC_ARM_REG_SP),8)))
            self.reader_args.append(args)
        m.uc.hook_add(UC_HOOK_CODE,observe,begin=0x80002830,end=0x80002830)

    def write(self,a):
        h,p,n,out=a[:4];actual=n;status=0
        if self.fail_write:
            status,actual=self.fail_write
        data=self.raw(p,actual);f=self.files[h];q=self.cursor[h]
        f.extend(bytes(max(0,q+actual-len(f))));f[q:q+actual]=data
        self.cursor[h]+=actual;put32(self.m,out,actual)
        self.write_calls.append((n,actual,status));return status
    def read(self,a):
        h,p,n,out=a[:4];d=self.files[h][self.cursor[h]:self.cursor[h]+n]
        if d:self.m.uc.mem_write(p,bytes(d))
        self.cursor[h]+=len(d);put32(self.m,out,len(d))
        return 0 if len(d)==n else 0xffffd759
    def seek(self,a):
        h,offset,mode=a[:3]
        offset=offset if offset<2**31 else offset-2**32
        assert mode in (0,1,2)
        base=self.cursor[h] if mode==0 else len(self.files[h]) if mode==1 else 0
        assert base+offset>=0
        self.cursor[h]=base+offset;return 0
    def stat(self,a):
        # Original file-info driver reports length at +0 and position at +4.
        # The remaining fields are unused by the windows executed here.
        self.m.uc.mem_write(a[1],struct.pack('<4I',len(self.files[a[0]]),self.cursor[a[0]],0,0))
        return 0
    def request(self,a):
        for address,value in zip(a,(self.index,self.frames,self.position,128)):
            put32(self.m,address,value)
        return 0
    def send(self,a):
        message=self.raw(a[1],16);self.queue.append(message)
        self.messages.append(struct.unpack('<4I',message));return 0
    def receive(self,a):
        if not self.queue:return stop(self.m)
        self.m.uc.mem_write(a[1],self.queue.pop(0));return 0
    def header(self):
        m=self.m
        m.invoke(0x8000fb68,[0,48000,self.channels,32])
        put32(m,0x21031000,512)
        m.uc.mem_write(m.stack,struct.pack('<3I',0,0x21031000,512))
        assert m.invoke(0x8000fc68,[1,0,0,0x801f8ee0])==0
        assert len(self.files[1])==512
    def master_block(self,left,right):
        # Values here use the internal +/-2^31 full-scale convention.
        self.floats(STAGING,left+right)
        self.window(0x20227622,0x20227626)
        assert self.m.uc.reg_read(UC_ARM_REG_S18)==0x30000000
        put32(self.m,B+0x53e4,self.position)
        self.m.uc.reg_write(UC_ARM_REG_R11,B);self.m.uc.reg_write(UC_ARM_REG_R4,64)
        self.window(0x2022a55a,0x2022a77a)
    def produce(self):
        put32(self.m,C+0x440,1<<self.index)
        put32(self.m,C+0x1e2c,0)
        self.m.invoke(0x80038e60,[])
    def drain(self):self.m.invoke(0x80037380,[])
    def finish(self):
        assert self.m.invoke(0x8000ea08,[1,len(self.files[1])-512,0])==0
        data=bytes(self.files[1]);chunks={};offset=12
        assert data[:4]==b'RIFF' and data[8:12]==b'WAVE'
        assert struct.unpack_from('<I',data,4)[0]==len(data)-8
        while offset+8<=len(data):
            tag=data[offset:offset+4];n=struct.unpack_from('<I',data,offset+4)[0]
            assert offset+8+n<=len(data)
            chunks[tag]=data[offset+8:offset+8+n];offset+=8+n+(n&1)
        assert offset==len(data)
        assert struct.unpack('<HHIIHH',chunks[b'fmt '])==(3,self.channels,48000,48000*self.channels*4,self.channels*4,32)
        return chunks[b'data']

def main():
    results=[]
    def passed(case,**details):results.append(dict(case=case,passed=True,**details))
    r=WriterRig();r.header();expected=[]
    # Five distinct blocks cover silence, signed values, full scale and >1 float
    # values, and multiple wraps of the synthetic 128-frame source ring.
    for block in range(5):
        left=[0.0 if block==0 else (i-32)*(block/32) for i in range(64)]
        right=[0.0 if block==0 else (31-i)*(block/64) for i in range(64)]
        r.position=(block%2)*64
        r.master_block([v*2**31 for v in left],[v*2**31 for v in right])
        r.produce();r.drain()
        expected.extend(v for pair in zip(left,right) for v in pair)
    assert r.finish()==packed(expected)
    assert all(a[3:]==[10,2,4] and a[2]==64 for a in r.reader_args)
    assert len(r.reader_args)==5
    passed('five_blocks_through_original_scaling_reader_producer_queue_worker_and_WAV_finalizer',
           frames=320,channels=2,sample_rate=48000,format='IEEE float32',
           scale_bits='0x30000000',scale=2**-31,wav_sha256=hashlib.sha256(r.files[1]).hexdigest())
    assert len(r.messages)==5 and all(q[0:2]==(0,10) and q[3]==512 for q in r.messages)
    passed('producer_uses_stereo_32bit_reader_arguments_and_stream_10_write_requests')
    assert max(struct.unpack('<%df'%len(expected),r.finish()))>1
    passed('recording_conversion_preserves_above_full_scale_float_values_without_clipping')

    # Connect actual mixing to the writer, with only the new tap modeled.
    r=WriterRig();r.header()
    pad_l=[(i-32)/128 for i in range(64)];pad_r=[(63-i)/128 for i in range(64)]
    live=[i/256 for i in range(64)]
    r.pad(0,[v*2**31 for v in pad_l],[v*2**31 for v in pad_r])
    r.floats(B+0x10,[v*2**31 for v in live])
    r.floats(B+0x5e34,[1]+[0]*9+[.5]+[0]*9)
    clean=r.raw(B+0x10,2560);r.mix();snapshot=r.raw(MIX)
    r.gain(.25);monitor=r.raw(MIX);r.stock_staging()
    l,rr=struct.unpack('<64f',snapshot[:256]),struct.unpack('<64f',snapshot[256:])
    r.master_block(list(l),list(rr));r.produce();r.drain()
    want=packed([v for i in range(64) for v in (pad_l[i]+live[i],pad_r[i]+live[i]*.5)])
    assert r.finish()==want and r.raw(MIX)==monitor and r.raw(B+0x10,2560)==clean
    passed('modeled_pre_gain_tap_of_original_live_plus_pad_mix_survives_into_finalized_WAV_payload',
           limitation='Compressor body/effects excluded; snapshot substitution is host-modeled')

    # Mono 32-bit recording is also dispatched correctly, independently of master.
    r=WriterRig(0,1);r.header()
    from verify_uncompressed_tap import RING
    mono=[i/128 for i in range(64)];r.floats(RING,mono)
    r.produce();assert not r.messages # 256-byte remainder, below sector size.
    r.position=64;r.floats(RING+256,mono);r.produce();r.drain()
    assert r.finish()==packed(mono*2)
    assert all(a[3:]==[0,1,4] for a in r.reader_args)
    passed('mono_stream_retains_partial_sector_until_next_block_then_writes_exact_samples')

    for status,n,name in ((0,128,'short_write'),(0xffffd825,0,'io_error')):
        r=WriterRig();r.header();r.master_block([0]*64,[0]*64);r.produce()
        r.fail_write=(status,n);r.drain()
        error=struct.unpack('<I',r.raw(C+0x1e48,4))[0]
        assert error==(0xffffd826 if status==0 else status)
        passed('original_worker_records_'+name,error=hex(error),
               limitation='Does not verify global recovery or assignment suppression')

    # Destination construction and real create-call arguments, not a path patch.
    r=WriterRig();m=r.m
    directory='A:\\RECORDER\\261003_120000'
    putstr(m,0x8060ff80,directory);m.invoke(0x80022e50,[0x800a32e0])
    paths=[];opened=[]
    segment=[1]
    m.hooks[0x80021d48]=lambda a:segment[0]
    def opened_file(a):
        opened.append(dict(path=getstr(m,a[1]),flags=hex(a[2]),attributes=hex(a[3])))
        put32(m,a[0],1);return 0
    m.hooks[0x8005ffe8]=opened_file
    for channel in (0,2,10):
        for part in (1,2):
            segment[0]=part
            working=getstr(m,m.invoke(0x80022bb8,[channel]))
            final=getstr(m,m.invoke(0x80022c80,[channel,part]))
            assert working==directory+'\\Work\\'+final.rsplit('\\',1)[1]
            m.uc.reg_write(UC_ARM_REG_R4,channel)
            r.window(0x8000438e,0x800043a6)
            assert opened[-1]['path']==working and opened[-1]['flags']=='0x102'
            paths.append(dict(stream=channel,part=part,working=working,final=final))
    passed('original_recording_create_uses_Work_paths_for_input_and_master_segments',paths=paths)
    original=getstr(m,m.invoke(0x80022c80,[10,1]))
    shared=m.invoke(0x80022c80,[0,1])
    assert getstr(m,shared)!=original
    passed('path_builders_share_storage_requiring_owned_paths_for_async_use')

    report=dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
      limitations=['Original instruction windows/functions, synthetic initialized state and in-memory files',
        'RTOS queue, locks, request metadata, disk-space check and public filesystem operations modeled',
        'WAV header created with original fmt chunk and padding; production BEXT/other metadata omitted',
        'No complete record start/stop, post-processing, pad destination change or assignment executed',
        'No concurrency, SD durability, real-time performance, hardware or firmware installation tested'])
    target=ROOT/'analysis/recording_writer_verification.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(target)),indent=2))

if __name__=='__main__':main()
