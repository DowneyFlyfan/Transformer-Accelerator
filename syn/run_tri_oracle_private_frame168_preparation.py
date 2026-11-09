"""Relink only the independently qualified private gate into the full parent."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchical_controller_adapter155 import checked_hierarchical_controller_adapter
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_private_relink162_validation import validate_private_relinked_parent
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def memory():
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024
    anonymous = int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available, anonymous


def main():
    root = Path(__file__).resolve().parents[1]
    result = root/'records/frame168_preparation_result.json'
    output = root/'.cache/physical/synthesis/tri_oracle_predicted_feedforward_private168'
    assert not result.exists() and not output.exists()
    started = time.monotonic()
    child = pause = None
    stop_requested = False
    prefix_path = root/'syn/tri_oracle_synthesize_resumed_frame145.tcl'
    tail_path = root/'syn/tri_oracle_relink_gate168.tcl'
    static_paths = [Path(__file__).resolve(), prefix_path, tail_path, Path('/opt/cadence/bin/genus'),
        root/'verilog/tri_oracle_fabric_gated_executor.sv',
        *[root/'syn'/name for name in ['tri_oracle_hierarchical_controller_adapter155.py',
            'tri_oracle_named_controller_adapters137.py', 'tri_oracle_checked_controller_adapters138.py',
            'tri_oracle_private_relink162_validation.py', 'tri_oracle_relinked_parent159_validation.py',
            'tri_oracle_namespace_mapped160.py', 'tri_oracle_validate_cold_restore145.py',
            'tri_oracle_artifact_fingerprint.py', 'tri_oracle_memory_pressure_guard.py', 'tri_oracle_process_guard.py']],
        Path('/opt/cadence/GENUS251/doc/genus_comref/change_link.html'),
        Path('/opt/cadence/GENUS251/doc/genus_comref/write_db.html')]
    static_hashes = {str(path): sha(path) for path in static_paths}
    record = dict(state='preflight', supervisor_pid=os.getpid(), static_source_sha256=static_hashes,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        full_paper_results_matched=False, routed_timing_qualified=False,
        scope='Full20-core prepared prediction/feed-forward parent relink checkpoint using the exact privately named '
              'gate netlist and independent cell ledger qualified in isolation. No full-parent synthesis, mapped '
              'simulation, physical timing or paper-result claim.')

    def save(**updates):
        record.update(updates, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)

    def unchanged(hashes):
        assert all(sha(path) == expected for path, expected in hashes.items()), 'Queued or running source changed'

    def stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    save()
    try:
        isolation_path = root/'records/gate164_private_qualification_result.json'
        while True:
            assert not stop_requested and time.monotonic()-started < 18000, 'Private mapped gate proof wait expired'
            if isolation_path.exists():
                isolation = json.loads(isolation_path.read_text())
                assert isolation['state'] != 'failed', 'Private mapped gate proof failed'
                if isolation['state'] == 'private_gate_import_and_mapped_functional_qualified':
                    break
            save(state='waiting_for_independently_qualified_private_gate')
            time.sleep(2)
        unchanged(static_hashes)
        unchanged(isolation['source_sha256'])
        assert isolation['cases_passed'] == 31 and isolation['projection_requests'] == 38
        assert isolation['wrong_mathematical_reference_rejected'] and isolation['exact_quantization_checks'] == 525
        assert isolation['known_activation_input_checks']==525
        normalization=isolation['tag_normalization']
        assert normalization['mode']=='remove_only_unimplemented_upper_tag_interface_bits'
        assert normalization['implemented_tag_width_bits']==8 and normalization['all_mapped_cell_statements_unchanged']
        isolated = Path(isolation['output_directory'])
        imported_path = isolated/'qualified_import.v'
        isolated_cells = isolated/'isolated_cells.tsv'
        assert sha(imported_path) == isolation['qualified_import_sha256']
        assert sha(isolated_cells) == isolation['isolated_cell_inventory_sha256']
        imported = 'tri_oracle_fabric_gated_executor_mapped153'
        modules = isolation['exported_module_names']
        assert imported in modules and len(modules) == len(set(modules))
        assert all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9$]*', name) for name in modules)
        assert all(name == imported or name.startswith('tri_oracle_gated160_') for name in modules)
        gate_path = root/'records/gated154_mapped_result.json'
        gate = json.loads(gate_path.read_text())
        assert gate['state'] == 'original_gate_controller_mapped_functional_qualified'
        unchanged(gate['source_sha256'])
        producer_path = root/'records/frame144_preparation_result.json'
        producer = json.loads(producer_path.read_text())
        assert producer['state'] == 'native_parent_preoptimization_checkpoint_saved_pending_validation'
        prepared = Path(producer['output_directory'])
        manifest_path = prepared/'elaborated_checkpoint_manifest.json'
        manifest = json.loads(manifest_path.read_text())
        assert sha(manifest_path) == producer['output_checkpoint_manifest_sha256']
        assert artifact_fingerprint(prepared/'elaborated.db') == manifest['checkpoint_fingerprint']
        unchanged(manifest['source_sha256'])
        unchanged(manifest['native_evidence_sha256'])
        prefix_source = prefix_path.read_text()
        assert prefix_source.count('\nsyn_generic\n') == 1
        prefix = prefix_source.split('\nsyn_generic\n', 1)[0]
        assert prefix.rstrip().endswith('puts TRI_ORACLE_FRAME145_COLD_RESTORE_AND_ORIGINAL_CONSTRAINTS_VERIFIED')
        entry_source = prefix+'\n'+tail_path.read_text()
        identities = {**manifest['source_sha256'], **isolation['source_sha256'], **gate['source_sha256'],
                      **{str(path): sha(path) for path in [isolation_path, gate_path, producer_path, manifest_path, imported_path, isolated_cells]},
                      **static_hashes}
        unchanged(identities)
        while True:
            available, anonymous = memory()
            if available > 14*1024**3 and anonymous < 3*1024**3:
                break
            assert not stop_requested and time.monotonic()-started < 21600, 'Parent relink initial headroom wait expired'
            save(state='waiting_for_initial_memory_headroom')
            time.sleep(2)
        unchanged(identities)
        output.mkdir()
        (output/'gated_import.v').write_bytes(imported_path.read_bytes())
        _, interface = checked_hierarchical_controller_adapter(root/'verilog/tri_oracle_fabric_gated_executor.sv',
                                                               output/'gated_import.v', imported)
        assert interface == isolation['interface']
        (output/'gated_interface.json').write_text(json.dumps(dict(module=imported, instance='numeric/engine/gated',
                                                                 ports=interface), indent=2)+'\n')
        (output/'native_entry.tcl').write_text(entry_source)
        generated = {name: sha(output/name) for name in ['gated_import.v', 'native_entry.tcl', 'gated_interface.json']}
        assert generated['gated_import.v'] == isolation['qualified_import_sha256']
        (output/'input_revision.json').write_text(json.dumps(dict(source_sha256=identities, generated_sha256=generated,
            mapped_gate_qualification=str(gate_path), isolated_gate_qualification=str(isolation_path),
            producer_checkpoint_fingerprint=manifest['checkpoint_fingerprint']), indent=2)+'\n')
        log_argument = str(output/'native')
        command = ['genus', '-no_gui', '-batch', '-log', log_argument, '-files', str(output/'native_entry.tcl')]
        native_started = time.monotonic()
        unchanged(identities)
        assert all(sha(output/name) == digest for name, digest in generated.items())
        with (output/'console.log').open('w') as stream:
            child = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=True, env=dict(os.environ, TRI_ORACLE_SYNTH_OUTPUT=str(output), TRI_ORACLE_PREOPT_SOURCE=str(prepared),
                    TRI_ORACLE_GATED168_MODULE=imported, TRI_ORACLE_GATED168_MODULE_NAMES=' '.join(modules),
                    TRI_ORACLE_GATED168_ISOLATED_CELLS=str(isolated_cells),
                    TRI_ORACLE_GATED168_BOUNDARY_BITS=str(sum(shape['width_bits'] for shape in interface.values()))))
            pause = OwnedProcessPause(child, log_argument)
            policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3, anonymous_limit_bytes=16*1024**3)
            save(state='native_full_parent_private_gate_relink_running', native_process_group=child.pid,
                 source_sha256=identities, generated_sha256=generated, output_directory=str(output), command=command)
            last_save = 0
            while child.poll() is None:
                assert not stop_requested and time.monotonic()-native_started < 900, 'Parent relink runtime limit'
                available, anonymous = memory()
                record.update(current_host_available_bytes=available, current_combined_anonymous_bytes=anonymous,
                              peak_combined_anonymous_bytes=max(record.get('peak_combined_anonymous_bytes', 0), anonymous))
                action = policy.observe(available, anonymous, time.monotonic())
                if action in ['pause', 'resume']:
                    groups = pause.pause() if action == 'pause' else pause.resume()
                    save(memory_pressure_events=record.get('memory_pressure_events', [])+
                         [dict(action=action, groups=groups, available=available, anonymous=anonymous)])
                if time.monotonic()-last_save > 5:
                    save(native_elapsed_seconds=time.monotonic()-native_started)
                    last_save = time.monotonic()
                time.sleep(.2)
            pause.resume()
            terminate_process_group(child, log_argument=log_argument)
        text = (output/'console.log').read_text(errors='replace')
        assert child.returncode == 0 and '\nTRI_ORACLE_FRAME168_MAPPED_GATE_RELINK_CHECKPOINT_WRITTEN\n' in text, text[-4000:]
        assert '\nTRI_ORACLE_FRAME168_NO_UNRESOLVED_IMPORTS_OR_RELINK\n' in text
        qualification = validate_private_relinked_parent(output, prepared, identities, generated)
        qualification_path = output/'elaborated_checkpoint_manifest.json'
        qualification_path.write_text(json.dumps(qualification, indent=2)+'\n')
        save(state='native_full_parent_private_gate_relink_checkpoint_qualified', native_exit_status=0,
             native_elapsed_seconds=time.monotonic()-native_started, output_checkpoint_manifest_sha256=sha(qualification_path),
             output_checkpoint_fingerprint=qualification['checkpoint_fingerprint'],
             mapped_gate_standard_cells=qualification['mapped_gate_standard_cells'],
             mapped_gate_boundary_bits=qualification['mapped_gate_boundary_bits'])
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=str(output/'native'))
        save(state='failed', exception=repr(error))
        raise
    finally:
        for name in ['gate_source_cells.sorted', 'isolated_expected_cells.sorted']:
            (output/name).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
