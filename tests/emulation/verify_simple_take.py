#!/usr/bin/env python3
"""Exact simplified-capture take trial image (experiment 20), offline only.

Original reset/scatter/startup, DSP windows, stock recording and the Editor
parser execute. Task creation, scheduling and cache effects are modeled.
"""
import json,struct,sys,tempfile
from pathlib import Path
from unicorn import UC_HOOK_CODE
from verify_simple_capture import SimpleRig,SimpleBoot,STATE,take
from verify_capture_integration import IntegrationRig,record
from verify_extra_capture import STREAMS
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT
from verify_record_scheduler import word
from verify_scheduling_boundaries import stop
from verify_uncompressed_tap import packed
import verify_health_probe as health
from build_simple_trial import trial,MODES
from build_deployment_probe import validate
from capture_jump_patches import SCATTER
from plan_capture_packing import DECOMPRESS,ZERO
from scatter_codec import expand
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_simple_probe import request,decode,validate_samples,validate_take,TAKE_FIELDS,PAINTED
from analyze_capture_take import analyze

IMAGE20,MANIFEST,T=trial('take');TP=T['pack'];TN=TP['names'];OUT=MODES['take']['out']

class TakeRig(SimpleRig):
    plan,pack,names=T,TP,TN
    def query(self):
        replies=[];self.m.hooks[0x80031648]=lambda a:replies.append(bytes(self.m.uc.mem_read(a[0],a[1]))) or 0
        self.m.uc.mem_write(INPUT,struct.pack('<I',8)+request(7)+bytes(16));self.m.uc.mem_write(0x80629b60,b'\x02')
        assert self.m.invoke(TN['sc_query'],[INPUT])==1
        return decode(replies[-1])
class TakeBoot(SimpleBoot):
    plan,pack,names=T,TP,TN

def boot():
    m=health.machine(False);u=m.uc
    for a,n in ((0,0x1000),(0x81000000,0x1000000),(0x20210000,0x20000),(0xe000e000,0x1000)):u.mem_map(a,n)
    u.mem_write(0x80001000,IMAGE20[0x200:0xb5ce4]);seen=[]
    h=u.hook_add(UC_HOOK_CODE,lambda u,a,n,x:seen.append(a) or u.emu_stop(),begin=0x80067a60,end=0x80067a60)
    u.emu_start(0x80001401,0x80067a62,count=100000000);u.hook_del(h)
    assert seen==[0x80067a60]
    for at in range(0x800a68dc,0x800a695c,16):
        s,d,n,helper=struct.unpack_from('<4I',IMAGE,at-BIAS)
        if d==SCATTER[1]:expected=TP['dsp']
        else:expected=bytes(n) if helper==ZERO else expand(IMAGE[s-BIAS:],n)[0] if helper==DECOMPRESS else IMAGE[s-BIAS:s-BIAS+n]
        assert bytes(u.mem_read(d,n))==expected,(hex(d),n)
    assert bytes(u.mem_read(MANIFEST['code_start'],len(TP['code'])))==TP['code']
    g=MANIFEST['globals_start'],MANIFEST['globals_end']
    assert bytes(u.mem_read(g[0],g[1]-g[0]))==bytes(g[1]-g[0])

