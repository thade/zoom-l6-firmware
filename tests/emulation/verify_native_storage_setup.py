#!/usr/bin/env python3
"""Original outer mount and folder setup with native FAT32 operations, offline.

GPIO, registration callback arrival, queue delivery and other board effects are
fixtures. No startup/storage permission or physical-completion provider.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_native_mount import MountedTree,MountedTreeSd,PARTITION,FAT,VOLUME
from verify_capture_hooks import HookNativeCapture
from verify_capture_integration import IntegrationRig,record
from verify_capture_native_files import failed,UI
from verify_capture_storage import callees,REGISTRATION
from verify_firmware_workflow import put32
from verify_record_scheduler import word,request_setup
from verify_pad_protocol import ROOT,IMAGE,RETURN

MAIN_QUEUE=0x6543
PUBLIC_DIRECTORY=(0x8005d8e8,0x8005d728,0x8005e708,0x8005e718,0x8005f3d0,0x8005bb08)

class FolderTree(MountedTree):
    def __init__(self,empty=True,**kwargs):
        kwargs.setdefault('spc',32)
        super().__init__(**kwargs)
        for pc in PUBLIC_DIRECTORY:self.m.hooks.pop(pc,None)
        if empty:
            # A freshly formatted fixture: only root allocated. The firmware
            # must create every recorder/pad folder and its on-card entries.
            fat=bytearray(self.sectors[PARTITION+FAT])
            for c in range(3,8):struct.pack_into('<I',fat,c*4,0)
            self.sectors[PARTITION+FAT]=self.sectors[PARTITION+FAT+self.fat_sectors]=bytes(fat)
            for c in range(2,8):
                for s in range(self.spc):self.sectors[self.physical(c,s)]=bytes(512)
        self.messages=[];self.mounts=[];self.directory_calls=[];self.registrations=[]
        for pc,label in ((0x8005d8e8,'find'),(0x8005d728,'find_close'),(0x8005f3d0,'mkdir'),(0x8005bb08,'change_directory')):
            self.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u,label=label:self.directory_calls.append(label),begin=pc,end=pc)
    def files_in_pad(self,pad=0):
        root=self.directory(2);sound=root.get('SOUND_PAD')
        if not sound:return {}
        folder=self.directory(sound['cluster']).get('PAD%d'%(pad+1))
        return self.directory(folder['cluster']) if folder else {}
    def setup_folders(self):return self.m.invoke(0x80002d80,[])
    def setup_card(self,present=True,phase=2,argument=2):
        m=self.m
        keep={0x8005fc98,0x8000ac80,0x8000ac70,0x80002d80,0x80002ec8,0x80008d68,0x80062230}
        saved={fn:m.hooks.get(fn) for fn in callees(0x80009a40,0x80009b18)-keep}
        for fn in saved:m.hooks[fn]=lambda a:0
        extra=(0x80032ad8,0x80052ce0,0x8000bad0,0x80077686,0x80068508)
        saved.update({fn:m.hooks.get(fn) for fn in extra})
        m.hooks[0x80032ad8]=lambda a:int(present)
        m.hooks[0x80052ce0]=lambda a:self.registrations.append(tuple(a[:4])) or 0
        m.hooks[0x8000bad0]=lambda a:0x21008000
        m.hooks[0x80068508]=lambda a:0 # outer detach software notification modeled
        m.hooks.pop(0x80077686,None)
        put32(m,0x801f8f3c,MAIN_QUEUE)
        previous=self.locks.send
        def send(a):
            if a[0]==MAIN_QUEUE:
                self.messages.append(self.raw(a[1],32));return 1
            return previous(a) if previous else 1
        self.locks.send=send
        active={'mount':False}
        def enter(uc,pc,n,u):active['mount']=True
        def arrive(uc,pc,n,u):
            # This callback progress is supplied, not a native SD/card init.
            uc.reg_write(A.UC_ARM_REG_R0,1);uc.reg_write(A.UC_ARM_REG_R1,0)
            uc.reg_write(A.UC_ARM_REG_R2,phase if active['mount'] else 0)
            uc.reg_write(A.UC_ARM_REG_PC,0x8004bd99)
        h=m.uc.hook_add(UC_HOOK_CODE,arrive,begin=0x80077686,end=0x80077686)
        def mounted(uc,pc,n,u):
            self.mounts.append(uc.reg_read(A.UC_ARM_REG_R0));active['mount']=False
        handles=[m.uc.hook_add(UC_HOOK_CODE,enter,begin=0x8005fc98,end=0x8005fc98)]
        handles += [m.uc.hook_add(UC_HOOK_CODE,mounted,begin=pc,end=pc) for pc in (0x8005fcd6,0x8005fce4,0x8005fdc0)]
        try:return m.invoke(0x80009a40,[argument])
        finally:
            m.uc.hook_del(h)
            for h in handles:m.uc.hook_del(h)
            self.locks.send=previous
            for fn,hook in saved.items():
                if hook is None:m.hooks.pop(fn,None)
                else:m.hooks[fn]=hook
    def verify_folders(self):
        root=self.directory(2)
        assert set(root)=={'RECORDER','SOUND_PAD'}
        assert all(root[n]['attributes']&0x10 for n in root)
        sound=self.directory(root['SOUND_PAD']['cluster'])
        assert set(sound)=={'.','..','PAD1','PAD2','PAD3','PAD4'}
        for i in range(4):
            p=sound['PAD%d'%(i+1)]
            assert p['attributes']&0x10
            entries=self.directory(p['cluster'])
            assert entries['.']['cluster']==p['cluster']
            assert entries['..']['cluster']==root['SOUND_PAD']['cluster']
            assert set(entries)=={'.','..'}
        assert self.geometry()==(0,(65526,65519,512,32))

class FolderTreeSd(FolderTree,MountedTreeSd):
    pass

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    for fs in (FolderTree,FolderTreeSd):
        r=fs();assert r.setup_card()==0 and r.mounts==[2]
        assert r.raw(REGISTRATION,3)==b'\x02\0\x02'
        r.verify_folders()
        assert r.directory_calls.count('mkdir')==6
        assert len(r.messages)==1 and struct.unpack_from('<I',r.messages[0])[0]==0x80049da1
        assert word(r.m,0x807348cc)==1
        assert r.locks.tokens=={UI} and word(r.m,0x801f8df0)==0
        assert all(r.sectors[PARTITION+FAT+i]==r.sectors[PARTITION+FAT+r.fat_sectors+i] for i in range(r.fat_sectors))
        passed('original_outer_mount_and_native_RECORDER_SOUND_PAD_four_PAD_creation_'+fs.__name__,
               folders=6,free_clusters=65519,deferred_reload_pending=True)

    r=FolderTree();assert r.setup_folders()==0;r.verify_folders()
    before=dict(r.sectors);r.directory_calls=[]
    assert r.setup_folders()==0 and r.sectors==before and 'mkdir' not in r.directory_calls
    passed('native_folder_setup_is_idempotent_and_preserves_existing_directory_sectors')

    # A filesystem-supported geometry need not be accepted by application mount.
    r=FolderTree(spc=8);assert r.setup_card()==0xffffffff and r.mounts==[10]
    assert r.geometry()==(0,(65526,65525,512,8))
    assert not r.messages and not r.directory(2) and not r.directory_calls.count('mkdir')
    passed('native_FAT32_ready_but_application_cluster_policy_rejects_card_without_folder_or_reload_work')

    r=FolderTree();assert r.setup_card(present=False)==0 and r.mounts==[1]
    assert r.raw(VOLUME+4,1)==b'\0' and not r.messages and not r.directory_calls
    passed('outer_absent_card_still_returns_zero_without_native_mount_or_folder_authorization')

    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2,blocks=23)
    for fs in (FolderTree,FolderTreeSd):
        r=HookNativeCapture(filesystem=fs)
        assert r.fs.setup_card()==0;r.fs.verify_folders()
        assert r.boot(release=True)==0;r.ready();r.sequence=0
        assert record(r,delay=2,blocks=23)==ordinary
        extra=r.completed_extra()
        assert len(extra)==13312 and r.fs.geometry()==(0,(65526,65518,512,32))
        # Filesystem traversal follows actual created PAD1 cluster 5; the extra
        # payload fits one native 16-KiB cluster, allocated after folders at 9.
        f=r.fs.files_in_pad()['OD_00000001.TMP']
        assert f['cluster']==9 and f['data']==extra
        assert not any(x.get('sector') is not None and x['op'] in (2,3) and x['sector']<=PARTITION+1<x['sector']+x['count'] for x in r.fs.requests)
        passed('encoded_hooks_capture_in_natively_created_folders_after_outer_mount_'+fs.__name__,
               frames=1600,extra_bytes=len(extra),extra_sha256=hashlib.sha256(extra).hexdigest())

    r=HookNativeCapture(filesystem=FolderTree);r.fs.readonly=True
    assert r.fs.setup_card()==0xffffffff and not r.fs.messages
    assert r.boot(release=True)==0;failed(r)
    before={h:bytes(data) for h,data in r.files.items()}
    # The actual outer failure detaches storage. Stock Record correctly refuses
    # admission as well; the seven-file recording helper assumes admission and
    # is therefore not used for this unavailable-card case.
    request_setup(r.m,0)
    for pc in (0x8000ac80,0x8000ac70):r.m.hooks.pop(pc,None)
    r.m.hooks[0x80076950]=r.file_take;r.m.hooks[0x800763d8]=r.file_give
    r.m.invoke(0x80034f40,[0xffffffff]);assert not r.wire
    assert {h:bytes(data) for h,data in r.files.items()}==before
    assert not r.fs.directory(2)
    passed('read_only_native_folder_failure_withholds_extra_capture_and_stock_Record_admission')

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        limitations=['Card sectors, GPIO, asynchronous registration/status callback arrival and initialized SD-card state are fixtures.',
            'Original outer mount/geometry policy and actual directory lookup/create/close/chdir execute; other board effects are modeled.',
            'Deferred pad reload is queued but not run; it is not required to create the private extra file.',
            'Capture worker registration/release and scheduling are explicit inputs; ordinary seven-file backend and middle DSP remain models.',
            'DMA bytes, physical completion, IRQ/source exclusion, cache visibility and outer transition protection are unbound.',
            'No image, transfer, mixer/card access or production startup authorization.'])
    (ROOT/'analysis/native_storage_setup_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
