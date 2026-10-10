#!/usr/bin/env python3
"""Native audio-mode request/acknowledgement boundaries; offline only.

Mailbox/semaphore scheduling, board setup and connection arrival are models.
Request and worker instructions execute in separate runs; no concurrent-boot or
physical source exclusion is claimed.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R7,UC_ARM_REG_LR
from verify_usb_memory_providers import initialized
from verify_usb_storage_sources import STATE,CALLBACK
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_scheduling_boundaries import stop
from build_added_code_probe import branch

REQUEST,ACK=0x7000,0x7001

def request(profile):
    """Run ordinary Main's USB outer call through its actual mailbox request."""
    m=initialized();events=[];modes=[]
    put32(m,STATE,REQUEST);put32(m,STATE+12,ACK)
    m.hooks[0x800345f8]=lambda a:0x1234
    for fn in (0x80077686,0x80073ec8,0x80073f18):m.hooks[fn]=lambda a:0
    m.hooks[0x80006aa8]=lambda a:modes.append(a[0]) or 0
    m.hooks[0x800763d8]=lambda a:events.append(('give',a[:4])) or 1
    # Deliberately supply an already-available ACK with no worker execution.
    m.hooks[0x80076950]=lambda a:events.append(('take',a[:2])) or 1
    m.invoke(0x8000c220,[0,profile])
    assert events==[('give',[REQUEST,0,0,0]),('take',[ACK,0xffffffff])]
    assert modes==[0]
    return dict(profile=profile,command=word(m,STATE+4),argument=word(m,STATE+8),
                outer_mode_updated_without_worker=True)

def worker(commands,success=True):
    m=initialized();commands=list(commands);acks=[];setup=[];posts=[];pids=[];polls=[]
    for address,size in ((0x401b0000,0x10000),(0x401f8000,0x1000),(0xe000e000,0x1000)):
        m.uc.mem_map(address,size)
    put32(m,STATE,REQUEST);put32(m,STATE+12,ACK);put32(m,STATE+24,0x7002)
    put32(m,0x802350e4,CALLBACK|1)
    index=0
    def wait(a):
        nonlocal index
        assert a[:2]==[REQUEST,10]
        if index==len(commands):return stop(m)
        put32(m,STATE+4,commands[index]);put32(m,STATE+8,0x1234);index+=1
        return 1
    def give(a):
        if a[0]==ACK:
            acks.append(dict(command=commands[index-1],pending=word(m,STATE+4),
                sd_active=m.uc.reg_read(UC_ARM_REG_R7),return_to=m.uc.reg_read(UC_ARM_REG_LR)&~1,
                setup=list(setup),usb_started=bool(m.uc.mem_read(0x80212e00,1)[0])))
        return 1
    def start(a):
        pids.append(struct.unpack('<H',m.uc.mem_read(a[0]+4,2))[0]);return int(success)
    # Alternate actual connected/disconnected callbacks across successive polls.
    # R0 is supplied by the arrival model; the native latch writer then executes.
    m.uc.mem_write(0x8003b5d0,branch(0x8003b5d0,0x80050360))
    def polling(uc,address,size,_):
        from unicorn.arm_const import UC_ARM_REG_R0
        connected=int(len(polls)%2==0);polls.append(connected)
        uc.reg_write(UC_ARM_REG_R0,connected)
    m.uc.hook_add(UC_HOOK_CODE,polling,begin=0x8003b5d0,end=0x8003b5d0)
    for fn in (0x8003b580,0x80073ec8,0x80073f18,0x80025f78,0x8001bcd8,
               0x8001bc98,0x80026bf0,0x8001bc20,0x80026b90,0x8003b558):
        m.hooks[fn]=lambda a:0
    m.hooks[0x800684b8]=lambda a:setup.append('unit0_setup') or 0
    m.hooks[0x80068318]=lambda a:setup.append('unit0_teardown') or 0
    m.hooks[0x80068508]=lambda a:posts.append(index) or 0
    m.hooks[CALLBACK]=lambda a:0
    m.hooks.update({0x80076950:wait,0x800763d8:give,0x8003b5a8:start})
    m.invoke(0x80045cf0,[])
    return dict(commands=commands,acks=acks,setup=setup,posts=posts,pids=pids,polls=polls)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    requests=[request(p) for p in range(3)]
    assert [r['command'] for r in requests]==[0x20,0x80,0x200]
    assert {r['argument'] for r in requests}=={0x1234}
    passed('Ordinary Main requests audio-only worker bits5,7,9 through the real public mailbox call',requests=requests)
    passed('Counterexample stale ACK lets outer mode update before any worker execution',
           limitation='Semaphore availability is injected; production occurrence is not established')

    rows=[]
    for req in requests:
        for success in (False,True):
            r=worker([req['command'],0,0,0],success);rows.append(r)
            assert len(r['acks'])==1 and not r['setup'] and not r['posts']
            ack=r['acks'][0]
            assert ack['pending']==0 and ack['sd_active']==0 and ack['return_to']==0x80046cd2
            assert ack['usb_started']==success
    passed('Cold audio-only worker acknowledges with inactive SD state, on USB setup success and failure',rows=rows)

    # Starting an audio mode alone does not necessarily reset the worker's
    # retained SD-active local. A genuine prior STOP is essential after SD mode.
    counterexamples=[]
    for req in requests:
        r=worker([0x40,req['command'],0,0]);counterexamples.append(r)
        assert r['acks'][0]['sd_active']==r['acks'][1]['sd_active']==1
        assert r['setup']==['unit0_setup'] and r['posts']
        clean=worker([0x40,0x800,req['command'],0,0])
        assert clean['setup']==['unit0_setup','unit0_teardown']
        assert clean['acks'][-1]['sd_active']==0
        assert not any(index>=3 for index in clean['posts'])
    passed('Counterexample audio request after SD mode retains SD notification eligibility without preceding STOP',
           rows=counterexamples)

    report=dict(passed_groups=len(cases),cases=cases,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        limitations=['Actual outer request, worker branches, ACK placement and callback routing; kernel and board/USB setup are modeled.',
            'Sequential request/worker runs are not one concurrent boot and do not establish fresh ACK identity.',
            'First-trial source admission must observe cold worker history and matched request consumption, not only requested mode or ACK return.',
            'No source port, controller reset guarantee, device operation or firmware image is supplied.'])
    out=ROOT/'analysis/usb_startup_ack_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
