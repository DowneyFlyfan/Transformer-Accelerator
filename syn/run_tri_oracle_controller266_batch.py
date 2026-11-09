"""Apply a transparent control tree, cold-verify it, and measure real corners."""
import csv
import datetime
import filecmp
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_frame202_preservation import CORES, require_reset_topology
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def main():
    root = Path(__file__).resolve().parents[1]
    out = root/'.cache/physical/pnr/tri_oracle_controller266_tree'
    result = root/'records/controller266_tree_result.json'
    assert not out.exists() and not result.exists()
    parent_path = root/'records/controller260_tree_result.json'
    parent = json.loads(parent_path.read_text())
    assert parent['state'] == 'noninverting_controller_tree_cold_preserved_and_three_corners_completed'
    assert parent['original600_memory_models_preserved'] and parent['all3_original_corner_constraints_preserved']
    baseline = Path(parent['output_directory'])/'cold'
    checkpoint = Path(parent['output_database'])
    input_fp = parent['output_database_fingerprint']
    control_path = root/'records/controller261_physical_functional_qualification.json'
    control = json.loads(control_path.read_text())
    assert control['state'] == 'control_tree_physical_preservation_and_mapped_functional_pair_qualified'
    assert control['physical_checkpoint_cold_preserved'] and control['original_constraints_preserved']
    plan_path = root/'records/controller262_plan_result.json'
    preparation = json.loads(plan_path.read_text())
    assert preparation['state'] == 'protected_enable_batch_plan_prepared_native_execution_pending' and preparation['total_trees'] == 114 and preparation['total_original_loads'] == 47503 and preparation['total_buffers'] == 1989
    plan_dir = Path(preparation['output_directory'])
    full_path = root/'records/sram_core_hierarchy68_full_control_validation.json'
    full = json.loads(full_path.read_text())
    models = root/'.cache/physical/pnr/tri_oracle_sram_memory_compute/hierarchy_full_control_68'
    model_fp = full['output_artifact_fingerprint']
    deps = {models/'ilm': {'type': 'directory', 'files': {name[4:]: value for name, value in model_fp['files'].items() if name.startswith('ilm/')}}}
    assert artifact_fingerprint(models) == model_fp and hierarchy_fingerprint(checkpoint, directory_dependencies=deps) == input_fp
    identities = {}

    def bind(path, expected=None):
        path = str(path)
        digest = sha(path)
        assert expected is None or digest == expected, 'Changed prerequisite '+path
        assert path not in identities or identities[path] == digest
        identities[path] = digest

    diagnosis_path = root/'records/controller264_probe_result.json'
    diagnosis = json.loads(diagnosis_path.read_text())
    assert diagnosis['state'] == 'indexed_native_driver_list_serialization_observed' and diagnosis['observed_drivers'] == 114
    assert diagnosis['canonical_name_sets_all_match'] and diagnosis['raw_list_string_mismatches'] > 0
    validation_path = root/'records/controller265_names_validation.json'
    validation = json.loads(validation_path.read_text())
    assert validation['state'] == 'indexed_name_comparison_regression_and_native_replay_passed'
    assert validation['unit_cases'] == 8 and validation['native_pairs'] == 114
    for path in [parent_path, control_path, plan_path, full_path, diagnosis_path, validation_path]:
        bind(path)
    for record in [parent, control, preparation, diagnosis, validation]:
        for key in ['source_sha256', 'native_evidence_sha256', 'generated_sha256', 'evidence_sha256']:
            for path, digest in record.get(key, {}).items():
                bind(path, digest)
    entry = root/'syn/tri_oracle_controller266_batch.tcl'
    corner_entry = root/'syn/tri_oracle_report_full_controller267_corner.tcl'
    names = ['run_tri_oracle_controller266_batch.py', 'tri_oracle_controller266_batch.tcl', 'tri_oracle_report_full_controller267_corner.tcl', 'tri_oracle_name265_lists.tcl', 'test_tri_oracle_name265_lists.tcl', 'tri_oracle_controller255_tree.py', 'test_tri_oracle_controller255_tree.py', 'tri_oracle_controller262_plan.py', 'test_tri_oracle_controller262_plan.py', 'tri_oracle_unique215_snapshot.tcl', 'tri_oracle_preservation233.tcl', 'tri_oracle_design242_metadata.tcl', 'tri_oracle_registered_reset_trace102.tcl', 'tri_oracle_check_registered_reset_fabric.tcl', 'tri_oracle_row_guard173_variants.py', 'run_tri_oracle_row_guard175_synthesis.py', 'tri_oracle_hierarchy_fingerprint.py', 'tri_oracle_artifact_fingerprint.py', 'tri_oracle_core_preservation.py', 'tri_oracle_frame202_preservation.py', 'tri_oracle_mapped_restore199.py', 'tri_oracle_row_guard175_checkpoint.py', 'tri_oracle_native_diagnostics.py', 'tri_oracle_memory_pressure_guard.py', 'tri_oracle_process_guard.py']
    for path in [*[root/'syn'/name for name in names], Path('/opt/cadence/INNOVUS251/doc/TCRcom/place_eco.html')]:
        bind(path)
    prefixes = root/'.cache/physical/pnr/tri_oracle_predicted_feedforward_placement202/core_prefixes.txt'
    assert str(prefixes) in identities and set(prefixes.read_text().splitlines()) == CORES
    started = time.monotonic()
    child = pause = token = None
    stopped = False
    evidence, runs = {}, {}
    output_db = output_fp = None
    record = dict(state='preflight', supervisor_pid=os.getpid(), started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), source_sha256=identities, native_workers=8, anonymous_limit_bytes=18*1024**3, host_reserve_bytes=5*1024**3, post_eco_mapped_functional_verification_pending=True, parent_timing_closed=False, parent_routing_completed=False, full_paper_results_matched=False, scope='1989 noninverting buffers on114 protected enable trees,47503 original loads. Exact original cells/masters/geometry/flags,60macroposes/halos,ports,constants,otherleafconnections,resetancestry,hierarchy/module/portprotection and86targets required. Full1889420corecells/600memorymodels/all3originalSDCs and coldreload required. Realcornerdiagnostics follow; no timing or functional pass inferred from connectivity.')

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

    def immutable():
        assert all(sha(path) == digest for path, digest in identities.items()), 'Tree source changed'
        assert all(sha(path) == digest for path, digest in evidence.items()), 'Tree evidence changed'
        assert artifact_fingerprint(models) == model_fp
        assert hierarchy_fingerprint(checkpoint, directory_dependencies=deps) == input_fp
        if output_db is not None:
            assert hierarchy_fingerprint(output_db, directory_dependencies=deps) == output_fp

    def native(phase, script, environment, marker):
        nonlocal child, pause, token
        directory = out/phase
        directory.mkdir()
        console = directory/'console.log'
        token = str(directory/'native')
        command = ['/opt/cadence/bin/innovus', '-stylus', '-no_gui', '-batch', '-log', token, '-files', str(script)]
        began = time.monotonic()
        with console.open('w') as stream:
            child = subprocess.Popen(command, cwd=directory, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, env=dict(os.environ, **environment))
            pause = OwnedProcessPause(child, token)
            policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3, anonymous_limit_bytes=18*1024**3)
            save(state='native_'+phase+'_running', phase=phase, native_process_group=child.pid, command=command)
            last = 0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-began < 3600, 'Tree wall/stop guard'
                    available, anonymous = memory()
                    record.update(peak_combined_anonymous_bytes=max(record.get('peak_combined_anonymous_bytes', 0), anonymous), current_host_available_bytes=available, current_combined_anonymous_bytes=anonymous)
                    action = policy.observe(available, anonymous, time.monotonic())
                    if action == 'pause':
                        pause.pause()
                    elif action == 'resume':
                        pause.resume()
                    if time.monotonic()-last > 5:
                        save(native_elapsed_seconds=time.monotonic()-began)
                        last = time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume()
                terminate_process_group(child, log_argument=token)
        text = console.read_text(errors='replace')
        require_clean_native(text)
        assert child.returncode == 0 and '\n'+marker+'\n' in text, str(console)
        for path in directory.rglob('*'):
            if path.is_file() and (path.suffix in ['.tsv', '.rpt', '.sdc', '.v', '.def', '.gz'] or path.name == 'console.log'):
                evidence[str(path)] = sha(path)
        runs[phase] = dict(native_exit_status=0, elapsed_seconds=time.monotonic()-began, console_sha256=sha(console))

    def sort_rows(path):
        target = path.with_suffix(path.suffix+'.sorted')
        subprocess.run(['sort', '-S', '64M', '-T', str(out), '-o', str(target), str(path)], check=True, env=dict(os.environ, LC_ALL='C'), timeout=600)
        evidence[str(target)] = sha(target)
        return target

    def equal(a, b):
        assert filecmp.cmp(sort_rows(a), sort_rows(b), shallow=False), 'Preserved data changed '+str(b)

    def placement(directory):
        text = (directory/'placement.rpt').read_text()
        assert 'Finished check_place' in text and re.search(r'Unplaced\s*=\s*0\b', text)
        assert not re.search(r'\b(overlap|violation|illegal|warning|error)s?\b', text, re.I)

    def tree_native(mode, database):
        marker = 'TRI_ORACLE_CONTROLLER266_TREE_PLACED_AND_ORIGINAL_CORES_EXPORTED' if mode == 'warm' else 'TRI_ORACLE_CONTROLLER266_COLD_TREE_AND_ORIGINAL_CORES_EXPORTED'
        native(mode, entry, dict(TRI266_OUT=str(out/mode), TRI266_INPUT=str(database), TRI266_MODE=mode, TRI266_PLAN=str(plan_dir/'plan.tsv'), TRI266_TREES=str(plan_dir/'trees.tsv'), TRI266_PREFIXES=str(prefixes)), marker)

    save()
    try:
        available, anonymous = memory()
        assert available > 20*1024**3 and anonymous < 1024**3
        immutable()
        out.mkdir()
        save(output_directory=str(out))
        tree_native('warm', checkpoint)
        warm = out/'warm'
        for kind in ['cells', 'ports', 'nets', 'pins', 'design', 'preservation', 'halos', 'core_pins', 'port_poses']:
            equal(baseline/f'cold_{kind}.tsv', warm/f'before_{kind}.tsv')
        pairs = [('before_cells', 'after_original_cells'), ('before_other_nets', 'after_other_nets')]+[(f'before_{kind}', f'after_{kind}') for kind in ['ports', 'pins', 'design', 'hierarchy', 'preservation', 'halos', 'core_pins', 'port_poses']]
        for before, after in pairs:
            equal(warm/(before+'.tsv'), warm/(after+'.tsv'))
        def positions(path):
            answer = {}
            with path.open() as stream:
                for row in csv.DictReader(stream, delimiter='\t'):
                    key=(row['tree'],row['pin'])
                    assert key not in answer
                    answer[key] = tuple(map(float, row['location'].strip('{}').split()))
            assert len(answer) == 47503
            return answer
        assert positions(plan_dir/'sinks.tsv') == positions(warm/'actual_sinks.tsv'), 'Plan used other sink geometry'
        with (warm/'placed_buffers.tsv').open() as stream:
            added = list(csv.DictReader(stream, delimiter='\t'))
        assert len(added) == len({row['instance'] for row in added}) == 1989
        assert all(row['status'] == 'placed' and row['master'] in ['BUFFD4BWP12T40P140', 'BUFFD8BWP12T40P140', 'BUFFD16BWP12T40P140'] for row in added)
        placement(warm)
        require_reset_topology(baseline/'cold_reset_roots.tsv', warm/'after_reset_roots.tsv')
        output_db = warm/'tree_full.db'
        output_fp = hierarchy_fingerprint(output_db, directory_dependencies=deps)
        immutable()
        save(state='transparent_tree_placed_original_parent_preserved_cold_pending', output_database=str(output_db), output_database_fingerprint=output_fp, added_noninverting_buffers=1989, all_original_parent_cells_geometry_flags_and_other_connections_preserved=True, native_runs=runs, native_evidence_sha256=evidence)
        tree_native('cold', output_db)
        cold = out/'cold'
        for kind in ['cells', 'ports', 'nets', 'pins', 'design', 'hierarchy', 'preservation', 'halos', 'core_pins', 'port_poses']:
            equal(warm/f'after_{kind}.tsv', cold/f'cold_{kind}.tsv')
        placement(cold)
        require_reset_topology(baseline/'cold_reset_roots.tsv', cold/'cold_reset_roots.tsv')
        preserved = {}
        for phase in ['warm', 'cold']:
            preserved[phase] = verify_core_snapshots(baseline/'core_cells.tsv', out/phase/'core_cells.tsv', sorted(CORES))
            assert preserved[phase]['total_original_cells'] == 1889420
            for view in ['setup_slow', 'setup_typ', 'hold_fast']:
                assert constraints_equivalent(commands(baseline/f'{view}.sdc'), commands(out/phase/f'{view}.sdc'))
            status = (out/phase/'full_model_status.rpt').read_text()
            instances = re.findall(r'^tri_oracle_sram_memory_compute\s+All\s+ILM\s+post-cts\s+(\S+)\s*$', status, re.M)
            assert len(instances) == 20 and set(instances) == CORES and 'current ilm data is for si mode' in status.lower()
        immutable()
        save(state='transparent_tree_and_original_models_cold_verified_corner_pending', original_core_preservation=preserved, original600_memory_models_preserved=True, all3_original_corner_constraints_preserved=True, original86_protected_targets_preserved=True, hierarchy_and_module_hport_policies_preserved=True, native_runs=runs, native_evidence_sha256=evidence)
        corners = {}
        for view in ['setup_slow', 'setup_typ', 'hold_fast']:
            immutable()
            phase = 'corner_'+view
            native(phase, corner_entry, dict(TRI_ORACLE_PARENT_DIAGNOSTIC_CHECKPOINT=str(output_db), TRI_ORACLE_PARENT_DIAGNOSTIC_DIRECTORY=str(out/phase), TRI_ORACLE_PARENT_DIAGNOSTIC_VIEW=view), 'TRI_ORACLE_FRAME267_CORNER_DIAGNOSTIC_FINISHED '+view)
            def path_row(name):
                with (out/phase/name).open() as stream:
                    rows = list(csv.DictReader(stream, delimiter='\t'))
                assert len(rows) == 1 and rows[0]['view'] == view
                row = rows[0]
                slack = float(row['slack_ns'])
                assert abs(slack) < 1e6
                return dict(slack_ns=slack, startpoint=row['startpoint'], endpoint=row['endpoint'])
            corners[view] = dict(worst=path_row('slack_properties.tsv'), original_parent_worst=parent['corner_diagnostics'][view]['worst'], native_run=runs[phase])
            if view != 'hold_fast':
                corners[view]['original_enable_endpoint'] = path_row('target_slack.tsv')
                corners[view]['original_down_enable_endpoint'] = path_row('original_down_target_slack.tsv')
            save(corner_diagnostics=corners, native_runs=runs, native_evidence_sha256=evidence)
        immutable()
        save(state='noninverting_controller_batch_cold_preserved_and_three_corners_completed', native_exit_status=0, corner_diagnostics=corners, native_runs=runs, native_evidence_sha256=evidence, timing_diagnostics_all_nonnegative=all(value['worst']['slack_ns'] >= 0 for value in corners.values()))
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=token)
        save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None)
        raise


if __name__ == '__main__':
    main()
