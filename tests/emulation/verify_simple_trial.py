#!/usr/bin/env python3
"""Exact simplified-capture tap trial image (experiment 19), offline only.

Original reset/scatter/startup, DSP windows, stock recording and the Editor
parser execute. Task creation, scheduling and cache effects are modeled.
"""
import hashlib,json,struct,sys
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_simple_capture import SimpleRig,SimpleBoot,STATE,OFF
from verify_capture_integration import IntegrationRig,record
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT,request as pad_request
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_scheduling_boundaries import stop
from verify_uncompressed_tap import packed
import verify_health_probe as health
from build_simple_trial import trial,OUT
from build_deployment_probe import validate
from capture_jump_patches import SCATTER
from plan_capture_packing import DECOMPRESS,ZERO
from plan_simple_capture import RECORDER_SPECS
from plan_capture_transitions import RECEIVERS
from scatter_codec import expand
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_simple_probe import request,decode,validate_samples,FIELDS

TRIAL,MANIFEST,T=trial();TP=T['pack'];TN=TP['names']
TAILS=[0x81429800+i*960000+223104*4 for i in range(8)]

class TrialRig(SimpleRig):
    plan,pack,names=T,TP,TN
    def redirect(self,address,name,always=False):pass # no recorder hooks in this image
class TrialBoot(SimpleBoot):
    plan,pack,names=T,TP,TN

def boot():
    """Run the exact image from reset through the application scatter table."""
    m=health.machine(False);u=m.uc
    for a,n in ((0,0x1000),(0x81000000,0x1000000),(0x20210000,0x20000),(0xe000e000,0x1000)):u.mem_map(a,n)
    u.mem_write(0x80001000,TRIAL[0x200:0xb5ce4]);seen=[]
    h=u.hook_add(UC_HOOK_CODE,lambda u,a,n,x:seen.append(a) or u.emu_stop(),begin=0x80067a60,end=0x80067a60)
    u.emu_start(0x80001401,0x80067a62,count=100000000);u.hook_del(h)
    assert seen==[0x80067a60]
    for at in range(0x800a68dc,0x800a695c,16):
        s,d,n,helper=struct.unpack_from('<4I',IMAGE,at-BIAS)
        if d==SCATTER[1]:expected=TP['dsp'] # the only changed destination: two tap jumps
        else:expected=bytes(n) if helper==ZERO else expand(IMAGE[s-BIAS:],n)[0] if helper==DECOMPRESS else IMAGE[s-BIAS:s-BIAS+n]
        assert bytes(u.mem_read(d,n))==expected,(hex(d),n)
    assert bytes(u.mem_read(MANIFEST['code_start'],len(TP['code'])))==TP['code']
    g=MANIFEST['globals_start'],MANIFEST['globals_end']
    assert bytes(u.mem_read(g[0],g[1]-g[0]))==bytes(g[1]-g[0])
    return m

def direct(m,packet,state=2):
    m.uc.mem_write(INPUT,struct.pack('<I',len(packet))+packet+bytes(16))
    m.uc.mem_write(0x80629b60,bytes([state]))
    return m.invoke(TN['sc_query'],[INPUT])

