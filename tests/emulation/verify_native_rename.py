#!/usr/bin/env python3
"""Native TMP-to-WAV rename/collision evidence; no production seal binding."""
import hashlib,json
from unicorn import arm_const as A
from verify_native_mount import MountedTree,MountedTreeSd
from verify_capture_native_files import seed,UI,FS1,FS5,FS6,READ,CLOSE,BUFFER,RESULT
from verify_capture_hooks import HookNativeCapture
from verify_native_storage_setup import FolderTreeSd
from verify_capture_integration import IntegrationRig,record
from verify_record_catalogue import putstr
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_pad_protocol import ROOT,IMAGE
from verify_sd_checked_recovery import RecoveryPorts

RENAME=0x80060a18
FROM,TO=0x20028000,0x20028400
TMP='A:\\SOUND_PAD\\PAD1\\OD_00000001.TMP'
WAV=TMP[:-3]+'WAV'

def rename(fs,source=TMP,destination=WAV):
    putstr(fs.m,FROM,source);putstr(fs.m,TO,destination)
    fs.m.hooks.pop(RENAME,None)
    return fs.m.invoke(RENAME,[FROM,TO])

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    payload=bytes(range(256))*19
    for fs in (MountedTree,MountedTreeSd):
        r=fs();seed(r,TMP,payload)
        before=r.files_in_pad()['OD_00000001.TMP'];free=r.geometry()[1][1];r.requests=[]
        assert rename(r)==0 and set(r.files_in_pad())=={'OD_00000001.WAV'}
        assert r.files_in_pad()['OD_00000001.WAV']==before
        assert r.geometry()[1][1]==free and r.locks.tokens=={UI}
        writes=[q for q in r.requests if q['op']==3]
        assert writes and all(q['sector']==r.physical(4) and q['count']==1 for q in writes)
        passed('native_same_folder_rename_preserves_payload_cluster_length_attributes_and_free_space_'+fs.__name__,
               payload_bytes=len(payload),metadata_sector_writes=len(writes),audio_copies=0)

    for fs in (MountedTree,MountedTreeSd):
        r=fs();seed(r,TMP,payload);seed(r,WAV,b'previous backing')
        before=dict(r.sectors);entries=r.files_in_pad();r.requests=[]
        assert rename(r)==0xffffd75b and r.sectors==before and r.files_in_pad()==entries
        assert not any(q['op']==3 for q in r.requests)
    passed('native_existing_destination_rejected_without_overwrite_or_persisted_sector_change')

    r=MountedTree();assert r.geometry()[0]==0;before=dict(r.sectors)
    assert rename(r)==0xffffd75a and r.sectors==before
    seed(r,TMP,payload);before=dict(r.sectors)
    assert rename(r,destination='A:\\SOUND_PAD\\MISSING\\OD_00000001.WAV')!=0
    assert r.sectors==before and r.files_in_pad()['OD_00000001.TMP']['data']==payload
    passed('native_missing_source_or_target_folder_failure_leaves_source_and_existing_sectors_intact')

    # A write error clears/changes native cache bookkeeping before completion;
    # even an unchanged persisted sector is not sufficient retry permission.
    r=MountedTree();seed(r,TMP,payload);before=dict(r.sectors)
    r.fail=lambda q:q['op']==3
    assert rename(r)==0xffffd827 and r.sectors==before and r.locks.tokens=={UI}
    assert r.files_in_pad()['OD_00000001.TMP']['data']==payload
    passed('metadata_write_error_propagates_without_claiming_atomicity_or_retry_permission')

    r=MountedTree();seed(r,TMP,payload)
    r.fail=lambda q:q['op']==6
    assert rename(r)==0xffffd827 and r.locks.tokens=={UI}
    assert set(r.files_in_pad())=={'OD_00000001.WAV'}
    assert r.files_in_pad()['OD_00000001.WAV']['data']==payload
    passed('negative_control_barrier_failure_returns_error_after_persisted_name_already_changed')

    r=MountedTreeSd();seed(r,TMP,payload);r.inject=(3,r.physical(4),'data')
    rename(r);assert r.stalled
    r.retained((UI,FS1,FS5,FS6));frame=r.frame();requests=list(r.requests)
    r.stalled=False;RecoveryPorts.resume(r);r.retained((UI,FS1,FS5,FS6))
    assert r.frame()==frame and r.requests==requests
    r.join_allowed=True;r.stalled=False;RecoveryPorts.resume(r)
    assert not r.owner() and r.locks.tokens=={UI} and r.requests==requests
    assert r.m.uc.reg_read(A.UC_ARM_REG_R0)==0xffffd827
    passed('native_rename_metadata_error_retains_exception_stack_file_domains_and_SD_token_until_MODEL_join')

    r=HookNativeCapture(filesystem=FolderTreeSd)
    assert r.fs.setup_card()==0 and r.boot(release=True)==0;r.ready();r.sequence=0
    record(r,delay=2,blocks=23);extra=r.completed_extra();path=r.result()[1]
    free=r.fs.geometry()[1][1];r.fs.requests=[]
    assert rename(r.fs,path,path[:-3]+'WAV')==0
    assert r.fs.files_in_pad()['OD_00000001.WAV']['data']==extra
    assert r.fs.geometry()[1][1]==free
    status,h=r.fs.open(path[:-3]+'WAV');assert status==0
    assert r.m.invoke(READ,[h,BUFFER,len(extra),RESULT])==0 and word(r.m,RESULT)==len(extra)
    assert r.fs.raw(BUFFER,len(extra))==extra and r.m.invoke(CLOSE,[h])==0
    passed('verified_native_take_can_be_renamed_and_reopened_byte_exact_without_audio_copy',frames=1600,extra_bytes=len(extra))

    result=dict(passed=True,groups=len(cases),results=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        limitations=['Only examined same-volume/same-folder TMP-to-WAV paths and collisions are covered; no power-loss atomicity claim.',
            'Metadata/barrier errors can follow name/cache mutation; public error must not be classified as unchanged SAFE.',
            'Card sectors, initialized card state, DMA bytes, scheduling and physical join permissions are models.',
            'No BackingGate.seal port, storage fence or production physical-completion provider has been bound.',
            'No firmware image, transfer, mixer/card access or deployment.'])
    (ROOT/'analysis/native_rename_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
