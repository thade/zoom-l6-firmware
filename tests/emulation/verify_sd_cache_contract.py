#!/usr/bin/env python3
"""Stock MPU/cache paths and opt-in read-cache experiment, entirely offline.

Unicorn does not implement a physical cache, DMA or MPU permissions here.
The stale-line case explicitly supplies those effects as a negative control.
It tests ordering under the live native stack/token, not hardware completion.
"""
import hashlib,json,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC
from verify_overdub_prototype import Emulator
from verify_sd_transfer_lifetime import Sd,BUFFER,HOST,EVENT
from verify_sd_transfer_probe import Probe,BOUNCE
from verify_pad_protocol import ROOT,IMAGE
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_storage_lifetimes import instructions
from sd_registers import DMA_ADDRESS,BLOCKS,MIX

CCR,CCSIDR=0xe000ed14,0xe000ed80
MPU_CONTROL,MPU_BASE,MPU_ATTRIBUTE=0xe000ed94,0xe000ed9c,0xe000eda0
INVALIDATE,CLEAN,CLEAN_INVALIDATE=0xe000ef5c,0xe000ef68,0xe000ef70
EXPECTED=[(0x10,0x1010003f),(0x80000011,0x03100039),
 (0x60000012,0x03100039),(0x13,0x0310003b),(0x14,0x0303001d),
 (0x20000015,0x03030021),(0x20200016,0x03030023),
 (0x20240017,0x0303001f),(0x20250018,0x0303001d),
 (0x20280019,0x03030023),(0x8000001a,0x03030031),
 (0x4000001b,0x0310002b),(0x4200001c,0x03100027)]

def stock_mpu(ccr=0,ways=4,sets=256):
    m=Emulator();m.uc.mem_map(0xe000e000,0x1000)
    put32(m,CCR,ccr);put32(m,CCSIDR,((sets-1)<<13)|((ways-1)<<3)|1)
    writes=[];base=None;pairs=[]
    def written(uc,access,address,size,value,user):
        nonlocal base
        assert size==4
        writes.append((uc.reg_read(UC_ARM_REG_PC),address,value))
        if address==MPU_BASE:base=value
        if address==MPU_ATTRIBUTE:
            assert base is not None;pairs.append((base,value));base=None
    m.uc.hook_add(UC_HOOK_MEM_WRITE,written,begin=0xe000ed00,end=0xe000ef78)
    m.invoke(0x8001b320,[]) # void board MPU/cache setup; R0 is not a status.
    assert pairs==EXPECTED and word(m,MPU_CONTROL)==5
    assert word(m,CCR)&0x30000==0x30000
    return m,writes,pairs

def region(rbar,rasr):
    size=1<<(((rasr>>1)&31)+1)
    return dict(number=rbar&15,base=(rbar&~31)&~(size-1),bytes=size,
                enabled=rasr&1,subregions=(rasr>>8)&255,xn=(rasr>>28)&1,
                access=(rasr>>24)&7,tex=(rasr>>19)&7,shareable=(rasr>>18)&1,
                cacheable=(rasr>>17)&1,bufferable=(rasr>>16)&1,
                rbar=rbar,rasr=rasr)

def covering(regions,address):
    candidates=[]
    for r in regions:
        if r['enabled'] and r['base']<=address<r['base']+r['bytes']:
            sub=(address-r['base'])*8//r['bytes']
            if r['bytes']<256 or not r['subregions']&(1<<sub):candidates.append(r)
    return max(candidates,key=lambda r:r['number'])

