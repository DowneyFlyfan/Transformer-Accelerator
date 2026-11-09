"""Observe native indexed-name list serialization without changing the design."""
import datetime
import filecmp
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def main():
    root = Path(__file__).resolve().parents[1]
    out = root/'.cache/physical/pnr/tri_oracle_controller264_probe'
    result = root/'records/controller264_probe_result.json'
    assert not out.exists() and not result.exists()
    producer_path = root/'records/controller260_tree_result.json'
    producer = json.loads(producer_path.read_text())
    assert producer['state'] == 'noninverting_controller_tree_cold_preserved_and_three_corners_completed'
    timing_path = root/'records/controller263_tree_result.json'
    timing = json.loads(timing_path.read_text())
    assert timing['state'] == 'failed' and 'TRI263_UNEXPECTED_TARGET_NET' in timing['exception']
    checkpoint = Path(producer['output_database'])
    input_fp = producer['output_database_fingerprint']
    assert hierarchy_fingerprint(checkpoint, directory_dependencies={Path(n): v for n,v in input_fp.get('directory_dependencies', {}).items()}) == input_fp
    entry = root/'syn/tri_oracle_controller264_names.tcl'
    names = ['run_tri_oracle_controller264_probe.py', 'tri_oracle_controller264_names.tcl', 'tri_oracle_unique215_snapshot.tcl', 'tri_oracle_preservation233.tcl', 'tri_oracle_design242_metadata.tcl', 'tri_oracle_row_guard173_variants.py', 'run_tri_oracle_row_guard175_synthesis.py', 'tri_oracle_hierarchy_fingerprint.py', 'tri_oracle_artifact_fingerprint.py', 'tri_oracle_native_diagnostics.py', 'tri_oracle_memory_pressure_guard.py', 'tri_oracle_process_guard.py']
    identities = {str(producer_path): sha(producer_path), str(timing_path): sha(timing_path)}
    for key in ['source_sha256', 'native_evidence_sha256']:
        for name, digest in producer[key].items():
            assert sha(name) == digest
            identities[name] = digest
    for path in [*[root/'syn'/name for name in names], Path('/opt/cadence/INNOVUS251/doc/TCRcom/eco_add_repeater.html'), Path('/opt/cadence/INNOVUS251/doc/TCRcom/eco_Category_Attributes.html'), Path('/opt/cadence/INNOVUS251/doc/DBcom/base_cell.html')]:
        digest = sha(path)
        assert str(path) not in identities or identities[str(path)] == digest
        identities[str(path)] = digest
    plan_path = root/'records/controller262_plan_result.json'
    plan = json.loads(plan_path.read_text())
    trees = Path(plan['output_directory'])/'trees.tsv'
    assert sha(trees) == plan['generated_sha256'][str(trees)]
    identities[str(plan_path)] = sha(plan_path)
    identities[str(trees)] = sha(trees)
    started = time.monotonic()
    child = pause = None
    token = str(out/'native')
    stopped = False
    record = dict(state='preflight', supervisor_pid=os.getpid(), started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), source_sha256=identities, native_workers=8, anonymous_limit_bytes=18*1024**3, host_reserve_bytes=5*1024**3, candidate_saved=False, placement_qualified=False, timing_qualified=False, functional_simulation_qualified=False, scope='Read-only114-driver diagnostic on the unchanged260 checkpoint. Compare returned driver names as raw strings and canonical Tcl lists. No circuit edit, placement, timing or functional result inferred.')

    def save(**updates):
        record.update(updates, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)

    def stop(signum, frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    save()
    try:
        available, anonymous = memory()
        assert available > 20*1024**3 and anonymous < 1024**3
        out.mkdir()
        console = out/'console.log'
        command = ['/opt/cadence/bin/innovus', '-stylus', '-no_gui', '-batch', '-log', token, '-files', str(entry)]
        with console.open('w') as stream:
            child = subprocess.Popen(command, cwd=out, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, env=dict(os.environ, TRI264_OUT=str(out), TRI264_INPUT=str(checkpoint), TRI264_TREES=str(trees)))
            pause = OwnedProcessPause(child, token)
            policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3, anonymous_limit_bytes=18*1024**3)
            save(state='native_protected_net_buffer_probe_running', native_process_group=child.pid, output_directory=str(out), command=command)
            last = 0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-started < 900, 'Buffer probe wall/stop guard'
                    available, anonymous = memory()
                    record.update(peak_combined_anonymous_bytes=max(record.get('peak_combined_anonymous_bytes', 0), anonymous), current_host_available_bytes=available, current_combined_anonymous_bytes=anonymous)
                    action = policy.observe(available, anonymous, time.monotonic())
                    if action == 'pause':
                        pause.pause()
                    elif action == 'resume':
                        pause.resume()
                    if time.monotonic()-last > 5:
                        save()
                        last = time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume()
                terminate_process_group(child, log_argument=token)
        text = console.read_text(errors='replace')
        require_clean_native(text)
        assert child.returncode == 0 and '\nTRI_ORACLE_CONTROLLER264_INDEXED_NAMES_OBSERVED\n' in text
        import csv
        with (out/'name_observations.tsv').open() as stream:
            observations = list(csv.DictReader(stream, delimiter='\t'))
        assert len(observations) == 114
        assert all(row['canonical_equal'] == '1' and row['net_count'] == '1' and row['net_name_equal'] == '1' and not row['driver_ports'] and not row['load_ports'] and row['constant'] == 'no_constant' and row['power'] == row['ground'] == 'false' for row in observations)
        assert all(sha(path) == digest for path,digest in identities.items())
        assert hierarchy_fingerprint(checkpoint, directory_dependencies={Path(n): v for n,v in input_fp.get('directory_dependencies', {}).items()}) == input_fp
        save(state='indexed_native_driver_list_serialization_observed', native_exit_status=0,
             observed_drivers=len(observations), raw_list_string_mismatches=sum(row['raw_equal'] == '0' for row in observations),
             canonical_name_sets_all_match=True, original_input_database_unchanged=True,
             native_evidence_sha256={str(path):sha(path) for path in [out/'console.log',out/'name_observations.tsv']})
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=token)
        save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None, temporary_comparison_ledgers_removed=True)
        raise


if __name__ == '__main__':
    main()
