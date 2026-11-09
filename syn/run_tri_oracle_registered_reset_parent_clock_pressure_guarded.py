"""Wait for qualified full-parent placement, then run guarded clock synthesis."""
from pathlib import Path
import csv
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import resource
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
root = Path('/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator')
os.chdir(root)
sys.path.insert(0, str(root/'syn'))
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause

parent = root/'.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30'
base = root/'.cache/physical/pnr/tri_oracle_sram_memory_compute'
out = parent/'clock59'
producer_path = Path('records/predicted_fabric_placement57_result.json')
probe_path = Path('records/preserved_core_clock35_qualification.json')
result_path = Path('records/predicted_fabric_clock59_result.json')
assert not result_path.exists() and not (out/'clocked.db').exists()
started = time.monotonic()
child = None
locks = []
stop_requested = False

def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

def available():
    return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith('MemAvailable:')))*1024

def anonymous():
    return int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])

def process(pid):
    try:
        text = (Path('/proc')/str(pid)/'stat').read_text()
        fields = text[text.rfind(')')+2:].split()
        return fields[0], int(fields[19])
    except FileNotFoundError:
        return None

def stop(signum, frame):
    global stop_requested
    stop_requested = True

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
preparation = json.loads(Path('records/predicted_fabric_clock59_preparation.json').read_text())
assert all(sha(p) == h for p,h in preparation['source_sha256'].items())
probe = json.loads(probe_path.read_text())
assert probe['state'] == 'passed' and probe['native_exit_status'] == 0
assert probe['core_preservation']['total_original_cells'] == 94471
assert probe['original_inputs_and_models_unchanged']
assert probe['protected_clock_boundaries_before'][0]['original_clock_root'] == 'core0/CTS_ccl_buf_00324/I'
assert probe['protected_clock_boundaries_after'][0]['sink_type'] == 'stop'
for path, expected in probe['source_sha256'].items():
    assert sha(path) == expected, 'Clock capability source changed: '+path
revision = json.loads(Path('.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/input_revision.json').read_text())
identities = dict(revision['candidate_rtl_inventory'])
assert len(identities) == 37
identities.update(preparation['source_sha256'])
for path in [Path(__file__).resolve(), probe_path, Path('records/predicted_fabric_clock59_preparation.json'),
             Path('syn/tri_oracle_clock_registered_reset_fabric_pressure_guarded.tcl'),
             Path('syn/tri_oracle_require_preserved_clock_boundaries.tcl'),
             Path('syn/tri_oracle_report_parent_postclock_single_corner.tcl'),
             Path('syn/tri_oracle_require_clean_placement.tcl'),
             Path('syn/tri_oracle_registered_reset_trace.tcl'),
             Path('syn/tri_oracle_check_registered_reset_fabric.tcl'),
             Path('syn/tri_oracle_core_preservation.py'),
             Path('syn/tri_oracle_process_guard.py'),
             Path('syn/tri_oracle_hierarchy_fingerprint.py'),
             Path('syn/tri_oracle_artifact_fingerprint.py'),
             Path('records/registered_reset34_sequential_masters.json'),
             Path('records/registered_reset34_graph_qualification.json')]:
    identities[str(path)] = sha(path)
producer = json.loads(producer_path.read_text())
owner = producer['supervisor_pid']
owner_identity = process(owner)
if producer['state'] != 'real_parent_full_model_placement_passed':
    assert owner_identity and owner_identity[0] not in ('Z','X')
record = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              state='waiting_for_full_parent_placement', supervisor_pid=os.getpid(),
              producer_supervisor_pid=owner, producer_start_ticks=owner_identity[1] if owner_identity else None,
              source_sha256=identities, peak_combined_anonymous_bytes=0,
              minimum_host_available_bytes=None, full_paper_results_matched=False,
              scope='Parent clock-tree implementation with all20 original complete core models and600 memories. Power grid, signal routing, final timing and paper metrics remain separate gates.')

