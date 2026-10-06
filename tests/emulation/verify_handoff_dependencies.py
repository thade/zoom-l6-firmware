#!/usr/bin/env python3
"""Same-CPU checked handoff + native SD dependency audit, entirely offline.
A synthetic sector router replaces the logical filesystem driver boundary.
File bytes, sector mapping, MMIO completion and kernel scheduling are modeled.
"""
import importlib.util,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP
from verify_handoff_locks import Locks,FS1,SCRATCH,word
from verify_sd_transfer_lifetime import TABLE,UNIT,CARD,HOST,EVENT,EXPECTED
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,REGS
from verify_scheduling_boundaries import stop

UI_TOKEN=0x7e10;UNIT_TOKEN=0x7e20;EVENT_TOKEN=0x7e21
READ_BYTES=0x2102bf00;WRITE_BYTES=0x2102bf04

class Dependencies(Locks):
    def __init__(self):
        super().__init__();m=self.m
        self.sd_calls=[];self.sd_waits=[];self.event_takes=[];self.unit_held=False
        self.current_io=None;self.pending_stage=None;self.timeout_once=False
        self.ui_attempts=[];self.irq_wakes=[];self.blocked_event=False
        assert m.invoke(0x80001994,[0x800a6980,0x801f5400,0x3780])==0
        assert list(struct.unpack('<11I',m.uc.mem_read(TABLE,44)))==EXPECTED
        for base in (0x402c0000,0x400fc000,0xe000e000):m.uc.mem_map(base,0x1000)
        m.uc.mem_write(UNIT+4,b'\x01');put32(m,UNIT+8,UNIT_TOKEN)
        m.uc.mem_write(CARD+4,b'\0\x02');m.uc.mem_write(0x802142b4,b'\x01')
        put32(m,HOST+4,EVENT);put32(m,EVENT,EVENT_TOKEN)
        put32(m,EVENT+4,0);put32(m,EVENT+8,0)
        put32(m,0x80446810,UI_TOKEN)
        put32(m,0x402c0010,0x100)
        m.hooks[READ_BYTES]=self.read;m.hooks[WRITE_BYTES]=self.write
        for native,shim in ((0x80060818,'dependency_read'),(0x800624a8,'dependency_write')):
            m.hooks.pop(native,None)
            m.uc.mem_write(native,struct.pack('<2I',0xf000f8df,self.syms[shim]|1))
            m.uc.ctl_remove_cache(native,native+8)
            def io(uc,addr,size,user):
                self.current_io=(2 if addr==0x80060818 else 3,uc.reg_read(REGS[1]),uc.reg_read(REGS[2]))
            m.uc.hook_add(UC_HOOK_CODE,io,begin=native,end=native)
        m.hooks[0x80076950]=self.take_token;m.hooks[0x800763d8]=self.give_token
        m.hooks.pop(0x800328c0,None)
        # Native event predicate runs; timer/critical/kernel endpoints are fixtures.
        m.hooks[0x80074580]=lambda a:put32(m,a[0],0) or 0
        m.hooks[0x80076bc8]=lambda a:0 # modeled deadline has not expired
        m.hooks[0x80073ec8]=m.hooks[0x80073f18]=lambda a:0
        m.hooks[0x80032250]=lambda a:0
        m.hooks[0x80076628]=lambda a:self.irq_wakes.append(a[0]) or 0
        def sd_entry(uc,addr,size,user):
            assert FS1 in self.tokens and self.current_io
            raw=bytes(uc.mem_read(uc.reg_read(REGS[0]),20))
            self.sd_calls.append((raw[0],*struct.unpack_from('<3I',raw,8)))
        m.uc.hook_add(UC_HOOK_CODE,sd_entry,begin=0x80068378,end=0x80068378)
        def wait_entry(uc,addr,size,user):
            mask=uc.reg_read(REGS[1])
            # Fifth argument is still on the native caller's stack.
            timeout=word(m,uc.reg_read(UC_ARM_REG_SP))
            assert self.unit_held and FS1 in self.tokens
            assert uc.reg_read(REGS[0])==EVENT and mask in (0x183,0x185) and timeout==5000
            self.sd_waits.append((self.current_io,mask,sorted(self.tokens)))
            initial=0x80735b80<=self.current_io[1]<0x8077c580
            pending=(initial and self.pending_stage==('command' if mask==0x183 else 'data'))
            put32(m,EVENT+8,0 if pending else (2 if mask==0x183 else 4))
            # Fixture can stop at a pending native event wait; it never invokes Main.
        m.uc.hook_add(UC_HOOK_CODE,wait_entry,begin=0x800328c0,end=0x800328c0)
        def unexpected(a):raise AssertionError('handoff attempted Main event service')
        for address in (0x8006e4b8,0x80020ca0,0x80020548,0x80020690,0x8002d568):
            m.hooks[address]=unexpected
    def take_token(self,a):
        token=a[0]
        if token==UI_TOKEN:
            self.ui_attempts.append('take');return stop(self.m)
        if token==UNIT_TOKEN:
            assert a[1]==0xffffffff and not self.unit_held and FS1 in self.tokens
            self.unit_held=True;return 1
        if token==EVENT_TOKEN:
            self.event_takes.append(a[1])
            if a[1]:
                self.blocked_event=True
                if self.timeout_once:
                    self.timeout_once=False;return 0
                return stop(self.m)
            return 1
        return super().take_token(a)
    def give_token(self,a):
        if a[0]==UI_TOKEN:raise AssertionError('handoff released another task\'s UI mutex')
        if a[0]==UNIT_TOKEN:
            assert self.unit_held;self.unit_held=False;return 1
        return super().give_token(a)
    def leave(self,a):
        assert not self.unit_held
        return super().leave(a)

