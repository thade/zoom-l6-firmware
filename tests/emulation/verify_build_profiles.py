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
placement_profiles=('capture-only-placement','capture-only-startup','capture-only-hooks','capture-only-minimal','capture-only-composed','capture-only-storage','capture-only-transitions')
startup_profiles=('capture-only-startup','capture-only-hooks','capture-only-minimal','capture-only-composed','capture-only-storage','capture-only-transitions')
arena_profiles=('capture-only-heap','capture-only-segmented','capture-only-composed','capture-only-storage','capture-only-transitions')
profiles=('capture-only','capture-only-heap','capture-only-segmented',*placement_profiles,'handoff')
for profile in profiles:
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
    assert not any(n.startswith(('storage_boot_','boot_probe_')) for n in names)
    assert ('native_arena_alloc' in names)==(profile in arena_profiles[:2])
    assert ('native_arena_bytes' in names)==(profile in arena_profiles[:2])
    assert ('native_arena_alloc_external' in names)==(profile in arena_profiles)
    assert ('placement_tap_hook' in names)==(profile in placement_profiles)
    assert ('placement_commit_hook' in names)==(profile in placement_profiles)
    assert ('startup_status' in names)==(profile in startup_profiles)
    assert ('startup_arena' in names)==(profile in arena_profiles[2:])
    assert any(n.startswith('storage_lease_') for n in names)==(profile in ('capture-only-storage','capture-only-transitions'))
    assert ('storage_transition_try' in names)==(profile=='capture-only-transitions')
    assert ('storage_main_receive' in names)==(profile=='capture-only-transitions')
    assert ('bridge_close_storage' in names)==(profile in ('capture-only-storage','capture-only-transitions'))
    assert ('startup_init_hook' in names)==(profile in startup_profiles)
    assert ('startup_idle_hook' in names)==(profile in startup_profiles)
    assert ('emulator_tap_hook' in names)==(profile not in startup_profiles)
    assert ('emulator_commit_hook' in names)==(profile not in startup_profiles)
assert {'pc_init','pc_stock_execute','dependency_read','dependency_write',
        'sdp_read','sdp_wait','sdp_irq_hook','sdp_stop_join','sdp_stop_begin',
        'sdp_stop_state','sdp_join_port','sdp_recovery_join','sdp_recovery_admit',
        'sdp_recovery_state','sdp_admit_port','sdp_kernel_port',
        'sdp_event_drain','sdp_event_state','sdp_finish_port',
        'sdp_cache_read_complete','sdp_cache_read_port',
        'sdp_chunk_finish_port','sdp_chunk_state','sdp_chunk_admit_port',
        'sdp_native_admit','sdp_native_chunk_join','sdp_admission_state',
        'sdp_program_direct_read','sdp_program_bounce_read',
        'sdp_program_direct_write','sdp_program_bounce_write'}<=symbols('handoff-test')
retained=symbols('capture-only-sd-retained')
assert {'storage_main_receive','native_arena_alloc_external','sdp_read','sdp_write',
        'sdp_wait','sdp_irq_hook','sdp_native_admit','sdp_native_chunk_join',
        'sdp_source_port','sdp_cache_read_complete'}<=retained
assert not any(n.startswith(('sdp_stop_','sdp_recovery_','backing_','bn_')) for n in retained)
assert 'sdp_join_port' not in retained and 'sdp_finish_port' not in retained
new_profiles=('capture-only-source-reuse','capture-only-boot-witness','capture-only-boot-probe')
for profile in new_profiles:
    names=symbols(profile)
    assert {'storage_main_receive','native_arena_alloc_external','sdp_source_port','sdp_native_admit'}<=names
    assert not any(n.startswith(('sdp_stop_','sdp_recovery_','backing_','bn_','od_')) for n in names)
    assert ('storage_boot_ready' in names)==(profile!='capture-only-source-reuse')
    assert ('boot_probe_query' in names)==(profile=='capture-only-boot-probe')
    assert ('boot_probe_polls' in names)==(profile=='capture-only-boot-probe')
print(json.dumps(dict(passed_groups=len(profiles)+5,profiles=[*profiles,'handoff-test','capture-only-sd-retained',*new_profiles])))
