#!/usr/bin/env python3
"""Original mount/directories/detach evidence for capture-only storage admission.

Lower file/geometry/GPIO responses, callback arrival and RTOS tokens are models.
No readiness provider, firmware patch, physical I/O join or device operation.
"""
import hashlib,json,struct,sys
from unicorn import UC_HOOK_CODE,UC_PROT_NONE
from unicorn import arm_const as A
from verify_overdub_prototype import Emulator
from verify_pad_protocol import ROOT,IMAGE,REGS,RETURN
from verify_firmware_workflow import put32,VOLUME,HANDLE,BUFFER,TABLE,RESULT
from verify_storage_readiness import callees,word
from verify_record_catalogue import getstr
from verify_scheduling_boundaries import stop
sys.path.insert(0,str(ROOT/'tools/firmware'))
from audit_capture_storage import audit

REGISTRATION=0x801f8f58
NOT_FOUND=0xffffd75a;IO_ERROR=0xffffd825

class Mount:
    def __init__(self,present=True,phase=2,aux=0,geometry=(4096,3000,512,32),geometry_result=0):
        self.m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True);m=self.m
        m.uc.mem_protect(0x10000000,0x10000,UC_PROT_NONE)
        m.uc.mem_map(0xe000e000,0x1000)
        self.events=[];self.mount_results=[];self.messages=[];self.lookup_errors={};self.create_errors={}
        self.directory_default=NOT_FOUND;self.mounting=False
        self.directory_checks=[];self.directory_creates=[]
        # Actual card-presence predicate executes; only its GPIO read is modeled.
        m.hooks[0x80032ad8]=lambda a:int(present)
        def notified(a):self.events.append(('notification',*a[:2]));return 0
        m.hooks[0x2103f000]=notified;put32(m,0x802350e4,0x2103f001)
        def geometry_query(a):
            assert a[0]==0x41
            self.events.append(('geometry',geometry_result))
            if geometry is not None:m.uc.mem_write(a[1],struct.pack('<4I',*geometry))
            return geometry_result
        m.hooks[0x8005e958]=geometry_query
        m.hooks[0x8005d8e8]=self.find
        m.hooks[0x8005d728]=lambda a:0
        m.hooks[0x8005e708]=lambda a:0
        m.hooks[0x8005e718]=lambda a:0
        m.hooks[0x8005f3d0]=self.mkdir
        m.hooks[0x8005bb08]=lambda a:self.events.append(('change_directory',getstr(m,a[0]))) or 0
        # Model callback arrival at the stock mount's delay. Execute the real
        # status setter with modeled arguments and the original delay LR.
        def arrive(uc,pc,n,u):
            assert uc.reg_read(REGS[0])==100
            self.events.append(('delay',word(m,REGISTRATION)&0xff))
            if self.mounting and phase is None:return stop(m)
            delivered=phase if self.mounting else 0 # modeled detach completion
            uc.reg_write(REGS[0],1);uc.reg_write(REGS[1],aux);uc.reg_write(REGS[2],delivered)
            uc.reg_write(A.UC_ARM_REG_PC,0x8004bd99)
        m.uc.hook_add(UC_HOOK_CODE,arrive,begin=0x80077686,end=0x80077686)
        # Error-reinitialization path: actual branching, modeled board/driver
        # reconfiguration. Its returns are deliberately errors in the tests.
        for fn in (0x80052f08,0x80026b90,0x80068318,0x8001bcd8,0x8001bc98,
                   0x800684b8,0x8006e4a8,0x80026bf0,0x800614b0,0x80052ce0):
            m.hooks[fn]=lambda a,fn=fn:self.events.append(('reconfigure',hex(fn))) or IO_ERROR
        def entering(uc,pc,n,u):self.mounting=True
        def finished(uc,pc,n,u):
            self.mount_results.append(uc.reg_read(REGS[0]));self.mounting=False
        m.uc.hook_add(UC_HOOK_CODE,entering,begin=0x8005fc98,end=0x8005fc98)
        for pc in (0x8005fcd6,0x8005fce4,0x8005fdc0):
            m.uc.hook_add(UC_HOOK_CODE,finished,begin=pc,end=pc)

    def find(self,a):
        path=getstr(self.m,a[0]);self.events.append(('find',path,a[1]))
        if self.mounting:return NOT_FOUND # modeled volume label/directory enumeration
        self.directory_checks.append(path)
        return self.lookup_errors.get(path,self.directory_default)

    def mkdir(self,a):
        path=getstr(self.m,a[0]);self.directory_creates.append(path)
        return self.create_errors.get(path,0)

    def mount(self):return self.m.invoke(0x8005fc98,[0x41])
    def status(self):return self.m.invoke(0x8005ec00,[0x41])
    def setup(self):
        m=self.m
        keep={0x8005fc98,0x8000ac80,0x8000ac70,0x80002d80,0x80002ec8,0x80008d68,0x80062230}
        for fn in callees(0x80009a40,0x80009b18)-keep:m.hooks[fn]=lambda a:0
        m.hooks[0x8000bad0]=lambda a:0x21008000
        m.hooks[0x80076950]=lambda a:1;m.hooks[0x800763d8]=lambda a:1
        put32(m,0x801f8f3c,0x6543)
        def send(a):
            assert a[0]==0x6543
            self.messages.append(bytes(m.uc.mem_read(a[1],32)));return 0
        m.hooks[0x800483f8]=send
        return m.invoke(0x80009a40,[2])