def save(**updates):
    record.update(updates, elapsed_seconds=time.monotonic()-started)
    temporary = result_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2)+'\n')
    temporary.replace(result_path)

def check_inputs():
    assert all(sha(path) == expected for path,expected in identities.items()), 'Clock-stage input changed'


current_native_log_argument = None

def run_native_stage(directory, entry, phase, marker, environment, seconds):
    global child,current_native_log_argument
    directory.mkdir(parents=True,exist_ok=True)
    console=directory/'console.log'
    assert not console.exists(), 'Refusing to replace a native phase log'
    current_native_log_argument=str(directory/'innovus')
    command=['/usr/bin/time','-v','/opt/cadence/INNOVUS251/bin/innovus',
        '-stylus','-no_gui','-batch','-log',current_native_log_argument,'-files',str(entry)]
    before_events={k:int(v) for k,v in dict(line.split() for line in Path('/sys/fs/cgroup/memory.events').read_text().splitlines()).items()}
    started_phase=time.monotonic()
    last_save=0
    def native_bounds():
        resource.setrlimit(resource.RLIMIT_CPU,(seconds*4,seconds*4))
    with console.open('w') as output:
        child=subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,
            stdout=output,stderr=subprocess.STDOUT,start_new_session=True,
            preexec_fn=native_bounds,env=dict(os.environ,**environment))
        pressure_policy = MemoryPressurePolicy(host_reserve_bytes=4*1024**3, resume_bytes=5*1024**3, anonymous_limit_bytes=21*1024**3)
        pause_controller = OwnedProcessPause(child, current_native_log_argument)
        save(state=phase,native_process_group=child.pid,native_phase_directory=str(directory),
             native_phase_command=command,native_phase_memory_events_before=before_events)
        try:
            while child.poll() is None:
                memory,combined=available(),anonymous()
                record['peak_combined_anonymous_bytes']=max(record['peak_combined_anonymous_bytes'],combined)
                record['minimum_host_available_bytes']=min(record['minimum_host_available_bytes'] or memory,memory)
                if time.monotonic()-last_save>=10:
                    save(native_phase_elapsed_seconds=time.monotonic()-started_phase,
                        current_combined_anonymous_bytes=combined,current_host_available_bytes=memory)
                    last_save=time.monotonic()
                assert not stop_requested, 'Clock workflow interrupted'
                assert time.monotonic()-started_phase < seconds, 'Clock native phase wall budget'
                action = pressure_policy.observe(memory, combined, time.monotonic())
                if action in ('pause', 'resume'):
                    groups = pause_controller.pause() if action == 'pause' else pause_controller.resume()
                    events = record.get('memory_pressure_events', []) + [{
                        'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        'phase': phase, 'action': action, 'verified_owned_process_groups': groups,
                        'host_available_bytes': memory, 'combined_anonymous_bytes': combined}]
                    save(memory_pressure_events=events, native_pressure_state=action)
                time.sleep(.1)
        finally:
            pause_controller.resume()
            terminate_process_group(child,log_argument=current_native_log_argument)
    text=console.read_text(errors='replace')
    assert child.returncode==0 and ('\n'+marker+'\n') in text, 'Native phase incomplete: '+phase
    assert not re.search(r'^\*\*ERROR:',text,re.M), 'Native phase logged an error: '+phase
    return {'native_exit_status':child.returncode,'native_elapsed_seconds':time.monotonic()-started_phase,
        'native_console_sha256':sha(console),'directory':str(directory),'command':command,
        'environment':environment,'memory_events_before':before_events,
        'memory_events_after':{k:int(v) for k,v in dict(line.split() for line in Path('/sys/fs/cgroup/memory.events').read_text().splitlines()).items()}}

