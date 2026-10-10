#!/usr/bin/env python3
"""Exact dormant full-payload image, native startup and fixed read-only query.

Kernel/task creation, scheduling and physical cache effects remain modeled.
No device access, staging or automatic capture release.
"""
import hashlib,json,struct,sys,subprocess,os,tempfile
from pathlib import Path
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import arm_const as A
from verify_pad_protocol import ROOT,IMAGE,BIAS,INPUT,RETURN,request as pad_request
from verify_firmware_workflow import put32
from verify_record_scheduler import word
from verify_scheduling_boundaries import stop
from verify_capture_composed import ComposedBoot
from verify_capture_boot_cache import run as continuous
from verify_native_worker import HANDLE
from verify_segmented_exchange import TAILS,TAIL_BYTES
from verify_memory_layout import HEAP_STATE
import verify_health_probe as health
from build_boot_probe import ELF,OUT,trial
from build_deployment_probe import validate
from capture_jump_patches import symbols,SCATTER
from plan_capture_packing import DECOMPRESS,ZERO
from scatter_codec import expand
sys.path.insert(0,str(ROOT/'tools/device'))
from l6_boot_probe import request,decode,validate_samples

TRIAL,MANIFEST,PACK,FULL=trial();N=symbols(ELF)
PLAN=dict(FULL,patches=MANIFEST['patches']);GLOBALS=tuple(FULL['packing']['globals'])

class DormantBoot(ComposedBoot):
    names=N;packed=PACK;patch_plan=PLAN;global_range=GLOBALS
    def guard(self):
        for a,n in ((GLOBALS[0]-8,8),(GLOBALS[1],16)):
            assert bytes(self.m.uc.mem_read(a,n))==PACK['source_blob'][a-SCATTER[0]:a-SCATTER[0]+n]

def boot(corrupt=False):
    m=health.machine(False);u=m.uc
    for a,n in ((0,0x1000),(0x81000000,0x1000000),(0x20210000,0x20000),(0xe000e000,0x1000)):
        u.mem_map(a,n)
    u.mem_write(0x80001000,TRIAL[0x200:0xb5ce4]);seen=[]
    if corrupt:u.mem_write(PACK['code_source'],b'\xff'*4)
    failed=PACK['names']['scatter_lz4_failed']&~1
    handles=[u.hook_add(UC_HOOK_CODE,lambda u,a,n,x:seen.append(a) or u.emu_stop(),begin=a,end=a)
             for a in (0x80067a60,failed)]
    u.emu_start(0x80001401,0x80067a62,count=100000000)
    for h in handles:u.hook_del(h)
    if corrupt:
        assert seen==[failed];return m
    assert seen==[0x80067a60]
    for at in range(0x800a68dc,0x800a695c,16):
        s,d,n,h=struct.unpack_from('<4I',IMAGE,at-BIAS)
        expected=bytes(n) if h==ZERO else expand(IMAGE[s-BIAS:],n)[0] if h==DECOMPRESS else IMAGE[s-BIAS:s-BIAS+n]
        assert bytes(u.mem_read(d,n))==expected,(hex(d),n)
    assert bytes(u.mem_read(N['placement_code_start'],len(PACK['code'])))==PACK['code']
    assert bytes(u.mem_read(GLOBALS[0],GLOBALS[1]-GLOBALS[0]))==bytes(GLOBALS[1]-GLOBALS[0])
    return m

def direct(m,packet,state=2):
    m.uc.mem_write(INPUT,struct.pack('<I',len(packet))+packet+bytes(16))
    m.uc.mem_write(0x80629b60,bytes([state]))
    return m.invoke(N['boot_probe_query'],[INPUT])

