#!/usr/bin/env python3
"""Run the unmodified stock pad renderer through return on an M-class CPU.

Synthetic buffers and schedules, no audio-device IO or installed fence. The
normal callback wrapper runs stock, with its three later DSP stages stubbed.
"""
import hashlib,json,math,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_PROT_NONE,UC_PROT_ALL
from unicorn.arm_const import UC_ARM_REG_PC
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from verify_uncompressed_tap import TapRig,B,packed
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,BIAS

AUDIO=B+0x5404
OUTPUT=B+0x2bb8
RENDERER=0x20220ac8
CALLBACK=0x2022a790
class RendererRig(TapRig):
    def __init__(self,**cpu_options):
        super().__init__(**cpu_options);self.access=[];self.markers=[]
        # Real renderer's ten input delay rings; not physical RAM claims.
        for i in range(10):
            self.m.uc.mem_write(B+0x5864+i*16,struct.pack('<4I',0x21010000+i*0x1000,128,127,0))
        self.m.uc.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,self.observe,begin=AUDIO,end=AUDIO+4*0x3c-1)
        self.m.uc.hook_add(UC_HOOK_MEM_READ,self.observe,begin=0x21028000,end=0x2102c000-1)
        for pc,label in ((RENDERER,'renderer_entry'),(0x2022a796,'renderer_return'),(0x8001078e,'callback_return')):
            self.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u,label=label:self.markers.append((label,len(self.access))),begin=pc,end=pc)
    def observe(self,uc,access,address,size,value,_):
        self.access.append(dict(pc=uc.reg_read(UC_ARM_REG_PC),access=access,address=address,size=size,value=value))
    def word(self,a):return struct.unpack('<I',self.raw(a,4))[0]
    def seed(self,pad=0,length=128,loop=0):
        self.pad(pad,[.25]*64,[-.25]*64)
        p=AUDIO+pad*0x3c
        put32(self.m,p+28,length);put32(self.m,p+32,loop)
        self.floats(0x21028000+pad*0x1000,[i/256 for i in range(128)])
        self.floats(0x21028400+pad*0x1000,[-i/256 for i in range(128)])
    def render(self):
        self.access=[];self.markers=[];self.m.invoke(RENDERER,[])
    def callback(self):
        self.access=[];self.markers=[]
        put32(self.m,B+0x53c8,CALLBACK|1)
        # Keep the whole first stage, including all pad and input-delay work.
        # These three subsequent stages are explicitly outside this experiment.
        for pc in (0x20224b90,0x20220000,0x202263e0,0x80010150):self.m.hooks[pc]=lambda a:0
        self.window(0x8001077c,0x80010792)
    def samples(self,pad=0):
        lo=0x21028000+pad*0x1000
        return [e for e in self.access if lo<=e['address']<lo+0x1000]
    def output(self,pad=0):return self.raw(OUTPUT+pad*512,512)

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    for length in (1,17,64,65,128):
        r=RendererRig();r.seed(length=length)
        for block in range(math.ceil(length/64)):
            r.render();n=min(64,length-block*64)
            assert len(r.samples())==2*n
            values=[i/256 for i in range(block*64,block*64+n)]+[0.]*(64-n)
            assert r.output()==packed(values+[-i/256 for i in range(block*64,block*64+n)]+[0.]*(64-n))
        assert r.word(AUDIO)==0
        r.render();assert not r.samples() and r.output()==bytes(512)
    passed('unmodified_renderer_executes_natural_EOF_for_short_partial_exact_and_multiblock_lengths',lengths=[1,17,64,65,128])

    r=RendererRig();r.seed(length=17);r.render()
    clear=next(i for i,e in enumerate(r.access) if e['pc']==0x20220c2e)
    late=[e for e in r.access[clear+1:] if AUDIO<=e['address']<AUDIO+0x3c]
    assert [e['pc'] for e in late]==[0x20220c4c,0x20220c4e,0x20220c58,0x20220c68,0x20220c6a]
    assert not [e for e in r.access[clear+1:] if 0x21028000<=e['address']<0x21029000]
    passed('natural_inactive_flag_precedes_five_remaining_pad_state_accesses',later_access_pcs=[hex(e['pc']) for e in late])

    for pc in (0x20220b38,0x20220ba4):
        r=RendererRig();r.seed();seen=[]
        def clear_after_active_check(uc,a,n,u):
            if not seen:
                seen.append(len(r.access));put32(r.m,AUDIO,0)
        r.m.uc.hook_add(UC_HOOK_CODE,clear_after_active_check,begin=pc,end=pc)
        r.render();assert seen and r.word(AUDIO)==0 and len(r.samples())==128
        assert all(e['pc'] in (0x20220bb2,0x20220bc8) for e in r.samples())
    passed('negative_control_clearing_active_after_admission_still_allows_full_stereo_block_of_old_buffer_reads')

    for length in (1,17,64,65):
        r=RendererRig();r.seed(length=length,loop=1)
        for block in range(3):
            r.render();assert r.word(AUDIO)==1 and len(r.samples())==128
            values=[((block*64+i)%length)/256 for i in range(64)]
            assert list(struct.unpack('<128f',r.output()))==values+[-v for v in values]
    passed('looping_crosses_end_without_inactive_flag_and_continues_original_buffer_reads')

    r=RendererRig();r.seed();r.floats(AUDIO+0x24,[0.])
    r.render();assert r.word(AUDIO)==1 and len(r.samples())==128 and all(v==0. for v in struct.unpack('<128f',r.output()))
    passed('zero_gain_is_silence_but_not_a_reader_fence')

    r=RendererRig();r.seed(length=128,loop=1);r.floats(AUDIO+0x28,[-1/192])
    for _ in range(4):r.render();assert r.word(AUDIO)==1 and len(r.samples())==128
    assert r.raw(AUDIO+0x24,4)==bytes(4)
    # Execute the actual zero-gain stop path and its original CPSID/CPSIE helpers.
    r.m.invoke(0x80018350,[0]);assert r.word(AUDIO)==0
    r.render();assert not r.samples()
    passed('actual_renderer_fade_reaches_zero_but_only_stock_stop_clears_active')

    r=RendererRig();r.seed(length=17);r.seed(pad=1,length=128,loop=1);r.render()
    assert r.word(AUDIO)==0 and r.word(AUDIO+0x3c)==1
    assert len(r.samples(0))==34 and len(r.samples(1))==128
    passed('one_pad_EOF_does_not_quiesce_other_pads')

    r=RendererRig();r.seed(length=17);r.callback()
    assert [x[0] for x in r.markers]==['renderer_entry','renderer_return','callback_return']
    assert r.markers[1][1]==r.markers[2][1]==len(r.access)
    assert r.word(AUDIO)==0 and len(r.samples())==34
    passed('stock_normal_dispatch_wrapper_returns_after_real_renderer_final_state_access',
           renderer_return='0x2022a796',callback_return='0x8001078e',later_DSP_stages='stubbed')

    r=RendererRig();r.seed(length=17);r.seed(pad=1,length=128,loop=1);r.callback()
    r.m.uc.mem_protect(0x21028000,0x1000,UC_PROT_NONE)
    for _ in range(3):
        r.callback();assert not r.samples(0) and len(r.samples(1))==128
    r.m.uc.mem_protect(0x21028000,0x1000,UC_PROT_ALL)
    passed('later_real_renderer_calls_do_not_access_protected_inactive_pad_buffers_while_another_pad_continues')

    r=RendererRig();r.seed(length=17);r.callback()
    # The fence does not persist if a start path remains admitted.
    r.m.invoke(0x80018310,[0]);r.callback()
    assert len(r.samples())==34
    passed('negative_control_stock_retrigger_after_return_reopens_old_buffer_access')

    r=RendererRig();r.seed();r.m.invoke(0x800181c0,[0])
    assert r.word(AUDIO+4)==0x80e49800 and r.word(AUDIO+8)==0x80f05800
    for pad in range(1,4):
        r.m.invoke(0x800181c0,[pad]);p=AUDIO+pad*0x3c
        assert r.word(p+4)==0x80e49800+pad*0x178000
        assert r.word(p+8)==r.word(p+4)+0xbc000
    passed('stock_sampler_pointer_initializer_uses_fixed_per_pad_stereo_buffer_addresses',
           first_left='0x80e49800',channel_stride='0xbc000',pad_stride='0x178000')

    # Direct references only: never label this a complete indirect-call graph.
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True
    refs=[]
    for data,base in ((IMAGE[0x600:0xa0000],BIAS+0x600),
                      (IMAGE[0x800a9408-BIAS:0x800a9408-BIAS+0xd6dc],0x20220000)):
        for addr,size,mn,op in md.disasm_lite(data,base):
            if mn in ('bl','b','b.w') and op==f'#{RENDERER:#x}':refs.append(hex(addr))
    assert refs==['0x2022a792']
    passed('linear_disassembly_finds_one_direct_renderer_call_in_normal_callback',direct_call_sites=refs,
           limitation='Does not rule out indirect entries, aliases, interrupts or DMA')

    report=dict(passed_groups=len(results),results=results,firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        modifications_to_firmware_bytes=False,
        limitations=['Original renderer executes completely with synthetic pad and input-delay buffers; no physical audio or SD',
          'Normal callback wrapper executes but three subsequent DSP stages and output continuation are stubbed',
          'Injected active-clear interleavings model competing control; no real RTOS/preemption/cache/DMA execution',
          'Return is a candidate acknowledgement site, not an installed fence; new starts and stream work must still be excluded',
          'M-class Cortex-M7 emulator configuration is not physical chipset identification'])
    out=ROOT/'analysis/pad_renderer_boundary_verification.json';out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
