#!/usr/bin/env python3
"""Original L6 file/FAT/cache instructions over a modeled sector device.

File handles and geometry are controlled fixtures. READ/WRITE/CLOSE, exception
unwinding, cluster translation, cache effects and directory serialization run
as stock instructions. Only the block callback and kernel endpoints are modeled.
No firmware image, mixer access or physical completion claim.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_PROT_NONE
from unicorn import arm_const as A
from verify_overdub_prototype import Emulator
from verify_capture_transitions import FileLocks,FS1,FS2,FS4,UI
from verify_firmware_workflow import HANDLE,BUFFER,RESULT,TABLE,put32
from verify_pad_protocol import ROOT,IMAGE,BIAS,REGS
from verify_record_scheduler import word

VOLUME=0x8020f660
CACHE=0x8020dd60
DESCRIPTOR=0x20029000
SECTOR_BYTES=512
PARTITION,FAT,DATA,DIRECTORY,MIRROR=2048,32,192,256,64
DIRECTORY_CLUSTER=(DIRECTORY-DATA)//8+2
READ,WRITE,CLOSE=0x80060620,0x800622b0,0x8005c1f8
SD=0x80068378
IO_ERROR=0xffffd827
DEVICE_RECORDS=(0x800a1298,0x800a12b0,0x800a12c8,0x800a12e0)

def half(m,p,n):m.uc.mem_write(p,struct.pack('<H',n))
def pattern(n,seed=0):return bytes((i*37+seed)%256 for i in range(n))

class NativeFiles:
    def __init__(self,chain=(2,3,5),cache_slots=4,m=None,task=None,send=None,ordinary_events=False):
        self.m=m or Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True);m=self.m
        m.uc.mem_protect(0x10000000,0x10000,UC_PROT_NONE)
        self.task=0x21039000;self.current_task=task or (lambda:self.task)
        self.locks=FileLocks(m,self.current_task,send,ordinary_events)
        m.hooks.pop(0x80001848) # execute actual setjmp and longjmp
        self.requests=[];self.fail=None;self.entries=[];self.chain=chain
        self.active_handle=HANDLE
        # Execute native registration with a controlled descriptor. The callback
        # comes from four actual vendor records; this is not a native mount test.
        assert all(word(m,p+4)==SD|1 for p in DEVICE_RECORDS)
        m.uc.mem_write(VOLUME+4,b'\xff')
        m.uc.mem_write(DESCRIPTOR,struct.pack('<IBBBBIII',TABLE,0,1,ord('A'),0,
                                            word(m,DEVICE_RECORDS[0]+4),0,PARTITION))
        assert m.invoke(0x8006b328,[DESCRIPTOR,0])==0
        assert word(m,VOLUME+0x240)==SD|1
        assert word(m,VOLUME+0x234)==PARTITION and word(m,VOLUME+0x258)==TABLE
        m.uc.mem_write(VOLUME+1,bytes((7,3,2))) # 8 sectors/cluster, two FAT copies
        m.uc.mem_write(VOLUME+0x205,b'\x02');half(m,VOLUME+0x20c,SECTOR_BYTES)
        for offset,value in ((0x210,FAT),(0x214,DATA),(0x218,64),(0x21c,MIRROR),(0x230,0x0ffffff0)):
            put32(m,VOLUME+offset,value)
        for i in range(cache_slots):
            p=CACHE+i*0x210
            put32(m,p+0x200,p+0x210 if i+1<cache_slots else 0xffffffff)
            m.uc.mem_write(p+0x204,b'\xff')
        m.uc.mem_write(HANDLE,b'\x40\x02\0')
        for offset,value in ((0x21c,len(chain)*4096),(0x220,chain[0]),(0x224,chain[0]),
                             (0x230,VOLUME),(0x268,DIRECTORY),(0x26c,32)):
            put32(m,HANDLE+offset,value)
        self.sectors={}
        fat=bytearray(SECTOR_BYTES)
        struct.pack_into('<II',fat,0,0x0ffffff8,0x0fffffff)
        struct.pack_into('<I',fat,DIRECTORY_CLUSTER*4,0x0fffffff)
        for i,cluster in enumerate(chain):
            struct.pack_into('<I',fat,cluster*4,chain[i+1] if i+1<len(chain) else 0x0fffffff)
            for sector in range(8):
                self.sectors[self.physical(cluster,sector)]=pattern(SECTOR_BYTES,cluster+sector)
        self.sectors[PARTITION+FAT]=bytes(fat)
        self.sectors[PARTITION+FAT+MIRROR]=bytes(fat)
        directory=bytearray(pattern(SECTOR_BYTES,91))
        directory[32:43]=b'OD_TEST TMP'
        self.sectors[PARTITION+DIRECTORY]=bytes(directory)
        m.hooks[SD]=self.block_device
        for pc,name in ((0x80060818,'read'),(0x800624a8,'write'),(0x8005c388,'close')):
            def observe(uc,address,size,user,name=name):
                self.active_handle=uc.reg_read(A.UC_ARM_REG_R0)
                self.locks.driver(name);self.entries.append(name)
            m.uc.hook_add(UC_HOOK_CODE,observe,begin=pc,end=pc)

    def physical(self,cluster,sector=0):return PARTITION+DATA+(cluster-2)*8+sector
    def raw(self,p,n):return bytes(self.m.uc.mem_read(p,n))
    def assert_context(self):assert word(self.m,0x801f8df0)==self.current_task()
    def block_device(self,a):
        packet=self.raw(a[0],20);op,unit=packet[:2]
        param,buf,count,sector=struct.unpack_from('<4I',packet,4)
        assert unit==1 and param==0 and FS1 in self.locks.tokens
        self.assert_context()
        request=dict(op=op,unit=unit,buffer=buf,count=count,sector=sector,
                     tokens=sorted(self.locks.tokens),handle_state=self.raw(self.active_handle,1)[0])
        if op==6:
            # Other packet words are uninitialized stack bytes for this opcode.
            assert packet[8]==4
            request.update(buffer=None,count=None,sector=None,subcommand=4)
        self.requests.append(request)
        if self.fail and self.fail(request):return 17
        if op==2:
            self.m.uc.mem_write(buf,b''.join(self.sectors.get(sector+i,bytes(SECTOR_BYTES)) for i in range(count)))
        elif op==3:
            for i in range(count):self.sectors[sector+i]=self.raw(buf+i*SECTOR_BYTES,SECTOR_BYTES)
        else:
            assert op==6 and packet[8]==4 # stock close barrier; modeled status only
        return 0
    def position(self,pos):
        assert 0<=pos<4096,'Controlled seeks here cover only the first cluster'
        put32(self.m,HANDLE+0x22c,pos)
        put32(self.m,HANDLE+0x224,self.chain[pos//4096])
    def io(self,entry,n,data=None):
        if data is not None:
            assert len(data)==n;self.m.uc.mem_write(BUFFER,data)
        put32(self.m,RESULT,0xdeadbeef)
        result=self.m.invoke(entry,[HANDLE,BUFFER,n,RESULT])
        assert self.locks.tokens=={UI} and word(self.m,0x801f8df0)==0
        return result,word(self.m,RESULT)
    def close(self):
        result=self.m.invoke(CLOSE,[HANDLE])
        assert self.locks.tokens=={UI} and word(self.m,0x801f8df0)==0
        return result
    def logical(self):
        return b''.join(self.sectors[self.physical(c,s)] for c in self.chain for s in range(8))
    def cache_nodes(self):
        p=CACHE
        while p!=0xffffffff:
            yield p;p=word(self.m,p+0x200)
    def empty(self,full=False):
        # Native allocator uses the FAT scan branch, with a bounded free-count
        # fixture and its normal FAT32 EOC mask. No allocation helper is mocked.
        fat=bytearray(SECTOR_BYTES)
        struct.pack_into('<II',fat,0,0x0ffffff8,0x0fffffff)
        struct.pack_into('<I',fat,DIRECTORY_CLUSTER*4,0x0fffffff)
        if full:
            for c in range(2,65):struct.pack_into('<I',fat,c*4,0x0fffffff)
        self.sectors[PARTITION+FAT]=self.sectors[PARTITION+FAT+MIRROR]=bytes(fat)
        for offset,value in ((0x218,64),(0x230,0x0ffffff0),(0x238,2),(0x23c,0 if full else 62)):
            put32(self.m,VOLUME+offset,value)
        self.m.uc.mem_write(VOLUME+0x207,b'\x01')
        for offset in (0x21c,0x220,0x224):put32(self.m,HANDLE+offset,0)
    def triples(self):return [(q['op'],q['sector'],q['count']) for q in self.requests]
    def cached(self,sector):
        return next(p for p in self.cache_nodes() if word(self.m,p+0x208)==sector and self.raw(p+0x204,1)!=b'\xff')

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=NativeFiles()
    passed('native_registration_copies_actual_SD_callback_into_volume',
           callback=hex(word(r.m,VOLUME+0x240)),vendor_records=[hex(p) for p in DEVICE_RECORDS])

    expected=r.logical()[:1024]
    assert r.io(READ,1024)==(0,1024) and r.raw(BUFFER,1024)==expected
    assert [(q['op'],q['sector'],q['count']) for q in r.requests]==[(2,PARTITION+FAT,1),(2,PARTITION+DATA,2)]
    assert r.requests[-1]['buffer']==BUFFER and r.entries==['read']
    passed('native_read_translates_cluster_and_partition_and_reads_FAT_before_payload')

    r=NativeFiles();payload=pattern(1024,77)
    assert r.io(WRITE,1024,payload)==(0,1024) and r.logical()[:1024]==payload
    assert [(q['op'],q['sector'],q['count']) for q in r.requests]==[(2,PARTITION+FAT,1),(3,PARTITION+DATA,2)]
    assert r.requests[-1]['buffer']==BUFFER
    passed('native_write_submits_original_buffer_and_two_real_sectors')

    for entry in (READ,WRITE):
        r=NativeFiles();expected=r.logical();payload=pattern(12288,77)
        assert r.io(entry,12288,payload if entry==WRITE else None)==(0,12288)
        assert r.triples()==[(2,PARTITION+FAT,1),
                            (2 if entry==READ else 3,r.physical(2),16),
                            (2 if entry==READ else 3,r.physical(5),8)]
        assert (r.raw(BUFFER,12288)==expected) if entry==READ else (r.logical()==payload)
    passed('native_FAT_chain_coalesces_adjacent_clusters_and_splits_at_fragment',operations=2)

    r=NativeFiles();before=r.logical();r.position(19);payload=pattern(1200,113)
    assert r.io(WRITE,1200,payload)==(0,1200)
    assert r.triples()==[(2,r.physical(2),1),(2,PARTITION+FAT,1),
                        (3,r.physical(2,1),1),(2,r.physical(2,2),1)]
    assert r.logical()!=before[:19]+payload+before[1219:] # partial sectors still cached
    assert r.close()==0
    assert r.logical()==before[:19]+payload+before[1219:]
    assert [q['sector'] for q in r.requests if q['op']==3]==[r.physical(2,1),r.physical(2),r.physical(2,2),PARTITION+DIRECTORY]
    passed('unaligned_write_preserves_partial_sectors_and_close_flushes_them')

    r=NativeFiles();before=r.logical();r.position(7);payload=pattern(80,59)
    assert r.io(WRITE,80,payload)==(0,80)
    node=r.cached(DATA)
    assert r.raw(node+0x204,1)==b'\x01' and r.logical()==before
    r.position(0);assert r.io(READ,512)==(0,512)
    assert r.raw(BUFFER,512)==before[:7]+payload+before[87:512]
    assert r.triples()==[(2,r.physical(2),1)] and r.raw(node+0x204,1)==b'\x01'
    passed('single_sector_native_read_uses_dirty_cache_without_storage_submission')
    r.position(0);assert r.io(READ,1024)==(0,1024)
    assert r.raw(BUFFER,1024)==before[:7]+payload+before[87:1024]
    assert r.triples()==[(2,r.physical(2),1),(2,PARTITION+FAT,1),
                        (3,r.physical(2),1),(2,r.physical(2),2)]
    passed('full_sector_read_flushes_overlapping_dirty_cache_before_payload_read')

    r=NativeFiles();r.position(7);assert r.io(WRITE,80,pattern(80))==(0,80)
    node=r.cached(DATA);r.position(0);payload=pattern(512,94)
    assert r.io(WRITE,512,payload)==(0,512)
    assert r.raw(node+0x204,1)==b'\xff' and r.logical()[:512]==payload
    assert [q['sector'] for q in r.requests if q['op']==3]==[r.physical(2)]
    passed('full_sector_write_invalidates_overlapping_cache_without_writing_superseded_bytes')

    r=NativeFiles();before=r.sectors[PARTITION+DIRECTORY]
    assert r.io(WRITE,512,pattern(512))==(0,512) and r.close()==0
    after=r.sectors[PARTITION+DIRECTORY];entry=after[32:64]
    assert after[:32]==before[:32] and after[64:]==before[64:]
    assert entry[:11]==b'OD_TEST TMP' and entry[11]==0x20
    assert struct.unpack_from('<H',entry,20)[0]==0 and struct.unpack_from('<H',entry,26)[0]==2
    assert struct.unpack_from('<I',entry,28)[0]==12288 and r.requests[-1]['op']==6
    assert all(q['tokens']==sorted((UI,FS1,FS2,FS4)) and q['handle_state']==255 for q in r.requests[-3:])
    passed('native_close_serializes_directory_cluster_size_and_attribute_under_three_file_tokens')

    r=NativeFiles();r.empty();first=pattern(700,131);second=pattern(5000,25)
    assert r.io(WRITE,len(first),first)==(0,len(first))
    assert word(r.m,HANDLE+0x220)==2 and word(r.m,HANDLE+0x21c)==700
    assert r.io(WRITE,len(second),second)==(0,len(second)) and r.close()==0
    assert word(r.m,HANDLE+0x21c)==5700
    fat=r.sectors[PARTITION+FAT]
    assert struct.unpack_from('<II',fat,8)==(3,0x0fffffff)
    assert fat==r.sectors[PARTITION+FAT+MIRROR]
    r.chain=(2,3);assert r.logical()[:5700]==first+second
    assert struct.unpack_from('<I',r.sectors[PARTITION+DIRECTORY],32+28)[0]==5700
    assert word(r.m,VOLUME+0x23c)==60
    passed('native_empty_file_allocation_and_append_extend_FAT_chain_and_flush_both_FAT_copies')

    r=NativeFiles();r.empty(full=True)
    assert r.io(WRITE,512,pattern(512))==(0xffffd826,0)
    assert not r.requests and word(r.m,HANDLE+0x21c)==0
    passed('full_volume_rejects_allocation_without_payload_submission')

    for entry,sector in ((READ,PARTITION+FAT),(READ,PARTITION+DATA),
                         (WRITE,PARTITION+FAT),(WRITE,PARTITION+DATA)):
        r=NativeFiles();before=r.logical()
        r.fail=lambda q,sector=sector:q['sector']==sector
        assert r.io(entry,1024,pattern(1024) if entry==WRITE else None)==(IO_ERROR,0)
        assert word(r.m,HANDLE+0x22c)==0 and r.logical()==before
        assert r.requests[-1]['sector']==sector
    passed('actual_setjmp_longjmp_maps_FAT_and_payload_failures_and_releases_file_token',combinations=4)

    r=NativeFiles();before=r.logical();payload=pattern(12288,33)
    r.fail=lambda q:q['op']==3 and q['sector']==r.physical(5)
    assert r.io(WRITE,len(payload),payload)==(IO_ERROR,0)
    assert r.logical()==payload[:8192]+before[8192:] and word(r.m,HANDLE+0x22c)==0
    passed('later_fragment_failure_reports_zero_bytes_even_after_earlier_payload_reached_sector_model')

    r=NativeFiles();before=r.logical();r.position(7)
    assert r.io(WRITE,80,pattern(80))==(0,80)
    node=r.cached(DATA);r.fail=lambda q:q['op']==3 and q['sector']==r.physical(2)
    assert r.close()==IO_ERROR and r.logical()==before
    assert r.raw(node+0x204,1)==b'\0' and r.raw(HANDLE,1)==b'\xff'
    assert not any(q['op']==6 for q in r.requests)
    prior=len(r.requests);assert r.close()!=0 and len(r.requests)==prior
    passed('failed_cached_payload_flush_leaves_cache_clean_and_handle_unused_no_safe_close_retry')

    for failure in ('directory','barrier'):
        r=NativeFiles();before=r.sectors[PARTITION+DIRECTORY]
        assert r.io(WRITE,512,pattern(512))==(0,512)
        r.fail=lambda q,failure=failure:q['op']==6 if failure=='barrier' else q['op']==3 and q['sector']==PARTITION+DIRECTORY
        assert r.close()==IO_ERROR and r.raw(HANDLE,1)==b'\xff'
        assert r.raw(r.cached(DIRECTORY)+0x204,1)==b'\0'
        assert (r.sectors[PARTITION+DIRECTORY]==before)==(failure=='directory')
    passed('directory_write_and_barrier_errors_unwind_actual_close_and_never_return_success',combinations=2)

    for sector in (PARTITION+FAT,PARTITION+FAT+MIRROR):
        r=NativeFiles();r.empty();before=r.sectors[sector]
        assert r.io(WRITE,700,pattern(700))==(0,700)
        r.fail=lambda q,sector=sector:q['op']==3 and q['sector']==sector
        assert r.close()==IO_ERROR and r.sectors[sector]==before
        assert r.raw(r.cached(FAT)+0x204,1)==b'\0'
        assert not any(q['op']==6 for q in r.requests)
    passed('either_FAT_copy_failure_aborts_close_after_native_cache_marked_clean',copies=2)

    report=dict(firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),passed_groups=len(cases),
                results=cases,limitations=['Controlled handle, small FAT32 chain, cache list and geometry; native OPEN, complete mount, free-space bitmap and FSInfo paths not exercised.',
                    'Block callback bytes/status and RTOS endpoints are modeled; no SD hardware, DMA, cache visibility or physical join.',
                    'No device image or automatic worker release binding.'])
    (ROOT/'analysis/native_filesystem_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