def main():
    cases=[]
    def passed(name):cases.append(name)
    spec=importlib.util.spec_from_file_location('dependency_inventory',ROOT/'tools/firmware/audit_handoff_dependencies.py')
    audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    inventory=audit.inventory()
    assert {int(u['movw'],16) for u in inventory['constant_formations']}=={
        0x80020366,0x8002043c,0x8002054e,0x8006e4be}
    assert len(inventory['targets']['SD_event_post']['direct_references'])>=8
    passed('pinned_bounded_inventory_identifies_four_UI_mutex_users_and_separate_SD_event_post_references')
    r=Dependencies();assert r.step()==0
    assert r.sd_calls and {c[0] for c in r.sd_calls}=={2,3}
    assert not r.unit_held and not r.tokens and not r.ui_attempts and not r.queue_calls
    assert set(r.event_takes)=={0}
    assert len(r.sd_waits)==3*len(r.sd_calls)
    assert [w[1] for w in r.sd_waits[:3]]==[0x183,0x185,0x183]
    assert all(FS1 in w[2] for w in r.sd_waits)
    passed('same_CPU_checked_handoff_runs_native_SD_commands_data_and_status_without_UI_mutex_or_Main_service')

    r=Dependencies();assert r.step()==0
    sample=[w for w in r.sd_waits if 0x80735b80<=w[0][1]<0x8077c580]
    assert sample and all(w[2]==[SCRATCH,FS1] for w in sample)
    assert any(w[0][0]==3 for w in r.sd_waits)
    passed('initial_audio_reads_and_settings_write_readback_retain_filesystem_and_SD_lifetimes_through_native_waits')

    r=Dependencies();raw=r.files[r.capture.result()[1]]
    raw.extend(bytes(range(256))*1200)
    struct.pack_into('<I',raw,4,len(raw)-8);struct.pack_into('<I',raw,508,len(raw)-512)
    assert r.step()==0 and not r.ui_attempts and not r.unit_held and not r.tokens
    assert len(r.sd_calls)>500
    passed('larger_initial_audio_load_repeats_same_native_SD_dependency_chain')

    for stage in ('command','data'):
        r=Dependencies();r.pending_stage=stage;r.step()
        assert r.blocked_event and r.unit_held and r.tokens=={FS1,SCRATCH} and r.locked
        assert not r.ui_attempts and not any(t[0]=='leave' for t in r.trace)
    passed('pending_command_or_data_event_retains_unit_filesystem_scratch_and_gate_ownership_without_waiting_for_Main')

    r=Dependencies();m=r.m
    put32(m,0x402c0030,2);put32(m,0x402c0038,0x157f003f)
    assert m.invoke(0x8006ea90,[])==0
    assert word(m,EVENT+8)==4 and r.irq_wakes==[EVENT_TOKEN] and not r.ui_attempts
    passed('original_SD_interrupt_and_event_post_wake_the_SD_event_object_independently_of_UI_queue')

    # A physical completion is NOT proved by native timeout return. This case
    # records the adapter's current bounded-fixture behavior, not safe hardware recovery.
    r=Dependencies();r.pending_stage='data';r.timeout_once=True
    # Only first failure is injected; rollback gets normal modeled completions.
    previous=r.take_token
    def once(a):
        result=previous(a)
        if r.blocked_event and not r.timeout_once:r.pending_stage=None
        return result
    r.m.hooks[0x80076950]=once
    assert r.step()==7 and r.blocked_event and not r.unit_held and not r.tokens
    assert not r.locked and not r.ui_attempts
    passed('negative_control_native_timeout_unlocks_and_current_adapter_rolls_back_without_physical_idle_evidence')

    report=dict(passed_groups=len(cases),cases=cases,firmware_sha256=inventory['firmware_sha256'],limitations=[
        'A synthetic C router bridges logical file callbacks to one-sector registered SD operations; real sector mapping/cache/metadata is not executed.',
        'Native SD dispatch/commands/event predicate and handoff run on one CPU; MMIO flags, kernel timing and file contents remain models.',
        'No Main event service or UI-mutex use on examined paths is not proof about every filesystem callback or gate/seal implementation.',
        'Timeout and event-flag faults still lack physical DMA/idle proof; real adapter binding remains disabled.',
        'No device access, production routing hook, placement approval or firmware image.'])
    (ROOT/'analysis/handoff_dependencies_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
