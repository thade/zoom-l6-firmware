#!/usr/bin/env python3
"""Original filesystem initialization and BPB/MBR mount, entirely offline.

Card bytes and RTOS object creation are fixtures. Geometry, free count, cache
links, native handles and allocation bitmap come from original instructions.
No physical-card completion, full board/card initialization or device access.
"""
import hashlib,json,struct
from verify_capture_native_files import (NativeTree,NativeCapture,NativeFileSd,
    directory_entries,POOL,POOL_COUNT,UI,FS1,OPEN,WRITE,READ,CLOSE,INFO,RESULT,BUFFER,
    PARTITION,FAT,VOLUME,CACHE,SD,IMAGE,ROOT,put32,word,record,IntegrationRig)
from verify_native_filesystem import DESCRIPTOR,TABLE
from verify_sd_transfer_lifetime import CARD
from verify_capture_native_files import failed,FS2,FS4,FS5,FS6,WORKER_TASK
from verify_sd_checked_recovery import RecoveryPorts
from verify_control_transport import TASK
from verify_session_manager import STOPPED,RESET
from verify_scheduling_boundaries import stop
from verify_record_catalogue import putstr
from verify_pad_protocol import INPUT
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A

BITMAP, BITMAP_BYTES=0x80579e60,0x80400
GEOMETRY=0x8005e958

def boot_sector(clusters,fat_sectors,spc=8,fsinfo=1):
    b=bytearray(512);b[:11]=b'\xeb\x58\x90L6 TEST '
    struct.pack_into('<H',b,11,512);b[13]=spc
    struct.pack_into('<H',b,14,FAT);b[16]=2;b[21]=0xf8
    struct.pack_into('<I',b,28,PARTITION)
    struct.pack_into('<I',b,32,FAT+2*fat_sectors+clusters*spc)
    struct.pack_into('<I',b,36,fat_sectors)
    struct.pack_into('<I',b,44,2)
    struct.pack_into('<HH',b,48,fsinfo,6)
    b[64]=0x80;b[66]=0x29;b[71:82]=b'L6 FIXTURE ';b[82:90]=b'FAT32   '
    b[510:512]=b'\x55\xaa';return bytes(b)