class Write:
    def __init__(self):
        self.m=Emulator(cpu_model=A.UC_CPU_ARM_CORTEX_M7,mclass=True);m=self.m
        m.uc.mem_protect(0x10000000,0x10000,UC_PROT_NONE)
        self.tokens=set();self.locks=[];self.arguments=[]
        self.task=0x21030000
        m.uc.mem_write(HANDLE,bytes([0x40,1]));put32(m,HANDLE+0x230,VOLUME)
        m.uc.mem_write(VOLUME+0x206,b'\x01');put32(m,VOLUME+0x258,TABLE)
        m.uc.mem_write(BUFFER,b'\x5a'*512)
        for slot,token in ((0x801f8da4,0x7101),(0x801f8da8,0x7102)):put32(m,slot,token)
        m.hooks[0x800770e8]=lambda a:self.task
        m.hooks[0x80001848]=lambda a:0
        def take(a):
            assert a[0] not in self.tokens
            self.tokens.add(a[0]);self.locks.append(('take',a[0]));return 1
        def give(a):
            assert a[0] in self.tokens
            self.tokens.remove(a[0]);self.locks.append(('give',a[0]));return 1
        m.hooks[0x80076950]=take;m.hooks[0x800763d8]=give
        def pending(a):
            assert self.tokens=={0x7101}
            self.arguments.append(tuple(a[:4]));return stop(m)
        m.hooks[0x800624a8]=pending
        # Healthy-looking registration status while file work is in flight.
        m.uc.mem_write(REGISTRATION,bytes([2,0,2,0])+b'\xa5'*0x30)
        m.hooks[0x80068508]=lambda a:0
        m.hooks[0x80077686]=lambda a:stop(m) # callback progress deliberately withheld
        put32(m,0x802350e4,0)

    def begin(self):self.m.invoke(0x800622b0,[HANDLE,BUFFER,512,RESULT])
    def finish(self,result=0,actual=512):
        m=self.m;put32(m,RESULT,actual)
        m.uc.reg_write(REGS[0],result);m.reached_return=False
        # Continue the retained public-write frame after the modeled driver
        # result. This models software return, not a physical transfer join.
        pc=m.uc.reg_read(A.UC_ARM_REG_PC)
        assert pc==0x80062464
        m.uc.emu_start(pc|1,RETURN+2,count=100000)
        assert m.reached_return
        return m.uc.reg_read(REGS[0])
    def detach(self):
        m=self.m;context=m.uc.context_save();old_stack=getattr(m,'stack',0x20010000)
        # Simulate another task on its separate stack while the write frame and
        # domain token remain live. No physical preemption is claimed.
        m.stack=0x20030000
        try:m.invoke(0x80062230,[0x41])
        finally:m.stack=old_stack;m.uc.context_restore(context)

    def getters(self):
        m=self.m;context=m.uc.context_save();old_stack=getattr(m,'stack',0x20010000)
        m.stack=0x20030000
        try:return m.invoke(0x8000ac80,[]),m.invoke(0x8000ac70,[])
        finally:m.stack=old_stack;m.uc.context_restore(context)