def parse_postclock_corner(directory,profile,view,expected_cores):
    def rows(name):
        with (directory/name).open() as stream:return list(csv.DictReader(stream,delimiter=chr(9)))
    counts=rows('core_counts.tsv')
    assert len(counts)==expected_cores and {int(r['full_original_cells']) for r in counts}=={94471}
    propagation=rows('clock_propagation.tsv')
    assert len(propagation)==1
    state=propagation[0]
    assert state['profile']==profile and state['view']==view
    assert state['propagated_after'] in ['true','1'] and int(state['original_cores'])==expected_cores
    assert abs(float(state['clock_period_ns'])-1.72414)<.00001
    boundary_sets=[]
    for name in ['clock_boundaries.tsv','clock_boundaries_after.tsv']:
        boundaries=rows(name)
        assert len(boundaries)==expected_cores
        assert all(r['sink_type']=='stop' and 'ilm' in r['reasons'].split() for r in boundaries)
        boundary_sets.append({r['original_clock_root'] for r in boundaries})
    assert boundary_sets[0]==boundary_sets[1]
    model_status=(directory/'model_status.rpt').read_text()
    assert 'current ilm data is for si mode' in model_status.lower()
    assert len(re.findall(r'\bAll\s+ILM\s+post-cts\s+',model_status))==expected_cores
    timing=rows('slack_properties.tsv');registers=rows('register_slack_properties.tsv')
    assert len(timing)==len(registers)==1 and timing[0]['view']==registers[0]['view']==view
    worst=float(timing[0]['slack_ns']);register_slack=float(registers[0]['slack_ns'])
    assert math.isfinite(worst) and math.isfinite(register_slack)
    register_report=(directory/'register_clock_path.rpt').read_text()
    propagated=re.findall(r'Net\s+Latency:\+\s+([-+0-9.eE]+)\s+\(P\)\s+([-+0-9.eE]+)\s+\(P\)',register_report)
    assert propagated and all(float(a)>0 and float(b)>0 for a,b in propagated), 'Register path lacks actual propagated clock network latency'
    return {'view':view,'profile':profile,'original_core_cells':expected_cores*94471,
        'memory_macros':600 if expected_cores==20 else 28,'slack_ns':worst,
        'register_slack_ns':register_slack,'startpoint':timing[0]['startpoint'],
        'endpoint':timing[0]['endpoint'],'waveform_clock_explicitly_propagated':True,
        'actual_register_clock_network_latencies_ns':propagated,
        'preserved_clock_roots':sorted(boundary_sets[0]),'clock_period_ns':float(state['clock_period_ns'])}

