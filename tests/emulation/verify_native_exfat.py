#!/usr/bin/env python3
"""Native exFAT mount and capture over modeled card bytes, entirely offline.

Geometry and metadata follow the Microsoft exFAT specification:
https://learn.microsoft.com/en-us/windows/win32/fileio/exfat-specification
The stock instructions mount, allocate and serialize files. Kernel scheduling
and SD completion are fixtures; no physical-card or deployment claim.
"""
import hashlib,json,struct
from verify_native_mount import MountedTree,MountedTreeSd,PARTITION,VOLUME
from verify_capture_native_files import (NativeCapture,OPEN,WRITE,READ,CLOSE,
    SEEK,BUFFER,RESULT,UI,ROOT,record,IntegrationRig,word,NOT_FOUND,EXISTS,failed,seed)
from verify_native_rename import rename
from verify_capture_heap import HeapNativeCapture
from verify_native_storage_setup import FolderTree,PUBLIC_DIRECTORY
from verify_capture_storage import REGISTRATION
from verify_capture_native_files import FS1
from verify_control_transport import TASK
from verify_session_manager import BLOCKED
from unicorn import UC_HOOK_CODE

def checksum(data,bits=32,skip=()):
    value=0;mask=(1<<bits)-1
    for i,b in enumerate(data):
        if i not in skip:value=(((value&1)<<(bits-1))+(value>>1)+b)&mask
    return value

