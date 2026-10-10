#!/usr/bin/env python3
"""Bounded native dispatch audit and optional-file shutdown regression.

Stock switches and physical-event decoding execute. Deeper callees are scalar
models, so this is neither a transitive caller audit nor physical SD admission.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_PC,UC_ARM_REG_LR
from verify_pad_protocol import Machine,IMAGE,BIAS,INPUT,RETURN,REGS,ROOT
from verify_storage_main import MainRig,MainPending,LOOPS,LATER,BUFFER,N,ELF
from verify_storage_stop import finish_storage
from verify_native_worker import MAIN_HANDLE
from verify_reload_queue_audit import packed

# Code bounds exclude inline strings. Only the first dispatcher level executes.
BOUNDS={0x8002c510:0x8002c8f0,0x8002c9d8:0x8002ce48,
        0x8002d090:0x8002d4d8,0x8002d568:0x8002d7d0,
        0x8002c960:0x8002c9d8}
BOUNDARIES={0x80009a40,0x80009b18,0x8000c220,0x8000c288,0x8000c2d8,
            0x8000ab08,0x8000a178,0x8000aae8,0x8002d6b0,
            0x80034568,0x8003d660}
DELAYED={0xa2:0x8000a178,0xa3:0x8000aae8}

class Routes(Machine):
    def __init__(self):
        super().__init__();self.uc.hook_add(UC_HOOK_CODE,self.leaf)
    def leaf(self,uc,address,size,_):
        if address==RETURN:return
        # This native power branch never returns; observe entry before effects.
        if address==0x8002d6b0:
            self.calls.append((address,[]));self.reached_return=True;uc.emu_stop();return
        if self.entry<=address<BOUNDS[self.entry] or 0x80020c60<=address<0x80020ca0:return
        self.calls.append((address,[uc.reg_read(r) for r in REGS]))
        uc.reg_write(UC_ARM_REG_R0,self.value)
        uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    def route(self,entry,packet,value=0):
        self.entry=entry;self.value=value;self.calls=[]
        self.uc.mem_write(INPUT,packed(packet));self.invoke(entry,[INPUT])
        return self.calls

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    # Read the original table as data, not a linear disassembly of its halfwords.
    table=0x8002c528
    targets=[table+2*v for v in struct.unpack_from('<165H',IMAGE,table-BIAS)]
    assert targets[0xa2:]==[0x8002c8cc,0x8002c8d8,0x8002c8e4]
    r=Routes()
    subtypes=(*range(10),0xffffffff)
    for subtype in subtypes:
        for code,target in DELAYED.items():
            assert [a for a,_ in r.route(0x8002c510,(2,subtype,code,91,92))]==[target]
    passed('Original delayed USB dispatch ignores subtype, including noncanonical and all-ones values',
           packets=len(subtypes)*2)

    # Uniform scalar-return scenarios explore selected branches, not every
    # combination of state getters. All deeper targets remain in the report.
    observed=set();leaves=set();runs=0
    for entry,category,limit in ((0x8002c510,2,165),(0x8002c960,2,165),
                                (0x8002c9d8,0,54),(0x8002d090,0,54),
                                (0x8002d568,1,31)):
        for subtype in range(10):
            for code in range(limit+1):
                for value in (0,1,2,5):
                    packet=(category,subtype,code,0,0);runs+=1
                    for target,args in r.route(entry,packet,value):
                        leaves.add(target)
                        if target in BOUNDARIES:
                            observed.add((entry,category,subtype,code,target))
    assert {c for e,cat,s,c,t in observed if cat==2}=={0xa2,0xa3}
    assert {c for e,cat,s,c,t in observed if cat==0}==set(range(0x32,0x36))
    assert {(s,c) for e,cat,s,c,t in observed if cat==1}=={(0,c) for c in range(6)}
    passed('Bounded five-dispatcher scan reaches the recovered storage and power boundaries',
           invocations=runs,unique_boundary_routes=len(observed))

    # Test the compiled wrapper, not a Python copy of the corrected predicate.
    packets={(cat,sub,code,91,92) for e,cat,sub,code,t in observed}
    packets.update((2,sub,code,91,92) for sub in subtypes for code in DELAYED)
    for packet in sorted(packets):
        q=MainRig();assert q.boot()==0;q.ui_setup([packet,LATER])
        assert q.other(lambda:q.m.invoke(N['storage_main_receive'],[BUFFER]),MAIN_HANDLE)==0
        assert q.lstate()==3,('unguarded native boundary',packet)
        assert q.raw(BUFFER,20)==packed(packet) and q.packets()==[LATER]
    passed('Compiled Main gate retires storage before every observed boundary packet',packets=len(packets))

    # Both Main loops which use the delayed-command dispatcher retain the whole
    # packet while the independent worker owns an outstanding file operation.
    combinations=0
    for loop in (LOOPS[2],LOOPS[4]):
        for code,target in DELAYED.items():
            for phase in ('create','initial_header','audio','final_header','read_header',
                          'read_audio','close_write','close_read'):
                q=MainPending();assert q.boot(release=True)==0
                if phase in ('create','initial_header'):
                    q.pause=phase;q.wait_pending()
                else:
                    q.ready();q.begin_recording()
                    for _ in range(5):q.audio_call();q.tick()
                    q.pause=phase
                    if phase=='audio':q.wait_pending(audio=True)
                    else:q.stop_recording();q.wait_pending(audio=True)
                before=list(q.calls);frame=q.frame();pending=q.pending
                q.ui_setup([(2,3,code,91,92),LATER]);effects=[]
                q.m.hooks[target]=lambda a:effects.append(q.lstate()) or 0
                q.run_main(loop)
                for _ in range(3):
                    assert q.waiting=='join' and not effects and q.packets()==[LATER]
                    assert q.frame()==frame and q.pending==pending and q.calls==before
                    q.resume_main()
                q.complete();finish_storage(q);q.resume_main()
                assert q.waiting=='empty' and not q.packets() and effects==[3]
                assert q.dispatched==[('reload',3)] and not q.opened
                combinations+=1
    passed('Both native delayed-command loops wait through all eight file phases and dispatch once',
           combinations=combinations)

    # a4 only cancels an ordinary UI timer; neighboring commands are not broadened.
    for subtype in subtypes:
        q=MainRig();assert q.boot()==0;q.ui_setup([(2,subtype,0xa4,0,0)])
        q.other(lambda:q.m.invoke(N['storage_main_receive'],[BUFFER]),MAIN_HANDLE)
        assert q.lstate()==0
    assert [a for a,_ in r.route(0x8002c510,(2,4,0xa4,0,0))]==[0x8000a198]
    passed('Neighboring a4 timer command remains ordinary for every tested subtype')

    report=dict(passed_groups=len(cases),cases=cases,
        stock_sha256=hashlib.sha256(IMAGE).hexdigest(),fixture_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
        boundary_routes=[dict(dispatcher=hex(e),category=cat,subtype=s,code=hex(c),target=hex(t))
                         for e,cat,s,c,t in sorted(observed)],
        modeled_leaf_targets=[hex(t) for t in sorted(leaves)],
        limitations=['Finite first-level dispatch and uniform scalar-return scenarios; not exhaustive state combinations or transitive callees.',
            'Noncanonical subtype reachability from production senders is not established; the guard now matches the accepting dispatcher.',
            'Kernel copying, task progress, file and physical completion are modeled; no hardware access or source admission.',
            'Startup/setup, indirect callers, independent USB worker notifications and physical card removal remain separate.'])
    out=ROOT/'analysis/storage_ingress_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))

if __name__=='__main__':main()
