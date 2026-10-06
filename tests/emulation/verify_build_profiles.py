#!/usr/bin/env python3
"""Check that current profiles cannot accidentally pull in the legacy overlay."""
from pathlib import Path
from elftools.elf.elffile import ELFFile
import json
ROOT=Path(__file__).resolve().parents[2]
def symbols(profile):
    with (ROOT/f'src/capture/{profile}.elf').open('rb') as f:
        elf=ELFFile(f)
        return {s.name for s in elf.get_section_by_name('.symtab').iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
for profile in ('capture-only','capture-only-placement','capture-only-startup','capture-only-hooks','capture-only-minimal','handoff'):
    names=symbols(profile)
    assert {'bridge_hook','manager_step','native_worker_poll','life_step'}<=names
    assert not any(n.startswith(('od_','pw_','rt_','rp_','rw_','op_','rc_','na_',
                                 'audio_fixture_','history_','manager_publish_')) for n in names)
    assert ('backing_step' in names)==(profile=='handoff')
    assert ('bn_init' in names)==(profile=='handoff')
    assert ('bn_close_hook' in names)==(profile=='handoff')
    assert not any(n.startswith('pc_') for n in names)
    assert not any(n.startswith('dependency_') for n in names)
    assert not any(n.startswith('sdp_') for n in names)
    assert ('placement_tap_hook' in names)==(profile in ('capture-only-placement','capture-only-startup','capture-only-hooks','capture-only-minimal'))
    assert ('placement_commit_hook' in names)==(profile in ('capture-only-placement','capture-only-startup','capture-only-hooks','capture-only-minimal'))
    assert ('startup_status' in names)==(profile in ('capture-only-startup','capture-only-hooks','capture-only-minimal'))
    assert ('startup_init_hook' in names)==(profile in ('capture-only-startup','capture-only-hooks','capture-only-minimal'))
    assert ('startup_idle_hook' in names)==(profile in ('capture-only-startup','capture-only-hooks','capture-only-minimal'))
    assert ('emulator_tap_hook' in names)==(profile not in ('capture-only-startup','capture-only-hooks','capture-only-minimal'))
    assert ('emulator_commit_hook' in names)==(profile not in ('capture-only-startup','capture-only-hooks','capture-only-minimal'))
assert {'pc_init','pc_stock_execute','dependency_read','dependency_write',
        'sdp_read','sdp_wait','sdp_irq_hook','sdp_stop_join','sdp_stop_begin',
        'sdp_stop_state','sdp_join_port','sdp_recovery_join','sdp_recovery_admit',
        'sdp_recovery_state','sdp_admit_port','sdp_kernel_port',
        'sdp_event_drain','sdp_event_state','sdp_finish_port'}<=symbols('handoff-test')
print(json.dumps(dict(passed_groups=7,profiles=['capture-only','capture-only-placement','capture-only-startup','capture-only-hooks','capture-only-minimal','handoff','handoff-test'])))