def stock_transfer(op,blocks=2,offset=0):
    r=Sd();m=r.m;trace=[]
    m.hooks.pop(0x8006a348);put32(m,0x402c0010,0x100)
    def written(uc,access,address,size,value,user):
        trace.append(dict(kind='dma' if address==DMA_ADDRESS else 'cache',
                          pc=uc.reg_read(UC_ARM_REG_PC),address=address,value=value))
    m.uc.hook_add(UC_HOOK_MEM_WRITE,written,begin=INVALIDATE,end=0xe000ef78)
    m.uc.hook_add(UC_HOOK_MEM_WRITE,written,begin=DMA_ADDRESS,end=DMA_ADDRESS)
    def wait(a):
        assert r.held and a[0]==EVENT and a[4]==5000
        trace.append(dict(kind='wait',mask=a[1],dma=word(m,DMA_ADDRESS),
                          block=word(m,BLOCKS),mix=word(m,MIX)))
        put32(m,a[3],2 if a[1]==0x183 else 4);return 0
    m.hooks[0x800328c0]=wait
    assert r.request(op,blocks,offset)==0 and not r.held
    return trace

class CacheRead(Probe):
    def __init__(self,enabled=True,advance_dma=False):
        super().__init__();self.invalidate=[];self.fresh={};self.stale=[]
        self.advance_dma=advance_dma
        if enabled:put32(self.m,self.syms['sdp_cache_read_port'],self.syms['sdp_cache_read_complete']|1)
        def written(uc,access,address,size,value,user):
            assert size==4 and self.held and self.state()['active']
            assert not self.state()['failed']
            self.invalidate.append(value)
            assert value in self.fresh,'Invalidation outside modeled owned read lines'
            # Explicit MODEL cache side effect: invalidate the stale CPU line,
            # making independently supplied DMA bytes visible to later reads.
            uc.mem_write(value,self.fresh[value])
        self.m.uc.hook_add(UC_HOOK_MEM_WRITE,written,begin=INVALIDATE,end=INVALIDATE)
    def deliver(self,a):
        result=super().deliver(a)
        dma=word(self.m,DMA_ADDRESS);block=word(self.m,BLOCKS)
        if a[1]==0x185 and word(self.m,MIX)&0x11==0x11 and dma!=BOUNCE:
            n=(block&0x1fff)*(block>>16)
            assert dma%32==n%32==0 and self.held
            for address in range(dma,dma+n,32):
                self.fresh[address]=bytes((i+address//32)&255 for i in range(32))
            # MODEL an intervening speculative refill with old CPU data. This
            # is not evidence such a refill occurred on the physical mixer.
            self.m.uc.mem_write(dma,b'\xa5'*n);self.stale.append((dma,n))
            if self.advance_dma:put32(self.m,DMA_ADDRESS,dma+n)
        return result

def main():
    checks=[]
    def passed(case,**kw):checks.append(dict(case=case,passed=True,**kw))
    m,writes,pairs=stock_mpu();regions=[region(*p) for p in pairs]
    passed('original_board_setup_programs_all_thirteen_MPU_regions_and_enables_both_caches',regions=regions,
           physical_permissions_emulated=False)
    m,writes,_=stock_mpu(0x30000,2,2)
    assert any(a==0xe000ef74 for pc,a,v in writes) # clean+invalidate old D-cache by set/way
    assert any(a==0xe000ef60 for pc,a,v in writes) # invalidate before enabling D-cache
    assert next(i for i,(pc,a,v) in enumerate(writes) if a==MPU_CONTROL)>next(
        i for i,(pc,a,v) in enumerate(writes) if a==CCR and not v&0x30000)
    passed('setup_disables_and_maintains_preexisting_caches_before_changing_MPU',
           cache_geometry='two ways/two sets explicitly modeled; installed geometry unmeasured')
    probes=dict(code=0x800b6b00,globals=0x80960080,heap_start=0x808e2fe0,
                heap_end=0x8095ffd7,ordinary_ring=0x81429800,last_history_end=0x81b7c800-1)
    for a in probes.values():
        r=covering(regions,a)
        assert r['number']==10 and r['base']==0x80000000 and r['bytes']==0x2000000
        assert (r['tex'],r['shareable'],r['cacheable'],r['bufferable'],r['xn'],r['access'])==(0,0,1,1,0,3)
    r=covering(regions,BOUNCE)
    assert r['number']==5 and (r['tex'],r['shareable'],r['cacheable'],r['bufferable'])==(0,0,1,1)
    passed('highest_SDRAM_region_covers_proposed_code_globals_heap_and_history_as_normal_writeback_memory',
           addresses=probes,native_bounce_region=r['number'],
           limitation='MPU attributes do not establish allocation, silicon extent, TCM bus reachability or alias exclusion')

    for op,cache_register in ((2,CLEAN_INVALIDATE),(3,CLEAN)):
        trace=stock_transfer(op,8)
        cache=[t for t in trace if t['kind']=='cache']
        assert [(t['address'],t['value']) for t in cache]==[(cache_register,a) for a in range(BUFFER,BUFFER+4096,32)]
        first_dma=next(i for i,t in enumerate(trace) if t['kind']=='dma')
        assert all(t['kind']=='cache' for t in trace[:first_dma]) and first_dma==128
        assert not any(t['kind']=='cache' for t in trace[first_dma:])
        a,b=(0x80069f52,0x80069fa6) if op==2 else (0x8006ab5a,0x8006abae)
        assert [i.mnemonic for i in instructions(a,b) if i.mnemonic in ('dsb','isb')]==['dsb','dsb','isb']
        passed('original_direct_'+('read_cleans_and_invalidates' if op==2 else 'write_cleans')+'_all_lines_before_DS_ADDR_only',
               cache_register=cache_register,lines=len(cache),post_read_invalidation_present=False if op==2 else None)
    cases=[]
    for op in (2,3):
        for n,offset in ((1,0),(2,4),(2,1),(9,1)):
            trace=stock_transfer(op,n,offset)
            assert not any(t['kind']=='cache' for t in trace)
            waits=[t for t in trace if t['kind']=='wait' and t['mask']==0x185]
            assert waits and all(t['dma']==BOUNCE for t in waits)
            assert sum(t['block']>>16 for t in waits)==n
            cases.append(dict(op=op,blocks=n,offset=offset,data_waits=len(waits)))
    passed('original_short_and_unaligned_transfers_use_CPU_bounce_copies_without_SCB_line_maintenance',cases=cases)

    r=CacheRead(False);assert r.request()==0 and r.stale and not r.invalidate
    assert bytes(r.m.uc.mem_read(BUFFER,1024))==b'\xa5'*1024
    passed('negative_control_original_read_can_return_modeled_stale_cache_lines_after_pretransfer_maintenance',
           reproduced_hardware_defect=False,physical_cache_effects_explicitly_modeled=True)
    r=CacheRead();assert r.request(blocks=8)==0 and len(r.invalidate)==128
    assert r.invalidate==list(range(BUFFER,BUFFER+4096,32))
    assert bytes(r.m.uc.mem_read(BUFFER,4096))==b''.join(r.fresh[a] for a in r.invalidate)
    assert not r.held and not r.state()['failed'] and r.state()['finished']
    passed('opt_in_compiled_invalidation_makes_modeled_DMA_bytes_visible_inside_live_native_read_frames',
           lines=128,physical_completion_still_modeled=True)
    r=CacheRead(advance_dma=True);assert r.request()==0
    assert word(r.m,DMA_ADDRESS)==BUFFER+1024
    assert r.invalidate==list(range(BUFFER,BUFFER+1024,32))
    passed('post_read_invalidation_uses_precommand_start_even_when_modeled_DS_ADDR_advances',
           actual_DS_ADDR_progress_behavior_unmeasured=True)
    class StaleTc(CacheRead):
        def deliver(self,a):
            result=super().deliver(a)
            if a[1]==0x185:
                # An old operation-wide TC and a software success event cannot
                # substitute for this command's raw completion observation.
                self.seed(raw=self.state()['raw']|2)
                put32(self.m,0x402c0030,0);put32(self.m,EVENT+8,4);return 0
            return result
    r=StaleTc();assert r.request()!=0 and not r.invalidate and r.state()['failed']
    passed('old_operation_wide_TC_plus_software_success_does_not_satisfy_new_read_command_latch',
           physical_prior_IRQ_join_still_modeled=True)
    for fault in ('hidden_error','timeout'):
        r=CacheRead();r.fault=(0x185,fault)
        assert r.request()!=0 and not r.invalidate and r.state()['failed'] and r.state()['joined']
    passed('hidden_raw_error_and_timeout_never_publish_or_invalidate_as_a_successful_read')
    r=CacheRead();r.fault=(0x185,'hidden_error');r.pending=True
    r.request()
    assert r.held and r.state()['active'] and r.state()['failed'] and not r.invalidate
    assert not r.state()['finished'] and not r.state()['joined']
    assert r.resume()!=0 and not r.held and not r.invalidate and r.state()['joined']
    passed('unresolved_read_fault_retains_native_stack_and_unit_without_cache_publication_until_modeled_join')
    for op,n,off in ((3,8,0),(2,1,0),(2,9,1)):
        r=CacheRead();assert r.request(op,n,off)==0 and not r.invalidate
    passed('opt_in_read_maintenance_skips_writes_and_exact_native_bounce_storage')
    r=Probe();m=r.m;writes=[]
    m.uc.hook_add(UC_HOOK_MEM_WRITE,lambda uc,a,p,s,v,u:writes.append((p,v)),begin=INVALIDATE,end=INVALIDATE)
    for address,n in ((0,32),(BUFFER,0),(BUFFER+1,512),(BUFFER,513),(0xffffffe0,64)):
        assert m.invoke(r.syms['sdp_cache_read_complete'],[address,n])==12 and not writes
    passed('compiled_leaf_rejects_zero_unaligned_partial_line_and_wrapping_ranges_without_MMIO')
    # The positive leaf is not a cache-coherency or completion proof. Pin its
    # barriers and invalidate-only register so it cannot clean stale read data
    # back over newer DMA bytes after completion.
    start=r.syms['sdp_cache_read_complete']&~1
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
    from elftools.elf.elffile import ELFFile
    from verify_sd_transfer_probe import ELF
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    with ELF.open('rb') as f:
        size=ELFFile(f).get_section_by_name('.symtab').get_symbol_by_name('sdp_cache_read_complete')[0]['st_size']
    body=list(md.disasm(bytes(m.uc.mem_read(start,size)),start))
    assert [i.mnemonic for i in body if i.mnemonic in ('dsb','isb')]==['dsb','dsb','isb']
    passed('compiled_read_completion_leaf_retains_DSB_DSB_ISB_and_invalidate_only_sequence')

    windows=((0x8001b320,0x8001b628),(0x80067a60,0x80067a70),
             (0x80069f42,0x8006a11e),(0x8006ab44,0x8006ad24))
    lines=[]
    for a,b in windows:
        lines.append(f'\n# {a:08x}..{b:08x}')
        lines.extend(f'{i.address:08x} {i.mnemonic:10} {i.op_str}' for i in instructions(a,b))
    (ROOT/'analysis/sd_cache_contract_disassembly.txt').write_text('\n'.join(lines)+'\n')
    out=ROOT/'analysis/sd_cache_contract_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(checks),results=checks,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),device_access=False,
      limitations=['Original MPU programming is traced, not physically enforced or read back',
       'Native direct and bounce paths use modeled command/data outcomes; no real elapsed time or bus accesses',
       'Stale CPU lines and DMA-visible bytes are explicit synthetic effects, not reproduced mixer faults',
       'Opt-in leaf assumes a joined transfer and exclusive aligned cache-line ownership; it supplies neither',
       'Raw TC freshness, IRQ/post exclusion, storage transitions and physical ownership remain unbound',
       'Normal builds and installed diagnostic exclude this experiment; no firmware image or device change']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(checks),report=str(out))))

if __name__=='__main__':main()