def main():
    cases=[]
    def passed(case,**data):cases.append(dict(case=case,**data))
    r=Mount();assert r.mount()==2 and r.status()==2 and r.mount_results==[2]
    assert r.m.uc.mem_read(REGISTRATION,3)==b'\x02\x00\x02'
    assert struct.unpack('<5I',r.m.uc.mem_read(REGISTRATION+4,20))==(16384,67108864,0,49152000,0)
    assert r.m.invoke(0x8000ac80,[])==1 and r.m.invoke(0x8000ac70,[])==0
    passed('actual_mount_publishes_geometry_and_supported_status_two',geometry_fixture=[4096,3000,512,32])

    r=Mount(present=False)
    assert r.status()==0 and r.m.invoke(0x8000ac80,[])==1 and r.m.invoke(0x8000ac70,[])==0
    assert not r.mount_results # zero-initialized status is not a completed mount
    assert r.setup()==0 and r.mount_results==[1]
    assert r.status()==1 and not r.messages and not r.directory_checks
    r=Mount(phase=0);assert r.mount()==1 and r.status()==1
    r=Mount(phase=None);r.mount()
    assert not r.mount_results and r.m.uc.mem_read(REGISTRATION,1)==b'\xff'
    passed('actual_absent_callback_failure_and_unfinished_mount_are_distinct_from_supported_mount')

    r=Mount(geometry=(4096,3000,512,64));assert r.mount()==10 and r.status()==10
    assert r.m.invoke(0x8000ac80,[])==1 and r.m.invoke(0x8000ac70,[])==1
    r=Mount(geometry=None,geometry_result=IO_ERROR);result=r.mount()
    assert result&8 and bytes(r.m.uc.mem_read(REGISTRATION+4,20))==bytes(20)
    r=Mount(aux=1);assert r.mount()==1 and any(e[0]=='reconfigure' for e in r.events)
    assert r.status()==1
    passed('unsupported_geometry_geometry_failure_and_reconfiguration_failure_do_not_supply_readiness')

    r=Mount();assert r.setup()==0 and r.mount_results==[2]
    assert r.directory_creates==['A:\\RECORDER','A:\\SOUND_PAD',*[f'A:\\SOUND_PAD\\PAD{i}' for i in range(1,5)]]
    assert len(r.messages)==1 and struct.unpack_from('<I',r.messages[0])[0]==0x80049da1
    assert word(r.m,0x807348cc)==1
    passed('actual_mount_and_directory_creation_finish_before_deferred_reload_submission')

    for path in ('A:\\RECORDER',*[f'A:\\SOUND_PAD\\PAD{i}' for i in range(1,5)]):
        r=Mount();r.create_errors[path]=IO_ERROR
        assert r.setup()==0xffffffff and not r.messages
        assert r.status()==1 # directory failure follows actual detach
    passed('recorder_or_each_pad_directory_create_failure_aborts_setup_before_reload')

    r=Mount();r.create_errors['A:\\SOUND_PAD']=IO_ERROR
    assert r.setup()==0 and r.mount_results==[2] and len(r.messages)==1
    assert 'A:\\SOUND_PAD' in r.directory_creates
    passed('pad_directory_setup_ignores_root_create_failure_if_later_modeled_pad_operations_succeed',
        limitation='Injected independent directory responses; not a claim that the root was absent on a real card')

    r=Mount();r.directory_default=IO_ERROR
    assert r.setup()==0 and not r.directory_creates and len(r.messages)==1
    assert len(r.directory_checks)==6
    passed('directory_lookup_errors_other_than_not_found_are_not_preserved_by_setup',
        limitation='All modeled lookups fail; original path constructors and branches execute')

    r=Write();r.begin();assert r.tokens=={0x7101} and len(r.arguments)==1
    held_frame=bytes(r.m.uc.mem_read(0x2000fe00,512));r.detach()
    assert r.tokens=={0x7101} and r.locks==[('take',0x7101)]
    assert bytes(r.m.uc.mem_read(REGISTRATION+4,0x30))==bytes(0x30)
    assert r.m.uc.mem_read(REGISTRATION,3)==b'\x02\x00\x02'
    assert bytes(r.m.uc.mem_read(0x2000fe00,512))==held_frame
    assert r.getters()==(1,0)
    passed('file_domain_lock_and_healthy_volume_bits_do_not_exclude_detach_registration_mutation',
        limitation='Suspended file driver and other-task scheduling are fixtures; no DMA or physical removal')

    for status,actual in ((0,512),(IO_ERROR,0)):
        r=Write();r.begin();assert r.tokens=={0x7101}
        assert r.finish(status,actual)==status and word(r.m,RESULT)==actual
        assert r.locks==[('take',0x7101),('give',0x7101)] and not r.tokens
        assert word(r.m,0x801f8df0)==0
    passed('public_write_retires_task_context_and_domain_after_both_modeled_success_and_error',
        limitation='Driver status/count are supplied; software return proves neither SD/DMA completion nor cancellation')

    from verify_capture_integration import IntegrationRig
    from verify_native_worker import WORKER
    r=IntegrationRig();assert r.boot(release=False)==0 and word(r.m,WORKER+8)==4
    r.m.uc.mem_write(REGISTRATION+2,b'\x01') # unavailable volume
    r.m.uc.mem_write(0x80212e00,b'\x01') # modeled USB active byte
    calls=list(r.calls)
    assert r.release()==0 and word(r.m,WORKER+8)==2 and r.calls==calls
    passed('worker_release_is_an_authorization_endpoint_and_does_not_detect_storage_readiness',
        limitation='Negative control: no worker polling or file calls after deliberate unauthorized release; production caller remains unwired')

    inventory=audit();assert inventory['status']=='storage_release_unbound'
    assert inventory['targets']['mount']['direct_references']
    assert inventory['targets']['detach']['direct_references']
    passed('bounded_transition_inventory_leaves_storage_release_unbound')
    out=ROOT/'analysis/capture_storage_verification.json'
    out.write_text(json.dumps(dict(passed=True,groups=len(cases),results=cases,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=inventory['limitations']+[
            'Stock mount, status callback/getters, directory constructors/setup and public write lock/context code execute',
            'GPIO/geometry/enumeration/mkdir responses, callback arrival, RTOS token effects and file driver are models',
            'Capture core is unchanged; no release, normal-file writes, native gate or hardware completion guarantee']),indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))

if __name__=='__main__':main()