def main():
    cases=[]
    def passed(case,**details):cases.append(dict(case=case,**details))

    assert (OUT/'trial_simple_take/L6.BIN').read_bytes()==IMAGE20;validate(IMAGE20)
    assert len(IMAGE20)==len(IMAGE) and IMAGE20[0x2851f8:]==IMAGE[0x2851f8:]
    adapters=sorted(p.get('adapter','size') for p in MANIFEST['patches'])
    assert len(MANIFEST['patches'])==11 and len(MANIFEST['DSP_patches'])==2 and adapters.count('sc_main_receive')==5
    assert {'sc_admit_hook','sc_stop_hook','health_parser','startup_init_hook','startup_idle_hook','size'}<=set(adapters)
    assert MANIFEST['files_created'] and MANIFEST['experiment']==20
    passed('exact_image_has_all_twelve_capture_sites_plus_the_status_query',
           trial_sha256=MANIFEST['trial_sha256'],code_bytes=MANIFEST['code_bytes'],
           globals_bytes=MANIFEST['globals_bytes'],spare_bytes=MANIFEST['spare_bytes'])

    boot()
    passed('original_reset_and_scatter_expand_the_take_image_into_the_reused_span')

    b=TakeBoot();b.boot();g=b.word(TN['sc_state']);mm=b.m
    assert b.created==[b'L6Capture\0'] and b.word(TN['sc_startup_status'])==4
    assert b.added_writes and all(MANIFEST['globals_start']<=a and a+n<=MANIFEST['globals_end'] for a,n in b.added_writes)
    # Worker entry paints 15 KiB below its frame once; the query measures use.
    delays=[];mm.hooks[0x80074158]=lambda a:delays.append(a[0]) or (stop(mm) if len(delays)==3 else 0)
    mm.invoke(TN['sc_worker_entry'],[0])
    low,high=b.word(TN['sc_stack_low']),b.word(TN['sc_stack_high'])
    assert delays==[25]*3 and high-low==PAINTED-128-((high+128)&3)
    replies=[];mm.hooks[0x80031648]=lambda a:replies.append(bytes(mm.uc.mem_read(a[0],a[1]))) or 0
    mm.uc.mem_write(INPUT,struct.pack('<I',8)+request(9)+bytes(16));mm.uc.mem_write(0x80629b60,b'\x02')
    assert mm.invoke(TN['sc_query'],[INPUT])==1;r=decode(replies[-1])
    assert r['schema']==2 and r['state']==g and r['polls']==3 and 128<=r['stack_used']<1024
    assert len(replies[-1])==8+5*len(TAKE_FIELDS)
    sample=dict(r,state=0x808f2000,task=0x808f4000,capacity=223104,epoch=1,ccr=0x30000,revoked=3,
                free_bytes=140000,minimum_free_bytes=139000,ticks=1000,frames=480000,polls=40)
    assert validate_samples([sample,dict(sample,ticks=2000,frames=528000,polls=80)],MANIFEST)
    for field,value in (('stack_used',0),('stack_used',PAINTED),('schema',1)):
        try:validate_samples([sample,dict(sample,ticks=2000,frames=528000,polls=80,**{field:value})],MANIFEST)
        except ValueError:pass
        else:raise AssertionError('host accepted abnormal '+field)
    passed('startup_registers_and_the_query_reports_the_painted_worker_stack',stack_used=r['stack_used'])

    # A whole take through the exact build: stock files identical, extra exact,
    # the query records it and the host checks and analysis tool accept it.
    baseline=IntegrationRig(enabled=False);ordinary=record(baseline,delay=2)
    t=TakeRig();t.audio_call();before=t.query();t.sequence=0 # hardware is already in epoch 1
    assert take(t,delay=2)==ordinary
    after=t.query();start,stop_=after['start'],after['stop']
    assert t.extra()[512:]==packed(t.expected_extra)==t.premaster(start,stop_)
    result=validate_take(dict(before,stack_used=200),dict(after,stack_used=200))
    assert result['frames']==24*64 and after['completed']==1 and after['bytes']==24*64*8
    for field,value in (('completed',0),('last_status',5),('file_open',1),('bytes',8)):
        try:validate_take(dict(before,stack_used=200),dict(after,stack_used=200,**{field:value}))
        except ValueError:pass
        else:raise AssertionError('take check accepted abnormal '+field)
    with tempfile.TemporaryDirectory() as d:
        take_dir=Path(d)/'261011_000000';take_dir.mkdir()
        names={10:'MASTER.WAV'}
        for index,ch in STREAMS:
            name=names.get(index,f'TRACK{index+1:02d}.WAV');(take_dir/name).write_bytes(bytes(t.files[t.handles[index]]))
        extra=Path(d)/'OD.TMP';extra.write_bytes(t.extra())
        report=analyze(extra,take_dir,expected_lag=0) # the harness omits the stock master body delay
    assert report['passed'] and report['frames_equal'] and report['correlation']>.999
    passed('capture_take_beside_byte_identical_stock_files_passes_host_take_check_and_analysis',
           frames=result['frames'],correlation=report['correlation'])

    out=ROOT/'analysis/simple_take_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),cases=cases,trial_sha256=MANIFEST['trial_sha256'],
        limitations=MANIFEST['limitations']+['Task creation, scheduling and physical cache effects are modeled.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))
if __name__=='__main__':main()
