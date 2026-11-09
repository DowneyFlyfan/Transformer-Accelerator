"""Restore every original core after electrical repair and diagnose three corners.

The repaired parent is the reference for connectivity and placement. The
qualified pre-repair full parent remains the reference for core internals and
all three original timing constraint sets. Negative timing is recorded, never
converted to a successful closure claim.
"""
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

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_frame202_preservation import require_reset_topology, CORES
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def main():
    root = Path(__file__).resolve().parents[1]
    base = root/'.cache/physical'
    out = base/'pnr/tri_oracle_restore_frame247'
    result = root/'records/frame247_restore_result.json'
    assert not out.exists() and not result.exists()
    producer_path = root/'records/frame251_electrical_result.json'
    producer = json.loads(producer_path.read_text())
    assert producer['state'] == 'guidance_electrical_optimization_completed_pending_full_restore_and_function'
    for flag in ['original86_protected_targets_retained', 'all382490_protected_controller_cell_names_and_masters_retained', 'original_macro_halos_hierarchy_and_port_poses_preserved', 'original_typical_constraints_preserved', 'temporary_reset_flags_exactly_restored', 'original_pre_route_rc_scale_factors_preserved']:
        assert producer[flag] is True
    checkpoint = Path(producer['output_database'])
    input_fp = producer['output_database_fingerprint']
    assert hierarchy_fingerprint(checkpoint) == input_fp
    identities = {}

    def bind(path, digest=None):
        path = str(path)
        observed = sha(path)
        assert digest is None or digest == observed, 'Changed input '+path
        assert path not in identities or identities[path] == observed, 'Conflicting input '+path
        identities[path] = observed

    bind(producer_path)
    for key in ['source_sha256', 'native_evidence_sha256']:
        for name, digest in producer[key].items():
            bind(name, digest)
    original_path = root/'records/unique235_parent_result.json'
    original = json.loads(original_path.read_text())
    assert original['state'] == 'unique_parent_connectivity_and_cold_full_core_preservation_verified'
    baseline = Path(original['output_directory'])
    core_before = baseline/'cold/core_after.tsv'
    assert str(core_before) in identities
    prefixes = base/'pnr/tri_oracle_predicted_feedforward_placement202/core_prefixes.txt'
    assert str(prefixes) in identities and set(prefixes.read_text().splitlines()) == CORES
    original_corners = {view: baseline/'warm'/f'before_{view}.sdc' for view in ['setup_slow', 'setup_typ', 'hold_fast']}
    for path in original_corners.values():
        assert str(path) in identities
    full_path = root/'records/sram_core_hierarchy68_full_control_validation.json'
    full = json.loads(full_path.read_text())
    models = base/'pnr/tri_oracle_sram_memory_compute/hierarchy_full_control_68'
    assert artifact_fingerprint(models) == full['output_artifact_fingerprint']
    deps = {models/'ilm': {'type': 'directory', 'files': {name[4:]: value for name, value in full['output_artifact_fingerprint']['files'].items() if name.startswith('ilm/')}}}
    imported_path = root/'records/frame207_import_result.json'
    imported = json.loads(imported_path.read_text())
    canonical = base/'pnr/tri_oracle_sram_memory_compute/hierarchy_twenty_core_75_inputs/wrapper.v'
    bind(canonical, imported['source_sha256'][str(canonical)])
    libraries, rcs = {}, {}
    for corner, suffix, rc in [('slow', 'ssg0p9v125c', 'qrc_rcworst'), ('typ', 'tt1v25c', 'qrc_typical'), ('fast', 'ffg1p05vm40c', 'qrc_rcbest')]:
        libraries[corner] = [base/f'library/tcbn28hpcplusbwp12t40p140{suffix}.lib', base/f'sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/NLDM/ts5n28hpcpsvta32x128m2fw_130a_{suffix}.lib', base/f'sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/NLDM/ts6n28hpcpsvta16x128m2f_130a_{suffix}.lib', base/f'sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/NLDM/ts5n28hpcpsvta512x64m4f_130a_{suffix}.lib']
        rcs[corner] = base/'rc'/rc
        for path in libraries[corner]+[rcs[corner]]:
            bind(path, imported['source_sha256'][str(path)])
    entry = root/'syn/tri_oracle_restore_frame247.tcl'
    corner_entry = root/'syn/tri_oracle_report_full_frame248_corner.tcl'
    names = ['run_tri_oracle_restore_frame247.py', 'tri_oracle_restore_frame247.tcl', 'tri_oracle_report_full_frame248_corner.tcl', 'tri_oracle_unique215_snapshot.tcl', 'tri_oracle_preservation233.tcl', 'tri_oracle_design242_metadata.tcl', 'tri_oracle_registered_reset_trace102.tcl', 'tri_oracle_check_registered_reset_fabric.tcl', 'tri_oracle_artifact_fingerprint.py', 'tri_oracle_hierarchy_fingerprint.py', 'tri_oracle_core_preservation.py', 'tri_oracle_frame202_preservation.py', 'tri_oracle_mapped_restore199.py', 'tri_oracle_row_guard175_checkpoint.py', 'tri_oracle_row_guard173_variants.py', 'run_tri_oracle_row_guard175_synthesis.py', 'tri_oracle_native_diagnostics.py', 'tri_oracle_memory_pressure_guard.py', 'tri_oracle_process_guard.py']
    for path in [original_path, full_path, imported_path, *[root/'syn'/name for name in names], Path('/opt/cadence/INNOVUS251/doc/DBcom/inst.html')]:
        bind(path)
    started = time.monotonic()
    child = pause = token = None
    stopped = False
    evidence, generated, runs = {}, {}, {}
    restored_db = restored_fp = None
    record = dict(state='preflight', supervisor_pid=os.getpid(), started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), source_sha256=identities, native_workers=4, anonymous_limit_bytes=18*1024**3, host_reserve_bytes=5*1024**3, post_eco_mapped_functional_verification_pending=True, parent_timing_closed=False, parent_routing_completed=False, full_paper_results_matched=False, scope='Fresh full-model import and cold reload of repaired20-core parent. Original1889420 core cells/600memory models and all3original timing constraints required; repaired parent connectivity/geometry/attributes preserved. Three independent full-model timing diagnostics follow; negative slack is retained as failure to meet timing, not waived.')

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
        assert all(sha(path) == digest for path, digest in identities.items()), 'Restore source changed'
        assert all(sha(path) == digest for path, digest in evidence.items()), 'Restore evidence changed'
        assert all(sha(path) == digest for path, digest in generated.items()), 'Restore generated input changed'
        assert hierarchy_fingerprint(checkpoint) == input_fp
        assert artifact_fingerprint(models) == full['output_artifact_fingerprint']
        if restored_db is not None:
            assert hierarchy_fingerprint(restored_db, directory_dependencies=deps) == restored_fp

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
                    assert not stopped and time.monotonic()-began < 3600, 'Full restore wall/stop guard'
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
        ordered = path.with_suffix(path.suffix+'.sorted')
        subprocess.run(['sort', '-S', '64M', '-T', str(out), '-o', str(ordered), str(path)], check=True, env=dict(os.environ, LC_ALL='C'), timeout=600)
        evidence[str(ordered)] = sha(ordered)
        return ordered

    def parent_equal(directory, tag):
        for kind in ['cells', 'ports', 'nets', 'pins', 'design', 'hierarchy', 'halos', 'port_poses', 'controller_cells']:
            source = sort_rows(out/'reference'/f'reference_{kind}.tsv')
            target = sort_rows(directory/f'{tag}_{kind}.tsv')
            assert filecmp.cmp(source, target, shallow=False), 'Repaired parent changed '+tag+' '+kind
        assert (out/'reference/reference_preservation.tsv').read_text() == (directory/f'{tag}_preservation.tsv').read_text()
        require_reset_topology(out/'reference/reference_reset_roots.tsv', directory/f'{tag}_reset_roots.tsv')
        def pins(path):
            with path.open() as stream:
                rows = list(csv.DictReader(stream, delimiter='\t'))
            assert len(rows) == len({row['pin'] for row in rows})
            return {row['pin']: row for row in rows}
        source = pins(out/'reference/reference_core_pins.tsv')
        original = {name: row for name, row in source.items() if row['direction'] != 'internal'}
        internal = {name: row for name, row in source.items() if row['direction'] == 'internal'}
        assert len(original) == 63160 and len(internal) == 20
        assert all(row['net'] == '' and row['constant'] == 'no_constant' and name.endswith('/_INT_clk_src_data_check_clk') for name, row in internal.items())
        assert pins(directory/f'{tag}_core_pins.tsv') == original
        text = (directory/f'{tag}_placement.rpt').read_text()
        assert 'Finished check_place' in text and re.search(r'Unplaced\s*=\s*0\b', text)
        assert not re.search(r'\b(overlap|violation|illegal|warning|error)s?\b', text, re.I)

    def restore_native(mode, database):
        native(mode, entry, dict(TRI247_OUT=str(out/mode), TRI247_PARENT=str(out), TRI247_MODE=mode, TRI247_INPUT=str(database), TRI247_PREFIXES=str(prefixes)), 'TRI_ORACLE_FRAME247_REPAIRED_REFERENCE_EXPORTED' if mode == 'reference' else 'TRI_ORACLE_FRAME247_ALL_ORIGINAL_CORES_VERIFIED '+mode)

    save()
    try:
        available, anonymous = memory()
        assert available > 18*1024**3 and anonymous < 1024**3, 'Concurrent native work or insufficient headroom'
        immutable()
        out.mkdir()
        save(output_directory=str(out))
        restore_native('reference', checkpoint)
        assert constraints_equivalent(commands(original_corners['setup_typ']), commands(out/'reference/setup_typ.sdc'))
        mapped = (out/'reference/parent.v').read_text()
        pattern = re.compile(r'^\s*module\s+tri_oracle_sram_memory_compute\s*\(', re.M)
        if not pattern.search(mapped):
            text = canonical.read_text()
            starts = list(pattern.finditer(text))
            assert len(starts) == 1
            end = re.search(r'^\s*endmodule\s*$', text[starts[0].start():], re.M)
            assert end
            mapped += '\n'+text[starts[0].start():starts[0].start()+end.end()]+'\n'
        path = out/'parent_import.v'
        path.write_text(mapped)
        generated[str(path)] = sha(path)
        mmmc = ''
        for corner, view, temp in [('slow', 'setup_slow', 125), ('typ', 'setup_typ', 25), ('fast', 'hold_fast', -40)]:
            mmmc += 'create_library_set -name ls_'+corner+' -timing [list '+' '.join('{'+str(path)+'}' for path in libraries[corner])+']\n'
            mmmc += f'create_rc_corner -name rc_{corner} -qrc_tech {{{rcs[corner]}}} -temperature {temp}\ncreate_timing_condition -name tc_{corner} -library_sets {{ls_{corner}}}\ncreate_delay_corner -name dc_{corner} -timing_condition tc_{corner} -rc_corner rc_{corner}\n'
            mmmc += f'create_constraint_mode -name functional_{corner} -sdc_files [list {{{original_corners[view]}}}]\nupdate_constraint_mode -name functional_{corner} -ilm_sdc_files [list {{{original_corners[view]}}}]\ncreate_analysis_view -name {view} -constraint_mode functional_{corner} -delay_corner dc_{corner}\n'
        mmmc += 'set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}\n'
        assert 'core_typ.lib' not in mmmc
        path = out/'full_mmmc.tcl'
        path.write_text(mmmc)
        generated[str(path)] = sha(path)
        immutable()
        save(native_evidence_sha256=evidence, generated_sha256=generated, native_runs=runs)
        restore_native('full', checkpoint)
        parent_equal(out/'full', 'imported')
        parent_equal(out/'full', 'restored')
        restored_db = out/'full/restored_full.db'
        restored_fp = hierarchy_fingerprint(restored_db, directory_dependencies=deps)
        immutable()
        save(state='full_original_models_restored_cold_validation_pending', output_database=str(restored_db), output_database_fingerprint=restored_fp, native_evidence_sha256=evidence, generated_sha256=generated, native_runs=runs)
        restore_native('cold', restored_db)
        parent_equal(out/'cold', 'restored')
        preserves = {}
        for phase in ['full', 'cold']:
            preserves[phase] = verify_core_snapshots(core_before, out/phase/'core_cells.tsv', sorted(CORES))
            assert preserves[phase]['total_original_cells'] == 1889420
            for view, reference in original_corners.items():
                assert constraints_equivalent(commands(reference), commands(out/phase/f'{view}.sdc')), 'Original constraints changed '+phase+' '+view
            status = (out/phase/'full_model_status.rpt').read_text()
            instances = re.findall(r'^tri_oracle_sram_memory_compute\s+All\s+ILM\s+post-cts\s+(\S+)\s*$', status, re.M)
            assert len(instances) == 20 and set(instances) == CORES and 'current ilm data is for si mode' in status.lower()
        immutable()
        save(state='full_original_models_and_repaired_parent_cold_preservation_verified_timing_pending', native_exit_status=0, original_core_preservation=preserves, all3_original_corner_constraints_preserved=True, all_repaired_parent_connectivity_geometry_attributes_preserved=True, original600_memory_models_restored=True, original86_protected_targets_preserved=True, native_evidence_sha256=evidence, generated_sha256=generated, native_runs=runs)
        corners = {}
        for view in original_corners:
            phase = 'corner_'+view
            immutable()
            native(phase, corner_entry, dict(TRI_ORACLE_PARENT_DIAGNOSTIC_CHECKPOINT=str(restored_db), TRI_ORACLE_PARENT_DIAGNOSTIC_DIRECTORY=str(out/phase), TRI_ORACLE_PARENT_DIAGNOSTIC_VIEW=view), 'TRI_ORACLE_FRAME248_CORNER_DIAGNOSTIC_FINISHED '+view)
            with (out/phase/'slack_properties.tsv').open() as stream:
                rows = list(csv.DictReader(stream, delimiter='\t'))
            assert len(rows) == 1 and rows[0]['view'] == view
            slack = float(rows[0]['slack_ns'])
            assert abs(slack) < 1e6
            corners[view] = dict(slack_ns=slack, startpoint=rows[0]['startpoint'], endpoint=rows[0]['endpoint'], check_scope='early_path_may_include_reset_removal' if view == 'hold_fast' else 'setup', native_run=runs[phase])
            save(corner_diagnostics=corners, native_evidence_sha256=evidence, native_runs=runs)
        immutable()
        save(state='full_original_models_cold_verified_and_three_corner_diagnostics_completed', native_exit_status=0, corner_diagnostics=corners, native_evidence_sha256=evidence, generated_sha256=generated, native_runs=runs, timing_diagnostics_all_nonnegative=all(item['slack_ns'] >= 0 for item in corners.values()))
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=token)
        save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None)
        raise


if __name__ == '__main__':
    main()
