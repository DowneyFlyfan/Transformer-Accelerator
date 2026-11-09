"""Qualify native guidance/full-model switching before parent optimization."""
import csv
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'syn'))
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group

OUT = ROOT / '.cache/physical/pnr/tri_oracle_core_model_switch84'
RESULT = ROOT / 'records/core_model_switch84_result.json'
BASE = ROOT / '.cache/physical/pnr/tri_oracle_sram_memory_compute'
ENTRY = ROOT / 'syn/tri_oracle_probe_core_model_switch.tcl'
started = time.monotonic()
record = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              state='preflight', supervisor_pid=os.getpid(),
              scope='One-core native switch from complete routed model to compact optimization guidance and back, then cold reload. No optimization or timing-correlation claim.',
              guidance_model_final_timing_qualified=False, full_paper_results_matched=False)
child = None
pause = None
log_argument = None
locks = []
stop_requested = False


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def save(**updates):
    record.update(updates, elapsed_seconds=time.monotonic()-started)
    temporary = RESULT.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2)+'\n')
    temporary.replace(RESULT)


def stop(signum, frame):
    global stop_requested
    stop_requested = True


def available():
    return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith('MemAvailable:')))*1024


def anonymous():
    return int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])


def rows(path):
    with Path(path).open() as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def native(directory, checkpoint, cold=False):
    global child, pause, log_argument
    directory.mkdir(parents=True, exist_ok=False)
    log_argument = str(directory/'native')
    console = directory/'console.log'
    environment = dict(os.environ, TRI_ORACLE_MODEL_SWITCH_DIRECTORY=str(directory),
                       TRI_ORACLE_MODEL_SWITCH_INPUT=str(checkpoint),
                       TRI_ORACLE_MODEL_SWITCH_COLD='1' if cold else '0')
    command = ['innovus', '-stylus', '-no_gui', '-batch', '-log', log_argument,
               '-files', str(ENTRY)]
    policy = MemoryPressurePolicy(host_reserve_bytes=7*1024**3,
                                  resume_bytes=8*1024**3, anonymous_limit_bytes=13*1024**3)
    stage_started = time.monotonic()
    with console.open('w') as stream:
        child = subprocess.Popen(command, cwd=directory, env=environment,
                                 stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        pause = OwnedProcessPause(child, log_argument)
        save(state='cold_reload_running' if cold else 'model_switch_running',
             native_process_group=child.pid, command=command)
        while child.poll() is None:
            assert not stop_requested, 'External stop requested'
            assert time.monotonic()-stage_started < 1800, 'Model-switch control wall budget'
            memory, combined = available(), anonymous()
            record['peak_combined_anonymous_bytes'] = max(record.get('peak_combined_anonymous_bytes',0),combined)
            record['minimum_host_available_bytes'] = min(record.get('minimum_host_available_bytes',memory),memory)
            action = policy.observe(memory, combined, time.monotonic())
            if action in ('pause','resume'):
                groups = pause.pause() if action == 'pause' else pause.resume()
                events = record.get('memory_pressure_events',[])+[dict(action=action, groups=groups,
                               host_available_bytes=memory, combined_anonymous_bytes=combined)]
                save(memory_pressure_events=events)
            if time.monotonic()-record.get('last_sample_monotonic',0) > 10:
                save(last_sample_monotonic=time.monotonic())
            time.sleep(.2)
        terminate_process_group(child, log_argument=log_argument)
    marker = ('TRI_ORACLE_MODEL_SWITCH84_COLD_COMPLETE_MODEL_VERIFIED' if cold else
              'TRI_ORACLE_MODEL_SWITCH84_COMPLETE_CORE_RESTORED')
    assert child.returncode == 0 and '\n'+marker+'\n' in console.read_text(errors='replace'), console
    return dict(native_exit_status=child.returncode, elapsed_seconds=time.monotonic()-stage_started,
                native_console_sha256=digest(console), output_directory=str(directory))


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
assert not RESULT.exists(), 'Existing model-switch result must remain immutable'
save()
try:
    assert available() > 16*1024**3 and anonymous() < 3*1024**3, 'Initial memory reserve'
    assert shutil.disk_usage(ROOT).free > 8*1024**3, 'Disk reserve'
    identities = {str(path):digest(path) for path in [ENTRY, Path(__file__),
                  ROOT/'syn/tri_oracle_hierarchy_fingerprint.py',
                  ROOT/'syn/tri_oracle_core_preservation.py',
                  ROOT/'syn/tri_oracle_process_guard.py',
                  ROOT/'syn/tri_oracle_memory_pressure_guard.py',
                  Path('/opt/cadence/INNOVUS251/doc/TCRcom/read_ilm.html')]}
    for name in ['sram_core_checkpoint44_qualification.json','preserved_core_clock35_qualification.json',
                 'sram_core_hierarchy68_full_control_validation.json','sram_core_hierarchy58_export_validation.json']:
        path = ROOT/'records'/name
        identities[str(path)] = digest(path)
    core_q = json.loads((ROOT/'records/sram_core_checkpoint44_qualification.json').read_text())
    parent_q = json.loads((ROOT/'records/preserved_core_clock35_qualification.json').read_text())
    assert parent_q['state'] == 'passed' and parent_q['native_exit_status'] == 0
    models, dependencies = {}, {}
    for number, dirname, filename in [
        (68,'hierarchy_full_control_68','sram_core_hierarchy68_full_control_validation.json'),
        (58,'hierarchy_export_58','sram_core_hierarchy58_export_validation.json')]:
        qualification = json.loads((ROOT/'records'/filename).read_text())
        expected = qualification['output_artifact_fingerprint']
        assert artifact_fingerprint(BASE/dirname) == expected
        models[str(BASE/dirname)] = expected
        dependencies[BASE/dirname/'ilm'] = {'type':'directory','files':{
            key[4:]:value for key,value in expected['files'].items() if key.startswith('ilm/')}}
    assert artifact_fingerprint(ROOT/core_q['output_database']) == core_q['output_database_fingerprint']
    checkpoint = Path(parent_q['output_database'])
    assert hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies) == parent_q['output_database_fingerprint']
    save(source_sha256=identities, input_database=str(checkpoint),
         input_database_fingerprint=parent_q['output_database_fingerprint'])
    for path in [ROOT/'.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock',
                 ROOT/'.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30/physical.guard.lock']:
        lock = path.open('a')
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        locks.append(lock)
    OUT.mkdir(exist_ok=False)
    first = OUT/'switch'
    run = native(first, checkpoint)
    preservation = verify_core_snapshots(first/'full_before.tsv',first/'full_after.tsv',['core0'])
    assert preservation['total_original_cells'] == 94471
    full = {row['instance']:row for row in rows(first/'full_before.tsv')}
    guidance = rows(first/'guidance.tsv')
    assert len(guidance) == 33818 and len({r['instance'] for r in guidance}) == 33818
    assert all(full.get(row['instance']) == row for row in guidance), 'Guidance cells changed physical identity'
    before_clocks = sorted((r['clock'],r['period_ns']) for r in rows(first/'clocks_before.tsv'))
    assert before_clocks and before_clocks == sorted((r['clock'],r['period_ns']) for r in rows(first/'clocks_after.tsv'))
    try:
        verify_core_snapshots(first/'full_before.tsv',first/'guidance.tsv',['core0'])
    except ValueError as error:
        assert 'Expected94471' in str(error), error
        rejected_guidance = str(error)
    else:
        raise AssertionError('Incomplete guidance model was accepted as complete')
    restored = first/'restored_full.db'
    fingerprint = hierarchy_fingerprint(restored,directory_dependencies=dependencies)
    save(state='restored_complete_model_requires_cold_reload', switch_run=run,
         complete_cell_preservation=preservation, guidance_original_subset_cells=len(guidance),
         guidance_rejected_by_complete_core_checker=rejected_guidance,
         output_database=str(restored), output_database_fingerprint=fingerprint)
    cold = OUT/'cold'
    reload_run = native(cold, restored, cold=True)
    cold_preservation = verify_core_snapshots(first/'full_before.tsv',cold/'full_before.tsv',['core0'])
    assert before_clocks == sorted((r['clock'],r['period_ns']) for r in rows(cold/'clocks_before.tsv'))
    for path, expected in identities.items():
        assert digest(path) == expected, 'Changed input '+path
    for path, expected in models.items():
        assert artifact_fingerprint(path) == expected, 'Changed model '+path
    assert hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies) == parent_q['output_database_fingerprint']
    assert hierarchy_fingerprint(restored,directory_dependencies=dependencies) == fingerprint
    assert artifact_fingerprint(ROOT/core_q['output_database']) == core_q['output_database_fingerprint']
    save(state='passed', native_exit_status=0, cold_reload_run=reload_run,
         cold_complete_cell_preservation=cold_preservation,
         original_clocks_and_periods_preserved=True,
         original_inputs_core_and_both_model_directories_unchanged=True,
         cold_reloaded_complete_original_cells=94471,
         native_switch_and_restoration_supported=True,
         full_parent_guided_optimization_pending=True)
    print('CORE_MODEL_SWITCH84_QUALIFIED', flush=True)
except BaseException as error:
    if child is not None:
        if pause is not None:
            pause.resume()
        terminate_process_group(child, log_argument=log_argument)
    save(state='failed', exception=repr(error), native_exit_status=child.returncode if child else None)
    raise
finally:
    for lock in reversed(locks):
        lock.close()
