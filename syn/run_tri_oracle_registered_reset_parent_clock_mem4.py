"""Wait for qualified full-parent placement, then run guarded clock synthesis."""
from pathlib import Path
import csv
import datetime
import fcntl
import hashlib
import json
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

parent = root/'.cache/physical/pnr/tri_oracle_predicted_fabric_registered_reset30'
base = root/'.cache/physical/pnr/tri_oracle_sram_memory_compute'
out = parent/'clock51'
producer_path = Path('records/predicted_fabric_placement50_result.json')
probe_path = Path('records/preserved_core_clock35_qualification.json')
result_path = Path('records/predicted_fabric_clock51_result.json')
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
preparation = json.loads(Path('records/predicted_fabric_clock51_preparation.json').read_text())
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
for path in [Path(__file__).resolve(), probe_path, Path('records/predicted_fabric_clock51_preparation.json'),
             Path('syn/tri_oracle_clock_registered_reset_fabric_physical_mem4.tcl'),
             Path('syn/tri_oracle_require_preserved_clock_boundaries.tcl'),
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
assert owner_identity and owner_identity[0] not in ('Z','X')
record = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              state='waiting_for_full_parent_placement', supervisor_pid=os.getpid(),
              producer_supervisor_pid=owner, producer_start_ticks=owner_identity[1],
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
    assert input_db == parent/'placement50/placed.db'
    assert hierarchy_fingerprint(input_db, directory_dependencies=dependencies) == manifest['closed_fingerprint']
    core_path = Path('records/sram_core_checkpoint44_qualification.json')
    core = json.loads(core_path.read_text())
    assert artifact_fingerprint(core['output_database']) == core['output_database_fingerprint']
    for path in [producer_path, manifest_path, model_path, core_path,
                 parent/'placement50/core_after.tsv', parent/'placement50/core_prefixes.txt']:
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
    console = out/'console.log'
    log_argument = str(out/'innovus')
    command = ['/usr/bin/time', '-v', '/opt/cadence/INNOVUS251/bin/innovus', '-stylus', '-no_gui',
               '-batch', '-log', log_argument, '-files', str(root/'syn/tri_oracle_clock_registered_reset_fabric_physical_mem4.tcl')]
    def bounds():
        resource.setrlimit(resource.RLIMIT_CPU, (28800*4, 28800*4))
    native_started = time.monotonic()
    with console.open('w') as output:
        child = subprocess.Popen(command, cwd=out, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, start_new_session=True, preexec_fn=bounds)
        save(state='native_full_parent_clock_running', native_process_group=child.pid, command=command)
        while child.poll() is None:
            memory, combined = available(), anonymous()
            record['peak_combined_anonymous_bytes'] = max(record['peak_combined_anonymous_bytes'], combined)
            record['minimum_host_available_bytes'] = min(record['minimum_host_available_bytes'] or memory, memory)
            assert not stop_requested and time.monotonic()-native_started < 28800, 'Clock stage interrupted or wall limit'
            assert combined < 21*1024**3 and memory > 4*1024**3, 'Clock actual-memory reserve'
            time.sleep(1)
        terminate_process_group(child, log_argument=log_argument)
    text = console.read_text(errors='replace')
    assert child.returncode == 0 and '\nTRI_ORACLE_REGISTERED_RESET_PARENT_CLOCK51_FINISHED\n' in text
    assert not re.search(r'^\*\*ERROR:', text, re.M), 'Native clock run logged errors'
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
    timing_rows = list(csv.DictReader((out/'slack_properties.tsv').open(), delimiter=chr(9)))
    assert len(timing_rows) == 3 and {r['view'] for r in timing_rows} == {'setup_slow','setup_typ','hold_fast'}
    postcts_slack = {r['view']:float(r['slack_ns']) for r in timing_rows}
    check_inputs()
    assert hierarchy_fingerprint(input_db, directory_dependencies=dependencies) == manifest['closed_fingerprint']
    assert artifact_fingerprint(base/'hierarchy_full_control_68') == model['output_artifact_fingerprint']
    assert artifact_fingerprint(core['output_database']) == core['output_database_fingerprint']
    fingerprint = hierarchy_fingerprint(out/'clocked.db', directory_dependencies=dependencies)
    manifest_path = out/'clocked_manifest.json'
    manifest_path.write_text(json.dumps({'database':str(out/'clocked.db'), 'closed_fingerprint':fingerprint,
        'producer_qualification':str(model_path), 'producer_qualification_sha256':sha(model_path),
        'scope':'Parent clock checkpoint only. Power delivery, signal routing and final timing/paper metrics are pending.'}, indent=2)+'\n')
    save(state='full_parent_clock_completed', native_exit_status=child.returncode,
         native_elapsed_seconds=time.monotonic()-native_started, native_console_sha256=sha(console),
         core_preservation=preservation, protected_core_clock_boundaries=after,
         postcts_slack_ns=postcts_slack, all3_original_views_have_actual_paths=True,
         output_manifest=str(manifest_path), output_manifest_sha256=sha(manifest_path),
         original_inputs_core_checkpoint_and_complete_models_unchanged=True,
         power_grid_signal_routing_and_final_timing_pending=True, routed_timing_closure_qualified=False)
except BaseException as error:
    if child is not None:
        terminate_process_group(child, log_argument=str(out/'innovus'))
    save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None)
    raise
finally:
    for lock in reversed(locks):
        lock.close()