def main():
    cases=[]
    def passed(case,**details):cases.append(dict(case=case,**details))

    assert (OUT/'trial_simple_tap/L6.BIN').read_bytes()==TRIAL;validate(TRIAL)
    assert len(TRIAL)==len(IMAGE) and TRIAL[0x2851f8:]==IMAGE[0x2851f8:]
    sites=sorted(p['site'] for p in MANIFEST['patches'])
    assert sites==[0x800121ce,0x800301f0,0x80067a84,0x800745e8] and len(MANIFEST['DSP_patches'])==2
    for site,old in [(s['site'],s['original']) for s in RECORDER_SPECS]+list(RECEIVERS):
        assert TRIAL[site-BIAS:site-BIAS+4]==bytes.fromhex(old)
    passed('exact_image_patches_only_startup_ring_size_query_and_DSP_tap_commit',
           trial_sha256=MANIFEST['trial_sha256'],code_bytes=MANIFEST['code_bytes'],spare_bytes=MANIFEST['spare_bytes'])

    m=boot()
    passed('original_reset_and_scatter_expand_DSP_then_code_over_its_consumed_input_then_zero_globals')

    b=TrialBoot();b.boot();g=b.word(TN['sc_state'])
    assert b.created==[b'L6Capture\0'] and b.word(TN['sc_startup_status'])==4 and g%32==0
    assert b.added_writes and all(MANIFEST['globals_start']<=a and a+n<=MANIFEST['globals_end'] for a,n in b.added_writes)
    passed('original_startup_registers_worker_from_native_heap_with_writes_only_to_8_global_bytes',state=hex(g))

    # Idle worker: counted 25-tick passes, no files (Boot forbids file APIs) and
    # no history access before audio runs.
    mm=b.m;delays=[];forbidden=lambda *a:(_ for _ in ()).throw(AssertionError('history touched'))
    guards=[mm.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,forbidden,begin=t,end=t+128*512-1) for t in TAILS]
    mm.hooks[0x80074158]=lambda a:delays.append(a[0]) or (stop(mm) if len(delays)==5 else 0)
    mm.invoke(TN['sc_worker_entry'],[0])
    for h in guards:mm.uc.hook_del(h)
    assert delays==[25]*5 and b.word(g+OFF['polls'])==5 and b.word(g+OFF['state'])==0
    replies=[];mm.hooks[0x80031648]=lambda a:replies.append(bytes(mm.uc.mem_read(a[0],a[1]))) or 0
    direct(mm,request(19));r=decode(replies[-1])
    assert (r['startup_status'],r['state'],r['task'],r['polls'],r['capacity'],r['epoch'])==(4,g,0x7f00,5,0,0)
    for n in ('code_start','code_end','globals_start','globals_end'):assert r[n]==MANIFEST[n],n
    passed('idle_worker_polls_every_25_ticks_without_files_or_history_and_query_reports_it')

    # The tap through original DSP windows: 64 frames per callback, one epoch,
    # history equal to the pre-master mix, and no take beside stock recording.
    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2)
    t=TrialRig();t.sequence=0
    assert record(t,delay=2)==ordinary
    frames=word(t.m,STATE+OFF['frames']);blocks=frames//64
    assert frames==len(t.stream)//2 and word(t.m,STATE+OFF['epoch'])==1 and word(t.m,STATE+OFF['take'])==0
    assert t.step()==0 and not t.disk and not t.opened
    first=[bytes(t.raw(0x23100000+i*512,512)) for i in range(blocks)]
    expected=[struct.pack('<64f',*[v*2**31 for v in t.stream[128*i:128*i+128:2]])+
              struct.pack('<64f',*[v*2**31 for v in t.stream[128*i+1:128*i+128:2]]) for i in range(blocks)]
    assert first==expected
    passed('tap_fills_history_with_the_pre_master_mix_and_stock_recording_starts_no_take',
           callbacks=blocks,stock_files_identical=True)

    # Host acceptance (fixture values; not a claim about the physical boot).
    sample=dict(r,state=0x808f2000,task=0x808f4000,capacity=223104,epoch=1,ccr=0x30000,
                free_bytes=140000,minimum_free_bytes=139000,ticks=1000,frames=480000,polls=40)
    later=dict(sample,ticks=2000,frames=528000,polls=80)
    assert validate_samples([sample,later],MANIFEST)['frames_per_tick']==48
    for field,value in (('epoch',2),('frames',600000),('take',1),('file_open',1),('worker_state',1),
                        ('startup_status',3),('code_end',0),('ccr',0),('task',0),('polls',40),('capacity',240000)):
        try:validate_samples([sample,dict(later,**{field:value})],MANIFEST)
        except ValueError:pass
        else:raise AssertionError('host accepted abnormal '+field)
    passed('host_acceptance_requires_48_frames_per_tick_one_epoch_idle_worker_and_exact_bounds')

    # Query hygiene and parser routing.
    m=boot();packet=request(19);bad=[packet[:-1],packet+b'\0']
    for i,v in ((0,0),(1,0),(2,1),(3,1),(4,0),(5,5),(6,128),(7,0)):
        q=bytearray(packet);q[i]=v;bad.append(bytes(q))
    for q in bad:
        before=len(m.replies);assert direct(m,q)==0 and len(m.replies)==before
    for state,ipsr in ((0,0),(1,0),(3,0),(2,16)):
        m.uc.reg_write(A.UC_ARM_REG_IPSR,ipsr);before=len(m.replies)
        assert direct(m,packet,state)==0 and len(m.replies)==before
    m.uc.reg_write(A.UC_ARM_REG_IPSR,0);writes=[]
    m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,x:writes.append(a),begin=MANIFEST['globals_start'],end=MANIFEST['globals_end']-1)
    assert direct(m,packet)==1;r=decode(m.replies[-1])
    assert r['token']==19 and r['state']==0 and r['startup_status']==0 and not writes
    assert len(m.replies[-1])==8+5*len(FIELDS)
    for pad in range(4):
        old=health.machine(False);new=boot()
        health.query(old,pad_request(0,pad));health.query(new,pad_request(0,pad))
        assert old.events==new.events and old.replies==new.replies
    passed('malformed_wrong_session_and_interrupt_queries_are_ignored_and_pad_requests_route_unchanged')

    out=ROOT/'analysis/simple_trial_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),cases=cases,trial_sha256=MANIFEST['trial_sha256'],
        limitations=MANIFEST['limitations']+['Task creation, scheduling and physical cache effects are modeled.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))
if __name__=='__main__':main()
