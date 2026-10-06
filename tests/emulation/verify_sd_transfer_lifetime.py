#!/usr/bin/env python3
"""Original SD transfer/lock lifetime; modeled kernel and MMIO, no device I/O."""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_FPEXC
from verify_overdub_prototype import Emulator,ELF
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_storage_lifetimes import instructions
from verify_scheduling_boundaries import stop
TABLE=0x801f5ff0;UNIT=0x801f5fb8;CARD=0x801f8e44;HOST=0x808e28dc
REQ=0x21008000;BUFFER=0x21010000;SEM=0x7001;EVENT=0x21009000
EXPECTED=[0x80069b21,0x80069a19,0x800699b9,0x8006a249,0x8006a749,0x8006a349,
          0x80069c59,0x8006a7f9,0x8006a281,0x800698a1,0x8006a719]

class Sd:
    def __init__(self,emulator=None):
        self.m=emulator if emulator is not None else Emulator();m=self.m
        assert m.invoke(0x80001994,[0x800a6980,0x801f5400,0x3780])==0
        assert list(struct.unpack('<11I',m.uc.mem_read(TABLE,44)))==EXPECTED
        for base in (0x402c0000,0x400fc000,0xe000e000):m.uc.mem_map(base,0x1000)
        m.uc.reg_write(UC_ARM_REG_FPEXC,0x40000000)
        self.events=[];self.held=False;self.pending=False;self.wait_result=0;self.flags=4
        self.command_error=0;self.status_error=0;self.status_ready=True;self.data_waits=0
        m.uc.mem_write(UNIT+4,b'\x01');put32(m,UNIT+8,SEM)
        m.uc.mem_write(CARD+4,b'\0\x02');m.uc.mem_write(0x802142b4,b'\x01')
        put32(m,HOST+4,EVENT);put32(m,EVENT,0x7002)
        m.hooks[0x800328f0]=self.lock;m.hooks[0x80032890]=self.unlock
        m.hooks[0x8006a348]=self.command;m.hooks[0x800328c0]=self.wait
        m.hooks[0x80032250]=lambda a:self.events.append(('delay',a[0])) or 0
    def lock(self,a):
        assert a[0]==SEM and not self.held;self.held=True;self.events.append(('lock',));return 0
    def unlock(self,a):
        assert a[0]==SEM and self.held;self.events.append(('unlock',));self.held=False;return 0
    def command(self,a):
        assert self.held
        code=self.m.uc.mem_read(a[0],1)[0]
        self.events.append(('command',code))
        # Auxiliary write-error diagnostic command is rejected by this fixture;
        # it is not part of the data-completion evidence under test.
        if code==28:return 11
        out=word(self.m,a[0]+8)
        if out:self.m.uc.mem_write(out,b'\0\0'+bytes([int(self.status_ready)])+b'\0')
        return self.status_error if code==15 else self.command_error
    def wait(self,a):
        assert self.held and a[0]==EVENT and a[1]==0x185 and a[4]==5000
        self.data_waits+=1;self.events.append(('data_wait',a[1],a[4]))
        if self.pending:return stop(self.m)
        put32(self.m,a[3],self.flags);return self.wait_result
    def request(self,op=2,blocks=2,offset=0):
        raw=bytearray(20);raw[0]=op;raw[1]=1
        struct.pack_into('<3I',raw,8,BUFFER+offset,blocks,7)
        self.m.uc.mem_write(REQ,bytes(raw))
        return self.m.invoke(0x80068378,[REQ])
    def barrier(self):
        raw=bytearray(20);raw[0]=6;raw[1]=1;raw[8]=4
        self.m.uc.mem_write(REQ,bytes(raw));return self.m.invoke(0x80068378,[REQ])

def irq(status):
    r=Sd();m=r.m;events=[]
    put32(m,0x402c0030,status);put32(m,0x402c0038,0x157f003f)
    m.hooks[0x80032828]=lambda a:events.append(tuple(a[:2])) or 0
    m.invoke(0x8006ea90,[]);return events

