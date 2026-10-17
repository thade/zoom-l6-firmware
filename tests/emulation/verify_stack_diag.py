#!/usr/bin/env python3
"""Experiment 42's diagnostic build: status schema 8, the task stack headroom
read from the stock A5 fill and the least stack each hook found free, executed
with the build's own code over control blocks and stacks laid out as the stock
task creator leaves them. The working tree still builds the 0.3.0 image byte
for byte. No device access.
"""
import json,struct,sys
from verify_pad_protocol import ROOT,INPUT
import verify_master_ref as V
from build_master_ref import build
from plan_master_ref import plan
from capture_jump_patches import symbols
from build_deployment_probe import SOURCE,digest
from build_master_trial import trial,trial_elf,assemble,MODES
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_padref_probe import request,decode

CURRENT=0x808e291c                     # the running task's control block (stock kernel)
SLOTS=dict(recplayctl=0x80446dc0,main=0x80446da4,midisetting=0x80446db0)
SIZES=dict(recplayctl=16384,main=32768,midisetting=4096,worker=8192)   # from the stock task table
FILL=b'\xa5'*4;PAINT=struct.pack('<I',0x5ca1ab1e);WRITTEN=b'\x11\x22\x33\x44'
TCBS=0x23020000                        # control blocks and stacks in the rig's scratch RAM
WINDOW=4096                            # the stack window the rig's calls run in, below its stack top