save()
try:
    check_inputs()
    missing = 0
    while True:
        assert not stop_requested and time.monotonic()-started < 172800, 'Clock prerequisite wait interrupted or expired'
        try:
            producer = json.loads(producer_path.read_text())
        except json.JSONDecodeError:
            time.sleep(1)
            continue
        if producer['state'] == 'real_parent_full_model_placement_passed':
            break
        assert producer['state'] != 'failed', producer.get('exception', 'Parent placement failed')
        current = process(owner)
        live = current is not None and current[1] == owner_identity[1] and current[0] not in ('Z','X')
        missing = 0 if live else missing+1
        assert missing < 5, 'Placement supervisor disappeared without terminal evidence'
        save(producer_state=producer['state'], producer_supervisor_verified_live=live)
        time.sleep(2)
    assert producer['native_exit_status'] == 0
    assert producer['all3_pre_cts_corners_checked_in_separate_native_runs']
    assert set(producer['separate_corner_diagnostics']) == {'setup_slow','setup_typ','hold_fast'}
    assert producer['original_inputs_core_checkpoint_and_complete_models_unchanged']
    assert producer['core_preservation']['total_original_cells'] == 1889420
    manifest_path = Path(producer['output_manifest'])
    assert sha(manifest_path) == producer['output_manifest_sha256']
    manifest = json.loads(manifest_path.read_text())
    model_path = Path('records/sram_core_hierarchy68_full_control_validation.json')
    model = json.loads(model_path.read_text())
    assert artifact_fingerprint(base/'hierarchy_full_control_68') == model['output_artifact_fingerprint']
    dependency = {'type':'directory', 'files':{k[4:]:v for k,v in model['output_artifact_fingerprint']['files'].items() if k.startswith('ilm/')}}
    dependencies = {base/'hierarchy_full_control_68/ilm':dependency}
    input_db = Path(manifest['database'])
    assert input_db == parent/'placement57/placed.db'
    assert hierarchy_fingerprint(input_db, directory_dependencies=dependencies) == manifest['closed_fingerprint']
    core_path = Path('records/sram_core_checkpoint44_qualification.json')
    core = json.loads(core_path.read_text())
    assert artifact_fingerprint(core['output_database']) == core['output_database_fingerprint']
    for path in [producer_path, manifest_path, model_path, core_path,
                 parent/'placement57/core_after.tsv', parent/'placement57/core_prefixes.txt']:
        identities[str(path)] = sha(path)
    check_inputs()
    for path in [root/'.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock', parent/'physical.guard.lock']:
        lock = path.open('a')
        deadline = time.monotonic()+60
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                assert not stop_requested and time.monotonic() < deadline, 'Physical stage lock busy'
                time.sleep(.2)
        locks.append(lock)
    deadline = time.monotonic()+1800
    while available() <= 18*1024**3 or anonymous() >= 3*1024**3:
        assert not stop_requested and time.monotonic() < deadline, 'Clock startup memory headroom unavailable'
        save(state='waiting_for_clock_memory_headroom')
        time.sleep(2)
    assert __import__('shutil').disk_usage(parent).free > 12*1024**3
    out.mkdir(exist_ok=True)
    post_entry=root/'syn/tri_oracle_report_parent_postclock_single_corner.tcl'
    probe_database=Path(probe['output_database'])
    assert hierarchy_fingerprint(probe_database,directory_dependencies=dependencies)==probe['output_database_fingerprint']
    preflight_directory=out/'propagated_clock_preflight'
    preflight=run_native_stage(preflight_directory,post_entry,'native_clock_propagation_preflight_running',
        'TRI_ORACLE_PARENT_POSTCLOCK_CORNER55_DIAGNOSTIC_FINISHED setup_typ',
        {'TRI_ORACLE_PARENT_DIAGNOSTIC_CHECKPOINT':str(probe_database),
         'TRI_ORACLE_PARENT_DIAGNOSTIC_DIRECTORY':str(preflight_directory),
         'TRI_ORACLE_PARENT_DIAGNOSTIC_VIEW':'setup_typ',
         'TRI_ORACLE_CLOCK_DIAGNOSTIC_PROFILE':'one_core'},3600)
    preflight.update(parse_postclock_corner(preflight_directory,'one_core','setup_typ',1))
    assert hierarchy_fingerprint(probe_database,directory_dependencies=dependencies)==probe['output_database_fingerprint']
    save(propagated_clock_reporting_preflight=preflight,propagated_clock_preflight_passed=True)
    deadline=time.monotonic()+1800
    while available()<=18*1024**3 or anonymous()>=3*1024**3:
        assert not stop_requested and time.monotonic()<deadline, 'Main clock memory headroom unavailable'
        save(state='waiting_for_main_clock_memory_headroom')
        time.sleep(2)
    main=run_native_stage(out,root/'syn/tri_oracle_clock_registered_reset_fabric_pressure_guarded.tcl',
        'native_full_parent_clock_running','TRI_ORACLE_REGISTERED_RESET_PARENT_CLOCK59_FINISHED',{},28800)
    console=out/'console.log'
    for name in ['input_core_preservation.json', 'core_preservation.json']:
        preservation = json.loads((out/name).read_text())
        assert preservation['total_original_cells'] == 1889420
        assert preservation['all_original_cell_names_masters_and_geometry_preserved']
        assert len(preservation['cells_per_core']) == 20 and set(preservation['cells_per_core'].values()) == {94471}
    before = list(csv.DictReader((out/'clock_boundaries_before.tsv').open(), delimiter='\t'))
    after = list(csv.DictReader((out/'clock_boundaries_after.tsv').open(), delimiter='\t'))
    assert len(before) == len(after) == 20
    assert len({row['core'] for row in before}) == 20
    assert {row['original_clock_root'] for row in before} == {row['original_clock_root'] for row in after}
    assert all(row['sink_type'] == 'stop' and 'ilm' in row['reasons'].split() for row in before+after)
    # Corner queries run after the native clocked checkpoint is saved.
    check_inputs()
    assert hierarchy_fingerprint(input_db, directory_dependencies=dependencies) == manifest['closed_fingerprint']
    assert artifact_fingerprint(base/'hierarchy_full_control_68') == model['output_artifact_fingerprint']
    assert artifact_fingerprint(core['output_database']) == core['output_database_fingerprint']
    fingerprint = hierarchy_fingerprint(out/'clocked.db', directory_dependencies=dependencies)
    save(native_clock_workflow_completed=True,clocked_checkpoint_written=True,
         clocked_checkpoint_fingerprint=fingerprint,native_clock_result=main)
    corners={}
    for view in ['setup_slow','setup_typ','hold_fast']:
        directory=out/('corner55_'+view)
        stage=run_native_stage(directory,post_entry,'native_full_parent_postcts_corner_running',
            'TRI_ORACLE_PARENT_POSTCLOCK_CORNER55_DIAGNOSTIC_FINISHED '+view,
            {'TRI_ORACLE_PARENT_DIAGNOSTIC_CHECKPOINT':str(out/'clocked.db'),
             'TRI_ORACLE_PARENT_DIAGNOSTIC_DIRECTORY':str(directory),
             'TRI_ORACLE_PARENT_DIAGNOSTIC_VIEW':view,
             'TRI_ORACLE_CLOCK_DIAGNOSTIC_PROFILE':'full_parent'},3600)
        stage.update(parse_postclock_corner(directory,'full_parent',view,20))
        assert hierarchy_fingerprint(out/'clocked.db',directory_dependencies=dependencies)==fingerprint
        corners[view]=stage
        save(separate_postcts_corner_diagnostics=corners)
    assert set(corners)=={'setup_slow','setup_typ','hold_fast'}
    postcts_slack={view:data['slack_ns'] for view,data in corners.items()}
    check_inputs()
    assert hierarchy_fingerprint(input_db,directory_dependencies=dependencies)==manifest['closed_fingerprint']
    manifest_path = out/'clocked_manifest.json'
    manifest_path.write_text(json.dumps({'database':str(out/'clocked.db'), 'closed_fingerprint':fingerprint,
        'producer_qualification':str(model_path), 'producer_qualification_sha256':sha(model_path),
        'scope':'Parent clock checkpoint only. Power delivery, signal routing and final timing/paper metrics are pending.'}, indent=2)+'\n')
    save(state='full_parent_clock_completed', native_exit_status=main['native_exit_status'],
         native_elapsed_seconds=main['native_elapsed_seconds'], native_console_sha256=sha(console),
         separate_postcts_corner_diagnostics=corners, all_register_clock_paths_use_propagated_timing=True,
         core_preservation=preservation, protected_core_clock_boundaries=after,
         postcts_slack_ns=postcts_slack, all3_original_views_have_actual_paths=True,
         output_manifest=str(manifest_path), output_manifest_sha256=sha(manifest_path),
         original_inputs_core_checkpoint_and_complete_models_unchanged=True,
         power_grid_signal_routing_and_final_timing_pending=True, routed_timing_closure_qualified=False)
except BaseException as error:
    if child is not None:
        terminate_process_group(child, log_argument=current_native_log_argument)
    save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None)
    raise
finally:
    for lock in reversed(locks):
        lock.close()
