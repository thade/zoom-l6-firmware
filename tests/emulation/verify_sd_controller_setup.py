#!/usr/bin/env python3
"""Original controller setup and transfer programming; no device operations.

MMIO has no automatic reset, W1C, DMA, NVIC or cache side effects. Selected
kernel results and clock arithmetic are fixtures, not physical recovery proof.
"""
import hashlib,json
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_sd_transfer_lifetime import Sd,HOST,CARD,EVENT,BUFFER
from verify_sd_transfer_probe import Probe,BOUNCE
from verify_sd_completion import observe_mmio
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_storage_lifetimes import instructions
from verify_pad_protocol import ROOT,IMAGE
from sd_registers import (SD,DMA_ADDRESS,BLOCKS,COMMAND,PRESENT,PROTOCOL,SYSTEM,
    IRQ_STATUS,IRQ_ENABLE,IRQ_SIGNAL,WATERMARK,MIX,ADMA_ADDRESS,VENDOR,VENDOR2,
    CLOCK_STABLE,RESET_ALL,INITIAL_CLOCKS,DMA_SELECT,DMA_ENABLE,FORCE_CLOCK,AUTO23_ARGUMENT)

SEED_MIX=0x40000100
NVIC_ENABLE=0xe000e10c # IRQ110: bank3, bit14, as in the candidate headers.

def setup(present=CLOCK_STABLE,clear_reset=False,existing=False,protocol=0x20):
    r=Sd();m=r.m
    put32(m,HOST,198000000);put32(m,PRESENT,present);put32(m,SYSTEM,0)
    put32(m,PROTOCOL,protocol);put32(m,MIX,0x101)
    put32(m,VENDOR,FORCE_CLOCK|1);put32(m,VENDOR2,AUTO23_ARGUMENT|0x20)
    put32(m,IRQ_ENABLE,0xffffffff);put32(m,IRQ_SIGNAL,0xffffffff)
    m.hooks[0x80069510]=lambda a:put32(m,a[0],1) or put32(m,a[1],1) or 0
    def delay(a):
        r.events.append(('delay',a[0]))
        if clear_reset and word(m,SYSTEM)&RESET_ALL:
            # Intentionally clear ONLY the modeled reset bit. Other state is
            # independent here; this is not an emulation of actual reset effects.
            put32(m,SYSTEM,word(m,SYSTEM)&~RESET_ALL)
        return 0
    m.hooks[0x80032250]=delay
    reads,writes=observe_mmio(r)
    card=bytes(m.uc.mem_read(CARD,32))
    result=m.invoke(0x80069a18 if existing else 0x80069b20,
                    [0] if existing else [0,198000000])
    assert bytes(m.uc.mem_read(CARD,32))==card
    return r,result,reads,writes

def event_create(r,semaphore=0x7003,event=EVENT):
    m=r.m;trace=[];deletes=[]
    def create_semaphore(a):trace.append(('semaphore',word(m,HOST+4)));return semaphore
    def create_event(a):trace.append(('event',word(m,HOST+4)));return event
    def delete(a):deletes.append(a[0]);return 0
    m.hooks[0x800321c0]=create_semaphore;m.hooks[0x800321b8]=create_event
    m.hooks[0x80032218]=delete
    def enabled(uc,access,address,size,value,user):
        trace.append(('NVIC_enable',word(m,HOST+4),value,uc.reg_read(UC_ARM_REG_PC)))
    m.uc.hook_add(UC_HOOK_MEM_WRITE,enabled,begin=NVIC_ENABLE,end=NVIC_ENABLE)
    result=m.invoke(0x800699b8,[0])
    return result,trace,deletes

