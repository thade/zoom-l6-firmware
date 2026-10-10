#!/usr/bin/env python3
"""Build an offline additional-capture ELF; no stock image changes."""
import argparse,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
env=dict(os.environ,ZIG_LOCAL_CACHE_DIR='/tmp/l6-zig-local',ZIG_GLOBAL_CACHE_DIR='/tmp/l6-zig-global')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--profile',choices=('capture-only','handoff','research'),default='capture-only')
parser.add_argument('--test-fixtures',action='store_true',help='Include synthetic DSP for offline tests only')
parser.add_argument('--layout',choices=('emulator','placement'),default='emulator',
                    help='Placement is a candidate address experiment, not an installable image')
parser.add_argument('--startup-fixture',action='store_true',
                    help='Include offline-only registration hooks at candidate RAM addresses')
parser.add_argument('--hooks-fixture',action='store_true',
                    help='Use complete byte-patch replay for offline MAIN audio/control hooks')
parser.add_argument('--minimal-link',action='store_true',
                    help='Drop unreachable research entries in a separate hooks fixture')
parser.add_argument('--heap-fixture',action='store_true',
                    help='Add a native heap arena in a separate offline capture-only ELF')
parser.add_argument('--segmented-fixture',action='store_true',
                    help='Build the external segmented-history arena experiment, offline only')
parser.add_argument('--composed-fixture',action='store_true',
                    help='Combine minimal placement/hooks and external heap arena, offline only; worker stays inactive')
parser.add_argument('--storage-fixture',action='store_true',
                    help='Add one-generation manager storage lease to composed fixture, offline only')
parser.add_argument('--transition-fixture',action='store_true',
                    help='Add offline Main receive binding and native transition executor test seam')
parser.add_argument('--sd-retained-fixture',action='store_true',
                    help='Combine capture/Main with retained-error SD guards; offline only, source admission unbound')
parser.add_argument('--source-reuse-fixture',action='store_true',
                    help='Separate offline retained-SD ELF inside consumed DSP source; no device image')
parser.add_argument('--boot-witness-fixture',action='store_true',
                    help='Add concrete first-Main directory/USB witnesses; no physical admission or release')
parser.add_argument('--boot-probe-fixture',action='store_true',
                    help='Dormant full-payload startup trial with fixed read-only query')
args=parser.parse_args()
if args.boot_probe_fixture:args.boot_witness_fixture=True
if args.boot_witness_fixture:args.source_reuse_fixture=True
if args.source_reuse_fixture:args.sd_retained_fixture=True
if args.sd_retained_fixture:args.transition_fixture=True
if args.transition_fixture:args.storage_fixture=True
if args.storage_fixture:args.composed_fixture=True
if args.composed_fixture:
    if args.profile!='capture-only' or args.test_fixtures or args.heap_fixture or args.segmented_fixture:
        parser.error('composed fixture requires capture-only without other arena/test fixtures')
    args.layout='placement';args.hooks_fixture=True;args.minimal_link=True
if args.heap_fixture and args.segmented_fixture:parser.error('choose one arena fixture')
if (args.heap_fixture or args.segmented_fixture) and (args.profile!='capture-only' or args.layout!='emulator' or
                         args.test_fixtures or args.startup_fixture or args.hooks_fixture):
    parser.error('arena fixtures require capture-only emulator layout without other fixtures')
if args.minimal_link and not args.hooks_fixture:parser.error('minimal link requires the hooks fixture')
if args.hooks_fixture:
    if args.layout!='placement' or args.profile!='capture-only' or args.test_fixtures:
        parser.error('hooks fixture requires capture-only placement without test fixtures')
    args.startup_fixture=True
if args.layout=='placement' and (args.profile!='capture-only' or args.test_fixtures):
    parser.error('placement requires capture-only without test fixtures')
if args.startup_fixture and (args.layout!='placement' or args.profile!='capture-only'):
    parser.error('startup fixture requires capture-only placement')
research=args.profile=='research'
output='src/capture/capture.elf' if research else f'src/capture/{args.profile}.elf'
if args.test_fixtures and not research:output=output.replace('.elf','-test.elf')
if args.layout=='placement':output=output.replace('.elf','-placement.elf')
if args.startup_fixture:output='src/capture/capture-only-startup.elf'
if args.hooks_fixture:output='src/capture/capture-only-hooks.elf'
if args.minimal_link:output='src/capture/capture-only-minimal.elf'
if args.heap_fixture:output='src/capture/capture-only-heap.elf'
if args.segmented_fixture:output='src/capture/capture-only-segmented.elf'
if args.composed_fixture:output='src/capture/capture-only-composed.elf'
if args.storage_fixture:output='src/capture/capture-only-storage.elf'
if args.transition_fixture:output='src/capture/capture-only-transitions.elf'
if args.sd_retained_fixture:output='src/capture/capture-only-sd-retained.elf'
if args.source_reuse_fixture:output='src/capture/capture-only-source-reuse.elf'
if args.boot_witness_fixture:output='src/capture/capture-only-boot-witness.elf'
if args.boot_probe_fixture:output='src/capture/capture-only-boot-probe.elf'
extra=(['tests/fixtures/audio_fixture.c','src/capture/history.c','src/capture/pad_publisher.c','src/overdub/overdub.c']
       if research else ['-DL6_CAPTURE_PRIVATE_FILES'])
if args.profile=='handoff':extra+=['-DL6_BACKING_NATIVE','src/capture/backing_handoff.c',
    'src/capture/backing_native.c','src/capture/backing_native_hooks.S',
    'src/overdub/stock_pad_adapter.c']
