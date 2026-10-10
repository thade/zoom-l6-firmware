#!/usr/bin/env python3
"""Reuse consumed boot data for combined code/globals. JSON only, no BIN.

Physical source admission is unchanged. This separate experiment removes the
proposed code/global gap intervals, conditional on one-shot scatter-data lifetime.
"""
import json
from capture_jump_patches import ROOT,SCATTER
from plan_capture_lz4 import packing
from plan_capture_sd_retained import plan as combined

ELF=ROOT/'src/capture/capture-only-source-reuse.elf'

def plan(pack=None,*,elf_path=ELF):
    p=packing(elf_path,source_reuse=True) if pack is None else pack
    assert p['source_reuse']
    result=combined(p,elf_path=elf_path)
    j=p['jumps']
    result.update(status='offline_consumed_source_reuse_not_deployable',
        reuse=dict(code=[j['candidate_code_start'],j['candidate_load_end']],
            globals=[j['globals_start'],j['globals_end']],
            live_loader=[SCATTER[0],SCATTER[0]+len(p['loader'])],
            consumed_DSP_input=[p['dsp_source'],p['dsp_source']+len(p['packed_dsp'])],
            unread_code_input=[p['code_source'],p['end']],
            order=['expand original DSP','expand combined code over consumed DSP input','zero globals over consumed DSP input'],
            additional_code_or_global_gap_bytes=0),
        limitations=[
            'No device image or physical-source admission. Ordinary block hooks still require unbound ports.',
            'This reuses only consumed original MAIN-loaded data; startup reentry without reloading the image is unsupported.',
            'Every write must follow DSP expansion and avoid live loader/unread code input; checks are required, not inferred from fit.',
            'Diagnostic16 qualifies only an eight-byte source-reuse marker and 16 zero bytes on hardware; full-payload publication, later indirect consumers and bootloader behavior remain to qualify.',
            'History-tail ownership, native buffer/cache/source joining, stack/timing and worker release remain separate gates.'])
    return result

if __name__=='__main__':
    r=plan();out=ROOT/'analysis/capture_source_reuse_plan.json'
    out.write_text(json.dumps(r,indent=2)+'\n')
    print(json.dumps(dict(raw_code_bytes=r['raw_code_bytes'],globals_bytes=r['globals_bytes'],
        lz4_spare_bytes=r['packing']['spare_bytes'],reuse=r['reuse'],report=str(out))))
