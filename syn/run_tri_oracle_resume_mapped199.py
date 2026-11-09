"""Cold-resume final optimization after the175 whole-flow wall guard expired."""
import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory


def extract_procedure(text, name):
    matches = re.findall(r'^proc ' + re.escape(name) + r' .*?^}\n', text, re.M | re.S)
    assert len(matches) == 1, 'Expected one independently pinned inventory procedure: ' + name
    return matches[0]


def main():
    root = Path(__file__).resolve().parents[1]
    result = root / 'records/resume199_synthesis_result.json'
    output = root / '.cache/physical/synthesis/tri_oracle_predicted_feedforward_resume199'
    assert not result.exists() and not output.exists()
    producer_path = root / 'records/rowguard175_synthesis_result.json'
    producer = json.loads(producer_path.read_text())
    assert producer['state'] == 'failed' and producer['exception'] == "AssertionError('Synthesis runtime limit')"
    assert not Path('/proc', str(producer['native_process_group'])).exists(), 'Original native job remains live'
    manifest_path = root / 'records/rowguard175_mapped_checkpoint_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['state'] == 'source_bound_native_full_parent_mapped_checkpoint_saved'
    previous = Path(manifest['checkpoint_path']).parent
    generic_path = root / 'records/rowguard175_generic_checkpoint_manifest.json'
    assert sha(generic_path) == manifest['generic_checkpoint_manifest_sha256']
    generic = json.loads(generic_path.read_text())
    assert generic['source_sha256'] == manifest['source_sha256']
    elaborated_path = previous / 'elaborated_checkpoint_manifest.json'
    assert sha(elaborated_path) == generic['elaborated_manifest_sha256']
    elaborated = json.loads(elaborated_path.read_text())
    assert all(sha(p) == h for p, h in elaborated['native_evidence_sha256'].items()), 'Archived175 baseline evidence changed'
    assert artifact_fingerprint(previous / 'mapped.db') == manifest['checkpoint_fingerprint']
    assert producer['source_sha256'] == manifest['source_sha256']
    data = (previous / 'console.log').read_bytes()[:manifest['console_prefix_length_bytes']]
    import hashlib
    assert hashlib.sha256(data).hexdigest() == manifest['console_prefix_sha256']
    assert data.endswith(('\n' + manifest['completed_marker'] + '\n').encode())
    paths = [Path(__file__).resolve(), root / 'syn/tri_oracle_resume_mapped199.tcl',
        root / 'syn/tri_oracle_mapped_restore199.py', root / 'syn/tri_oracle_row_guard175_checkpoint.py',
        root / 'syn/tri_oracle_mapped_boundary199.tcl',
        root / 'syn/tri_oracle_artifact_fingerprint.py', root / 'syn/tri_oracle_process_guard.py',
        root / 'syn/tri_oracle_memory_pressure_guard.py', producer_path, manifest_path, generic_path, elaborated_path,
        previous / 'elaborated_constraints.sdc', previous / 'reused_controls_before.tsv.sorted',
        previous / 'preserved_banks_before.tsv', previous / 'gate_cells_before.tsv']
    identities = {**manifest['source_sha256'], **elaborated['native_evidence_sha256'],
                  **{str(p): sha(p) for p in paths}}
    assert all(sha(p) == h for p, h in identities.items())
    prefix = root / 'syn/tri_oracle_prepare_hierarchical_frame144.tcl'
    tail = root / 'syn/tri_oracle_synthesize_row_guard175.tcl'
    gate_procedure = extract_procedure(tail.read_text(), 'gate_snapshot175')
    before = '''        set net [get_db $pin .hnet]
        if {[llength $net]!=1} {error FRAME175_GATE_BOUNDARY_DISCONNECTED}
        puts $stream "[get_db $pin .name]\\t[get_db $net .name]"'''
    after = '''        set description [tri_oracle_boundary199_connection $pin $gate]
        puts $stream "[get_db $pin .name]\\t$description"'''
    assert gate_procedure.count(before) == 1
    gate_procedure = gate_procedure.replace(before, after).replace('proc gate_snapshot175 ', 'proc gate_snapshot199 ')
    procedures = ''.join(extract_procedure(prefix.read_text(), name) for name in
        ['snapshot_reused_controls131', 'verify_real_banks']) + gate_procedure
    started = time.monotonic()
    child = pause = None
    stop_requested = False
    def stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    record = dict(state='preflight', supervisor_pid=os.getpid(), source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        mapped_checkpoint_fingerprint=manifest['checkpoint_fingerprint'], maximum_requested_cpu_workers=20,
        native_anonymous_limit_bytes=16*1024**3, host_reserve_bytes=5*1024**3,
        native_wall_limit_seconds=10800, generic_synthesis_repeated=False, technology_mapping_repeated=False,
        full_mapped_function_qualified=False, routed_timing_qualified=False, full_paper_results_matched=False,
        scope='Resume only whole-parent final optimization from source-bound completed175 mapping. '
              'Independent native retained-cell/constraint cold-restore checks precede optimization. '
              'Same twenty cores, forty aggregate memories,26 mapped controllers and1.72414ns constraints; '
              'provisional core80 timing guidance, not final physical timing or paper results.')
    def save(**changes):
        record.update(changes, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)
    def unchanged():
        assert all(sha(p) == h for p, h in identities.items()), 'Consumed input changed'
        assert artifact_fingerprint(previous / 'mapped.db') == manifest['checkpoint_fingerprint']
    save()
    try:
        while True:
            available, anonymous = memory()
            if available > 14*1024**3 and anonymous < 3*1024**3:
                break
            assert not stop_requested and time.monotonic()-started < 7200, 'Resume headroom wait expired'
            save(state='waiting_for_initial_memory_headroom')
            time.sleep(2)
        unchanged()
        output.mkdir()
        generated = output / 'retained_inventory_procedures.tcl'
        generated.write_text(procedures)
        identities[str(generated)] = sha(generated)
        revision = output / 'input_revision.json'
        revision.write_text(json.dumps(dict(source_sha256=identities,
            mapped_checkpoint_fingerprint=manifest['checkpoint_fingerprint']), indent=2)+'\n')
        identities[str(revision)] = sha(revision)
        unchanged()
        command = ['genus', '-no_gui', '-batch', '-log', str(output/'native'),
                   '-files', str(root/'syn/tri_oracle_resume_mapped199.tcl')]
        native_started = time.monotonic()
        console = output / 'console.log'
        with console.open('w') as stream:
            child = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True, env=dict(os.environ,
                    TRI_ORACLE_SYNTH_OUTPUT=str(output), TRI_ORACLE_RESUME199_SOURCE=str(previous),
                    TRI_ORACLE_RESUME199_REVISION_SHA256=sha(revision),
                    TRI_ORACLE_GATE175_ISOLATED_CELLS=str(root/'.cache/physical/synthesis/tri_oracle_private_gate164/isolated_cells.tsv')))
            pause = OwnedProcessPause(child, str(output/'native'))
            policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3,
                                          anonymous_limit_bytes=16*1024**3)
            save(state='native_mapped_cold_restore_and_optimization_running', source_sha256=identities,
                 native_process_group=child.pid, output_directory=str(output), command=command)
            last_save = 0
            while child.poll() is None:
                assert not stop_requested and time.monotonic()-native_started < 10800, 'Optimization runtime or external stop guard'
                available, anonymous = memory()
                action = policy.observe(available, anonymous, time.monotonic())
                if action in ['pause', 'resume']:
                    groups = pause.pause() if action == 'pause' else pause.resume()
                    save(memory_pressure_events=record.get('memory_pressure_events', [])+
                         [dict(action=action, groups=groups, available=available, anonymous=anonymous)])
                record['peak_combined_anonymous_bytes'] = max(record.get('peak_combined_anonymous_bytes', 0), anonymous)
                if time.monotonic()-last_save > 5:
                    save(native_elapsed_seconds=time.monotonic()-native_started,
                         current_combined_anonymous_bytes=anonymous, current_host_available_bytes=available)
                    last_save = time.monotonic()
                time.sleep(.2)
            pause.resume()
            terminate_process_group(child, log_argument=str(output/'native'))
        text = console.read_text(errors='replace')
        assert child.returncode == 0 and '\nTRI_ORACLE_FRAME199_PARENT_OPTIMIZATION_COMPLETED\n' in text, text[-4000:]
        unchanged()
        proof_path = output / 'mapped_cold_restore_qualification.json'
        proof = json.loads(proof_path.read_text())
        assert proof['state'] == 'source_bound_full_parent_mapped_cold_restore_qualified'
        post_path = output / 'optimized_topology_qualification.json'
        assert json.loads(post_path.read_text())['state'] == 'source_bound_full_parent_optimized_topology_qualified'
        save(state='native_parent_mapping_completed_pending_report_review', native_exit_status=0,
            native_elapsed_seconds=time.monotonic()-native_started, console_sha256=sha(console),
            output_netlist_sha256=sha(output/'netlist.v'), output_constraints_sha256=sha(output/'constraints.sdc'),
            cold_restore_validation_sha256=sha(proof_path),
            optimized_topology_validation_sha256=sha(post_path),
            optimized_checkpoint_fingerprint=artifact_fingerprint(output/'optimized.db'))
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=str(output/'native'))
        save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None)
        raise


if __name__ == '__main__':
    main()