if args.profile=='handoff' and args.test_fixtures:
    # Raw-command, synthetic-sector and SD-recovery experiments are test-only.
    # The SD probe's join/IRQ-delivery callbacks have no device implementation.
    extra+=['src/capture/pad_commands.c','tests/fixtures/sd_dependency_route.c',
            'tests/fixtures/sd_transfer_probe.c','tests/fixtures/sd_transfer_probe_hooks.S',
            'tests/fixtures/sd_stop_probe.c','tests/fixtures/sd_recovery_probe.c',
            'tests/fixtures/sd_event_probe.c','tests/fixtures/sd_cache_probe.c',
            'tests/fixtures/sd_admission_probe.c']
if args.test_fixtures and not research:extra+=['tests/fixtures/audio_fixture.c','src/capture/history.c']
if args.heap_fixture or args.segmented_fixture or args.composed_fixture:extra+=['src/capture/native_arena.c']
if args.storage_fixture:extra+=['-DL6_CAPTURE_STORAGE_LEASE','src/capture/storage_lease.c']
if args.transition_fixture:extra+=['src/capture/storage_transition.c','src/capture/storage_main.c']
if args.boot_witness_fixture:extra+=['-DL6_CAPTURE_BOOT_WITNESS',
    'src/capture/storage_boot.c','src/capture/storage_boot_hooks.S']
if args.boot_probe_fixture:extra+=['-DL6_CAPTURE_BOOT_PROBE','src/capture/boot_probe.c',
    'src/diagnostics/health_hooks.S','-DHEALTH_QUERY_CALLBACK=boot_probe_query']
if args.sd_retained_fixture:
    extra+=['-DL6_SD_RETAIN_ONLY','tests/fixtures/sd_transfer_probe.c',
            'tests/fixtures/sd_transfer_probe_hooks.S','tests/fixtures/sd_event_probe.c',
            'tests/fixtures/sd_admission_probe.c','tests/fixtures/sd_cache_probe.c']
if args.layout=='placement':extra+=['src/capture/placement_hooks.S']
if args.startup_fixture:extra+=['-DL6_CAPTURE_STARTUP_FIXTURE',
                              ('tests/fixtures/capture_composed_startup.c' if args.composed_fixture
                               else 'tests/fixtures/capture_startup.c'),
                              'tests/fixtures/capture_startup_hooks.S']
if args.hooks_fixture:extra+=['-DL6_CAPTURE_ENCODED_HOOKS']
if args.minimal_link:
    # Addresses embedded in the patch plan are invisible to linker reachability.
    # Assembly adapters retain their sections; the C patch entries need roots.
    patch_entries=('ct_queue_send','ct_record_request','ct_stop_request','ct_play_request',
                   'ct_stop_argument','ct_stop_other')
    external_controls=('native_worker_release','manager_cancel','manager_resume','manager_copy_result')
    observation_roots=('ct_emulator_admit','extra_init','life_verified_path',
        'extra_layout','life_layout','exchange_layout','bridge_layout',
        'rr_layout','ct_layout','manager_layout','native_worker_layout')
    from plan_capture_hooks import SPECS
    planned_entries={s['adapter'] for s in SPECS if s['adapter'].startswith('ct_')}
    if set(patch_entries)!=planned_entries:parser.error('minimal C patch roots differ from the hook plan')
    roots=patch_entries+external_controls+observation_roots
    if args.composed_fixture:
        roots+=('native_arena_layout','native_arena_bytes_external')
        extra+=['-DL6_CAPTURE_COMPOSED_FIXTURE']
    if args.storage_fixture:
        roots+=('storage_lease_layout','storage_lease_admit','storage_lease_close','storage_lease_join')
    if args.transition_fixture:roots+=('storage_transition_try','storage_main_receive')
    if args.boot_witness_fixture:roots+=('storage_boot_card','storage_boot_usb','storage_boot_ready')
    if args.boot_probe_fixture:roots+=('health_parser',)
    if len(set(roots))!=len(roots):parser.error('duplicate minimal link root')
    extra+=['-DL6_CAPTURE_MINIMAL_LINK','-ffunction-sections','-fdata-sections']
    extra += [f'-Wl,-u,{name}' for name in roots]
linker='tests/fixtures/capture_source_reuse.ld' if args.source_reuse_fixture else f'src/capture/{args.layout}.ld'
subprocess.run([sys.executable,'-m','ziglang','cc','-target','thumb-freestanding-eabihf',
 # Zig 0.13 derives final FPU features from the CPU model. An explicit feature
 # is necessary: -mfpu alone still emitted software __aeabi_fmul calls.
 '-mcpu=cortex_m7+fp_armv8d16sp','-mfpu=fpv5-d16','-mfloat-abi=hard','-Os','-g','-ffreestanding',
 '-fno-builtin','-fno-stack-protector','-nostdlib','-Wall','-Wextra','-Werror',
 f'-Wl,-T,{linker}','-Wl,-e,extra_capture','-Wl,--gc-sections',
 'src/capture/capture.c','src/capture/lifecycle.c',
 'src/capture/block_exchange.c','src/capture/history_storage.c',
 'src/capture/emulator_bridge.c','src/capture/request_router.c',
 'src/capture/control_transport.c',
 'src/capture/session_manager.c',
 'src/capture/native_worker.c',
 *extra,
 'src/capture/emulator_hooks.S',
 '-o',output],
 cwd=ROOT,env=env,check=True)
print(ROOT/output)
