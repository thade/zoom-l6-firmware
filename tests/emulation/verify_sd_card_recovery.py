#!/usr/bin/env python3
"""Stock CMD12/card-init audit and retained-stack stop experiment; no device I/O."""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC,UC_ARM_REG_R4
from verify_sd_transfer_lifetime import Sd,CARD,HOST,EVENT,BUFFER,REQ
from verify_sd_transfer_probe import Probe,ELF,BOUNCE,install
from verify_sd_completion import observe_mmio
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_storage_lifetimes import instructions
from verify_pad_protocol import ROOT,IMAGE,REGS,RETURN
from verify_scheduling_boundaries import stop
from sd_registers import (SD,PRESENT,PROTOCOL,SYSTEM,COMMAND,DMA_ADDRESS,
                         CLOCK_STABLE,RESET_ALL,ACTIVITY)

COMMAND_TABLE=0x800a07ec;STOP_ROW=COMMAND_TABLE+14*12
STOP_FIELDS='active unit event request attempted status raw errors present_after system_after'.split()

def stock_stop(flags=2,wait_result=0,present=0x206,abort=False):
    r=Sd();m=r.m;r.held=True;m.hooks.pop(0x8006a348)
    raw=bytearray(24);raw[0]=14;struct.pack_into('<I',raw,8,BUFFER)
    m.uc.mem_write(REQ,bytes(raw));put32(m,PRESENT,present);put32(m,SD+0x10,0x100)
    if abort:put32(m,STOP_ROW+4,word(m,STOP_ROW+4)|0xc00000)
    def wait(a):
        assert a[0]==EVENT and a[1]==0x183 and a[4]==5000
        put32(m,a[3],flags);return wait_result
    m.hooks[0x800328c0]=wait
    reads,writes=observe_mmio(r)
    result=m.invoke(0x8006b0b8,[REQ,0])
    return r,result,reads,writes

class CardInit(Sd):
    """Original upper card state machine; command/read responses are fixtures."""
    def __init__(self,width=5,rca=0x1234,capacity_field=0xfff):
        super().__init__();m=self.m
        self.commands=[];self.metadata_reads=[];self.width=width;self.rca=rca
        self.capacity_field=capacity_field;self.fail_code=None;self.fail_clock=False
        m.uc.mem_write(CARD+4,bytes(20));put32(m,PRESENT,CLOCK_STABLE);put32(m,HOST,198000000)
        m.hooks[0x80069510]=lambda a:put32(m,a[0],1) or put32(m,a[1],1) or 0
        m.hooks[0x8006b0b8]=self.command;m.hooks[0x8006b1e0]=self.read_metadata
        m.hooks[0x8006ae58]=lambda a:m.uc.mem_write(a[0],bytes(2)) or 0
        m.hooks[0x8006ae80]=lambda a:1
        m.hooks[0x80032878]=lambda a:put32(m,a[1],0) or 0
        # Execute the original clock wrapper/callback, fail only when asked.
        def clock_entry(uc,pc,size,user):
            if self.fail_clock:put32(m,PRESENT,0)
        m.uc.hook_add(UC_HOOK_CODE,clock_entry,begin=0x800698a0,end=0x800698a0)
    def command(self,a):
        assert self.held
        m=self.m;raw=bytes(m.uc.mem_read(a[0],24));code=raw[0]
        arg=int.from_bytes(raw[4:8],'little');out=int.from_bytes(raw[8:12],'little')
        self.commands.append(dict(code=code,arg=arg,rca=int.from_bytes(raw[18:20],'little')))
        if code==self.fail_code:return 11
        # Synthetic SDHC metadata selected to exercise native branch parsing.
        # This is not a protocol-complete card or valid physical media image.
        csd=bytearray(16);csd[0]=0x40;csd[3]=0x32;csd[4]=0x5b;csd[5]=0x59
        csd[7:10]=self.capacity_field.to_bytes(3,'big')
        data={0:b'',10:bytes.fromhex('000001aa'),38:bytes.fromhex('c0ff8000'),
              2:bytes(range(16)),3:(self.rca<<16).to_bytes(4,'big'),12:bytes(csd)}.get(code,bytes(4))
        if out and data:m.uc.mem_write(out,data)
        return 0
    def read_metadata(self,a):
        assert self.held
        m=self.m;raw=bytes(m.uc.mem_read(a[0],24));code=raw[0]
        out=int.from_bytes(raw[12:16],'little');self.metadata_reads.append(code)
        if out:m.uc.mem_write(out,bytes([0,self.width,0,0,0,0,0,0]) if code==41 else bytes(64))
        return 0

