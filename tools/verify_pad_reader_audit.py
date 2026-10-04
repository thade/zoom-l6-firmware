#!/usr/bin/env python3
"""Audit all four recovered audio callbacks using unmodified stock instructions.

Uses Unicorn ARM MAX for double-precision instructions rejected by its M7 model.
This is an instruction-coverage fixture, NOT device/CPU identification or a fence.
"""
import hashlib,json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from unicorn import UC_HOOK_CODE,UC_PROT_NONE,UC_PROT_ALL,UcError,UC_ERR_INSN_INVALID
from unicorn.arm_const import UC_CPU_ARM_MAX,UC_ARM_REG_PC
from verify_pad_renderer_boundary import RendererRig,AUDIO,B,OUTPUT,CALLBACK
from verify_firmware_workflow import put32
from verify_pad_protocol import ROOT,IMAGE,BIAS

SELECTOR=B+0x53c8
SECONDARY=B+0x630c
TARGETS=(CALLBACK,0x80010960,0x800124d8,0x800133e8)
class AuditRig(RendererRig):
    def __init__(self):
        super().__init__(cpu_model=UC_CPU_ARM_MAX,mclass=False)
        put32(self.m,SECONDARY,0x2022a789)
        # Two input pointers consumed by the alternate 0x800124d8 callback.
        put32(self.m,B+0x63a0,0x21030000);put32(self.m,B+0x63a4,0x21031000)
        self.entries=[]
        for fn in (*TARGETS,0x20224b90,0x20220000,0x202263e0,0x8000e380):
            self.m.uc.hook_add(UC_HOOK_CODE,lambda uc,a,n,u:self.entries.append(a),begin=fn,end=fn)
    def full(self,target=CALLBACK,select=True):
        self.access=[];self.markers=[];self.entries=[]
        if select:put32(self.m,SELECTOR,target|1)
        # Stop on original common continuation, after callback return. No DSP
        # stage, secondary callback, math instruction or helper is replaced.
        self.window(0x8001077c,0x8001078e)