def file_entries(name,cluster,length,attrs=0x10,contiguous=False):
    units=list(struct.unpack('<%dH'%len(name),name.encode('utf-16le')))
    entries=bytearray(64+32*((len(units)+14)//15))
    entries[0]=0x85;entries[1]=len(entries)//32-1
    struct.pack_into('<H',entries,4,attrs)
    for offset in (8,12,16):struct.pack_into('<I',entries,offset,0x00210000)
    entries[32]=0xc0;entries[33]=1|(2 if contiguous else 0);entries[35]=len(units)
    struct.pack_into('<H',entries,36,checksum(name.upper().encode('utf-16le'),16))
    struct.pack_into('<Q',entries,40,length)
    struct.pack_into('<IQ',entries,52,cluster,length)
    for i,u in enumerate(units):
        p=64+32*(i//15);entries[p]=0xc1;struct.pack_into('<H',entries,p+2+2*(i%15),u)
    struct.pack_into('<H',entries,2,checksum(entries,16,(2,3)))
    return bytes(entries)

class ExfatTree(MountedTree):
    def __init__(self,spc=32,clusters=65526,empty=False,**kwargs):
        # Reuse native constructor/registration only. Its discarded FAT32
        # sectors do not constrain the exFAT sectors-per-cluster byte/shift.
        super().__init__(spc=32,clusters=65526,**kwargs)
        assert spc>=8 and spc&(spc-1)==0
        self.clusters=clusters;self.last_cluster=clusters+1;self.spc=spc
        self.fat_sectors=((clusters+2)*4+511)//512
        self.fat_offset=24;self.data_area=self.fat_offset+self.fat_sectors
        self.root_cluster=4;self.total=PARTITION+self.data_area+clusters*spc
        # Complete Unicode mapping: ASCII case conversion followed by a
        # compressed identity run for the remaining code points.
        upcase=struct.pack('<130H',*[ord(chr(i).upper()) if 97<=i<=122 else i for i in range(128)],0xffff,65408)
        boot=bytearray(12*512);boot[:11]=b'\xeb\x76\x90EXFAT   '
        struct.pack_into('<QQIIIIIIHH',boot,64,PARTITION,self.total-PARTITION,
                         self.fat_offset,self.fat_sectors,self.data_area,clusters,
                         self.root_cluster,0x12345678,0x100,0)
        boot[108:113]=bytes((9,spc.bit_length()-1,1,0x80,0xff))
        boot[510:512]=b'\x55\xaa'
        for i in range(1,9):struct.pack_into('<I',boot,512*i+508,0xaa550000)
        c=checksum(boot[:11*512],skip=(106,107,112))
        boot[11*512:]=struct.pack('<128I',*([c]*128))
        self.sectors={PARTITION+i:bytes(boot[i*512:(i+1)*512]) for i in range(12)}
        self.sectors.update({PARTITION+12+i:self.sectors[PARTITION+i] for i in range(12)})
        mbr=bytearray(512);mbr[450]=7
        struct.pack_into('<II',mbr,454,PARTITION,self.total-PARTITION)
        mbr[510:512]=b'\x55\xaa';self.sectors[0]=bytes(mbr)
        # Unrepresented sectors read as zero: a sparse, completely defined
        # virtual card, rather than a multi-gigabyte host allocation.
        fat=bytearray(512)
        struct.pack_into('<II',fat,0,0xfffffff8,0xffffffff)
        allocated=3 if empty else 8
        for cluster in range(2,allocated+2):struct.pack_into('<I',fat,4*cluster,0xffffffff)
        self.sectors[PARTITION+self.fat_offset]=bytes(fat)
        bitmap=bytearray((clusters+7)//8);bitmap[0]=(1<<allocated)-1
        self.store_cluster(2,bitmap);self.store_cluster(3,upcase)
        root=bytearray(64);root[0]=0x81;root[32]=0x82
        struct.pack_into('<IQ',root,20,2,len(bitmap))
        struct.pack_into('<I',root,36,checksum(upcase))
        struct.pack_into('<IQ',root,52,3,len(upcase))
        self.store_cluster(4,root+(b'' if empty else file_entries('SOUND_PAD',5,spc*512)))
        if not empty:
            self.store_cluster(5,b''.join(file_entries('PAD%d'%(i+1),6+i,spc*512) for i in range(4)))
            for cluster in range(6,10):self.store_cluster(cluster,b'')
    def store_cluster(self,cluster,data):
        assert len(data)<=self.spc*512
        data=bytes(data).ljust(self.spc*512,b'\0')
        for s in range(self.spc):self.sectors[self.physical(cluster,s)]=data[s*512:(s+1)*512]
    def content(self,length,cluster,contiguous=False):
        data=bytearray();seen=set()
        while len(data)<length:
            assert 2<=cluster<=self.last_cluster and cluster not in seen
            seen.add(cluster)
            data.extend(b''.join(self.sectors.get(self.physical(cluster,s),bytes(512)) for s in range(self.spc)))
            p=cluster*4;fat=self.sectors.get(PARTITION+self.fat_offset+p//512,bytes(512))
            cluster=cluster+1 if contiguous else struct.unpack_from('<I',fat,p%512)[0]
        return bytes(data[:length])
    def directory(self,cluster):
        data=self.content(self.spc*512,cluster);files={};p=0
        while p<len(data) and data[p]:
            e=data[p:p+32]
            if e[0]!=0x85:p+=32;continue
            size=(e[1]+1)*32;entry=data[p:p+size];stream=entry[32:64]
            assert len(entry)==size and stream[0]==0xc0
            assert struct.unpack_from('<H',entry,2)[0]==checksum(entry,16,(2,3))
            units=b''.join(entry[i+2:i+32] for i in range(64,size,32))[:stream[3]*2]
            assert all(entry[i]==0xc1 for i in range(64,size,32))
            name=units.decode('utf-16le')
            assert struct.unpack_from('<H',stream,4)[0]==checksum(name.upper().encode('utf-16le'),16)
            first,length=struct.unpack_from('<IQ',stream,20)
            valid=struct.unpack_from('<Q',stream,8)[0]
            assert valid<=length
            files[name]=dict(cluster=first,length=length,valid=valid,attributes=struct.unpack_from('<H',entry,4)[0],
                             contiguous=bool(stream[1]&2),data=self.content(length,first,bool(stream[1]&2)))
            p+=size
        return files
    def files_in_pad(self,pad=0):return self.directory(6+pad)

class ExfatTreeSd(ExfatTree,MountedTreeSd):
    def __init__(self,**kwargs):
        ExfatTree.__init__(self,**kwargs)
        # MountedTreeSd's constructor configured the modeled capacity before
        # ExfatTree replaced the geometry. Refresh only that fixture input.
        from verify_sd_transfer_lifetime import CARD
        from verify_firmware_workflow import put32
        put32(self.m,CARD+0x10,self.total)

class ExfatFolders(ExfatTree):
    setup_folders=FolderTree.setup_folders
    setup_card=FolderTree.setup_card
    def __init__(self,**kwargs):
        kwargs.setdefault('empty',True);super().__init__(**kwargs)
        for pc in PUBLIC_DIRECTORY:self.m.hooks.pop(pc,None)
        self.messages=[];self.mounts=[];self.directory_calls=[];self.registrations=[]
        for pc,label in ((0x8005d8e8,'find'),(0x8005d728,'find_close'),(0x8005f3d0,'mkdir'),(0x8005bb08,'change_directory')):
            self.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u,label=label:self.directory_calls.append(label),begin=pc,end=pc)
    def files_in_pad(self,pad=0):
        root=self.directory(self.root_cluster);sound=root.get('SOUND_PAD')
        if not sound:return {}
        folder=self.directory(sound['cluster']).get('PAD%d'%(pad+1))
        return self.directory(folder['cluster']) if folder else {}
    def verify_folders(self):
        root=self.directory(self.root_cluster)
        assert set(root)=={'RECORDER','SOUND_PAD'} and all(f['attributes']&0x10 for f in root.values())
        sound=self.directory(root['SOUND_PAD']['cluster'])
        assert set(sound)=={'PAD1','PAD2','PAD3','PAD4'}
        for f in sound.values():assert f['attributes']&0x10 and not self.directory(f['cluster'])
        assert self.geometry()==(0,(self.clusters,self.clusters-9,512,self.spc))

class ExfatFoldersSd(ExfatFolders,ExfatTreeSd):pass

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    path='A:\\SOUND_PAD\\PAD1\\OD_00000001.TMP'
    def write(fs,h,data):
        fs.m.uc.mem_write(BUFFER,data)
        assert fs.m.invoke(WRITE,[h,BUFFER,len(data),RESULT])==0 and word(fs.m,RESULT)==len(data)
    def read(fs,h,data):
        assert fs.m.invoke(READ,[h,BUFFER,len(data),RESULT])==0 and word(fs.m,RESULT)==len(data)
        assert fs.raw(BUFFER,len(data))==data
    for spc,clusters in ((32,65526),(512,1952360)):
        r=ExfatTree(spc=spc,clusters=clusters)
        assert r.geometry()==(0,(clusters,clusters-8,512,spc))
        assert r.raw(VOLUME+4,1)==b'\x01' and word(r.m,VOLUME+0x224)==4
        assert word(r.m,VOLUME+0x214)==r.data_area and word(r.m,VOLUME+0x234)==PARTITION
        assert r.directory(4)['SOUND_PAD']['cluster']==5
        passed('native_exFAT_MBR_boot_root_allocation_bitmap_and_free_count_'+str(spc),
               clusters=clusters,cluster_bytes=spc*512)

    for fs in (ExfatTree,ExfatTreeSd):
        r=fs();assert r.open(path)==(NOT_FOUND,0)
        status,h=r.open(path,0x501,0x80);assert status==0
        payload=bytes((i*37)%256 for i in range(35001));write(r,h,payload)
        assert r.m.invoke(CLOSE,[h])==0
        f=r.files_in_pad()['OD_00000001.TMP']
        assert f['data']==payload and f['valid']==len(payload) and f['contiguous']
        assert r.sectors[r.physical(2)][:2]==b'\xff\x07'
        assert r.geometry()==(0,(65526,65515,512,32))
        status,h=r.open(path.lower());assert status==0
        assert r.m.invoke(SEEK,[h,16371,2])==0;read(r,h,payload[16371:16412])
        assert r.m.invoke(SEEK,[h,0,2])==0;read(r,h,payload)
        assert r.m.invoke(CLOSE,[h])==0
        before=dict(r.sectors)
        assert r.open(path,0x501,0x80)==(EXISTS,0) and r.sectors==before
        passed('native_exFAT_contiguous_cross_cluster_SEEK_case_insensitive_reopen_and_exclusive_collision_'+fs.__name__,bytes=len(payload))

    r=ExfatTree();status,h=r.open(path,0x501,0x80);assert status==0
    first=bytes((i*13)%256 for i in range(17001));write(r,h,first)
    status,other=r.open(path.replace('00000001','00000002'),0x501,0x80);assert status==0
    write(r,other,b'previous backing');assert r.m.invoke(CLOSE,[other])==0
    tail=bytes((i*17)%256 for i in range(23000));write(r,h,tail);assert r.m.invoke(CLOSE,[h])==0
    f=r.files_in_pad()['OD_00000001.TMP']
    assert not f['contiguous'] and f['data']==first+tail
    assert r.sectors[r.physical(2)][:2]==b'\xff\x0f'
    assert r.files_in_pad()['OD_00000002.TMP']['data']==b'previous backing'
    status,h=r.open(path);assert status==0;read(r,h,first+tail);assert r.m.invoke(CLOSE,[h])==0
    passed('native_exFAT_interleaved_allocations_convert_contiguous_file_to_FAT_chain_without_altering_other_file')

    r=ExfatTree(spc=512,clusters=1952360);status,h=r.open(path,0x501,0x80);assert status==0
    chunk=bytes(range(256))*32;payload=chunk*33+b'last partial sector'
    for i in range(0,len(payload),len(chunk)):write(r,h,payload[i:i+len(chunk)])
    assert r.m.invoke(CLOSE,[h])==0
    assert r.files_in_pad()['OD_00000001.TMP']['data']==payload
    status,h=r.open(path);assert status==0
    assert r.m.invoke(SEEK,[h,262137,2])==0;read(r,h,payload[262137:262180])
    assert r.m.invoke(CLOSE,[h])==0
    passed('native_exFAT_256KiB_cluster_boundary_write_close_and_readback',bytes=len(payload))

    for fault in ('signature','shift','revision','bitmap','upcase'):
        r=ExfatTree();sector=PARTITION if fault in ('signature','shift','revision') else r.physical(4)
        b=bytearray(r.sectors[sector])
        if fault=='signature':b[511]=0
        elif fault=='shift':b[109]=0xff
        elif fault=='revision':struct.pack_into('<H',b,104,0x200)
        elif fault=='bitmap':b[0]=1
        else:b[32]=1
        r.sectors[sector]=bytes(b);before=dict(r.sectors)
        assert r.geometry()[0]!=0 and r.raw(VOLUME+4,1)==b'\0'
        if fault in ('bitmap','upcase'):
            # PercentInUse is written before mandatory root entries have
            # been validated. Mount error is not an unchanged-card result.
            expected=bytearray(before[PARTITION]);expected[112]=0
            before[PARTITION]=bytes(expected)
        assert r.sectors==before
    passed('native_exFAT_invalid_boot_or_missing_metadata_withholds_mount_despite_earlier_PercentInUse_write',faults=5)

    r=ExfatTree();b=bytearray(r.sectors[PARTITION]);b[100]^=1;r.sectors[PARTITION]=bytes(b)
    assert r.geometry()==(0,(65526,65518,512,32))
    assert not any(q['op']==2 and q['sector']<=PARTITION+11<q['sector']+q['count'] for q in r.requests)
    passed('negative_control_examined_mount_accepts_boot_checksum_mismatch_without_reading_checksum_sector')

    for location in ('boot','root','bitmap_first','bitmap_last'):
        r=ExfatTree();sector={'boot':PARTITION,'root':r.physical(4),
            'bitmap_first':r.physical(2),'bitmap_last':r.physical(2,15)}[location]
        r.fail=lambda q,s=sector:q['op']==2 and q['sector']<=s<q['sector']+q['count']
        assert r.geometry()[0]!=0 and r.raw(VOLUME+4,1)==b'\0'
        r.fail=None;assert r.geometry()==(0,(65526,65518,512,32))
    passed('native_exFAT_boot_root_and_early_late_bitmap_errors_withhold_ready_and_completed_retry_recovers',faults=4)

    for fs in (ExfatTree,ExfatTreeSd):
        r=fs(readonly=True)
        # Correct usage metadata avoids an otherwise attempted boot-sector
        # update during mount, which the real SD write-protect branch rejects.
        for sector in (PARTITION,PARTITION+12):
            b=bytearray(r.sectors[sector]);b[112]=0;r.sectors[sector]=bytes(b)
        assert r.geometry()==(0,(65526,65518,512,32))
        before=dict(r.sectors);assert r.open(path,0x501,0x80)[0]!=0 and r.sectors==before
    passed('native_exFAT_read_only_mount_rejects_optional_file_without_sector_changes')
    r=ExfatTreeSd(readonly=True);before=dict(r.sectors)
    assert r.geometry()[0]==0xffffd827 and r.raw(VOLUME+4,1)==b'\0' and r.sectors==before
    passed('native_exFAT_unknown_usage_metadata_on_write_protected_SD_fails_mount_before_optional_capture')

    for fs in (ExfatTree,ExfatTreeSd):
        r=fs();payload=bytes(range(256))*19;seed(r,path,payload)
        entry=r.files_in_pad()['OD_00000001.TMP'];free=r.geometry()[1][1]
        assert rename(r,path,path[:-3]+'WAV')==0
        assert r.files_in_pad()=={'OD_00000001.WAV':entry} and r.geometry()[1][1]==free
        status,h=r.open(path[:-3]+'WAV');assert status==0;read(r,h,payload)
        assert r.m.invoke(CLOSE,[h])==0
        seed(r,path,b'new take');before=dict(r.sectors)
        assert rename(r,path,path[:-3]+'WAV')==EXISTS and r.sectors==before
        assert r.files_in_pad()['OD_00000001.WAV']['data']==payload
        assert r.files_in_pad()['OD_00000001.TMP']['data']==b'new take'
        passed('native_exFAT_TMP_WAV_rename_readback_and_existing_destination_preservation_'+fs.__name__)

    for fault in ('metadata','barrier'):
        r=ExfatTree();seed(r,path,b'verified take');before=dict(r.sectors)
        r.fail=lambda q,f=fault:q['op']==(3 if f=='metadata' else 6)
        assert rename(r,path,path[:-3]+'WAV')==0xffffd827
        assert r.locks.tokens=={UI}
        if fault=='metadata':assert r.sectors==before
        else:assert r.files_in_pad()=={'OD_00000001.WAV':dict(cluster=10,length=13,valid=13,attributes=32,contiguous=True,data=b'verified take')}
    passed('native_exFAT_rename_write_error_and_barrier_after_changed_name_never_imply_safe_retry',faults=2)

    ordinary=record(IntegrationRig(enabled=False),delay=2,blocks=23)
    for fs in (ExfatTree,ExfatTreeSd):
        r=NativeCapture(filesystem=fs)
        assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        data=r.completed_extra();assert len(data)==13312
        assert r.fs.sectors[r.fs.physical(2)][:2]==b'\xff\x01'
        passed('complete_extra_capture_native_exFAT_'+fs.__name__,extra_sha256=hashlib.sha256(data).hexdigest())
    for fs in (ExfatFolders,ExfatFoldersSd):
        r=fs();assert r.setup_card()==0 and r.mounts==[2]
        r.verify_folders();assert r.raw(REGISTRATION,3)==b'\x02\0\x02'
        assert r.directory_calls.count('mkdir')==6 and len(r.messages)==1
        before=dict(r.sectors);r.directory_calls=[]
        assert r.setup_folders()==0 and r.sectors==before and 'mkdir' not in r.directory_calls
        passed('original_outer_mount_native_exFAT_folder_creation_and_idempotence_'+fs.__name__)

    fs=lambda **kwargs:ExfatFoldersSd(spc=512,clusters=1952360,**kwargs)
    r=HeapNativeCapture(fs);assert r.fs.setup_card()==0;r.fs.verify_folders()
    assert r.boot(release=True)==0;r.ready();r.sequence=0
    assert record(r,delay=2,blocks=23)==ordinary
    extra=r.completed_extra();r.assert_reserved()
    assert r.fs.sectors[r.fs.physical(2)][:2]==b'\xff\x03'
    passed('heap_owned_capture_native_exFAT_original_mount_folders_and_SD_with_256KiB_clusters',
           requested_bytes=r.requested,extra_sha256=hashlib.sha256(extra).hexdigest())

    r=NativeCapture(filesystem=ExfatTree);r.fs.fail=lambda q:q['op']==2 and q['sector']==PARTITION
    assert r.boot(release=True)==0;failed(r)
    r.sequence=0;assert record(r,delay=2,blocks=23)==ordinary
    passed('native_exFAT_mount_failure_disables_extra_capture_and_preserves_ordinary_recording')

    for fault in ('barrier','readback'):
        r=NativeCapture(filesystem=ExfatTree);assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        r.fs.fail=lambda q,f=fault:(q['op']==6 and q.get('subcommand')==4) if f=='barrier' else (q['op']==2 and q['sector']==r.fs.physical(10,1))
        failed(r,BLOCKED) if fault=='barrier' else failed(r)
    passed('native_exFAT_close_barrier_and_readback_errors_withhold_verified_result',faults=2)

    r=HeapNativeCapture(ExfatTreeSd);assert r.boot(release=True)==0;r.ready();r.begin_recording(delay=2)
    r.fs.inject=(3,r.fs.physical(10,1),'data')
    for _ in range(12):
        r.audio_call();r.tick()
        if r.fs.stalled:break
    assert r.fs.stalled;r.retained((UI,FS1));frame=r.fs.frame();requests=list(r.fs.requests)
    r.resume_sd();r.retained((UI,FS1));assert r.fs.frame()==frame and r.fs.requests==requests
    r.other_task(word(r.m,TASK),r.audio_call);r.other_task(word(r.m,TASK),r.stop_recording)
    assert r.fs.frame()==frame and r.fs.requests==requests
    r.fs.join_allowed=True;r.resume_sd();failed(r);r.assert_reserved()
    passed('heap_exFAT_native_SD_error_retains_frames_and_buffers_until_explicit_MODELED_join')

    report=dict(passed=True,groups=len(cases),results=cases,
        limitations=['Virtual exFAT sectors follow the Microsoft specification; no actual card sectors or exact on-card geometry were read.',
            'The large fixture uses 1,952,360 clusters and 256 KiB clusters; capacity resembles the observed card but is not its measured BPB.',
            'The custom Unicode upcase table maps ASCII case and leaves other characters unchanged; it is not the card table.',
            'Audio/ordinary file endpoints, scheduling, card initialization, DMA/cache effects and physical completion are modeled.',
            'Heap-backed composition uses the separate offline heap ELF; live headroom/startup/storage authorization remain unbound.',
            'Mount success does not validate all exFAT metadata; the boot checksum negative control is accepted by this stock path.',
            'A failed mount can already have changed boot PercentInUse; error does not imply an unchanged card.',
            'No power-loss, real SD latency, production join, pad handoff, firmware image or device deployment claim.'])
    (ROOT/'analysis/native_exfat_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