class MountedTree(NativeTree):
    def __init__(self,clusters=65526,bitmap_bytes=BITMAP_BYTES,discover=True,readonly=False,spc=8,**kwargs):
        NativeTree.__init__(self,**kwargs);m=self.m
        # Build card sectors, then discard the inherited ready-volume settings.
        # The default has a FAT32-sized cluster count; reduced geometries in
        # boundary tests are explicitly synthetic branch fixtures.
        self.clusters=clusters;self.last_cluster=clusters+1;self.spc=spc
        self.readonly=readonly
        self.fat_sectors=((clusters+2)*4+511)//512
        self.data_area=FAT+2*self.fat_sectors
        self.total=PARTITION+self.data_area+clusters*self.spc
        fat=bytearray(self.fat_sectors*512)
        struct.pack_into('<II',fat,0,0x0ffffff8,0x0fffffff)
        for c in range(2,8):struct.pack_into('<I',fat,c*4,0x0fffffff)
        self.sectors={PARTITION:boot_sector(clusters,self.fat_sectors,spc)}
        for i in range(self.fat_sectors):
            self.sectors[PARTITION+FAT+i]=self.sectors[PARTITION+FAT+self.fat_sectors+i]=bytes(fat[i*512:(i+1)*512])
        for c in range(2,8):
            for s in range(self.spc):self.sectors[self.physical(c,s)]=bytes(512)
        root=directory_entries('SOUND_PAD',b'SOUND_~1   ',3)
        sound=b''.join(directory_entries('PAD%d'%(i+1),('PAD%d'%(i+1)).encode().ljust(11,b' '),c) for i,c in enumerate((4,5,6,7)))
        self.sectors[self.physical(2)]=root.ljust(512,b'\0')
        self.sectors[self.physical(3)]=sound.ljust(512,b'\0')
        mbr=bytearray(512);mbr[446+4]=0xc
        struct.pack_into('<II',mbr,446+8,PARTITION,self.total-PARTITION)
        mbr[510:512]=b'\x55\xaa';self.sectors[0]=bytes(mbr)
        fsinfo=bytearray(512);struct.pack_into('<I',fsinfo,0,0x41615252)
        struct.pack_into('<III',fsinfo,484,0x61417272,0,2)
        struct.pack_into('<I',fsinfo,508,0xaa550000);self.sectors[PARTITION+1]=bytes(fsinfo)
        self.object_creates=[]
        self.aux_creates=[]
        m.uc.mem_write(0x801f8da0,bytes(0x58))
        def mutex(a):
            self.object_creates.append(('mutex',a[0]));return 0x7100+len(self.object_creates)
        m.hooks[0x800321f8]=mutex
        def auxiliary(kind,a):
            self.aux_creates.append((kind,a[0]));return 0x7200+len(self.aux_creates)
        m.hooks[0x800321e8]=lambda a:auxiliary('auxiliary',a)
        m.hooks[0x80032200]=lambda a:auxiliary('event',a)
        for fn in (0x80026bf0,0x800320f8,0x80062d68,0x80074d08,0x80063c08,GEOMETRY):m.hooks.pop(fn,None)
        assert m.invoke(0x80026bf0,[])==0
        assert len(self.object_creates)==6
        assert len(self.aux_creates)==4
        assert list(self.cache_nodes())==[CACHE+i*0x280 for i in range(10)]
        assert all(self.raw(POOL+i*0x2c4,1)==b'\xff' for i in range(POOL_COUNT))
        m.uc.mem_write(DESCRIPTOR,struct.pack('<IBBBBIII',TABLE,0,1,ord('A'),0,SD|1,0,0xffffffff if discover else PARTITION))
        assert m.invoke(0x8006b328,[DESCRIPTOR,0])==0
        # This actual stock registration supplies its bitmap buffer/budget.
        m.uc.mem_write(BITMAP,b'\xa5'*BITMAP_BYTES)
        assert m.invoke(0x800614b0,[ord('A'),BITMAP,bitmap_bytes])==0
        assert self.raw(VOLUME+4,1)==b'\0'
        self.requests=[];self.entries=[]
    def physical(self,cluster,sector=0):
        return PARTITION+getattr(self,'data_area',192)+(cluster-2)*getattr(self,'spc',8)+sector
    def block_device(self,a):
        packet=self.raw(a[0],20)
        if packet[0]!=6 or packet[8]==4:return NativeTree.block_device(self,a)
        assert packet[1]==1 and FS1 in self.locks.tokens
        self.assert_context()
        sub=packet[8];out,count=struct.unpack_from('<II',packet,12)
        q=dict(op=6,unit=1,subcommand=sub,sector=None,buffer=None,count=None,
               tokens=sorted(self.locks.tokens),handle_state=self.raw(self.active_handle,1)[0])
        self.requests.append(q)
        if self.fail and self.fail(q):return 17
        if sub==1:
            assert count==8;self.m.uc.mem_write(out,struct.pack('<II',self.total-1,512))
            put32(self.m,a[0]+16,8)
        else:
            assert sub in (5,6) and count==1
            if sub==5:return 0xffffd827 # unsupported by original SD dispatcher
            self.m.uc.mem_write(out,bytes([int(self.readonly)]))
            put32(self.m,a[0]+16,1)
        return 0
    def assert_context(self):
        # Public OPEN/geometry discover the partition while holding file tokens
        # but before constructing their exception frame. Those direct callback
        # returns are checked by the partition scanner instead of longjmp.
        context=word(self.m,0x801f8df0)
        if context==0:assert word(self.m,VOLUME+0x234)==0xffffffff
        else:assert context==self.current_task()
    def content(self,length,cluster):
        data=bytearray();seen=set()
        while len(data)<length:
            assert 2<=cluster<=self.last_cluster and cluster not in seen
            seen.add(cluster)
            data.extend(b''.join(self.sectors.get(self.physical(cluster,s),bytes(512)) for s in range(self.spc)))
            p=cluster*4;fat=self.sectors.get(PARTITION+FAT+p//512,bytes(512))
            cluster=struct.unpack_from('<I',fat,p%512)[0]&0x0fffffff
        return bytes(data[:length])
    def geometry(self):
        put32(self.m,RESULT,0xdeadbeef)
        status=self.m.invoke(GEOMETRY,[ord('A'),RESULT])
        assert self.locks.tokens=={UI} and word(self.m,0x801f8df0)==0
        return status,struct.unpack('<4I',self.raw(RESULT,16))

class MountedTreeSd(MountedTree,NativeFileSd):
    def __init__(self,**kwargs):
        MountedTree.__init__(self,**kwargs)
        self.configure_sd()
        self.m.uc.mem_write(CARD+5,bytes([2|(4 if self.readonly else 0)]))
        put32(self.m,CARD+0x10,self.total) # modeled card-initialization capacity

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=MountedTree();status,geometry=r.geometry()
    assert status==0,(hex(status),r.requests)
    assert geometry==(65526,65520,512,8),geometry
    assert r.raw(VOLUME+4,1)==b'\x01'
    assert word(r.m,VOLUME+0x234)==PARTITION
    assert word(r.m,VOLUME+0x214)==r.data_area and word(r.m,VOLUME+0x21c)==512
    assert word(r.m,VOLUME+0x224)==2 and word(r.m,VOLUME+0x218)==65527
    assert r.raw(BITMAP,1)==b'\xff'
    assert r.raw(BITMAP+1,8190)==bytes(8190)
    assert r.raw(BITMAP+8192,16)==b'\xa5'*16
    assert r.requests[2]['sector']==0 and r.requests[3]['sector']==PARTITION
    assert [q['sector'] for q in r.requests if q['op']==2][2:]==list(range(PARTITION+FAT,PARTITION+FAT+512,8))
    before=r.raw(CACHE,0x332c);created=list(r.object_creates)
    assert r.m.invoke(0x80026bf0,[])==0xffffffff
    assert r.raw(CACHE,0x332c)==before and r.object_creates==created
    passed('native_filesystem_constructor_cache_handle_pool_MBR_BPB_and_full_FAT32_bitmap_scan',
           clusters=65526,free_clusters=65520,cache_nodes=10,handle_slots=100)

    for budget,enabled in ((0,False),(8191,False),(8192,True)):
        r=MountedTree(bitmap_bytes=budget)
        assert r.geometry()==(0,(65526,65520,512,8))
        assert r.raw(VOLUME+0x24c,1)==bytes([int(enabled)])
        assert r.raw(VOLUME+0x207,1)==b'\x01'
        if not enabled:assert r.raw(BITMAP,BITMAP_BYTES)==b'\xa5'*BITMAP_BYTES
        else:assert r.raw(BITMAP+budget,16)==b'\xa5'*16
    passed('native_bitmap_capacity_boundary_uses_FAT_scan_fallback_without_overwriting_short_buffers')

    r=MountedTree(discover=False);assert r.geometry()==(0,(65526,65520,512,8))
    assert r.requests[0]['op']==2 and r.requests[0]['sector']==PARTITION
    assert not any(q['op']==2 and q['sector']==0 for q in r.requests)
    passed('explicit_partition_mount_parses_BPB_without_MBR_discovery')

    for value,hint in ((0,2),(65526,65520),(0xffffffff,0xffffffff)):
        r=MountedTree();b=bytearray(r.sectors[PARTITION+1])
        struct.pack_into('<II',b,488,value,hint);r.sectors[PARTITION+1]=bytes(b)
        assert r.geometry()==(0,(65526,65520,512,8))
        assert not any(q['op'] in (2,3) and q['sector']<=PARTITION+1<q['sector']+q['count'] for q in r.requests)
        assert r.sectors[PARTITION+1]==bytes(b)
    passed('examined_FAT32_mount_ignores_FSInfo_free_count_and_hint_and_counts_actual_FAT_entries')

    for fault in ('signature','cluster_size','sector_size','total_sectors','partition'):
        r=MountedTree();b=bytearray(r.sectors[0 if fault=='partition' else PARTITION])
        if fault=='signature':b[511]=0
        elif fault=='cluster_size':b[13]=3
        elif fault=='sector_size':struct.pack_into('<H',b,11,1024)
        elif fault=='total_sectors':struct.pack_into('<I',b,32,0)
        else:b[446:462]=bytes(16)
        r.sectors[0 if fault=='partition' else PARTITION]=bytes(b)
        assert r.geometry()[0]!=0
        assert r.raw(VOLUME+4,1)==b'\0' and r.raw(VOLUME+0x207,1)==b'\0'
        assert r.raw(BITMAP,16)==b'\xa5'*16
    passed('invalid_partition_or_boot_geometry_never_marks_volume_or_free_count_ready',faults=5)

    for sector in (0,PARTITION,PARTITION+FAT,PARTITION+FAT+8):
        r=MountedTree();r.fail=lambda q,s=sector:q['op']==2 and q['sector']==s
        assert r.geometry()[0]==0xffffd827
        assert r.raw(VOLUME+4,1)==b'\0' and r.raw(VOLUME+0x207,1)==b'\0'
        if sector>=PARTITION+FAT:
            # A partially initialized map exists, but mount/free-count validity
            # is not published until the complete FAT scan succeeds.
            assert r.raw(VOLUME+0x24c,1)==b'\x01'
        r.fail=None;assert r.geometry()==(0,(65526,65520,512,8))
    passed('MBR_BPB_and_early_or_late_FAT_read_errors_withhold_ready_state_and_completed_error_retry_rebuilds_map',faults=4)

    for native_sd in (False,True):
        r=(MountedTreeSd if native_sd else MountedTree)(readonly=True)
        assert r.geometry()==(0,(65526,65520,512,8)) and r.raw(VOLUME+0x208,1)==b'\x01'
        before=dict(r.sectors)
        assert r.open('A:\\SOUND_PAD\\PAD1\\OD_00000001.TMP',0x501,0x80)==(0xffffd827,0)
        assert r.sectors==before
    passed('native_read_only_card_query_permits_mount_but_rejects_capture_file_creation_without_sector_changes')

    r=MountedTree();r.fail=lambda q:q['op']==6 and q.get('subcommand')==6
    assert r.geometry()==(0,(65526,65520,512,8)) and r.raw(VOLUME+4,1)==b'\x01'
    assert r.raw(VOLUME+0x208,1)==b'\0'
    passed('negative_control_native_mount_masks_write_protection_query_failure_and_still_reports_ready')

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    for native_sd in (False,True):
        r=NativeCapture(filesystem=MountedTreeSd if native_sd else MountedTree)
        assert r.fs.raw(VOLUME+4,1)==b'\0'
        # Explicit test release, with lazy mount inside the compiled lifecycle's
        # first native OPEN. This is not an automatic readiness provider.
        assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert r.fs.raw(VOLUME+4,1)==b'\x01'
        assert record(r,delay=2,blocks=23)==ordinary
        data=r.completed_extra()
        assert r.fs.geometry()==(0,(65526,65516,512,8))
        assert r.fs.raw(BITMAP,2)==b'\xff\x0f'
        assert all(r.fs.sectors[PARTITION+FAT+s]==r.fs.sectors[PARTITION+FAT+r.fs.fat_sectors+s] for s in range(r.fs.fat_sectors))
        assert not any(q['op'] in (2,3) and q['sector']<=PARTITION+1<q['sector']+q['count'] for q in r.fs.requests)
        passed('complete_capture_after_lazy_native_mount_and_bitmap_allocation_'+('with_native_SD' if native_sd else 'with_sector_callback'),
               frames=1600,extra_bytes=len(data),extra_sha256=hashlib.sha256(data).hexdigest())

    for fault in ('BPB','FAT'):
        r=NativeCapture(filesystem=MountedTree);sector=PARTITION if fault=='BPB' else PARTITION+FAT+8
        r.fs.fail=lambda q,s=sector:q['op']==2 and q['sector']==s
        assert r.boot(release=True)==0;failed(r)
        assert r.fs.raw(VOLUME+4,1)==b'\0' and not r.fs.files_in_pad()
        r.sequence=0;assert record(r,delay=2,blocks=23)==ordinary
    passed('compiled_capture_rejects_lazy_mount_failure_and_preserves_seven_ordinary_files',faults=2)

    r=NativeCapture(filesystem=MountedTreeSd)
    r.fs.inject=(2,PARTITION+FAT+8,'data')
    assert r.boot(release=True)==0
    for _ in range(4):
        r.tick()
        if r.fs.stalled:break
    r.retained((UI,FS1,FS2,FS4,FS5,FS6))
    assert r.fs.raw(VOLUME+4,1)==b'\0' and r.fs.raw(VOLUME+0x207,1)==b'\0'
    assert r.fs.raw(VOLUME+0x24c,1)==b'\x01'
    frame=r.fs.frame();requests=list(r.fs.requests)
    r.resume_sd();r.retained((UI,FS1,FS2,FS4,FS5,FS6))
    assert r.fs.frame()==frame and r.fs.requests==requests
    r.fs.join_allowed=True;r.resume_sd();failed(r)
    assert not r.fs.owner() and r.fs.raw(VOLUME+4,1)==b'\0'
    assert r.fs.requests==requests and not r.fs.files_in_pad()
    passed('late_native_mount_SD_failure_retains_worker_OPEN_exception_frame_and_all_file_tokens_until_MODEL_join')

    report=dict(passed_groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        capture_sha256=hashlib.sha256((ROOT/'src/capture/capture-only.elf').read_bytes()).hexdigest(),
        limitations=['Card/partition/boot/FAT/directory bytes and capacity/write-protection state are controlled fixtures; full card/board initialization is not executed.',
            'Filesystem initializer, MBR/BPB parsing, ten cache nodes, 100 native handles, bitmap sizing/build and free count execute as original instructions.',
            'FSInfo statement is scoped to these FAT32 mount/capture paths, not every filesystem mode or firmware caller.',
            'Kernel object allocation, DMA bytes, IRQ timing, source exclusion, CPU cache effects and physical completion remain MODEL inputs.',
            'Ordinary seven-file backend and worker release/scheduling are integration fixtures; no production readiness gate, image or device operation.'])
    (ROOT/'analysis/native_mount_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