def event_wait(flags):
    r=Sd();m=r.m;m.hooks.pop(0x800328c0)
    put32(m,EVENT+4,0);put32(m,EVENT+8,flags)
    m.hooks[0x80076950]=lambda a:1
    m.hooks[0x80074580]=lambda a:put32(m,a[0],0) or 0
    m.hooks[0x80073ec8]=m.hooks[0x80073f18]=lambda a:0
    # Use real event-wait code through data driver: timeout parameter is on the
    # original caller's stack. Existing event bits model an IRQ already delivered.
    result=r.request();return r,result

def native_commands(op,flags=4):
    r=Sd();m=r.m;m.hooks.pop(0x8006a348)
    def trace(uc,a,n,u):
        from verify_pad_protocol import REGS
        assert r.held
        r.events.append(('native_command',m.uc.mem_read(uc.reg_read(REGS[0]),1)[0]))
    m.uc.hook_add(UC_HOOK_CODE,trace,begin=0x8006a348,end=0x8006a348)
    def wait(a):
        assert r.held and a[0]==EVENT and a[4]==5000
        assert a[1] in (0x183,0x185)
        r.events.append(('native_wait',a[1]))
        put32(m,a[3],2 if a[1]==0x183 else flags)
        return 0
    m.hooks[0x800328c0]=wait
    put32(m,0x402c0010,0x100) # synthetic command response with ready bit
    return r,r.request(op)

def cleanup5(clock_unstable=False):
    r=Sd();m=r.m
    def divider(a):put32(m,a[0],1);put32(m,a[1],1);return 0
    m.hooks[0x80069510]=divider
    m.hooks[0x80032878]=lambda a:put32(m,a[1],0) or 0
    m.hooks[0x8006a760]=lambda a:r.events.append(('clock_probe',int(clock_unstable))) or int(clock_unstable)
    result=r.request(op=5);return r,result