def transfer_trace(op,blocks,offset=0,protocol=0x20,vendor2=0):
    r=Probe();m=r.m;submissions=[];cache=[];order=[]
    put32(m,PROTOCOL,protocol);put32(m,VENDOR2,vendor2);put32(m,MIX,SEED_MIX)
    reads,writes=observe_mmio(r)
    def submitted(uc,access,address,size,value,user):
        snap=dict(command=value,dma=word(m,DMA_ADDRESS),blocks=word(m,BLOCKS),
                  mix=word(m,MIX),protocol=word(m,PROTOCOL),vendor2=word(m,VENDOR2))
        submissions.append(snap);order.append(('command',value))
    def maintained(uc,access,address,size,value,user):
        cache.append((uc.reg_read(UC_ARM_REG_PC),address,value));order.append(('cache',value))
    m.uc.hook_add(UC_HOOK_MEM_WRITE,submitted,begin=COMMAND,end=COMMAND)
    m.uc.hook_add(UC_HOOK_MEM_WRITE,maintained,begin=0xe000ef70,end=0xe000ef70)
    result=r.request(op,blocks,offset)
    return r,result,reads,writes,submissions,cache,order

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    cases=[]
    for op in (2,3):
        for blocks,offset in ((1,0),(2,0),(2,4),(2,1),(9,1)):
            r,result,reads,writes,submissions,cache,order=transfer_trace(op,blocks,offset)
            assert result==0 and not r.held
            data=[s for s in submissions if s['command']&0x200000]
            assert data and sum(s['blocks']>>16 for s in data)==blocks
            for s in data:
                count=s['blocks']>>16
                expected=(0x37 if op==2 else 0x27) if count>1 else (0x11 if op==2 else 1)
                assert s['mix']==SEED_MIX|expected and s['blocks']&0x1fff==512
                assert s['protocol']&DMA_SELECT==0 and s['vendor2']&AUTO23_ARGUMENT==0
                assert s['dma']==(BUFFER if blocks==2 and offset==0 else BOUNCE)
            assert not any(a in (PROTOCOL,ADMA_ADDRESS) for pc,a,v in writes)
            assert {a for pc,a,v in writes if pc==0x8006a54e}=={MIX}
            assert not any(a in (VENDOR,VENDOR2) for pc,a,v in writes)
            assert word(r.m,IRQ_SIGNAL)==0 # Original IRQ handler masks signals.
            cases.append(dict(op=op,blocks=blocks,offset=offset,submissions=data))
    passed('original_direct_and_bounce_transfers_program_DS_ADDR_and_actual_MIX_CTRL_for_simple_DMA',
           cases=cases,limitation='Simple DMA interpretation assumes restored PROT_CTRL and VEND_SPEC2; no memory bus simulation')

    for protocol,vendor2 in ((0x220,0),(0x20,AUTO23_ARGUMENT),(0,0)):
        r,result,reads,writes,submissions,cache,order=transfer_trace(2,2,protocol=protocol,vendor2=vendor2)
        assert result==0 and submissions[0]['protocol']==protocol and submissions[0]['vendor2']==vendor2
        assert not any(a in (PROTOCOL,VENDOR2,ADMA_ADDRESS) for pc,a,v in writes)
    passed('negative_seeded_ADMA_auto23_argument_and_endian_modes_are_not_repaired_by_transfer_submission',
           limitation='Synthetic waits report success; these seeds do not demonstrate a valid physical transfer')

    r,result,reads,writes,submissions,cache,order=transfer_trace(2,2)
    assert result==0 and [v for pc,a,v in cache]==list(range(BUFFER,BUFFER+1024,32))
    assert order[:32]==[('cache',a) for a in range(BUFFER,BUFFER+1024,32)] and order[32][0]=='command'
    barriers=[(i.address,i.mnemonic) for i in instructions(0x80069f52,0x80069fa6) if i.mnemonic in ('dsb','isb')]
    assert barriers==[(0x80069f52,'dsb'),(0x80069f9e,'dsb'),(0x80069fa2,'isb')]
    passed('aligned_direct_read_performs_32_byte_cache_register_sequence_before_command_with_DSB_and_ISB',
           limitation='Cache effects, MPU attributes and bus access are not emulated')

    r=Probe();put32(r.m,IRQ_STATUS,2);at_address=[]
    reads,writes=observe_mmio(r)
    def address_programmed(uc,access,address,size,value,user):
        at_address.append((value,word(r.m,IRQ_STATUS)))
    r.m.uc.hook_add(UC_HOOK_MEM_WRITE,address_programmed,begin=DMA_ADDRESS,end=DMA_ADDRESS)
    assert r.request()==0 and at_address[0]==(BUFFER,2)
    address_index=next(i for i,(_,a,_) in enumerate(writes) if a==DMA_ADDRESS)
    ack_index=next(i for i,(_,a,_) in enumerate(writes) if a==IRQ_STATUS)
    assert address_index<ack_index and writes[ack_index][0]==0x8006a526
    passed('negative_seeded_old_TC_remains_at_DS_ADDR_programming_before_stock_command_acknowledgement',
           limitation='Native sequence assumes earlier completion was drained; no W1C or dynamic-address hardware effects simulated')

    r,result,reads,writes=setup(CLOCK_STABLE|0x207,protocol=0x226)
    assert result==0 and r.events==[('delay',1)]*10
    assert word(r.m,SYSTEM)&(RESET_ALL|INITIAL_CLOCKS)==RESET_ALL|INITIAL_CLOCKS
    assert word(r.m,PRESENT)==CLOCK_STABLE|0x207 and word(r.m,HOST+4)==0
    assert word(r.m,PROTOCOL)==0x03000220 and word(r.m,MIX)==0x101
    assert word(r.m,VENDOR)==1 and word(r.m,VENDOR2)==0x20
    assert word(r.m,IRQ_ENABLE)==word(r.m,IRQ_SIGNAL)==0
    assert not any(a in (DMA_ADDRESS,ADMA_ADDRESS,WATERMARK,MIX) for pc,a,v in writes)
    assert not any(a==SYSTEM and pc>=0x80069b9c and pc<0x80069c14 for pc,a,v in reads)
    passed('boot_controller_setup_returns_zero_after_inhibit_poll_exhaustion_and_requests_initial_clocks_while_reset_remains_set',
           limitation='Reset and inhibit state are independent synthetic registers')

    for active in (0,4,0x100,0x200,0x204):
        r,result,reads,writes=setup(CLOCK_STABLE|active)
        assert result==0 and not r.events and word(r.m,SYSTEM)&RESET_ALL
        assert word(r.m,PRESENT)==CLOCK_STABLE|active
        assert [(pc,v) for pc,a,v in reads if a==PRESENT and 0x80069b9c<=pc<0x80069c14]==[(0x80069b9c,CLOCK_STABLE|active)]
    passed('boot_controller_setup_polls_only_command_data_inhibit_and_does_not_check_reset_bit_or_transfer_activity')

    for clear_reset in (False,True):
        for clock in (0,CLOCK_STABLE):
            r,result,reads,writes=setup(clock|0x207,clear_reset,existing=True)
            assert result==0 and word(r.m,HOST+4)==0 and word(r.m,PRESENT)==clock|0x207
            assert bool(word(r.m,SYSTEM)&RESET_ALL)==(not clear_reset)
            assert len(r.events)==(1 if clear_reset else 10)+(0 if clock else 10)
            assert not any(a==PRESENT and 0x80069a9a<=pc<0x80069b12 for pc,a,v in reads)
            assert not any(a in (PROTOCOL,DMA_ADDRESS,ADMA_ADDRESS,MIX,WATERMARK) for pc,a,v in writes)
    passed('existing_controller_reset_callback_discards_event_handle_and_returns_zero_for_both_reset_completion_and_timeout',
           limitation='Clock arithmetic and reset self-clear modeled; no card reinitialization occurs in this callback')

    r,result,reads,writes=setup()
    assert result==0
    result,trace,deletes=event_create(r)
    assert result==0 and trace==[('semaphore',0),('NVIC_enable',0,1<<14,0x80033e52),('event',0)]
    assert word(r.m,HOST+4)==EVENT and word(r.m,HOST+8)==0x7003 and not deletes
    passed('actual_event_setup_enables_IRQ110_before_storing_new_completion_event_handle',
           limitation='No automatic NVIC delivery; this ordering alone does not prove a boot race')

    for semaphore,event,expected_trace in ((0,EVENT,['semaphore']),(0x7003,0,['semaphore','NVIC_enable','event'])):
        r,result,reads,writes=setup()
        result,trace,deletes=event_create(r,semaphore,event)
        assert result==1 and [t[0] for t in trace]==expected_trace
        assert word(r.m,HOST+4)==word(r.m,HOST+8)==0
        assert deletes==([semaphore] if semaphore else [])
        assert word(r.m,NVIC_ENABLE)==((1<<14) if semaphore else 0)
    passed('failed_event_creation_deletes_semaphore_but_has_no_matching_NVIC_disable',
           limitation='Fixture observes requested NVIC writes, not actual interrupt enable/pending state')

    r,result,reads,writes=setup();posts=[]
    put32(r.m,IRQ_STATUS,2);put32(r.m,IRQ_SIGNAL,2)
    r.m.hooks[0x80032828]=lambda a:posts.append(tuple(a[:2])) or 0
    r.m.invoke(0x8006ea90,[])
    assert posts==[(0,4)]
    passed('negative_forced_IRQ_before_event_recreation_posts_completion_to_zero_handle',
           limitation='IRQ explicitly injected after reset; not evidence it occurs during stock boot')

    r,result,reads,writes=setup(clear_reset=True,existing=True)
    assert result==0 and event_create(r)[0]==0
    put32(r.m,PRESENT,0);put32(r.m,SD+0x10,0x100)
    r.m.hooks.pop(0x8006a348)
    def wait(a):
        assert r.held and a[0]==EVENT and a[1] in (0x183,0x185)
        put32(r.m,a[3],2 if a[1]==0x183 else 4);return 0
    r.m.hooks[0x800328c0]=wait
    assert r.request()==0 and not r.held
    passed('original_transfer_can_run_after_modeled_reset_and_explicit_event_recreation',
           limitation='Card-ready response and wait events injected; card init, reset effects and durability not recovered')

    for width,value in ((0,0),(1,2),(2,4),(3,None)):
        r=Sd();put32(r.m,PROTOCOL,0x03000226)
        assert r.m.invoke(0x8006a718,[width])==(1 if value is None else 0)
        assert word(r.m,PROTOCOL)==(0x03000226 if value is None else 0x03000220|value)
    passed('stock_bus_width_callback_preserves_DMA_selection_endian_and_wakeup_bits')

    windows=[(0x800699b8,0x80069a12),(0x80069a18,0x80069b18),
             (0x80069b20,0x80069c4e),(0x8006a522,0x8006a554),
             (0x8006a718,0x8006a75a),(0x80033e08,0x80033e5a)]
    lines=[]
    for a,b in windows:
        lines.append(f'\n# {a:08x}..{b:08x}')
        lines.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(a,b))
    (ROOT/'analysis/sd_controller_setup_disassembly.txt').write_text('\n'.join(lines)+'\n')
    out=ROOT/'analysis/sd_controller_setup_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),limitations=[
      'Original firmware instructions run with synthetic MMIO, kernel endpoints and clock-divider arithmetic',
      'No reset, W1C, DMA, cache, NVIC delivery, card initialization or persistence side effects simulated',
      'Generic ARM/VFP emulator for double-precision init arithmetic; M7 fixture for transfer/IRQ/event probe',
      'Candidate headers and NXP SDK do not identify installed silicon or guarantee applicable reset semantics',
      'No controller recovery binding, deployment image, hardware access or installation']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out)),indent=2))

if __name__=='__main__':main()
