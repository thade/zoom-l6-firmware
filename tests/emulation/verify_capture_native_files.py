#!/usr/bin/env python3
"""Capture-only lifecycle through stock create/open/seek/info and FAT code.

Only card sectors, mounted geometry and kernel scheduling are fixtures. File
names, handles, allocation, cached metadata and readback are native instructions.
Ordinary files retain the integration harness's independent bytearray backend.
No image/device access; a sector callback return models synchronous completion.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_capture_integration import IntegrationRig,record
from verify_native_filesystem import NativeFiles,VOLUME,CACHE,PARTITION,FAT,DATA,MIRROR,SD,READ,WRITE,CLOSE,IO_ERROR,SECTOR_BYTES
from verify_native_filesystem_sd import NativeFileSd
from verify_capture_transitions import CaptureFiles,POOL,UI,FS1,FS2,FS4,FS5,FS6
from verify_native_worker import HANDLE as WORKER_TASK
from verify_sd_checked_recovery import RecoveryPorts
from sd_registers import PRESENT,CLOCK_STABLE,DAT0_HIGH
from verify_control_transport import TASK
from verify_record_catalogue import putstr,getstr
from verify_firmware_workflow import put32,BUFFER,RESULT
from verify_record_scheduler import word
from verify_pad_protocol import IMAGE,ROOT,REGS,INPUT
from verify_session_manager import LIVE,STOPPED,BLOCKED,RESET
from verify_uncompressed_tap import packed

OPEN,SEEK,INFO=0x8005ffe8,0x8005f168,0x8005ef40
NOT_FOUND,EXISTS=0xffffd75a,0xffffd75b
PAD_CLUSTERS=(4,5,6,7)
POOL_COUNT=100

def directory_entries(name,short,cluster,attrs=0x10,size=0):
    """Encode fixture directory bytes; firmware parses these, never this helper."""
    assert len(short)==11
    entry=bytearray(32);entry[:11]=short;entry[11]=attrs
    struct.pack_into('<H',entry,20,cluster>>16)
    struct.pack_into('<H',entry,26,cluster&0xffff)
    struct.pack_into('<I',entry,28,size)
    if name.upper()==(short[:8].decode().rstrip()+('.'+short[8:].decode().rstrip() if short[8:].strip() else '')):
        return bytes(entry)
    checksum=0
    for c in short:checksum=(((checksum&1)<<7)+(checksum>>1)+c)&255
    units=list(struct.unpack('<%dH'%len(name),name.encode('utf-16le')))+[0]
    units += [0xffff]*((-len(units))%13)
    lfn=[]
    for i in reversed(range(len(units)//13)):
        e=bytearray(b'\xff'*32);e[0]=(i+1)|(0x40 if i==len(units)//13-1 else 0)
        e[11:14]=bytes((0xf,0,checksum));e[26:28]=b'\0\0'
        for p,u in zip((1,3,5,7,9,14,16,18,20,22,24,28,30),units[i*13:(i+1)*13]):
            struct.pack_into('<H',e,p,u)
        lfn.append(bytes(e))
    return b''.join(lfn)+bytes(entry)

class NativeTree(NativeFiles):
    def __init__(self,**kwargs):
        NativeFiles.__init__(self,**kwargs);m=self.m
        # A controlled already-mounted FAT32 volume. Neither BPB mount nor
        # allocation bitmap/FSInfo initialization is represented by this setup.
        m.uc.mem_write(VOLUME+4,b'\x01');m.uc.mem_write(VOLUME+0x206,b'\x01')
        m.uc.mem_write(VOLUME+0x207,b'\x01')
        for offset,value in ((0x224,2),(0x22c,0),(0x238,8),(0x23c,57)):
            put32(m,VOLUME+offset,value)
        fat=bytearray(SECTOR_BYTES);struct.pack_into('<II',fat,0,0x0ffffff8,0x0fffffff)
        for c in range(2,8):struct.pack_into('<I',fat,c*4,0x0fffffff)
        self.sectors={PARTITION+FAT:bytes(fat),PARTITION+FAT+MIRROR:bytes(fat)}
        for c in range(2,8):
            for s in range(8):self.sectors[self.physical(c,s)]=bytes(SECTOR_BYTES)
        root=directory_entries('SOUND_PAD',b'SOUND_~1   ',3)
        sound=b''.join(directory_entries('PAD%d'%(i+1),('PAD%d'%(i+1)).encode().ljust(11,b' '),c) for i,c in enumerate(PAD_CLUSTERS))
        self.sectors[self.physical(2)]=root.ljust(SECTOR_BYTES,b'\0')
        self.sectors[self.physical(3)]=sound.ljust(SECTOR_BYTES,b'\0')
        for i in range(POOL_COUNT):m.uc.mem_write(POOL+i*0x2c4,b'\xff')
        for pc in (OPEN,READ,WRITE,CLOSE,SEEK,INFO,0x800670b0,0x8001d9b0,
                   0x800604e8,0x80060818,0x800624a8,0x8005c388,0x8005f350,0x8005f0a0):
            m.hooks.pop(pc,None)
        # Original immutable locale tables remain loaded with MAIN.
        assert word(m,0x8000173c)==0x80079d2c and word(m,0x80079d2c)==0x80079ca9
        m.invoke(0x80074d08,[]) # stock long-filename scratch initialization
        for pc,name in ((0x800604e8,'open'),(0x8005f350,'seek'),(0x8005f0a0,'info')):
            def observe(uc,address,size,user,name=name):
                self.active_handle=uc.reg_read(A.UC_ARM_REG_R0)
                if name=='info':
                    # INFO constructs an exception context but does not take
                    # filesystem tokens; its driver only copies handle fields.
                    assert self.locks.tokens=={UI} and word(m,0x801f8df0)==self.current_task()
                else:self.locks.driver(name)
                self.entries.append(name)
            m.uc.hook_add(UC_HOOK_CODE,observe,begin=pc,end=pc)
    def open(self,path,flags=0,attrs=0x100):
        putstr(self.m,INPUT,path);put32(self.m,RESULT,0xdeadbeef)
        status=self.m.invoke(OPEN,[RESULT,INPUT,flags,attrs])
        assert self.locks.tokens=={UI} and word(self.m,0x801f8df0)==0
        return status,word(self.m,RESULT)
    def file_bytes(self,handle):
        """Independent sector/FAT inspection after close, not a read provider."""
        length=word(self.m,handle+0x21c);cluster=word(self.m,handle+0x220)
        return self.content(length,cluster)
    def content(self,length,cluster):
        data=bytearray();seen=set();fat=self.sectors[PARTITION+FAT]
        while len(data)<length:
            assert 2<=cluster<=64 and cluster not in seen
            seen.add(cluster)
            data.extend(b''.join(self.sectors.get(self.physical(cluster,s),bytes(SECTOR_BYTES)) for s in range(8)))
            cluster=struct.unpack_from('<I',fat,cluster*4)[0]&0x0fffffff
        return bytes(data[:length])
    def files_in_pad(self,pad=0):
        return self.directory(PAD_CLUSTERS[pad])
    def directory(self,cluster):
        directory=b''.join(self.sectors.get(self.physical(cluster,s),bytes(SECTOR_BYTES)) for s in range(getattr(self,'spc',8)))
        files={};long={};last=None;checksum=None
        for p in range(0,len(directory),32):
            e=directory[p:p+32]
            if e[0]==0:break
            if e[0]==0xe5:long={};continue
            if e[11]==0xf:
                ordinal=e[0]&0x1f
                if e[0]&0x40:long={};last=ordinal;checksum=e[13]
                assert ordinal and e[13]==checksum and e[12]==0 and e[26:28]==b'\0\0'
                long[ordinal]=[struct.unpack_from('<H',e,i)[0] for i in (1,3,5,7,9,14,16,18,20,22,24,28,30)]
                continue
            if long:
                actual=0
                for c in e[:11]:actual=(((actual&1)<<7)+(actual>>1)+c)&255
                assert checksum==actual and set(long)==set(range(1,last+1))
                units=[u for i in range(1,last+1) for u in long[i]]
                if 0 in units:units=units[:units.index(0)]
                assert 0xffff not in units
                name=struct.pack('<%dH'%len(units),*units).decode('utf-16le')
            else:name=e[:8].decode().rstrip()+('.'+e[8:11].decode().rstrip() if e[8:11].strip() else '')
            long={}
            cluster=(struct.unpack_from('<H',e,20)[0]<<16)|struct.unpack_from('<H',e,26)[0]
            length=struct.unpack_from('<I',e,28)[0]
            files[name]=dict(cluster=cluster,length=length,attributes=e[11],data=self.content(length,cluster))
        return files

class NativeTreeSd(NativeTree,NativeFileSd):
    def __init__(self,**kwargs):
        NativeTree.__init__(self,**kwargs)
        self.configure_sd()

class NativeCapture(IntegrationRig):
    other_task=CaptureFiles.other_task
    def __init__(self,native_sd=False,filesystem=None):
        super().__init__();m=self.m
        self.fs=(filesystem or (NativeTreeSd if native_sd else NativeTree))(m=m,task=lambda:word(m,TASK),send=self.kernel_send,ordinary_events=True)
        self.file_take=m.hooks[0x80076950];self.file_give=m.hooks[0x800763d8]
        self.native_calls=[]
        ordinary={WRITE:self.io_write,READ:self.io_read,SEEK:self.io_seek,INFO:self.io_info}
        for pc,name in ((OPEN,'open'),(WRITE,'write'),(READ,'read'),(SEEK,'seek'),(INFO,'info'),(CLOSE,'close')):
            def public(uc,address,size,user,pc=pc,name=name):
                a=[uc.reg_read(reg) for reg in REGS]
                assert not self.audio_active,'File I/O inside audio callback'
                if pc in ordinary and a[0] in self.files:
                    uc.reg_write(REGS[0],ordinary[pc](a))
                    uc.reg_write(A.UC_ARM_REG_PC,uc.reg_read(A.UC_ARM_REG_LR));return
                assert not self.locks.tokens-{UI}
                self.calls.append('native_'+name)
                self.native_calls.append(dict(operation=name,args=a,
                    path=getstr(m,a[1]) if pc==OPEN else None))
            m.uc.hook_add(UC_HOOK_CODE,public,begin=pc,end=pc)
    @property
    def locks(self):return self.fs.locks
    def request(self,ui=0):
        try:return super().request(ui)
        finally:
            self.m.hooks[0x80076950]=self.file_take
            self.m.hooks[0x800763d8]=self.file_give
    def completed_extra(self):
        self.drive(lambda:self.mstate()==RESET,with_audio=False)
        session,path=self.result();assert session==123 and path.endswith('.TMP')
        data=self.fs.files_in_pad()[path.rsplit('\\',1)[1]]['data']
        assert data[512:]==packed(self.expected_extra)
        assert struct.unpack_from('<I',data,508)[0]==len(self.expected_extra)*4
        assert self.locks.tokens=={UI} and word(self.m,0x801f8df0)==0
        assert not self.opened and not any(self.raw(POOL+i*0x2c4,1)==b'\x40' for i in range(POOL_COUNT))
        self.assert_ordinary();return data
    def retained(self,tokens):
        previous=word(self.m,TASK);put32(self.m,TASK,WORKER_TASK)
        try:self.fs.retained(tokens)
        finally:put32(self.m,TASK,previous)
    def resume_sd(self):
        previous=word(self.m,TASK);put32(self.m,TASK,WORKER_TASK)
        self.fs.stalled=False
        try:return RecoveryPorts.resume(self.fs)
        finally:put32(self.m,TASK,previous)

def seed(fs,path,data=b'old backing'):
    status,h=fs.open(path,0x501,0x80);assert status==0
    fs.m.uc.mem_write(BUFFER,data)
    assert fs.m.invoke(WRITE,[h,BUFFER,len(data),RESULT])==0 and word(fs.m,RESULT)==len(data)
    assert fs.m.invoke(CLOSE,[h])==0

def failed(r,state=STOPPED):
    r.drive(lambda:r.mstate()==state,with_audio=False)
    assert r.result()==12 and not r.life('life_verified_path')
    assert r.locks.tokens=={UI} and word(r.m,0x801f8df0)==0
    calls=list(r.calls);snapshot=r.raw(0x22000000,0x1d000)
    for _ in range(3):r.tick()
    assert r.calls==calls and r.raw(0x22000000,0x1d000)==snapshot
    if state==BLOCKED:assert r.resume()==12

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=NativeTree();path='A:\\SOUND_PAD\\PAD1\\OD_00000001.TMP'
    assert r.open(path)==(NOT_FOUND,0)
    status,h=r.open(path,0x501,0x80);assert status==0,(hex(status),h,r.requests)
    payload=bytes((i*37)%256 for i in range(5700));r.m.uc.mem_write(BUFFER,payload)
    assert r.m.invoke(WRITE,[h,BUFFER,len(payload),RESULT])==0 and word(r.m,RESULT)==len(payload)
    assert r.m.invoke(SEEK,[h,0,2])==0
    assert r.m.invoke(CLOSE,[h])==0
    assert r.file_bytes(h)==payload
    status,h=r.open(path);assert status==0
    assert r.m.invoke(INFO,[h,RESULT])==0 and word(r.m,RESULT)==len(payload)
    assert struct.unpack('<4I',r.raw(RESULT,16))==(5700,0,0,8192-5700)
    assert r.m.invoke(SEEK,[h,4200,2])==0
    assert r.m.invoke(READ,[h,BUFFER,37,RESULT])==0 and word(r.m,RESULT)==37
    assert r.raw(BUFFER,37)==payload[4200:4237]
    assert r.m.invoke(SEEK,[h,0,2])==0
    assert r.m.invoke(READ,[h,BUFFER,len(payload),RESULT])==0 and word(r.m,RESULT)==len(payload)
    assert r.raw(BUFFER,len(payload))==payload and r.m.invoke(CLOSE,[h])==0
    assert r.files_in_pad()['OD_00000001.TMP']['data']==payload
    assert r.open(path,0x501,0x80)==(EXISTS,0)
    assert r.files_in_pad()['OD_00000001.TMP']['data']==payload
    passed('native_pool_create_LFN_exclusive_collision_INFO_cross_cluster_SEEK_close_and_reopen_readback',bytes=len(payload))

    for pad in range(4):
        r=NativeTree();seed(r,f'A:\\SOUND_PAD\\PAD{pad+1}\\OD_00000001.TMP')
        assert r.files_in_pad(pad)['OD_00000001.TMP']['data']==b'old backing'
        assert all(not r.files_in_pad(p) for p in range(4) if p!=pad)
    passed('native_path_traversal_and_creation_resolve_each_of_the_four_pad_folders')
    r=NativeTree()
    for i in range(POOL_COUNT):r.m.uc.mem_write(POOL+i*0x2c4,b'\0')
    before=dict(r.sectors)
    assert r.open(path,0x501,0x80)[0]!=0 and r.sectors==before and not r.requests
    assert not r.entries
    passed('native_pool_exhaustion_fails_before_filesystem_driver_or_sector_mutation')

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    for native_sd in (False,True):
        r=NativeCapture(native_sd);assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        extra=r.completed_extra()
        assert extra[512:]!=ordinary[7][512:]
        assert r.fs.sectors[PARTITION+FAT]==r.fs.sectors[PARTITION+FAT+MIRROR]
        # Inspect the finalized on-sector filename/size/cluster, independently
        # of the native readback which made the lifecycle eligible.
        f=r.fs.files_in_pad()['OD_00000001.TMP']
        assert f['attributes']==0x20 and f['length']==len(extra) and f['cluster']==8
        assert [c['args'][2] for c in r.native_calls if c['operation']=='read']==[512,4096,4096,4096,512]
        status,h=r.fs.open(r.result()[1]);assert status==0
        put32(r.m,r.m.stack,0x21034000)
        assert r.m.invoke(0x8000f0b0,[h,0,0x21033100,0])==0
        assert r.raw(0x21033100,24)==extra[12:36]
        assert struct.unpack('<Q',r.raw(0x21034000,8))[0]==25*64
        assert r.m.invoke(CLOSE,[h])==0
        if native_sd:
            assert sum(n for op,dma,n,s in r.fs.dma_effects)==sum(q['count'] for q in r.fs.requests if q['op'] in (2,3))
            assert {op for op,dma,n,s in r.fs.dma_effects if dma==0x2000c4d4}=={2,3}
            assert not r.fs.joins and len(r.fs.finishes)==sum(q['op'] in (2,3) for q in r.fs.requests)
        passed('complete_capture_through_native_files_and_'+('SD_driver' if native_sd else 'sector_callback')+'_preserves_seven_stock_files_and_passes_original_WAV_parser',
               frames=25*64,extra_bytes=len(extra),requests=len(r.fs.requests),extra_sha256=hashlib.sha256(extra).hexdigest())

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2)
    r=NativeCapture()
    seed(r.fs,'A:\\SOUND_PAD\\PAD1\\OD_00000001.WAV',b'previous mix')
    seed(r.fs,'A:\\SOUND_PAD\\PAD1\\OD_00000002.TMP',b'abandoned take')
    old=r.fs.files_in_pad()
    assert r.boot(release=True)==0;r.ready();r.sequence=0
    assert r.path().endswith('00000003.TMP')
    assert record(r,delay=2)==ordinary;r.completed_extra()
    files=r.fs.files_in_pad()
    assert all(files[name]==value for name,value in old.items())
    passed('compiled_lifecycle_skips_native_WAV_and_TMP_collisions_without_altering_either_existing_file')

    r=NativeCapture()
    for i in range(1,33):seed(r.fs,f'A:\\SOUND_PAD\\PAD1\\OD_{i:08X}.TMP',bytes([i]))
    before=r.fs.files_in_pad();r.native_calls=[];preparations=[]
    def prepare(uc,pc,n,u):preparations.append(sum(c['operation']=='open' for c in r.native_calls))
    pc=r.syms['life_prepare']&~1
    r.m.uc.hook_add(UC_HOOK_CODE,prepare,begin=pc,end=pc)
    assert r.boot(release=True)==0;r.ready();r.sequence=0
    # The private-file profile yields after 32 candidates, then searches the
    # next batch. It does not treat one full batch as permanent exhaustion.
    assert preparations==[0,64] and r.path().endswith('00000021.TMP')
    assert record(r,delay=2)==ordinary;r.completed_extra()
    assert all(r.fs.files_in_pad()[name]==value for name,value in before.items())
    passed('native_TMP_collision_search_yields_after_32_candidates_then_creates_next_name_without_altering_existing_files')

    for fault in ('lookup','full'):
        r=NativeCapture()
        if fault=='lookup':r.fs.fail=lambda q:q['op']==2 and q['sector']==PARTITION+FAT
        else:put32(r.m,VOLUME+0x23c,0)
        assert r.boot(release=True)==0;failed(r)
        r.sequence=0;assert record(r,delay=2)==ordinary
    passed('native_lookup_error_and_full_volume_withhold_capture_without_changing_ordinary_recording',faults=2)

    for sector in (PARTITION+FAT,PARTITION+FAT+MIRROR,PARTITION+DATA+16,None):
        r=NativeCapture();assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2)==ordinary
        r.fs.fail=lambda q,s=sector:q['op']==(6 if s is None else 3) and q['sector']==s
        failed(r,BLOCKED)
        assert r.raw(POOL,1)==b'\xff'
        assert not any(c['operation']=='info' for c in r.native_calls)
    passed('native_close_FAT_primary_mirror_directory_and_barrier_errors_block_eligibility_and_close_retry',faults=4)

    for fault in ('read_error','corrupt_audio'):
        r=NativeCapture();assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2)==ordinary
        if fault=='read_error':r.fs.fail=lambda q:q['op']==2 and q['sector']==r.fs.physical(8,1)
        else:
            def corrupt(uc,pc,n,u):
                p=r.fs.physical(8,1);b=bytearray(r.fs.sectors[p]);b[0]^=1;r.fs.sectors[p]=bytes(b)
            r.m.uc.hook_add(UC_HOOK_CODE,corrupt,begin=0x8005f0a0,end=0x8005f0a0)
        failed(r)
        assert any(c['operation']=='read' for c in r.native_calls)
    passed('native_readback_error_or_changed_sector_bytes_withhold_verified_result',faults=2)

    # A native OPEN lookup failure holds all five file tokens while the MODEL
    # SD join withholds permission. Only the original call is resumed.
    r=NativeCapture(native_sd=True);r.fs.inject=(2,PARTITION+FAT,'data')
    assert r.boot(release=True)==0
    for _ in range(4):
        r.tick()
        if r.fs.stalled:break
    r.retained((UI,FS1,FS2,FS4,FS5,FS6));frame=r.fs.frame();requests=list(r.fs.requests)
    r.resume_sd();r.retained((UI,FS1,FS2,FS4,FS5,FS6))
    assert frame==r.fs.frame() and requests==r.fs.requests
    r.fs.join_allowed=True;r.resume_sd();failed(r)
    assert not r.fs.owner() and len(r.fs.joins)==3 and r.fs.requests==requests
    passed('native_OPEN_failure_retains_compiled_worker_lifecycle_exception_frame_and_five_file_tokens_until_MODEL_join')

    for nominal in (False,True):
        r=NativeCapture(native_sd=True);assert r.boot(release=True)==0;r.ready();r.sequence=0
        r.begin_recording(delay=2);sector=r.fs.physical(8,1)
        if nominal:r.fs.finish_pending=sector
        else:r.fs.inject=(3,sector,'data')
        for _ in range(12):
            r.audio_call();r.tick()
            if r.fs.stalled:break
        if nominal:
            assert not r.fs.probe()['failed']
            # Apply late controller activity at the final checkpoint, after
            # the native bounce/status sequence has completed successfully.
            put32(r.m,PRESENT,CLOCK_STABLE|0x206)
        r.retained((UI,FS1));frame=r.fs.frame();requests=list(r.fs.requests)
        r.resume_sd();r.retained((UI,FS1))
        assert frame==r.fs.frame() and requests==r.fs.requests
        # Schedule stock audio on another stack while preserving the suspended
        # worker CPU frame. It adds clean stems/master, with no extra file call.
        r.other_task(word(r.m,TASK),r.audio_call)
        assert frame==r.fs.frame() and requests==r.fs.requests
        stock=r.other_task(word(r.m,TASK),r.stop_recording)
        assert all(stock[h]==packed(r.expected[h]) for h in range(1,8))
        r.retained((UI,FS1));assert frame==r.fs.frame() and requests==r.fs.requests
        if nominal:
            r.fs.finish_pending=r.fs.busy_sector=None
            put32(r.m,PRESENT,CLOCK_STABLE|DAT0_HIGH)
        else:r.fs.join_allowed=True
        r.resume_sd()
        assert not r.fs.owner() and r.locks.tokens=={UI}
        assert sum(q['op']==3 and q['sector']==sector for q in r.fs.requests)==1
        if nominal:r.completed_extra()
        else:failed(r)
        passed(('nominal' if nominal else 'failed')+'_native_payload_retains_entire_capture_call_while_ordinary_audio_continues_then_resumes_same_request_after_MODEL_join')

    report=dict(passed_groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        capture_sha256=hashlib.sha256((ROOT/'src/capture/capture-only.elf').read_bytes()).hexdigest(),
        limitations=['Mounted FAT32 geometry, cache lists, free count and folder sectors are controlled inputs; no full BPB mount, bitmap or FSInfo proof.',
            'Ordinary seven-file backend and scheduling remain integration models; selected original audio/recording windows execute.',
            'SD DMA bytes, IRQ delivery, source exclusion, CPU cache effects and completion permissions are MODEL inputs.',
            'A separate test-only SD probe ELF is composed; no production hook, automatic startup release, firmware image or mixer access.'])
    (ROOT/'analysis/capture_native_files_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