def cleanup1(delete_error=0,event_error=0):
    r=Sd();m=r.m;put32(m,HOST+8,0x7003)
    for fn,res in ((0x80032248,0xffff1234),(0x80032218,delete_error),(0x80032210,event_error)):
        m.hooks[fn]=lambda a,fn=fn,res=res:r.events.append((hex(fn),a[0])) or res
    result=r.request(op=1);return r,result

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    r=Sd();passed('original_startup_decompressor_recovers_all_eleven_SD_driver_callbacks',table=[hex(x) for x in EXPECTED])
    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(2,4),(2,1),(9,1)):
            r=Sd();result=r.request(op,blocks,offset)
            assert result==0 and not r.held and r.data_waits and r.events[0]==('lock',) and r.events[-1]==('unlock',)
    passed('original_read_write_and_driver_paths_hold_unit_lock_across_direct_and_bounce_buffer_data_waits',
           cases='1,2,9 blocks; aligned, word-offset and byte-offset buffers; data and command outcomes modeled')
    for op in (2,3):
        r=Sd();r.pending=True;r.request(op)
        assert r.held and r.data_waits==1 and r.events[-1][0]=='data_wait'
    passed('unfinished_data_wait_does_not_reach_outer_unlock',limitation='Emulator observation stops at wait; no native scheduler progress modeled')
    for op in (2,3):
        r=Sd();r.wait_result=0xffffffce;result=r.request(op)
        assert result==0xffffd8ef and not r.held
        assert r.barrier()==0 and not r.held
    passed('data_wait_timeout_propagates_error_but_unlocks_and_later_stop_barrier_succeeds_without_remembering_it')
    for op in (2,3):
        r=Sd();r.command_error=11;result=r.request(op)
        assert result==0xffffd8ef and r.data_waits==0 and not r.held
    passed('command_submission_failure_exits_before_data_wait_and_propagates_through_unit_unlock')
    for op in (2,3):
        r=Sd();r.command_error=19;assert r.request(op)==0xffffd8ef
        assert r.m.uc.mem_read(0x802142b4,1)==b'\0' and not r.held
    passed('driver_code19_disables_driver_before_outer_unlock')

    # Verify kernel event semantics rather than treating wait-success as data success.
    for flags in (4,1,0x80,0x100):
        r,result=event_wait(flags)
        assert result==0 and not r.held
    passed('actual_event_wait_accepts_any_0x185_bit_and_read_data_path_does_not_inspect_returned_event_bits')
    mapping={1:2,2:4,0x10:0x10,0x20:8,0x10000:0x80,0x20000:1,0x200000:1,0x100002:4}
    for raw,flag in mapping.items():assert irq(raw)==[(EVENT,flag)]
    passed('original_SD_interrupt_maps_completion_and_error_status_to_distinct_software_events',mapping={hex(k):hex(v) for k,v in mapping.items()})

    for op in (2,3):
        r,result=native_commands(op)
        assert result==0 and not r.held
        masks=[e[1] for e in r.events if e[0]=='native_wait']
        assert masks==[0x183,0x185,0x183],masks
    passed('actual_command_engine_executes_command_data_and_final_status_waits_under_same_outer_lock')
    for op in (2,3):
        for flags in (1,0x80,0x100):
            r,result=native_commands(op,flags)
            assert result==0 and not r.held
    passed('actual_command_engine_does_not_recover_data_error_event_when_later_status_response_is_good',
           limitation='Injected wait event and later-good response, not verified on hardware')

    r=Sd();r.status_error=11;assert r.request(op=2)==0 and not r.held
    passed('read_returns_transfer_result_and_ignores_followup_status_command_error')
    r=Sd();r.status_error=11;assert r.request(op=3)==0xffffd8ef and not r.held
    passed('write_ready_poll_status_failure_propagates')
    r=Sd();r.status_ready=False;assert r.request(op=3)==0xffffd8ef
    assert len([e for e in r.events if e[0]=='delay'])==6000 and not r.held
    passed('write_ready_poll_exhaustion_returns_failure_after_6000_modeled_delays_before_unlock')

    for unstable in (False,True):
        r,result=cleanup5(unstable)
        assert result==0 and not r.held and r.m.uc.mem_read(0x802142b4,1)==b'\0'
        assert ('clock_probe',int(unstable)) in r.events
    passed('operation5_disables_driver_and_runs_actual_cleanup_but_returns_zero_when_clock_stability_probe_fails',
           limitation='Divider and clock helper modeled here; verify_sd_completion.py executes the actual clock helper. Physical idle/cache/clock behavior remains unverified')
    for error,event_error in ((0,0),(0,0xffff1234),(0xffff1234,0)):
        r,result=cleanup1(error,event_error)
        assert result==(0xffffd8ef if error else 0)
        assert word(r.m,HOST+4)==0 and not r.held
        assert r.m.uc.mem_read(UNIT+4,1)==bytes([1 if error else 0])
    passed('operation1_checks_one_cleanup_result_but_discards_event_delete_failure_and_clears_event_handle')

    windows=[(0x80068db0,0x80068fa0),(0x8006b050,0x8006b0b8),(0x8006b1e0,0x8006b2f0),
      (0x80069c58,0x8006a248),(0x8006a248,0x8006a340),(0x8006a7f8,0x8006ae48),
      (0x8006ea90,0x8006eba8),(0x800326c0,0x800327c0),(0x80069488,0x800694d8)]
    lines=[]
    for a,b in windows:
        lines.append(f'\n# {a:08x}..{b:08x}')
        lines.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(a,b))
    (ROOT/'analysis/sd_transfer_lifetime_disassembly.txt').write_text('\n'.join(lines)+'\n')
    out=ROOT/'analysis/sd_transfer_lifetime_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),limitations=[
      'Original startup decompression, dispatcher, transfer drivers, event predicate and IRQ mapping execute with synthetic RAM/MMIO',
      'Most command bodies are modeled; two groups run the actual command engine with modeled wait events and response registers. Kernel scheduling, SD contents, MMIO side effects and time remain fixtures',
      'Auxiliary write-error diagnostic command 0x1c is rejected in failure fixtures; its successful transfer path is unverified',
      'Success under injected error events is a control-flow result, not a reproduced hardware fault or proof that every event timing can occur on the mixer',
      'No native checked-stop binding, firmware patch, hardware access, card write or physical DMA/persistence claim']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))
if __name__=='__main__':main()