class StopProbe(Probe):
    """Original CMD12 runs inside compiled join; physical JOINED still a model."""
    def __init__(self,abort=False):
        super().__init__();m=self.m
        self.fault=(0x185,'hidden_error');self.pending=True
        self.stop_fault=None;self.keep_command_inhibit=False;self.stale_stop=False
        self.stop_snapshots=[];self.submissions=[]
        put32(m,self.syms['sdp_join_port'],self.syms['sdp_stop_join']|1)
        m.hooks[0x2102bc00]=self.join
        if abort:
            # Counterfactual TABLE change in emulator memory only. No firmware
            # image/table patch is generated or selected for installation.
            put32(m,STOP_ROW+4,word(m,STOP_ROW+4)|0xc00000)
        def submit(uc,access,address,size,value,user):self.submissions.append(value)
        m.uc.hook_add(UC_HOOK_MEM_WRITE,submit,begin=COMMAND,end=COMMAND)
    def stop_state(self):
        raw=struct.unpack('<10I',self.m.uc.mem_read(self.syms['sdp_stop_state'],40))
        return dict(zip(STOP_FIELDS,raw))
    def deliver(self,a):
        if not self.stop_state()['active']:
            reply=super().deliver(a)
            if self.fault and not self.fault_once and a[1]==0x185 and not self.keep_command_inhibit:
                # Explicit model condition: CMD line is available, but data
                # inhibit/activity and low DAT0 remain. No cancellation assumed.
                put32(self.m,PRESENT,0x206)
            return reply
        assert self.held and a[0]==EVENT and a[1]==0x183
        raw=0 if self.stop_fault=='timeout' or self.stale_stop else 0x20000 if self.stop_fault=='error' else 1
        put32(self.m,EVENT+8,2 if self.stale_stop else 0)
        put32(self.m,SD+0x30,raw);put32(self.m,PRESENT,0x206)
        return int(bool(raw))
    def join(self,a):
        state=self.stop_state()
        assert state['attempted']==1 and not state['active'] and state['request']==0
        assert self.held and self.state()['active'] and not self.state()['finished']
        self.stop_snapshots.append(state)
        return super().join(a)

