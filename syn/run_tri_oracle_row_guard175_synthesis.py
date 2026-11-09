"""Map the full prepared parent after equivalent row-overflow guard reduction."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchical_controller_adapter155 import checked_hierarchical_controller_adapter
from tri_oracle_row_guard173_variants import sha, once
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def memory():
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024
    anonymous = int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available, anonymous


def main():
    root = Path(__file__).resolve().parents[1]
    result = root/'records/rowguard175_synthesis_result.json'
    output = root/'.cache/physical/synthesis/tri_oracle_predicted_feedforward_rowguard175'
    assert not result.exists() and not output.exists()
    started = time.monotonic()
    child = pause = None
    stop_requested = False
    def stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    prefix_path = root/'syn/tri_oracle_prepare_hierarchical_frame144.tcl'
    tail_path = root/'syn/tri_oracle_synthesize_row_guard175.tcl'
    prior_path = root/'records/frame144_preparation_result.json'
    prior = json.loads(prior_path.read_text())
    assert prior['state'] == 'native_parent_preoptimization_checkpoint_saved_pending_validation'
    prepared = Path(prior['output_directory'])
    manifest_path = prepared/'elaborated_checkpoint_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert sha(manifest_path) == prior['output_checkpoint_manifest_sha256']
    assert all(sha(p) == h for p, h in manifest['source_sha256'].items())
    assert all(sha(p) == h for p, h in manifest['native_evidence_sha256'].items())
    isolation_path = root/'records/gate164_private_qualification_result.json'
    isolation = json.loads(isolation_path.read_text())
    assert isolation['state'] == 'private_gate_import_and_mapped_functional_qualified'
    assert isolation['exact_quantization_checks'] == isolation['known_activation_input_checks'] == 525
    assert isolation['wrong_mathematical_reference_rejected']
    gate_folder = Path(isolation['output_directory'])
    imported = gate_folder/'qualified_import.v'
    ledger = gate_folder/'isolated_cells.tsv'
    assert sha(imported) == isolation['qualified_import_sha256']
    assert sha(ledger) == isolation['isolated_cell_inventory_sha256']
    revision_path = prepared/'input_revision.json'
    revision = json.loads(revision_path.read_text())
    libraries = revision['library_list']
    static_paths = [Path(__file__).resolve(), prefix_path, tail_path, prior_path, manifest_path,
        isolation_path, revision_path, prepared/'compiled_cluster_sources.sv', ledger, imported,
        Path('/opt/cadence/bin/genus'), root/'verilog/tri_oracle_fabric_gated_executor.sv',
        root/'syn/tri_oracle_hierarchical_controller_adapter155.py',
        root/'syn/tri_oracle_named_controller_adapters137.py', root/'syn/tri_oracle_checked_controller_adapters138.py',
        root/'syn/tri_oracle_row_guard173_variants.py', root/'syn/tri_oracle_artifact_fingerprint.py',
        root/'syn/tri_oracle_row_guard175_checkpoint.py',
        root/'syn/tri_oracle_memory_pressure_guard.py', root/'syn/tri_oracle_process_guard.py']
    identities = {**manifest['source_sha256'], **manifest['native_evidence_sha256'], **isolation['source_sha256'],
                  **{str(p): sha(p) for p in static_paths}}
    frozen_path = root/'.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/input_revision.json'
    frozen = json.loads(frozen_path.read_text())['candidate_rtl_inventory']
    assert all(sha(root/p) == h for p, h in frozen.items())
    identities.update({str(root/p): h for p, h in frozen.items()})
    record = dict(state='preflight', supervisor_pid=os.getpid(), source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), full_paper_results_matched=False,
        routed_timing_qualified=False, maximum_requested_cpu_workers=20,
        native_anonymous_limit_bytes=16*1024**3, host_reserve_bytes=5*1024**3,
        scope='Full prepared20-core/40-aggregate-bank prediction/feed-forward parent,26 preserved mapped controllers. '
              'Only shared/projection row-address validation refactored to the largest active ID; '
              'same1.72414ns clock and IO constraints. Provisional core80 synthesis timing guidance; '
              'whole mapped function, full physical timing and paper metrics remain separate gates.')
    def save(**changes):
        record.update(changes, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)
    def unchanged():
        assert all(sha(p) == h for p, h in identities.items()), 'Static or generated consumed input changed'
    save()
    try:
        functional_path = root/'records/rowguard182_full_frame_result.json'
        while True:
            unchanged()
            assert not stop_requested and time.monotonic()-started < 7200, 'Source functional wait expired'
            if functional_path.exists():
                functional = json.loads(functional_path.read_text())
                assert functional['state'] != 'failed', 'Reduced-guard source functional qualification failed'
                if functional['state'] == 'row_guard_full_frame_source_functional_qualified':
                    break
            save(state='waiting_for_reduced_guard_full_frame_qualification')
            time.sleep(2)
        assert functional['cases_seen'] == 12 and functional['hidden_outputs_checked'] == 4420
        assert functional['actual_cores'] == 20 and functional['actual_compiled_memories'] == 600
        assert functional['wrong_mathematical_reference_rejected']
        identities.update(functional['source_sha256'])
        identities[str(functional_path)] = sha(functional_path)
        variants_path = root/'.cache/physical/rtl/rowguard173/variants.json'
        variants = json.loads(variants_path.read_text())
        assert sha(variants_path) == functional['variants_manifest_sha256']
        assert all(sha(p) == h for p, h in variants['generated_sha256'].items())
        compiled = (prepared/'compiled_cluster_sources.sv').read_text()
        assert sha(prepared/'compiled_cluster_sources.sv') == manifest['consumed_bundle_sha256']
        for original, replacement in variants['replacements'].items():
            compiled = once(compiled, '`include "'+original+'"', '`include "'+replacement+'"')
        for name in ['silu_gate', 'fabric_gated_executor']:
            compiled = once(compiled, '`include "'+str(root/'verilog'/('tri_oracle_'+name+'.sv'))+'"\n', '')
        adapter, interface = checked_hierarchical_controller_adapter(root/'verilog/tri_oracle_fabric_gated_executor.sv',
            imported, 'tri_oracle_fabric_gated_executor_mapped153')
        assert interface == isolation['interface']
        compiled = adapter+'`include "'+str(root/'verilog/tri_oracle_row_address_guard.sv')+'"\n'+compiled
        prefix = prefix_path.read_text()
        prefix = once(prefix, 'set_db max_cpus_per_server 18', 'set_db max_cpus_per_server 20')
        prefix = once(prefix, 'set_db syn_global_effort none\n',
                      'set_db syn_global_effort none\nset_db control_logic_optimization none\n')
        prefix = once(prefix, 'read_hdl -sv $output/compiled_cluster_sources.sv',
                      'read_hdl -netlist $::env(TRI_ORACLE_GATE175_IMPORT)\nread_hdl -sv $output/compiled_cluster_sources.sv')
        assert prefix.count('write_sdc > $output/elaborated_constraints.sdc\n') == 1
        prefix = prefix.split('write_sdc > $output/elaborated_constraints.sdc\n', 1)[0]
        entry = prefix+tail_path.read_text()
        while True:
            available, anonymous = memory()
            if available > 14*1024**3 and anonymous < 3*1024**3:
                break
            assert not stop_requested and time.monotonic()-started < 10800, 'Synthesis headroom wait expired'
            save(state='waiting_for_initial_memory_headroom')
            time.sleep(2)
        unchanged()
        output.mkdir()
        bundle = output/'compiled_cluster_sources.sv'
        bundle.write_text(compiled)
        entry_path = output/'native_entry.tcl'
        entry_path.write_text(entry)
        identities.update({str(p): sha(p) for p in [bundle, entry_path]})
        (output/'input_revision.json').write_text(json.dumps(dict(source_sha256=identities,
            compiled_bundle=compiled, library_list=libraries, explicit_gate_interface=interface,
            original_checkpoint_manifest_sha256=sha(manifest_path), functional_qualification_sha256=sha(functional_path)),
            indent=2)+'\n')
        identities[str(output/'input_revision.json')] = sha(output/'input_revision.json')
        unchanged()
        command = ['genus', '-no_gui', '-batch', '-log', str(output/'native'), '-files', str(entry_path)]
        native_started = time.monotonic()
        with (output/'console.log').open('w') as stream:
            child = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=stream,
                stderr=subprocess.STDOUT, start_new_session=True,
                env=dict(os.environ, TRI_ORACLE_SYNTH_OUTPUT=str(output), TRI_ORACLE_TOP='tri_oracle_predicted_feedforward_frame',
                    TRI_ORACLE_LIBS=' '.join(libraries), TRI_ORACLE_GATE175_IMPORT=str(imported),
                    TRI_ORACLE_REUSE_DOWN_NETLIST=str(root/'.cache/physical/synthesis/tri_oracle_down_executor_staged116/netlist.v'),
                    TRI_ORACLE_REUSE_DMA_NETLIST=str(root/'.cache/physical/synthesis/tri_oracle_sparse_weight_dma_pipelined107/netlist.v'),
                    TRI_ORACLE_GATE175_ISOLATED_CELLS=str(ledger),
                    TRI_ORACLE_GATE175_PREPARED=str(prepared),
                    TRI_ORACLE_ROW175_INPUT_REVISION_SHA256=sha(output/'input_revision.json'),
                    TRI_ORACLE_GATE175_ORIGINAL_CONTROLS=str(prepared/'reused_controls_before.tsv.sorted')))
            pause = OwnedProcessPause(child, str(output/'native'))
            policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3,
                                          anonymous_limit_bytes=16*1024**3)
            save(state='native_reduced_guard_parent_synthesis_running', source_sha256=identities,
                 native_process_group=child.pid, command=command, output_directory=str(output))
            last_save = 0
            while child.poll() is None:
                assert not stop_requested and time.monotonic()-native_started < 7200, 'Synthesis runtime limit'
                available, anonymous = memory()
                action = policy.observe(available, anonymous, time.monotonic())
                if action in ['pause', 'resume']:
                    groups = pause.pause() if action == 'pause' else pause.resume()
                    save(memory_pressure_events=record.get('memory_pressure_events', [])+
                         [dict(action=action, groups=groups, available=available, anonymous=anonymous)])
                record['peak_combined_anonymous_bytes'] = max(record.get('peak_combined_anonymous_bytes', 0), anonymous)
                if time.monotonic()-last_save > 5:
                    text = (output/'console.log').read_text(errors='replace')
                    if 'elaborated_checkpoint_manifest_sha256' not in record and '\nTRI_ORACLE_FRAME175_FULL_PARENT_GUARD_CHECKPOINT_WRITTEN\n' in text:
                        unchanged()
                        checkpoint_path = output/'elaborated_checkpoint_manifest.json'
                        checkpoint = json.loads(checkpoint_path.read_text())
                        assert checkpoint['state'] == 'source_bound_reduced_guard_full_parent_checkpoint_qualified'
                        assert checkpoint['checkpoint_fingerprint'] == artifact_fingerprint(output/'elaborated.db')
                        record.update(elaborated_checkpoint_manifest_sha256=sha(checkpoint_path),
                                      elaborated_checkpoint_fingerprint=checkpoint['checkpoint_fingerprint'])
                    save(native_elapsed_seconds=time.monotonic()-native_started, current_host_available_bytes=available,
                         current_combined_anonymous_bytes=anonymous)
                    last_save = time.monotonic()
                time.sleep(.2)
            pause.resume()
            terminate_process_group(child, log_argument=str(output/'native'))
        text = (output/'console.log').read_text(errors='replace')
        assert child.returncode == 0 and '\nTRI_ORACLE_FRAME175_PARENT_MAPPING_COMPLETED\n' in text, text[-4000:]
        unchanged()
        save(state='native_parent_mapping_completed_pending_report_review', native_exit_status=0,
             native_elapsed_seconds=time.monotonic()-native_started, console_sha256=sha(output/'console.log'),
             output_netlist_sha256=sha(output/'netlist.v'), output_constraints_sha256=sha(output/'constraints.sdc'),
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
