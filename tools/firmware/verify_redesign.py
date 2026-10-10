#!/usr/bin/env python3
"""Build and verify the capture-first redesign locally. No device operations."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
# Suites import planners/builders by module name; do not rely on the caller's shell.
ENV=dict(os.environ,PYTHONPATH=os.pathsep.join(filter(None,[str(ROOT/'tools/firmware'),os.environ.get('PYTHONPATH')])))
def run(*args):
    return subprocess.run([sys.executable,*args],cwd=ROOT,env=ENV,text=True,capture_output=True)
for profile,fixture in (('research',False),('capture-only',False),('handoff',False),('handoff',True)):
    r=run('tools/firmware/build_extra_capture.py','--profile',profile,*(['--test-fixtures'] if fixture else []))
    if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--profile','capture-only','--layout','placement')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--profile','capture-only','--layout','placement','--startup-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--layout','placement','--hooks-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--layout','placement','--hooks-fixture','--minimal-link')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_overdub_prototype.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_capture_io_probe.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--heap-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--segmented-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--composed-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--storage-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--transition-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--sd-retained-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--source-reuse-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_extra_capture.py','--boot-witness-fixture')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/build_boot_probe.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_binding.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/capture_jump_patches.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_packing.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_startup.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_hooks.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_composed.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_lease.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_transitions.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_sd_retained.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/plan_capture_boot.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/audit_capture_ram.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/audit_capture_storage.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/audit_capture_storage_ingress.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
r=run('tools/firmware/audit_native_filesystem.py')
if r.returncode:sys.exit(r.stdout+r.stderr)
names=['build_profiles','capture_performance','native_writer_staging','stock_ring_layout','stock_ring_modes','tap_processing','effect_memory_providers','effect_deferred_providers','extra_capture','extra_lifecycle','history_capture','block_exchange',
       'segmented_exchange','emulator_bridge','bridge_events','audio_invocation','request_router','control_transport',
       'session_handover','session_manager','large_capture_handover','manager_boot','native_worker','storage_ingress',
       'audio_startup','shared_audio','capture_integration','capture_heap','capture_segmented','capture_placement','capture_packing','capture_startup','capture_hooks','capture_minimal','capture_composed','storage_lease','storage_stop','storage_transitions','storage_main','capture_storage','capture_transitions','capture_io_lifetime','native_filesystem','native_filesystem_sd','capture_native_files','native_mount','native_exfat','native_storage_setup','native_startup_boundary','native_rename','simple_handoff','backing_native','handoff_locks',
       'handoff_admission','pad_commands','pad_dispatch','native_event_window','handoff_dependencies',
       'sd_transfer_lifetime','sd_completion','sd_transfer_probe','sd_controller_setup','sd_cold_start','sd_cache_contract','sd_chunk_guard','sd_chunk_admission','sd_card_recovery',
       'sd_checked_recovery','sd_native_event','sd_event_sources',
       'read_producer','read_callback',
       'ordinary_routing','publication_workflow','startup_sites','lz4_packing','capture_sd_retained','capture_boot_cache','sd_enumeration_guard','capture_source_reuse','usb_startup_ack','storage_boot','boot_probe','native_worker_allocation','simple_capture','simple_trial']
results=[]
for name in names:
    r=run(f'tests/emulation/verify_{name}.py')
    result=dict(suite=name,passed=r.returncode==0)
    if r.returncode:
        result['output']=r.stdout+r.stderr
        print(name+': FAIL\n'+result['output'],flush=True)
    else:
        data=json.loads(r.stdout)
        result['groups']=data.get('passed_groups',data.get('groups',0))
        print(f'{name}: PASS ({result["groups"]})',flush=True)
    results.append(result)
report=dict(passed=all(r['passed'] for r in results),suites=len(results),
            groups=sum(r.get('groups',0) for r in results),results=results,
            limitations=['Offline emulation with modeled storage, fence and scheduling ports.',
                         'No firmware image, physical placement or device safety claim.'])
out=ROOT/'analysis/redesign_verification.json';out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ('passed','suites','groups')}),flush=True)
sys.exit(not report['passed'])