def main():
    results=[]
    def passed(case,**data):results.append(dict(case=case,passed=True,**data))
    # Cross-check the existing single-precision renderer evidence on both CPUs.
    for length,loop in ((17,0),(64,0),(65,0),(17,1),(128,1)):
        m7=RendererRig();wide=AuditRig()
        for r in (m7,wide):r.seed(length=length,loop=loop);r.render()
        assert m7.raw(AUDIO,240)==wide.raw(AUDIO,240)
        assert m7.raw(OUTPUT,2048)==wide.raw(OUTPUT,2048)
        assert m7.access==wide.access
    passed('M7_and_ARM_MAX_original_renderer_accesses_state_and_output_agree_for_tested_cases')

    r=RendererRig();r.seed(length=17)
    try:r.m.invoke(CALLBACK,[])
    except UcError as e:
        assert e.errno==UC_ERR_INSN_INVALID and r.m.uc.reg_read(UC_ARM_REG_PC)==0x2022788e
    else:raise AssertionError('Expected known M7 fixture double-precision limit')
    passed('M7_fixture_rejects_stock_double_precision_conversion_without_silent_substitution',pc='0x2022788e',instruction='vcvt.f64.f32 d0,s0')

    r=AuditRig();r.seed(length=17);r.full()
    assert r.entries==[CALLBACK,0x20224b90,0x20220000,0x8000e380,0x202263e0]
    assert len(r.samples())==34 and r.word(AUDIO)==0
    assert r.markers[-1]==('callback_return',len(r.access))
    assert r.markers[1][0]=='renderer_return' and r.markers[1][1]==len(r.access)
    passed('complete_normal_callback_including_later_DSP_and_stock_secondary_target_returns_without_later_pad_access',
           executed_stages=[hex(a) for a in r.entries],effects_fixture='idle/no active effects processor')

    for target in TARGETS:
        r=AuditRig();r.seed(length=17);r.full(target)
        if target in (CALLBACK,0x800133e8):assert len(r.samples())==34 and r.word(AUDIO)==0
        else:assert not r.access and r.word(AUDIO)==1
        assert r.markers[-1][0]=='callback_return'
    passed('all_four_recovered_callbacks_execute_to_shared_return_two_read_pads_in_tested_configuration',
           pad_readers=['0x2022a790','0x800133e8'],other_callbacks=['0x80010960','0x800124d8'])

    for length,loop in ((17,0),(17,1),(64,0),(65,0)):
        r=AuditRig();r.seed(length=length,loop=loop);r.full(0x800133e8)
        assert len(r.samples())==2*(64 if loop else min(length,64))
        assert all(e['pc'] in (0x800134d0,0x800134d8) for e in r.samples())
        if not loop and length<=64:
            i=next(i for i,e in enumerate(r.access) if e['pc']==0x80013544)
            late=[e['pc'] for e in r.access[i+1:] if AUDIO<=e['address']<AUDIO+60]
            assert late==[0x80013562,0x80013566,0x8001356a,0x80013580,0x80013582]
    passed('alternate_renderer_has_its_own_source_reads_and_post_EOF_state_accesses',
           source_loads=['0x800134d0','0x800134d8'],inactive_write='0x80013544')

    r=AuditRig();r.seed(length=128);seen=[]
    def clear(uc,a,n,u):
        if not seen:seen.append(True);put32(r.m,AUDIO,0)
    r.m.uc.hook_add(UC_HOOK_CODE,clear,begin=0x800134c8,end=0x800134c8)
    r.full(0x800133e8);assert seen and r.word(AUDIO)==0 and len(r.samples())==128
    passed('alternate_renderer_also_keeps_reading_after_midblock_active_clear')

    r=AuditRig();r.seed(length=17);r.seed(pad=1,length=128,loop=1);r.full()
    r.m.uc.mem_protect(0x21028000,0x1000,UC_PROT_NONE)
    for target in TARGETS*2:
        r.full(target);assert not r.samples(0)
        assert len(r.samples(1))==(128 if target in (CALLBACK,0x800133e8) else 0)
    r.m.uc.mem_protect(0x21028000,0x1000,UC_PROT_ALL)
    passed('inactive_pad_buffer_stays_unaccessed_across_all_four_full_callbacks_while_other_pad_loops')

    for setter,target in ((0x8000ca98,0x80010960),(0x8000cab0,0x800133e8)):
        r=AuditRig();r.seed(length=17);r.m.invoke(setter,[])
        assert r.word(SELECTOR)==target|1
        r.full(select=False);assert r.entries[0]==target
        assert len(r.samples())==(34 if target==0x800133e8 else 0)
    passed('original_runtime_setters_select_callbacks_without_waiting_for_renderer_or_session_fence')

    r=AuditRig();r.seed(length=128,loop=1);changed=[]
    def replace_after_load(uc,a,n,u):
        if not changed:
            changed.append(True);put32(r.m,SELECTOR,0x800133e9)
    h=r.m.uc.hook_add(UC_HOOK_CODE,replace_after_load,begin=0x8001078c,end=0x8001078c)
    r.full();assert r.entries[0]==CALLBACK and 0x800133e8 not in r.entries and r.word(SELECTOR)==0x800133e9
    r.m.uc.hook_del(h);r.full(select=False);assert r.entries[0]==0x800133e8
    passed('loaded_callback_can_finish_after_selector_changes_then_next_block_uses_replacement',
           implication='A fence must track admitted callback identity and serialize mode changes, not inspect only the current selector')

    r=AuditRig();r.seed(length=17);r.full(0x80010960)
    assert not r.access and r.word(AUDIO)==1
    r.m.invoke(0x8000cab0,[]);r.full(select=False);assert len(r.samples())==34
    passed('negative_control_callback_with_no_pad_access_does_not_prove_future_callbacks_cannot_read_active_pad')

    r=AuditRig();r.seed(length=17);r.full();r.m.uc.mem_protect(0x21028000,0x1000,UC_PROT_NONE)
    put32(r.m,SELECTOR,0);r.full(select=False)
    assert not r.entries and not r.access and r.markers==[('callback_return',0)]
    r.m.uc.mem_protect(0x21028000,0x1000,UC_PROT_ALL)
    passed('null_callback_reaches_same_continuation_without_providing_a_rendered_block')

    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS);md.skipdata=True
    direct=[];secondary=[]
    for data,base in ((IMAGE[0x600:0xa0000],BIAS+0x600),
                      (IMAGE[0x800a9408-BIAS:0x800a9408-BIAS+0xd6dc],0x20220000)):
        for addr,size,mn,op in md.disasm_lite(data,base):
            if mn in ('bl','b','b.w') and op=='#0x80002868':direct.append(hex(addr))
            if mn=='movw' and op.endswith(', #0x630c'):secondary.append(hex(addr))
    assert direct==['0x80006cb4','0x80006f7c','0x80006fda','0x8001d8fa']
    assert secondary==['0x80011e6c','0x800124e2','0x80016884','0x2022000a']
    passed('static_inventory_locates_mode_switch_callers_and_secondary_callback_slot_references',
           alternate_mode_callers=direct,secondary_slot_references=secondary,
           limitation='Linear immediate/direct-reference search is not exhaustive dataflow or indirect-reference proof')

    for producer,slot,buffer,poll,size in ((0x8005b740,0x80445308,0x80445164,0x8005b776,16),
                                            (0x8005b790,0x80445310,0x804451f0,0x8005b7c6,32)):
        r=AuditRig();source=0x21037000;destination=0x21038000
        payload=bytes(range(size));r.m.uc.mem_write(source,payload);observed=[]
        def drain_on_audio_cpu(uc,a,n,u):
            if observed:return
            assert r.word(slot)==destination and r.word(slot+4)==4
            assert r.raw(destination,size)==bytes(size)
            peer=AuditRig()
            peer.m.uc.mem_write(slot,r.raw(slot,8));peer.m.uc.mem_write(buffer,r.raw(buffer,size))
            peer.full() # Actual normal DSP + secondary dispatcher drains request.
            assert peer.raw(destination,size)==payload and peer.raw(slot,8)==bytes(8)
            observed.append(True)
            r.m.uc.mem_write(destination,peer.raw(destination,size))
            r.m.uc.mem_write(slot,peer.raw(slot,8))
        r.m.uc.hook_add(UC_HOOK_CODE,drain_on_audio_cpu,begin=poll,end=poll)
        r.m.invoke(producer,[destination,source,size])
        assert observed and r.raw(destination,size)==payload and r.raw(slot,8)==bytes(8)
    passed('actual_deferred_word_and_double_copy_producers_wait_until_full_audio_callback_drains_requests',
           producers=['0x8005b740','0x8005b790'],slots=['0x80445308','0x80445310'],
           limitation='Peer CPU with explicit shared-state transfer; caller destinations and concurrent producers not exhaustively covered')

    for producer,size in ((0x8005b740,16),(0x8005b790,32)):
        r=AuditRig();put32(r.m,0x801f5f08,1);payload=bytes(range(size))
        r.m.uc.mem_write(0x21037000,payload)
        r.m.invoke(producer,[0x21038000,0x21037000,size])
        assert r.raw(0x21038000,size)==payload and r.raw(0x80445308,16)==bytes(16)
    passed('same_parameter_copy_producers_have_direct_copy_bypass_when_mode_flag_is_set',
           implication='Admission belongs at producer entry, before testing immediate versus deferred path')

    out=ROOT/'analysis/pad_reader_audit_verification.json'
    out.write_text(json.dumps(dict(passed_groups=len(results),results=results,
      firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
      limitations=['Synthetic RAM, routing, delay rings and input buffers; no active effects processor; selected deferred writes only, not all parameter states',
        'No DSP stages or math helpers stubbed in full-callback checks; outer output continuation is not executed',
        'ARM MAX enables required instructions but does not identify device CPU or model hardware interrupts/cache/DMA',
        'Selector-race injection models another writer; actual RTOS priorities and mode admission remain unbound',
        'No installed completion acknowledgement, all-reader fence or hardware changes']),indent=2)+'\n')
    print(json.dumps(dict(passed_groups=len(results),report=str(out)),indent=2))
if __name__=='__main__':main()
