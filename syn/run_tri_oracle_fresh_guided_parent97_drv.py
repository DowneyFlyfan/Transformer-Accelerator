"""Bound parent optimization memory, then require complete-model diagnostics."""
import csv
import datetime
import fcntl
import filecmp
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'syn'))
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_parent_candidate_acceptance import require_reset_topology, require_snapshot_binding

PARENT = ROOT/'.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30'
BASE = ROOT/'.cache/physical/pnr/tri_oracle_sram_memory_compute'
GUIDE = PARENT/'guided97_drv'
RESTORED = PARENT/'restored97_drv'
RESULT = ROOT/'records/guided_parent97_drv_result.json'
started = time.monotonic()
child = None
pause = None
log_argument = None
locks = []
stop_requested = False
record = dict(state='preflight', started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              supervisor_pid=os.getpid(), guidance_model_final_timing_qualified=False,
              full_paper_results_matched=False,
              scope='Repair only electrical violations in the placed prediction parent using compact core58 guidance; independently restore complete cores68 and diagnose all3 original timing corners. No final routed timing or complete-processor qualification.')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def save(**updates):
    record.update(updates, elapsed_seconds=time.monotonic()-started)
    temporary = RESULT.with_suffix('.tmp')
    temporary.write_text(json.dumps(record,indent=2)+'\n')
    temporary.replace(RESULT)


def stop(signum, frame):
    global stop_requested
    stop_requested = True


def available():
    return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith('MemAvailable:')))*1024


def anonymous():
    return int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])


def native(directory, entry, marker, environment, seconds=7200):
    global child, pause, log_argument
    directory.mkdir(exist_ok=False)
    log_argument = str(directory/'native')
    console = directory/'console.log'
    command = ['innovus','-stylus','-no_gui','-batch','-log',log_argument,'-files',str(entry)]
    policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3,
                                  anonymous_limit_bytes=19*1024**3)
    native_started = time.monotonic()
    with console.open('w') as stream:
        child = subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,
            stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
            env=dict(os.environ,**environment))
        pause = OwnedProcessPause(child,log_argument)
        save(native_process_group=child.pid,native_entry=str(entry),command=command)
        while child.poll() is None:
            assert not stop_requested, 'External stop requested'
            assert time.monotonic()-native_started < seconds, 'Native stage wall budget'
            memory,combined = available(),anonymous()
            record['peak_combined_anonymous_bytes'] = max(record.get('peak_combined_anonymous_bytes',0),combined)
            record['minimum_host_available_bytes'] = min(record.get('minimum_host_available_bytes',memory),memory)
            action = policy.observe(memory,combined,time.monotonic())
            if action in ('pause','resume'):
                groups = pause.pause() if action=='pause' else pause.resume()
                save(memory_pressure_events=record.get('memory_pressure_events',[])+[
                    dict(action=action,groups=groups,host_available_bytes=memory,combined_anonymous_bytes=combined,
                         utc=datetime.datetime.now(datetime.timezone.utc).isoformat())])
            if time.monotonic()-record.get('last_sample_monotonic',0)>10:
                save(last_sample_monotonic=time.monotonic(),native_elapsed_seconds=time.monotonic()-native_started)
            time.sleep(.1)
        terminate_process_group(child,log_argument=log_argument)
    assert child.returncode==0 and '\n'+marker+'\n' in console.read_text(errors='replace'), console
    return dict(native_exit_status=0,elapsed_seconds=time.monotonic()-native_started,
                console_sha256=sha(console),output_directory=str(directory))


def legal_report(path):
    text = Path(path).read_text()
    assert 'Finished check_place' in text and re.search(r'Unplaced\s*=\s*0\b',text), path
    assert not re.search(r'\b(overlap|violation|illegal|warning|error)s?\b',text,re.I), text
    return text


def same_guidance_snapshots(before, after):
    with tempfile.TemporaryDirectory(prefix='guidance_compare_',dir=GUIDE) as directory:
        files = []
        for index,path in enumerate([before,after]):
            target = Path(directory)/str(index)
            subprocess.run(['sort','-S','64M','-T',directory,'-o',str(target),str(path)],
                           env=dict(os.environ,LC_ALL='C'),timeout=600,check=True)
            files.append(target)
        assert filecmp.cmp(*files,shallow=False), 'Original guidance cells changed'
        return sha(files[0])


signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
assert not RESULT.exists(), 'Existing experiment result must remain immutable'
save()
try:
    assert available()>18*1024**3 and anonymous()<3*1024**3, 'Initial memory reserve'
    assert shutil.disk_usage(PARENT).free>12*1024**3, 'Disk reserve'
    prepared_path=ROOT/'records/guidance_parent96_result.json'
    prepared_q=json.loads(prepared_path.read_text())
    assert prepared_q['state']=='guidance_only_checkpoint_and_fresh_reload_qualified'
    assert prepared_q['complete_model_directory_absent_from_prepared_dependencies']
    prepared_database=Path(prepared_q['output_database'])
    assert prepared_database==PARENT/'guidance96/prepare/prepared_guidance.db'
    for path,expected in prepared_q['source_sha256'].items():
        assert sha(path)==expected,'Changed guidance preparation prerequisite '+path
    switch_path = ROOT/'records/core_model_switch84_result.json'
    switch = json.loads(switch_path.read_text())
    assert switch['state']=='passed' and switch['native_switch_and_restoration_supported']
    assert switch['cold_reloaded_complete_original_cells']==94471
    for path,expected in switch['source_sha256'].items():
        assert sha(path)==expected, 'Changed model-switch prerequisite '+path
    placement_path = ROOT/'records/predicted_fabric_placement79_result.json'
    placement = json.loads(placement_path.read_text())
    assert placement['state']=='real_parent_full_model_geometric_placement_passed'
    assert placement['all3_pre_cts_corners_checked_in_separate_native_runs']
    identities = dict(placement['source_sha256'])
    identities[str(prepared_path)]=sha(prepared_path)
    identities.update(prepared_q['source_sha256'])
    # Bind every consumed accepted inventory before native execution.
    for path,expected in placement['core_preservation']['input_sha256'].items():
        assert sha(path)==expected, 'Changed accepted core inventory '+path
        identities[path]=expected
    reset_baseline=PARENT/'placement79/registered_reset_roots.tsv'
    assert sha(reset_baseline)==placement['native_registered_reset_report_sha256']
    identities[str(reset_baseline)]=placement['native_registered_reset_report_sha256']

    for path in [Path(__file__).resolve(),switch_path,placement_path,
                 ROOT/'syn/tri_oracle_guided_parent_checks.tcl',ROOT/'syn/tri_oracle_optimize_fresh_guided_parent97_drv.tcl',
                 ROOT/'syn/tri_oracle_restore_guided_parent86.tcl',ROOT/'syn/tri_oracle_report_parent_single_corner.tcl',
                 ROOT/'syn/tri_oracle_core_preservation.py',ROOT/'syn/tri_oracle_hierarchy_fingerprint.py',
                 ROOT/'syn/tri_oracle_process_guard.py',ROOT/'syn/tri_oracle_memory_pressure_guard.py',
                 ROOT/'syn/tri_oracle_parent_candidate_acceptance.py',
                 Path('/opt/cadence/INNOVUS251/doc/TCRcom/opt_design.html')]:
        identities[str(path)]=sha(path)
    dependencies,models = {},{}
    for dirname,filename in [('hierarchy_full_control_68','sram_core_hierarchy68_full_control_validation.json'),
                             ('hierarchy_export_58','sram_core_hierarchy58_export_validation.json')]:
        path = ROOT/'records'/filename
        identities[str(path)] = sha(path)
        expected = json.loads(path.read_text())['output_artifact_fingerprint']
        assert artifact_fingerprint(BASE/dirname)==expected
        models[str(BASE/dirname)]=expected
        dependencies[BASE/dirname/'ilm']={'type':'directory','files':{
            k[4:]:v for k,v in expected['files'].items() if k.startswith('ilm/')}}
    core_q = json.loads((ROOT/'records/sram_core_checkpoint44_qualification.json').read_text())
    source_db = PARENT/'placement79/placed.db'
    def immutable():
        for path,expected in identities.items():
            assert sha(path)==expected, 'Changed original input '+path
        for path,expected in models.items():
            assert artifact_fingerprint(path)==expected, 'Changed model '+path
        assert artifact_fingerprint(ROOT/core_q['output_database'])==core_q['output_database_fingerprint']
        assert hierarchy_fingerprint(source_db,directory_dependencies=dependencies)==placement['placed_checkpoint_fingerprint']
        assert hierarchy_fingerprint(prepared_database,directory_dependencies=dependencies)==prepared_q['output_database_fingerprint']
    immutable()
    save(source_sha256=identities,input_database_fingerprint=placement['placed_checkpoint_fingerprint'],
         prepared_guidance_fingerprint=prepared_q['output_database_fingerprint'],fresh_prepared_guidance_used=True)
    for path,flags in [(ROOT/'.cache/physical/synthesis/tri_oracle_predicted_fabric/guard.lock',fcntl.LOCK_SH),
                       (ROOT/'.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock',fcntl.LOCK_EX),
                       (PARENT/'physical.guard.lock',fcntl.LOCK_EX)]:
        lock=path.open('a'); fcntl.flock(lock,flags|fcntl.LOCK_NB); locks.append(lock)
    save(state='guidance_only_parent_electrical_repair_running')
    run = native(GUIDE,ROOT/'syn/tri_oracle_optimize_fresh_guided_parent97_drv.tcl',
        'TRI_ORACLE_GUIDED97_DRV_PARENT_OPTIMIZATION_FINISHED_REQUIRES_FULL_RESTORE',
        dict(TRI_ORACLE_GUIDED_PARENT_DIRECTORY=str(GUIDE)))
    guidance_digest = same_guidance_snapshots(GUIDE/'guidance_before.tsv',GUIDE/'guidance_after.tsv')
    legal_report(GUIDE/'placement.rpt')
    guidance_reset=require_reset_topology(reset_baseline,GUIDE/'registered_reset_roots.tsv')
    guided_fingerprint = hierarchy_fingerprint(GUIDE/'guided.db',directory_dependencies=dependencies)
    immutable()
    save(state='independent_complete_model_restore_running',guidance_optimization=run,
         guidance_original_cell_snapshot_sha256=guidance_digest,
         guidance_database_fingerprint=guided_fingerprint)
    restored_run = native(RESTORED,ROOT/'syn/tri_oracle_restore_guided_parent86.tcl',
        'TRI_ORACLE_RESTORE86_ALL_ORIGINAL_CORES_RESTORED_REQUIRES_COLD_TIMING',
        dict(TRI_ORACLE_GUIDED_PARENT_DIRECTORY=str(GUIDE),TRI_ORACLE_RESTORED_PARENT_DIRECTORY=str(RESTORED)),1800)
    preservation = verify_core_snapshots(PARENT/'placement79/core_after.tsv',RESTORED/'full_after.tsv',
                                       (RESTORED/'core_prefixes.txt').read_text().splitlines())
    assert preservation['total_original_cells']==1889420
    assert len(preservation['cells_per_core'])==20
    legal_report(RESTORED/'placement.rpt')
    complete_reset=require_reset_topology(reset_baseline,RESTORED/'registered_reset_roots.tsv')
    full_status = (RESTORED/'full_model.rpt').read_text()
    assert 'current ilm data is for si mode' in full_status.lower()
    assert len(re.findall(r'\bAll\s+ILM\s+post-cts\s+',full_status))==20
    checkpoint=RESTORED/'restored_full.db'
    fingerprint=hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies)
    assert hierarchy_fingerprint(GUIDE/'guided.db',directory_dependencies=dependencies)==guided_fingerprint
    immutable()
    save(state='cold_complete_model_original_corner_diagnostics_running',restoration=restored_run,
         exact_registered_reset_topology={'guidance':guidance_reset,'restored':complete_reset},
         complete_core_preservation=preservation,output_database=str(checkpoint),
         output_database_fingerprint=fingerprint)
    corners={}
    for view in ['setup_slow','setup_typ','hold_fast']:
        cold=RESTORED/('corner_'+view)
        save(diagnostic_view=view)
        run=native(cold,ROOT/'syn/tri_oracle_report_parent_single_corner.tcl',
                   'TRI_ORACLE_PARENT_CORNER53_DIAGNOSTIC_FINISHED '+view,
                   dict(TRI_ORACLE_PARENT_DIAGNOSTIC_CHECKPOINT=str(checkpoint),
                        TRI_ORACLE_PARENT_DIAGNOSTIC_DIRECTORY=str(cold),TRI_ORACLE_PARENT_DIAGNOSTIC_VIEW=view),1800)
        with (cold/'slack_properties.tsv').open() as stream:
            rows=list(csv.DictReader(stream,delimiter='\t'))
        assert len(rows)==1 and rows[0]['view']==view
        with (cold/'core_counts.tsv').open() as stream:
            counts=list(csv.DictReader(stream,delimiter='\t'))
        assert len(counts)==20 and {int(r['full_original_cells']) for r in counts}=={94471}
        assert hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies)==fingerprint
        corners[view]=dict(run,slack_ns=float(rows[0]['slack_ns']),startpoint=rows[0]['startpoint'],
                           endpoint=rows[0]['endpoint'],original_core_cells=1889420,memory_macros=600)
        save(separate_corner_diagnostics=corners)
    immutable()
    save(state='restored_full_model_diagnostics_completed',native_exit_status=0,
         all3_original_corners_diagnosed=True,original_inputs_and_models_unchanged=True,
         accepted_core_snapshot_and_full_reset_topology_bound=True,
         electrical_repair_only=True,setup_optimization_executed=False,
         pre_route_signal_interference_qualified=False,
         all3_pre_clock_slacks_nonnegative=all(c['slack_ns']>=0 for c in corners.values()),
         clock_tree_and_final_signal_routing_pending=True,routed_timing_closure_qualified=False)
    print('GUIDED_PARENT97_DRV_FULL_MODEL_DIAGNOSTICS_FINISHED',flush=True)
except BaseException as error:
    if child is not None:
        if pause is not None: pause.resume()
        terminate_process_group(child,log_argument=log_argument)
    save(state='failed',exception=repr(error),native_exit_status=child.returncode if child else None)
    raise
finally:
    for lock in reversed(locks): lock.close()