def handoff_case(passed):
    from verify_handoff_dependencies import Dependencies,FS1,SCRATCH
    class HandoffStop(Dependencies):
        def __init__(self):
            super().__init__();m=self.m;install(m,self.syms)
            self.inject=True;self.pending=True;self.stops=[];self.commands=[]
            put32(m,self.syms['sdp_join_port'],self.syms['sdp_stop_join']|1)
            m.hooks[0x2102bd04]=self.deliver;m.hooks[0x2102bc00]=self.join
            def command(uc,pc,size,user):
                assert self.unit_held and FS1 in self.tokens
                self.commands.append(uc.reg_read(UC_ARM_REG_R4))
            m.uc.hook_add(UC_HOOK_CODE,command,begin=0x8006a350,end=0x8006a350)
        def stop_state(self):
            values=struct.unpack('<10I',self.m.uc.mem_read(self.syms['sdp_stop_state'],40))
            return dict(zip(STOP_FIELDS,values))
        def deliver(self,a):
            assert self.unit_held and FS1 in self.tokens
            recovering=self.stop_state()['active']
            initial=self.current_io and 0x80735b80<=self.current_io[1]<0x8077c580
            faulty=self.inject and initial and a[1]==0x185
            raw=1 if a[1]==0x183 else 2
            if faulty:raw|=0x100000;self.inject=False
            put32(self.m,EVENT+8,0);put32(self.m,SD+0x30,raw)
            put32(self.m,PRESENT,0x206 if recovering or faulty else 0)
            return 1
        def join(self,a):
            state=self.stop_state();assert state['status']==0 and state['raw']==1
            assert state['present_after']==0x206 and state['attempted']==1 and not state['active']
            assert self.unit_held and self.tokens=={FS1,SCRATCH} and self.locked
            self.stops.append(state)
            if self.pending:return stop(self.m)
            put32(self.m,PRESENT,0);put32(self.m,SYSTEM,0);return 1
        def resume(self):
            m=self.m;self.pending=False;m.reached_return=False
            m.uc.emu_start(m.uc.reg_read(UC_ARM_REG_PC)|1,RETURN+2,count=100000000)
            assert m.reached_return
            return m.uc.reg_read(REGS[0])
    r=HandoffStop();r.step()
    assert len(r.stops)==1 and r.commands.count(14)==1
    assert r.unit_held and r.tokens=={FS1,SCRATCH} and r.locked
    assert not r.ui_attempts and not any(t[0]=='leave' for t in r.trace)
    assert r.resume()==7 and len(r.stops)==2 and r.commands.count(14)==1
    assert not r.unit_held and not r.tokens and not r.locked and not r.ui_attempts
    passed('whole_checked_handoff_retains_gate_filesystem_scratch_and_SD_unit_through_stock_stop_then_explicit_model_join',
           limitation='Synthetic sector routing/logical file data; rollback after resume still assumes physical MODEL JOINED contract')

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    r=Sd();table=[struct.unpack('<3I',r.m.uc.mem_read(COMMAND_TABLE+i*12,12)) for i in range(43)]
    assert table[14]==(12,0x1b0000,0x10) and not any(flags&0xc00000 for code,flags,mix in table)
    passed('pinned_stock_command_table_maps_software14_to_CMD12_R1b_without_explicit_controller_abort_type',
           row=[hex(v) for v in table[14]],limit='Bounded 43-row table; other directly programmed paths not excluded')

    for abort in (False,True):
        r,result,reads,writes=stock_stop(abort=abort)
        assert result==0 and r.events==[('delay',1)]*100 and word(r.m,PRESENT)==0x206
        assert [v for pc,a,v in writes if a==COMMAND]==[0x0cdb0000 if abort else 0x0c1b0000]
        assert not any(a==SYSTEM for pc,a,v in writes)
        assert [pc for pc,a,v in reads if a==PRESENT][-1]==0x8006a6f6
    passed('stock_CMD12_and_counterfactual_abort_type_return_zero_after_100_DAT0_busy_delays_without_idle_check',
           limitation='Abort flag patched only in emulator table; DAT0/activity have no hardware side effects')

    for flags,result in ((1,10),(0x80,3),(0x100,19)):
        r,status,reads,writes=stock_stop(flags)
        assert status==result and word(r.m,SYSTEM)&RESET_ALL and len(r.events)==10
    r,status,reads,writes=stock_stop(wait_result=0xffffffce)
    assert status==11 and not any(a==SYSTEM for pc,a,v in writes)
    r,status,reads,writes=stock_stop(present=0x207)
    assert status==12 and len(r.events)==100 and not writes
    passed('stop_command_error_reset_wait_timeout_and_precommand_inhibit_have_distinct_paths_without_checked_join')

    for op in (2,3):
        for stop_result in (0,11):
            r=Sd();r.wait_result=0xffffffce;commands=[];m=r.m
            original=r.command
            def command(a):
                code=m.uc.mem_read(a[0],1)[0];commands.append(code)
                return stop_result if code==14 else original(a)
            m.hooks[0x8006a348]=command
            assert r.request(op)==0xffffd8ef and 14 in commands and not r.held
    passed('stock_read_write_error_wrappers_attempt_CMD12_but_discard_its_return_status')

    for width,bus in ((1,0),(5,2)):
        r=CardInit(width);assert r.request(4)==0 and not r.held
        codes=[c['code'] for c in r.commands]
        assert codes==[0,10,38,2,3,12,9]+([8] if width==5 else [])+[21]
        assert r.metadata_reads==[17,41]
        assert word(r.m,HOST+4)==EVENT and word(r.m,PROTOCOL)&6==bus
        assert int.from_bytes(r.m.uc.mem_read(CARD+10,2),'little')==0x1234
        assert word(r.m,CARD+16)==0x400000 and r.m.uc.mem_read(CARD+5,1)==b'\x02'
        assert r.commands[-1]['arg']==512 and r.commands[-1]['rca']==0x1234
    passed('original_upper_SDHC_negotiation_recovers_RCA_capacity_card_selection_bus_width_and_block_size_without_event_recreation',
           limitation='Command responses/CID/CSD/SCR/SD-status metadata and divider arithmetic synthetic; native lower card commands not executed here')

    r=CardInit();assert r.request(4)==0;count=len(r.commands)
    assert r.request(4)==0xffffd8ef and len(r.commands)==count # already initialized -> code2
    r.held=True;assert r.m.invoke(0x80069488,[0])==0;r.held=False
    assert r.m.uc.mem_read(CARD+5,1)==b'\x08' and word(r.m,HOST+4)==EVENT
    r.rca=0x5678;r.capacity_field=0x7ff
    assert r.request(4)==0 and int.from_bytes(r.m.uc.mem_read(CARD+10,2),'little')==0x5678
    assert word(r.m,CARD+16)==0x200000 and word(r.m,HOST+4)==EVENT
    passed('card_reinitialization_requires_ready_state_transition_and_accepts_changed_address_capacity_without_identity_comparison',
           limitation='Deinit power callback no-op in stock table; this does not authorize reusing filesystem handles or replacing physical media')

    for code in (0,12,9,8,21):
        r=CardInit();r.fail_code=code
        assert r.request(4)==0xffffd8ef and not r.held
        assert r.m.uc.mem_read(CARD+5,1)==b'\x08' and word(r.m,HOST+4)==EVENT
        assert r.m.uc.mem_read(0x802142b4,1)==b'\x01'
    r=CardInit();r.fail_clock=True
    assert r.request(4)==0xffffd8ef and not r.held and not r.commands
    passed('upper_card_init_failures_clear_card_readiness_but_leave_driver_enable_set_and_preserve_completion_handle',
           limitation='Modeled status11 failure; status19 disable behavior remains separately covered by stock command tests')

    for abort in (False,True):
        for op in (2,3):
            for blocks,offset in ((1,0),(2,0),(9,1)):
                r=StopProbe(abort);r.request(op,blocks,offset)
                state=r.stop_snapshots[-1]
                assert state['status']==0 and state['raw']==1 and state['errors']==0
                assert state['present_after']&ACTIVITY and r.state()['errors']==0x100000
                assert r.held and r.state()['failed'] and not r.state()['finished'] and not r.state()['joined']
                assert word(r.m,DMA_ADDRESS)==(BUFFER if blocks==2 else BOUNCE)
                if op==2:assert not r.copies
                copies=list(r.copies);commands=list(r.native_commands)
                assert len(commands)==2 and commands[-1]==14 and commands[0]!=14
                assert r.submissions[-1]==(0x0cdb0000 if abort else 0x0c1b0000)
                assert r.resume()==0xffffd8ef and not r.held and r.state()['joined']==1
                assert r.native_commands==commands and r.copies==copies
    passed('compiled_stop_attempt_retains_native_read_write_direct_or_bounce_transfer_and_never_treats_CMD12_success_as_JOINED',
           limitation='Only MODEL join after resume clears synthetic activity and authorizes unwind')

    for fault in ('error','timeout'):
        r=StopProbe();r.stop_fault=fault;r.request()
        state=r.stop_snapshots[-1]
        assert state['status']==11 and state['errors']==(0x20000 if fault=='error' else 0)
        assert r.held and r.state()['join_calls']==1 and not r.state()['joined']
        assert r.resume()==0xffffd8ef and not r.held and r.native_commands==[23,14]
    r=StopProbe();r.keep_command_inhibit=True;r.request()
    assert r.stop_snapshots[-1]['status']==12 and r.held and len(r.submissions)==1
    assert r.resume()==0xffffd8ef and not r.held
    passed('stop_error_timeout_or_unavailable_command_line_remains_inside_outer_join_without_recursive_fault_unwind')

    r=StopProbe();r.stale_stop=True;r.request()
    assert r.stop_snapshots[-1]['status']==0 and r.stop_snapshots[-1]['raw']==0
    assert r.held and not r.state()['joined'] and r.stop_snapshots[-1]['present_after']&ACTIVITY
    assert r.resume()==0xffffd8ef and not r.held
    passed('negative_old_software_command_completion_can_satisfy_stop_wait_without_new_IRQ_but_cannot_release_outer_join')

    r=StopProbe();assert r.m.invoke(r.syms['sdp_stop_join'],[0,BUFFER,1024,1])==0
    r.seed(active=1,failed=1,unit=0,buffer=BUFFER,bytes=1024)
    for args in ([1,BUFFER,1024,1],[0,BUFFER+4,1024,1],[0,BUFFER,512,1]):
        assert r.m.invoke(r.syms['sdp_stop_join'],args)==0
    assert not r.stop_snapshots and not r.submissions and not r.stop_state()['attempted']
    passed('stop_probe_rejects_inactive_or_mismatched_unit_buffer_size_without_command_or_model_join')

    r=StopProbe()
    for reply in (2,0xffffffce):
        r.fault_once=True;r.pending=True;r.join_reply=reply;r.request()
        assert r.held and not r.state()['joined'] and r.stop_state()['attempted']==1
        assert r.resume()==0xffffd8ef and not r.held
    assert r.native_commands==[23,14,23,14]
    passed('stop_attempt_is_once_per_failed_transfer_and_unknown_or_failed_model_join_never_releases_it')

    handoff_case(passed)

    windows=[(0x800687d0,0x80068d98),(0x8006a348,0x8006a480),
             (0x8006a6c4,0x8006a712),(0x8006b1e0,0x8006b2b0),
             (0x80069488,0x800694d8),(0x8006b2b0,0x8006b324)]
    lines=[]
    for a,b in windows:
        lines.append(f'\n# {a:08x}..{b:08x}')
        lines.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(a,b))
    (ROOT/'analysis/sd_card_recovery_disassembly.txt').write_text('\n'.join(lines)+'\n')
    out=ROOT/'analysis/sd_card_recovery_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),test_elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
      limitations=['Original instructions and compiled test-only stop probe, with modeled kernel/MMIO/time/physical join',
      'Upper card-init metadata/responses and clock arithmetic synthetic; not a full controller/card protocol model',
      'Abort-type table change exists only in emulator memory, not in any deployment image',
      'No reset/cache/DMA/IRQ freshness/card persistence guarantee or filesystem remount/identity proof',
      'No recovery binding, hardware/card access, deployment image or installation']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))

if __name__=='__main__':main()
