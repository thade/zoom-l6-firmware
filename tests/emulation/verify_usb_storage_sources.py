#!/usr/bin/env python3
"""Original USB-worker SD notification eligibility, offline only.

Kernel progress, USB/controller setup and callback arrival are fixtures. Original
mode selection, worker state, callback latch and storage notification routing run.
This bounds one known source; it does not supply physical SD exclusion.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from verify_usb_memory_providers import initialized
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
from verify_scheduling_boundaries import stop
from verify_record_scheduler import word
from build_added_code_probe import branch

STATE=0x801f9108
CALLBACK=0x20022000

def worker(selector,success=True,connected=False,stop_after=False):
    m=initialized();requests=[];notifications=[];callbacks=[];polls=[];setup=[]
    for address,size in ((0x401b0000,0x10000),(0x401f8000,0x1000),(0xe000e000,0x1000)):
        m.uc.mem_map(address,size)
    for offset,value in ((0,0x7000),(12,0x7001),(24,0x7002)):
        put32(m,STATE+offset,value)
    put32(m,0x802350e4,CALLBACK|1)
    waits=[]
    def wait(a):
        assert a[:2]==[0x7000,10]
        waits.append(1)
        if len(waits)==1:command=1<<selector
        elif stop_after and len(waits)==2:command=0x800
        else:return stop(m)
        put32(m,STATE+4,command);put32(m,STATE+8,0)
        return 0
    def start(a):
        requests.append(struct.unpack('<H',m.uc.mem_read(a[0]+4,2))[0])
        return int(success)
    # Synthetic USB polling body tail-calls the actual card-state callback.
    # No nested emulator execution or direct write replaces its native latch.
    m.uc.mem_write(0x8003b5d0,bytes([int(connected),0x20])+branch(0x8003b5d2,0x80050360))
    m.uc.hook_add(UC_HOOK_CODE,lambda u,p,n,x:polls.append(word(m,STATE+16)),
                 begin=0x8003b5d0,end=0x8003b5d0)
    fixtures=(0x8003b580,0x80073ec8,0x80073f18,0x80025f78,
              0x8001bcd8,0x8001bc98,0x80026bf0,0x8001bc20,
              0x80026b90,0x8003b558)
    for fn in fixtures:m.hooks[fn]=lambda a:0
    m.hooks[0x800684b8]=lambda a:setup.append('unit0_setup') or 0
    m.hooks[0x80068318]=lambda a:setup.append('unit0_teardown') or 0
    m.hooks[0x80068508]=lambda a:notifications.append(a[0]) or 0
    m.hooks[CALLBACK]=lambda a:callbacks.append(a[:2]) or 0
    m.hooks.update({0x80076950:wait,0x800763d8:lambda a:1,0x8003b5a8:start})
    m.invoke(0x80045cf0,[])
    return dict(selector=selector,started=success,connected=connected,stop_after=stop_after,
                requests=requests,notifications=notifications,callbacks=callbacks,
                poll_states=polls,setup=setup,state=word(m,STATE+16))

def main():
    cases=[]
    def passed(name,**details):cases.append(dict(case=name,**details))
    rows=[worker(selector,success,connected) for selector in range(11)
          for success in (False,True) for connected in (False,True)]
    for r in rows:
        assert len(r['requests'])==1,r
        mass=r['selector'] in (4,6,8,10)
        assert ('unit0_setup' in r['setup'])==mass,r
        assert r['notifications']==[],r
        assert r['callbacks']==([[1,1]] if mass and r['started'] and r['connected'] else []),r
    passed('All eleven cold worker configurations separate audio-only from SD-capable modes',
           cases=rows,scope='44 finite configurations with injected setup outcomes and one callback arrival')

    # Start with a disconnected latch (2), connect (1), then disconnect (2).
    # The cold one-poll rows above cannot produce the 1->2 notification by design.
    # Test the precise native worker tail separately without inventing Main work.
    from unicorn import arm_const as A
    for selector in (0,1,2,3,5,7,9):
        r=worker(selector,True,False,True)
        assert not r['notifications'] and 'unit0_teardown' not in r['setup'],r
    passed('Audio-only start followed by original USB-stop request does not enter unit0 teardown')

    for selector in (4,6,8,10):
        r=worker(selector,True,True,True)
        assert r['setup']==['unit0_setup','unit0_teardown'],r
    passed('SD-capable start followed by original USB-stop request enters unit0 teardown')

    for active in (0,1):
        for old,new in ((0,1),(2,1),(1,2),(2,2)):
            m=initialized();posts=[];callbacks=[]
            put32(m,0x802350e4,CALLBACK|1)
            put32(m,STATE+16,old);put32(m,STATE+20,new)
            m.hooks[0x80073ec8]=lambda a:0;m.hooks[0x80073f18]=lambda a:0
            m.hooks[0x80068508]=lambda a:posts.append(a[0]) or 0
            m.hooks[CALLBACK]=lambda a:callbacks.append(a[:2]) or 0
            m.hooks[0x80076950]=lambda a:stop(m)
            m.uc.reg_write(A.UC_ARM_REG_R4,active)
            m.uc.reg_write(A.UC_ARM_REG_R8,STATE)
            m.uc.reg_write(A.UC_ARM_REG_R10,0)
            m.invoke(0x80046cde,[])
            assert posts==([0] if active and old!=new and new==2 else []),(active,old,new,posts)
            assert callbacks==([[1,int(new==1)]] if active and old!=new else [])
    passed('Original SD-enabled worker tail posts unit0 abort wakeup on connected-to-disconnected change; inactive tail does not',
           limitation='Latch arrival and worker state controlled; not proof of all ingress or physical completion')

    out=ROOT/'analysis/usb_storage_sources_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),device_access=False,
        limitations=['Original worker, mode branches, callback latch and outer notification router execute.',
            'USB/controller setup, semaphore scheduling and callback arrival are modeled.',
            'Unit0 driver setup/teardown and final event post are observed at entry, not physically executed.',
            'No complete indirect-source inventory, source lease, IRQ/DMA joining or runtime mode admission is supplied.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