def control_block(m,at,base,size,used,painted=0):
    """A control block whose stack (base, size) is A5-filled with `used` bytes
    written at the top and `painted` bytes of the worker's paint below them."""
    top=(base+size-4)&~7
    m.uc.mem_write(at,bytes(0x94));V.put32(m,at+0x30,base);V.put32(m,at+0x64,top)
    free=size-used-painted
    m.uc.mem_write(base,FILL*(free//4)+PAINT*(painted//4)+WRITTEN*(used//4))
    return at

def main():
    cases=[]
    def passed(case,**d):cases.append(dict(case=case,**d))
    elf=build(trial=True,stereo=True,link=True,stack=True);P=plan(elf,trial=True)
    V.PLAN=P;V.PACK=P['pack'];V.N=symbols(elf);N=V.N
    image,_,manifest,_=trial('stack_diag')
    adapters=sorted(p['adapter'] for p in manifest['patches'])
    assert manifest['experiment']==42 and len(adapters)==16 and 'health_parser' in adapters and len(manifest['DSP_patches'])==2
    assert manifest['linked_aux_limiters'] and manifest['diagnostics'] and 'schema8' in manifest['protocol']
    # The release sources are the same: the working tree still builds 0.3.0.
    everyday=dict(MODES['release']);del everyday['pin']
    with trial_elf(everyday) as release_elf:t=plan(release_elf,trial=False)
    assert digest(assemble(SOURCE.read_bytes(),t))==MODES['release']['sha']
    passed('the_diagnostic_build_patches_the_release_sites_plus_the_query_and_the_tree_still_builds_0_3_0',
           trial_sha256=manifest['trial_sha256'],code_bytes=manifest['code_bytes'],release_sha256=MODES['release']['sha'])

    r=V.MasterRig();m=r.m;replies=[];V.put32(m,CURRENT,0)   # the rig's stock boot left a task current
    m.hooks[0x80031648]=lambda a:replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    m.uc.mem_write(0x80629b60,b'\x02')
    def query(token=1):
        m.uc.mem_write(INPUT,struct.pack('<I',8)+request(token)+bytes(16));assert m.invoke(N['mr_query'],[INPUT])==1
        return decode(replies[-1])
    # Headroom: the bytes at the bottom of each task's stack never written.
    used=dict(recplayctl=3000,main=5000,midisetting=1500,worker=1200)
    tcbs={}
    for i,(name,size) in enumerate(SIZES.items()):
        at=TCBS+i*0x10000;tcbs[name]=control_block(m,at,at+0x100,size,used[name],painted=4096 if name=='worker' else 0)
    for name,slot in SLOTS.items():V.put32(m,slot,tcbs[name])
    r.set('task',tcbs['worker'])
    s=query();assert s['schema']==8 and s['aux_mode']==0 and s['pads']==['#NO ASSIGN']*4,s
    assert s['headroom']==dict(recplayctl=16384-3000,main=32768-5000,midisetting=4096-1500,worker=8192-1200),s['headroom']   # the worker's own paint counts as unwritten
    assert s['hooks']=={h:dict(free=0,task='none') for h in ('admit','stop','play','receive','query')},s['hooks']
    # A missing task reads 0; so does a stack written to its bottom.
    V.put32(m,SLOTS['main'],0);control_block(m,tcbs['midisetting'],tcbs['midisetting']+0x100,4096,4096)
    s=query();assert s['headroom']['main']==0 and s['headroom']['midisetting']==0 and s['headroom']['recplayctl']==16384-3000
    V.put32(m,SLOTS['main'],tcbs['main'])
    passed('schema_8_reads_each_tasks_headroom_from_the_stock_fill_and_the_workers_paint',headroom=s['headroom'])

    # The hooks note the least stack free below their own frame and their task.
    # The rig runs every call in one window below its stack top: each task's
    # control block claims it in turn, A5-filled again before each.
    window=m.stack-WINDOW
    def run_as(name,call):
        V.put32(m,tcbs[name]+0x30,window);V.put32(m,tcbs[name]+0x64,(window+WINDOW-4)&~7)
        m.uc.mem_write(window,FILL*(WINDOW//4));V.put32(m,CURRENT,tcbs[name]);call();V.put32(m,CURRENT,0)
    V.put32(m,CURRENT,0);V.normal_recording_state(m);m.invoke(N['mr_admit'],[])   # no running task known: nothing noted
    assert r.field('stock_recording')==1
    run_as('recplayctl',lambda:m.invoke(N['mr_stop'],[0,V.REC_STOP]));assert r.field('stopped')==1
    run_as('recplayctl',lambda:(V.normal_recording_state(m),m.invoke(N['mr_admit'],[])))
    run_as('main',lambda:r.play(0))
    run_as('main',lambda:r.main_receive(0,0,0,0))
    run_as('midisetting',lambda:query(2))
    V.put32(m,CURRENT,tcbs['midisetting']);s=query(3);V.put32(m,CURRENT,0)
    hooks=s['hooks']
    assert {h:v['task'] for h,v in hooks.items()}==dict(admit='recplayctl',stop='recplayctl',play='main',receive='main',query='midisetting'),hooks
    # Each note is taken below the hook's own frame (at most 216 bytes, the
    # query's). The pad start runs through its adapter, which saves the full
    # context (192 bytes) first.
    for h in ('admit','stop','receive','query'):assert WINDOW-256<=hooks[h]['free']<WINDOW,(h,hooks[h])
    assert WINDOW-192-256<=hooks['play']['free']<=WINDOW-192,hooks['play']
    # Running again no deeper leaves the minimum alone; a deeper run lowers it.
    before=dict(hooks)
    run_as('recplayctl',lambda:(V.normal_recording_state(m),m.invoke(N['mr_admit'],[])))
    V.put32(m,CURRENT,tcbs['midisetting']);s=query(4);V.put32(m,CURRENT,0)
    assert s['hooks']['admit']==before['admit'] and s['hooks']['query']['free']<=before['query']['free']
    V.put32(m,tcbs['recplayctl']+0x30,window+256);V.put32(m,CURRENT,tcbs['recplayctl'])
    V.normal_recording_state(m);m.invoke(N['mr_admit'],[]);V.put32(m,CURRENT,0)
    V.put32(m,CURRENT,tcbs['midisetting']);s=query(5);V.put32(m,CURRENT,0)
    assert s['hooks']['admit']['free']==before['admit']['free']-256,s['hooks']['admit']
    passed('each_hook_notes_the_least_stack_free_below_its_entry_and_the_task_it_ran_on',
           hooks={h:v['free'] for h,v in hooks.items()},adapter_frame=192)
    result=dict(passed=True,groups=len(cases),results=cases,trial_sha256=manifest['trial_sha256'])
    (ROOT/'analysis/stack_diag_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
