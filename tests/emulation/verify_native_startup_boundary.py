#!/usr/bin/env python3
"""Concrete cold-mount success branch and Main boot paths, offline only.

Original file/card setup uses virtual sectors and modeled card arrival. A
separate original Main branch test models board initialization and setup input.
No capture admission, physical source lease or firmware patch is supplied.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from verify_native_storage_setup import FolderTree
from verify_native_exfat import ExfatFolders
from verify_pad_protocol import ROOT,IMAGE
from verify_overdub_prototype import Emulator
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_storage_lifetimes import instructions

SUCCESS=0x80009ab4
NORMAL_RECEIVE=0x8002c440

def mounted(fs,**kwargs):
    r=fs(**kwargs.pop('constructor',{}));seen=[]
    r.m.uc.hook_add(UC_HOOK_CODE,lambda u,p,n,x:seen.append(p),begin=SUCCESS,end=SUCCESS)
    result=r.setup_card(argument=0,**kwargs)
    return r,result,seen

def boot(mode,exit_setup=False):
    m=Emulator();calls=[];received=[]
    # Only Main itself executes in this half of the test. The other half runs
    # actual filesystem setup. No nested emulation or fabricated card readiness.
    entries={int(i.op_str[1:],16) for i in instructions(0x8002c1e8,0x8002c510)
             if i.mnemonic=='bl'}
    for p in entries:
        m.hooks[p]=lambda a,p=p:calls.append((p,tuple(a[:2]))) or 0
    m.hooks[0x80006248]=lambda a:mode
    m.hooks[0x8000ac80]=lambda a:1
    m.hooks[0x80076950]=lambda a:1
    # Initial type/profile is zero; normal startup calls c220(0,profile).
    m.hooks[0x80005e28]=lambda a:0
    def receive(a):
        site=m.uc.reg_read(A.UC_ARM_REG_LR)-5
        received.append(site)
        if site==0x8002c258 and exit_setup and len(received)==1:
            m.uc.mem_write(a[0],struct.pack('<5I',0,0,0x20,0,0));return 0
        return stop(m)
    m.hooks[0x80020690]=receive
    # Special boot modes may branch to additional board setup beyond this
    # bounded window. Halt at its entry instead of making hardware assumptions.
    for p in (0x8002c480,0x8002c4b4):
        m.uc.hook_add(UC_HOOK_CODE,lambda u,p,n,x:stop(m),begin=p,end=p)
    m.invoke(0x8002c1e8,[])
    return calls,received

def main():
    cases=[]
    def passed(case,**details):cases.append(dict(case=case,**details))
    for fs in (FolderTree,ExfatFolders):
        r,result,seen=mounted(fs)
        assert result==0 and r.mounts==[2] and seen==[SUCCESS]
        r.verify_folders()
        assert r.locks.tokens=={0x7110}
    passed('Cold argument-zero setup reaches success only after native FAT32 or exFAT mount, folder preparation and directory changes')

    for fs in (FolderTree,ExfatFolders):
        r,result,seen=mounted(fs,present=False)
        assert result==0 and r.mounts==[1] and not seen and not r.directory_calls
        r,result,seen=mounted(fs,constructor={'readonly':True})
        assert result==0xffffffff and r.mounts==[2] and not seen
    r,result,seen=mounted(FolderTree,constructor={'spc':8})
    assert result==0xffffffff and r.mounts==[10] and not seen
    passed('Missing card, rejected cluster geometry and read-only folder failure never reach success; missing card still returns zero')

    for entry in (0x80002d80,0x80002ec8):
        r=FolderTree();seen=[];r.m.hooks[entry]=lambda a:0xffffffff
        # setup_card deliberately retains both native directory callees, so
        # these explicit fault injections are not replaced by board fixtures.
        r.m.uc.hook_add(UC_HOOK_CODE,lambda u,p,n,x:seen.append(p),begin=SUCCESS,end=SUCCESS)
        assert r.setup_card(argument=0)==0xffffffff and not seen
    passed('Both folder preparation and subsequent directory-change failures bypass the success branch')

    calls,received=boot(0)
    assert received==[NORMAL_RECEIVE]
    assert [a for p,a in calls if p==0x80009a40]==[(0,0)]
    assert [a for p,a in calls if p==0x8000c220]==[(0,0)]
    passed('Original ordinary Main boot calls card setup with zero and starts the audio-only USB path before the normal receive loop')

    for mode in (2,3):
        calls,received=boot(mode,True)
        assert received==[0x8002c258,NORMAL_RECEIVE],(mode,received)
        assert any(p==0x80006a30 and a[0]==0 for p,a in calls)
    passed('Setup boot modes can later reach the same normal receive site; that site alone cannot authorize initial capture',modes=[2,3])

    out=ROOT/'analysis/native_startup_boundary_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),device_access=False,
        limitations=['Native mount/filesystem/folder branches use virtual sectors and modeled card notification.',
            'Separate Main trace models all board callees; not one complete boot execution.',
            'Success branch is a logical setup witness, not exclusive storage ownership or physical completion.',
            'No worker release, new readiness API, code patch or on-device change.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
