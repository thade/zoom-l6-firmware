#!/usr/bin/env python3
"""Original effect setup, parameter destinations and engine traversal, offline.

Uses original synchronous update modes to bound destination providers; this is
not deferred-copy scheduling proof. Kernel mutex/delay and input audio are
fixtures. All five stock engines execute, without hardware or optional capture.
"""
import hashlib,json,math,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_stock_ring_modes import initialized
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE
from verify_uncompressed_tap import B,RING,STRIDE
from audit_ram_gap_consumers import GAPS
from verify_scheduling_boundaries import stop

TABLE=0x801f5bfc
PROCESSORS=(0x2022b8d1,0x2022ad41,0x2022c4a9,0x80024051,0x2022aa09)
EXPECTED_COPIES=(((0x2000bba0,20),(0x2000bc24,20),(0x2000bc7c,12)),
                 ((0x2000bb98,20),),
                 ((0x2000bd08,20),(0x2000bd1c,20),(0x2000bd30,20)),(),())

def effect_case(effect, *, deferred_service=None):
    r=initialized(223104);m=r.m;copies=[];engines=[];delays=[]
    copy_digest=hashlib.sha256()
    m.invoke(0x80001994,[0x800a6980,0x801f5400,0x3780])
    # Original initialized DTCM contains the effect window coefficients and
    # 48-kHz constant at2000baf0. Zero-filled emulator RAM is not equivalent.
    m.invoke(0x80001994,[0x800a9208,0x20000000,0xbb00])
    assert r.word(0x2000baf0)==48000
    descriptor=struct.unpack('<7I',r.raw(TABLE+28*effect,28))
    assert descriptor[0]==PROCESSORS[effect]
    assert descriptor[-2:]==((100,100) if effect<3 else (1999,100))
    for pc in (0x80076950,0x800763d8):m.hooks[pc]=lambda a:1
    def delay(a):
        delays.append(a[0]);assert len(delays)<100,'Unexpected unadvanced scheduler dependency'
        return 0
    m.hooks[0x80077686]=delay
    def copied(u,p,n,x):
        destination,source,size=[u.reg_read(a) for a in (A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2)]
        assert m.stack-256<=source<source+size<=m.stack
        copies.append((destination,size))
        copy_digest.update(struct.pack('<2I',destination,size)+r.raw(source,size))
    for pc in (0x8005b740,0x8005b790):m.uc.hook_add(UC_HOOK_CODE,copied,begin=pc,end=pc)
    m.uc.hook_add(UC_HOOK_CODE,lambda u,p,n,x:engines.append(p),
                 begin=descriptor[0]&~1,end=descriptor[0]&~1)
    def forbidden(u,k,a,n,v,x):
        raise AssertionError(('Effect accessed proposed memory',hex(u.reg_read(A.UC_ARM_REG_PC)),hex(a),n))
    # Reject reads as well as writes. These are emulator addresses, not physical
    # alias checks. The full twelve tails are covered, including unused four.
    intervals=[*GAPS,(0x800b6b00,0x801f5400),
               *[(RING+i*STRIDE+223104*4,RING+(i+1)*STRIDE) for i in range(12)]]
    for a,z in intervals:
        m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,forbidden,begin=a,end=z-1)
    m.invoke(0x80051780,[]) # Original synchronous copy mode, used during setup.
    m.invoke(0x8000e9b0,[]) # Full original effects context/provider initialization.
    put32(m,m.stack,0)     # Fifth AAPCS argument: ordinary initial selection.
    m.invoke(0x8000e818,[0,effect,50,50])
    assert r.word(0x8053d198)==descriptor[0]
    assert struct.unpack('<5I',r.raw(0x801f8cc0,20))==(0x2000bb14,0x2000c18c,0x80bb9400,0x80c74c00,0xbb800)
    # Reverb selection schedules a delayed enable callback. Execute the real
    # timer worker for one semaphore wake per step, rather than silently leaving
    # its output muted. Wake timing is modeled; counter/callback bodies are not.
    timer_steps=0
    def timer_tick():
        wakes=[]
        def acquire(a):
            if a[0]==r.word(0x80446860):
                wakes.append(1)
                if len(wakes)>1:return stop(m)
            return 1
        # Give the two modeled mutex/semaphore objects distinct identities.
        put32(m,0x80446860,0x2103e000);put32(m,0x80446818,0x2103e040)
        m.hooks[0x80076950]=acquire
        m.invoke(0x80026720,[]);m.invoke(0x80051780,[])
        m.invoke(0x80026260,[])
        m.hooks[0x80076950]=lambda a:1
    while r.raw(0x801f8c7c,1)!=b'\0':
        timer_tick();timer_steps+=1
        assert timer_steps<=1000,'Unsettled native effect-enable timer'
    # Optional test scheduler supplies only consumer timing. Original providers,
    # staging writes, request slots, consumer copies and waits execute unchanged.
    service=deferred_service(r) if deferred_service is not None else None
    count=0
    for fn,maximum in zip((0x8000e748,0x8000e7b0),descriptor[-2:]):
        for value in range(maximum+1):
            # Actual native synchronous controls avoid requiring an invented
            # background audio thread. Provider arithmetic and both copy bodies
            # remain original; queued delivery has its own earlier tests.
            m.invoke(0x80026720,[])
            m.invoke(0x8004ea40 if service is not None else 0x80051780,[])
            m.invoke(fn,[0,value]);count+=1
            if service is not None:service.idle()
    assert tuple(sorted(set(copies)))==EXPECTED_COPIES[effect]
    m.invoke(0x80026730,[])
    digest=hashlib.sha256();peak=0.;nonzero_blocks=0
    for block in range(2048):
        r.floats(B+0x29b8,([2**27]+[0]*127) if block==0 else [0]*128)
        m.invoke(0x8000e380,[]) # Full original dispatcher and selected engine.
        output=r.raw(B+0x29b8,512);values=struct.unpack('<128f',output)
        assert all(math.isfinite(v) for v in values)
        peak=max(peak,max(map(abs,values)));nonzero_blocks+=int(any(values));digest.update(output)
    assert engines==[descriptor[0]&~1]*2048 and nonzero_blocks,(effect,len(engines),nonzero_blocks,peak)
    return dict(effect=effect,processor=hex(descriptor[0]),parameter_calls=count,
                parameter_limits=descriptor[-2:],copy_calls=len(copies),
                copy_inputs_sha256=copy_digest.hexdigest(),
                deferred_copies=0 if service is None else service.completed,
                copy_destinations=[dict(address=hex(a),bytes=n) for a,n in sorted(set(copies))],
                engine_blocks=len(engines),frames=2048*64,nonzero_blocks=nonzero_blocks,
                output_peak=peak,output_sha256=digest.hexdigest(),delay_calls=delays,
                enable_timer_steps=timer_steps)

def main():
    cases=[effect_case(effect) for effect in range(5)]
    assert sum(r['parameter_calls'] for r in cases)==4808
    out=ROOT/'analysis/effect_memory_providers_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),device_access=False,
        limitations=['Original cold context/provider/parameter/copy code and all five engines execute.',
            'Each parameter independently spans its valid range; combinations and all history states are not exhaustive.',
            'Synchronous stock update modes qualify destinations, not deferred delivery, preemption or timing.',
            '131072 generated frames per effect at final maximum parameters; not whole-device elapsed playback.',
            'Kernel mutexes/delay, timer wake timing and mono input impulse are fixtures. ARM MAX is not CPU identification.',
            'No ADC/USB/DMA/cache model, physical aliases, optional capture writer or on-device ownership proof.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
