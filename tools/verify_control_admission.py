#!/usr/bin/env python3
"""Original effect handlers/import table and candidate admission boundaries.

Kernel lock/wakeup and plug-in bodies are explicit models. Original handlers,
import initialization, mode setters and full audio callbacks execute unchanged.
"""
import hashlib,json
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_LR,UC_ARM_REG_R0,UC_ARM_REG_R1
from verify_pad_reader_audit import AuditRig,SELECTOR
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,RETURN,REGS

TABLE=0x80440cdc
EFFECT=0x8053d190
LOCK_SLOT=0x80446818
HANDLE=0x21036000
PLUGIN=0x21000280
WAIT=0x80076950
SIGNAL=0x800763d8
class ControlRig(AuditRig):
    def __init__(self):
        super().__init__();self.events=[];self.held=False;self.suspended=False
        self.lock_result=1;self.acquired=False;self.plugin_result=0
        self.m.invoke(0x8001dc10,[])
        put32(self.m,LOCK_SLOT,HANDLE)
        put32(self.m,EFFECT+0x14,PLUGIN|1);put32(self.m,EFFECT+0x18,PLUGIN|1)
        put32(self.m,EFFECT+0x1c,100);put32(self.m,EFFECT+0x20,100)
        self.m.hooks[0x8006f840]=lambda a:self.events.append(('update',*a[:3])) or 0
        self.m.hooks[PLUGIN]=self.plugin
        self.m.hooks[SIGNAL]=self.signal
        self.m.uc.hook_add(UC_HOOK_CODE,self.wait,begin=WAIT,end=WAIT)
    def wait(self,uc,a,n,u):
        args=[uc.reg_read(reg) for reg in REGS]
        assert args[:2]==[HANDLE,0xffffffff],args
        if self.held:
            self.suspended=True;self.events.append(('suspend',))
            # Stop this fixture CPU at the wait instruction WITHOUT returning
            # from wait or resetting its stack. Reached_return only satisfies
            # the generic invoke helper; this class separately tracks suspension.
            self.m.reached_return=True;uc.emu_stop();return
        self.suspended=False;self.events.append(('wait_return',self.lock_result))
        self.acquired=self.lock_result==1
        uc.reg_write(UC_ARM_REG_R0,self.lock_result)
        uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    def plugin(self,a):
        assert a[:2]==[0x80446944,TABLE]
        assert self.word(TABLE+0x2c)==0x8005b741 and self.word(TABLE+0x30)==0x8005b791
        self.events.append(('plugin',self.acquired))
        return self.plugin_result
    def signal(self,a):
        assert a[:4]==[HANDLE,0,0,0]
        self.events.append(('give',self.acquired));self.acquired=False;return 1
    def start_handler(self,fn,value=37):
        self.m.invoke(fn,[0,value]);return not self.suspended
    def resume(self):
        assert self.suspended and not self.held
        pc=self.m.uc.reg_read(UC_ARM_REG_PC);assert pc==WAIT
        self.m.reached_return=False
        self.m.uc.emu_start(pc|1,RETURN+2,count=100000000)
        assert self.m.reached_return and not self.suspended

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    r=ControlRig()
    assert r.m.invoke(0x8001dc00,[])==TABLE
    assert r.word(TABLE+0x2c)==0x8005b741 and r.word(TABLE+0x30)==0x8005b791
    passed('original_initializer_and_getter_recover_effect_import_table_and_copy_slots',table=hex(TABLE),slots=['+0x2c','+0x30'])

    for fn,index in ((0x8000e748,2),(0x8000e7b0,3)):
        r=ControlRig();assert r.start_handler(fn)
        assert r.events==[('wait_return',1),('update',0,index,37),('plugin',True),('give',True)]
    passed('both_parameter_handlers_acquire_shared_effect_lock_before_updates_and_imported_plugin_call')

    for fn,index in ((0x8000e748,2),(0x8000e7b0,3)):
        r=ControlRig();r.held=True
        before=r.raw(EFFECT,0x24)
        assert not r.start_handler(fn,91) and r.events==[('suspend',)]
        assert r.raw(EFFECT,0x24)==before and not r.acquired
        # Run real audio on a separate CPU while the control task waits. No
        # modeled lock acquisition is called from this baseline audio fixture.
        peer=AuditRig();peer.seed(length=17);calls=[]
        peer.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:calls.append(a),begin=WAIT,end=WAIT)
        peer.full();assert not calls
        r.held=False;r.resume()
        assert r.events==[('suspend',),('wait_return',1),('update',0,index,91),('plugin',True),('give',True)]
    passed('suspending_at_real_lock_wait_preserves_caller_arguments_and_defers_all_observed_handler_mutations_while_audio_runs')

    r=ControlRig();r.lock_result=0;assert r.start_handler(0x8000e748)
    assert r.events==[('wait_return',0),('update',0,2,37),('plugin',False),('give',False)]
    passed('negative_control_returning_failed_lock_status_does_not_defer_original_handler',
           implication='Existing caller ignores wait result; a try-lock BUSY result cannot be returned as a replacement for waiting')

    for result in (1,0xffffffff):
        r=ControlRig();r.plugin_result=result;assert r.start_handler(0x8000e748)
        assert r.events[-1]==('give',True)
    passed('plugin_error_like_return_values_are_not_a_verified_retry_or_deferral_protocol')

    r=ControlRig();r.held=True;put32(r.m,SELECTOR,0x2022a791)
    r.m.invoke(0x8000cab0,[])
    assert r.word(SELECTOR)==0x800133e9 and not r.events
    passed('effect_lock_alone_does_not_exclude_original_audio_mode_setter')

    # Original mode workflow: model only its other subsystem calls and watch
    # what has already happened when it reaches the actual mode setter.
    for fn,prefix in ((0x80006ca8,[0x8002fa18,0x80007ff8]),
                      (0x80006fc8,[0x8002fba8,0x8002fa18,0x80007ff8])):
        r=ControlRig();events=[]
        for target in (0x8002fba8,0x8002fa18,0x80007ff8,0x800060b8,0x80006098,0x80002388,0x8001e4d8):
            r.m.hooks[target]=lambda a,target=target:events.append(target) or 0
        r.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:events.append('mode_store'),begin=0x8000cab0,end=0x8000cab0)
        r.m.invoke(fn,[])
        assert events[:len(prefix)+1]==prefix+['mode_store'] and r.word(SELECTOR)==0x800133e9
    passed('two_mode_workflows_already_call_other_subsystems_before_selector_store',
           implication='Deferring only the final store would pause a partially applied workflow; candidate admission is before whole handler entry')

    r=ControlRig();r.held=True;events=[]
    r.m.hooks[0x800494c0]=lambda a:events.append(r.word(SELECTOR)) or 0
    r.m.invoke(0x8001d968,[])
    assert events==[0x80010961] and not r.events
    passed('opposite_mode_handler_changes_selector_before_following_subsystem_call_without_effect_lock')

    # Show why an already admitted parameter-copy operation needs audio progress.
    # Stop at the first original poll; do not fake completion or let the harness
    # spin through its generic 100-million instruction limit.
    r=ControlRig();source=0x21037000;dest=0x21038000
    r.m.uc.mem_write(source,bytes(range(16)));polls=[]
    def pending(uc,a,n,u):
        polls.append((r.word(0x80445308),r.word(0x8044530c)))
        r.m.reached_return=True;uc.emu_stop()
    r.m.uc.hook_add(UC_HOOK_CODE,pending,begin=0x8005b776,end=0x8005b776)
    r.m.invoke(0x8005b740,[dest,source,16])
    assert polls==[(dest,4)] and r.raw(dest,16)==bytes(16)
    passed('admitted_deferred_copy_retains_pending_work_until_audio_consumer_runs',
           implication='Join existing controls while audio continues; stopping audio first would prevent this call from completing')

    out=ROOT/'analysis/control_admission_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
      limitations=['Kernel lock blocking/wakeup and imported plug-in bodies modeled; not device scheduler validation',
        'Actual import table and original handlers/mode setters execute; deep mode-workflow subsystem calls are stubs',
        'No proof of every imported callback caller, active effects processor, hardware task priority or complete mode ingress',
        'No new fence installed; original synchronous calls must not be silently dropped or reported complete']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
