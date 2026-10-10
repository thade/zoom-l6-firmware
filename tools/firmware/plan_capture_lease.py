#!/usr/bin/env python3
"""Plan the offline storage-lease composition; no native release/transition hook."""
import json
from capture_jump_patches import ROOT
from plan_capture_composed import plan as composed_plan
ELF=ROOT/'src/capture/capture-only-storage.elf'
def plan():
    p=composed_plan(ELF,0x809600e8,9887)
    p.update(status='offline_storage_lease_fixture_not_deployable',
        storage_gate='one generation; pin each manager step; nonblocking close/join; retired until reboot',
        limitations=p['limitations']+[
            'Mount/directory results are supplied by an explicit setup observer; no production observer is wired',
            'An outer transition caller must defer its entire native operation before effects; these APIs do not patch those callers',
            'Lower native transfer completion/cache validity remains a mandatory unbound prerequisite',
            'Software lease joining is not physical completion and cannot make early driver unwinding safe'])
    return p
def main():
    p=plan();out=ROOT/'analysis/capture_lease_plan.json'
    out.write_text(json.dumps(p,indent=2)+'\n')
    print(json.dumps(dict(status=p['status'],spare_bytes=p['packing']['spare_bytes'],report=str(out))))
if __name__=='__main__':main()