def main():
    cases=[]
    def passed(case,**details):cases.append(dict(case=case,**details))
    assert (OUT/'trial_dormant_boot/L6.BIN').read_bytes()==TRIAL;validate(TRIAL)
    assert TRIAL[0x2851f8:]==IMAGE[0x2851f8:] and len(TRIAL)==len(IMAGE)
    enabled={p['site'] for p in MANIFEST['patches']}
    assert len(enabled)==15 and len(PACK['code'])==MANIFEST['code_bytes']
    for p in FULL['patches']:
        if p['site'] not in enabled:
            at=p['site']-BIAS;assert TRIAL[at:at+len(bytes.fromhex(p['original']))]==bytes.fromhex(p['original'])
    assert PACK['dsp']==IMAGE[SCATTER[0]-BIAS:SCATTER[0]-BIAS+SCATTER[2]]
    passed('Exact image enables only startup/witness/closure/query and existing capacity; DSP/audio/control/SD hooks remain stock',
        trial_sha256=MANIFEST['trial_sha256'],code_bytes=MANIFEST['code_bytes'],globals_bytes=MANIFEST['globals_bytes'],
        spare_bytes=MANIFEST['spare_bytes'])
    with tempfile.TemporaryDirectory(prefix='l6-boot-layout-') as directory:
        source=Path(directory)/'size.S';output=Path(directory)/'size.elf'
        for code_size,global_size,valid in ((16,16,True),(0x7378,16,False),(16,0x784,False)):
            source.write_text('.syntax unified\n.thumb\n.section .text.extra_capture,"ax",%progbits\n'
                '.global extra_capture\n.thumb_func\nextra_capture:\n bx lr\n'+f'.space {code_size}\n'
                '.section .bss.fill,"aw",%nobits\n'+f'.space {global_size}\n')
            result=subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
                '-mcpu=cortex_m7','-nostdlib','-Wl,-T,tests/fixtures/capture_source_reuse.ld',
                str(source),'-o',str(output)],cwd=ROOT,capture_output=True,text=True,
                env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global'))
            assert (result.returncode==0)==valid,result.stderr
            if not valid:assert 'overflow' in result.stderr or 'exceed' in result.stderr,result.stderr
    passed('Bounded linker regions accept fitting code and reject code or globals that cross their limits')
    m=boot();boot(True)
    passed('Exact update image runs original reset/scatter with all eight stock destinations unchanged and full extra code/globals; corruption stops before Main')

    for ccr in (0,0x30000):
        result=continuous(ccr,boot_factory=DormantBoot,pack=PACK,names=N,globals_range=GLOBALS)
        passed('Continuous original scatter/cache/MPU/native dormant registration',**result)
    b=DormantBoot();b.boot();b.guard();before=b.word(HEAP_STATE+4)
    delayed=[];m=b.m
    def forbidden(*args):raise AssertionError('Dormant worker accessed manager/history')
    guards=[m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,forbidden,begin=b.manager,end=b.manager+2208-1)]
    guards += [m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,forbidden,begin=a,end=a+TAIL_BYTES-1) for a in TAILS]
    m.hooks[0x800770e8]=lambda a:HANDLE
    m.hooks[0x80074158]=lambda a:delayed.append(a[0]) or (stop(m) if len(delayed)==5 else 0)
    m.invoke(N['native_worker_entry'],[b.worker])
    for h in guards:m.uc.hook_del(h)
    assert delayed==[25]*5 and b.word(N['boot_probe_polls'])==5
    assert b.word(b.worker+8)==4 and b.word(HEAP_STATE+4)==before
    assert all(b.word(N[n])==0 for n in ('ct_active','emulator_bridge_current','sdp_source_port',
        'sdp_chunk_admit_port','sdp_chunk_finish_port','sdp_cache_read_port'))
    passed('Worker makes five counted sleeping passes without manager/history access, file calls, hook activation or further allocation')
    replies=[];m.hooks[0x80031648]=lambda a:replies.append(bytes(m.uc.mem_read(a[0],a[1]))) or 0
    direct(m,request(19));observed=decode(replies[-1])
    assert observed['arena']==b.arena() and observed['arena_bytes']==9887
    assert observed['worker_state']==4 and observed['worker_status']==0 and observed['manager_state']==4
    assert observed['worker_polls']==5 and observed['lease_control']==0
    # Host acceptance uses explicit kernel/boot/tick fixtures. These mutations
    # are not an assertion that the real Main boot or physical task ran here.
    first=dict(observed,boot_phase=9,worker_task=0x808f3000,ccr=0x30000,
               free_bytes=136000,minimum_free_bytes=135000,ticks=1000,worker_polls=20)
    last=dict(first,ticks=2000,worker_polls=60)
    assert validate_samples([first,last],MANIFEST)['worker_poll_delta']==40
    for field,value in (('boot_phase',10),('worker_state',2),('manager_state',0),('lease_control',1),
                        ('physical_ports_or',1),('active_hooks_or',1),('code_end',0),('ccr',0),
                        ('worker_polls',20),('worker_task',0)):
        try:validate_samples([first,dict(last,**{field:value})],MANIFEST)
        except ValueError:pass
        else:raise AssertionError('host accepted abnormal '+field)
    passed('Query reports real dormant arena/manager state; strict host acceptance rejects missing readiness, running capture, bad bounds or stalled worker')

    put32(m,N['storage_boot_phase'],9)
    put32(m,0x80446da4,0x7003);m.hooks[0x800770e8]=lambda a:0x7003
    m.hooks[0x80020690]=lambda a:m.uc.mem_write(a[0],struct.pack('<5I',2,0,0xa3,0,0)) or 0
    continued=[]
    h=m.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:continued.append(a) or stop(m),begin=0x8002c444,end=0x8002c444)
    try:m.invoke(0x8002c440,[0x20030000])
    finally:m.uc.hook_del(h)
    assert continued==[0x8002c444] and b.word(N['storage_boot_phase'])==10
    replies.clear();direct(m,request(19));observed=decode(replies[-1])
    assert observed['lease_control']==3 and observed['worker_state']==4 and observed['manager_state']==4
    passed('A real patched Main receive retires the dormant lease and resumes the original transition once without waiting or file work')

    for outcome in ('zero','negative','missing_handle'):
        b=DormantBoot(optional=outcome);b.boot();assert b.word(b.worker+8)==3
        assert b.word(N['ct_active'])==b.word(N['emulator_bridge_current'])==0
    b=DormantBoot(allocation_failure=True);b.boot();assert not b.arena() and b.kernel_entered
    passed('Optional allocation/task failures preserve native startup and keep capture closed')

    m=boot();reads=[];writes=[]
    m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda u,k,a,n,v,x:writes.append((a,n)),begin=GLOBALS[0],end=GLOBALS[1]-1)
    for token in (0,19,127):
        assert direct(m,request(token))==1
        r=decode(m.replies[-1]);assert r['token']==token and r['marker']==0x4c3701
        assert all(r[n]==0 for n in ('startup_status','boot_phase','arena','worker_state','worker_polls','physical_ports_or','active_hooks_or'))
        for key in ('code_start','code_end','globals_start','globals_end'):assert r[key]==MANIFEST[key]
    assert not writes
    # Observe live fields; do not normalize unexpected values into success.
    put32(m,N['storage_boot_phase'],10);put32(m,N['sdp_source_port'],0x1234);put32(m,N['boot_probe_polls'],37)
    direct(m,request(19));r=decode(m.replies[-1]);assert (r['boot_phase'],r['physical_ports_or'],r['worker_polls'])==(10,0x1234,37)
    passed('Fixed query reports actual publication bounds and live boot/worker/fault observations without mutable reply state')

    packet=request(19);bad=[packet[:-1],packet+b'\0']
    for i,v in ((0,0),(1,0),(2,1),(3,1),(4,0),(5,4),(6,128),(7,0)):
        q=bytearray(packet);q[i]=v;bad.append(bytes(q))
    for q in bad:
        before=len(m.replies);assert direct(m,q)==0 and len(m.replies)==before
    for state,ipsr in ((0,0),(1,0),(3,0),(2,16)):
        m.uc.reg_write(A.UC_ARM_REG_IPSR,ipsr);before=len(m.replies)
        assert direct(m,packet,state)==0 and len(m.replies)==before
    m.uc.reg_write(A.UC_ARM_REG_IPSR,0);direct(m,packet);reply=m.replies[-1]
    for i,v in ((6,128),(7,2),(11,16),(-1,0)):
        q=bytearray(reply);q[i]=v
        try:decode(bytes(q))
        except ValueError:pass
        else:raise AssertionError('bad reply accepted')
    passed('Malformed requests/replies, wrong session and interrupt context are rejected')

    m.hooks.pop(0x80031648);given=[];ring=0x8062ad84
    put32(m,0x8062cd84,8191);put32(m,0x8062cd8c,8192)
    put32(m,0x804468b4,0x7111);put32(m,0x80446924,0x7112)
    m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:given.append(a[0]) or 1
    health.query(m,packet)
    actual=bytes(m.uc.mem_read(ring+8191,1))+bytes(m.uc.mem_read(ring,len(reply)-1))
    assert actual==reply and given==[0x7111,0x7112]
    for pad in range(4):
        old=health.machine(False);new=boot()
        health.query(old,pad_request(0,pad));health.query(new,pad_request(0,pad))
        assert old.events==new.events and old.replies==new.replies
    passed('Original parser routes pad requests unchanged and native sender copies the full118-byte query across ring wrap')
    out=ROOT/'analysis/boot_probe_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(cases),cases=cases,manifest=MANIFEST,
        limitations=MANIFEST['limitations']+['Native task stacks/TCBs, scheduling and physical cache/controller behavior remain modeled.']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(cases),report=str(out))))
if __name__=='__main__':main()
