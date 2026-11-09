"""Validate the reserved-slot executor in the existing twenty-core gated top."""
import argparse
import datetime
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from test_tri_oracle_sram_memory_compute import models
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def memory():
    available = int(next(s.split()[1] for s in Path('/proc/meminfo').read_text().splitlines()
                         if s.startswith('MemAvailable:')))*1024
    anonymous = int(dict(line.split() for line in
                         Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available, anonymous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--negative-reference', action='store_true')
    args = parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    assert 30 <= args.seconds <= 1800
    root = Path(__file__).resolve().parents[1]
    result = root/'records'/(args.label+'_result.json')
    assert not result.exists()
    executable = Path('/opt/cadence/bin/xrun')
    assert executable.is_file()
    units = ['pe_array', 'sram_memory_compute', 'sram_activation_cache',
             'sram_compute_cluster', 'cluster_projection_executor', 'cluster_projection', 'sparse_weight_dma', 'word_bank',
             'fabric_projection', 'silu_gate', 'fabric_gated_executor', 'gated_fabric',
             'strip_predictor', 'channel_compactor', 'predicted_dispatch',
             'predicted_gated_fabric', 'predicted_gated_fabric_tb']
    sources = [root/'verilog'/('tri_oracle_'+unit+'.sv') for unit in units]
    vendor = [Path(p) for p in models('tt1v25c')]
    bank_path = root/'records/sram_activation_cache_bank_views.json'
    metadata = json.loads(bank_path.read_text())['banks']['metadata']
    model = Path(metadata['models']['tt1v25c'])
    assert digest(model) == metadata['sha256'][str(model)]
    vendor.append(model)
    inputs = [Path(__file__).resolve(), executable, *sources, *vendor, bank_path,
              root/'records/sram_core_bank_views.json',
              root/'syn/test_tri_oracle_sram_memory_compute.py',
              root/'syn/tri_oracle_process_guard.py',
              root/'syn/tri_oracle_memory_pressure_guard.py']
    identities = {str(p): digest(p) for p in dict.fromkeys(inputs)}
    record = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'state': 'prepared', 'supervisor_pid': __import__('os').getpid(),
              'negative_reference': args.negative_reference,
              'source_sha256': identities, 'cases_seen': 0,
              'scope': 'Experimental reserved-slot projection adapter in actual channel prediction, frame batching, paired gate/up '
                       'projection and nonlinear activation using all600 compiled memories at the typical '
                       'corner with UNIT_DELAY. Full5632-channel frames and full2048-input sparse '
                       'arithmetic are checked. Not a down-projection, whole-processor, mapped '
                       'timing, accuracy or paper-energy qualification.',
              'full_paper_results_matched': False}
    started = time.monotonic()
    child = None
    folder_path = None

    def save(**changes):
        record.update(changes, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)

    save()
    try:
        while True:
            available, anonymous = memory()
            if available > 6*1024**3 and anonymous < 19*1024**3:
                break
            assert time.monotonic()-started < 7200, 'Source simulation headroom wait expired'
            save(state='waiting_for_source_simulation_headroom',
                 current_host_available_bytes=available, current_combined_anonymous_bytes=anonymous)
            time.sleep(2)
        with tempfile.TemporaryDirectory(prefix=args.label+'_', dir=root/'.cache/physical') as folder:
            folder_path = Path(folder)
            bundle = folder_path/'canonical_sources.sv'
            text = ''.join('`define '+name+'\n' for name in ['UNIT_DELAY',
                'TRI_ORACLE_SRAM_CORE_BIND_PUBLIC', 'TRI_ORACLE_SRAM_CACHE_BIND_PUBLIC',
                'TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC'])
            # A temporary adapter preserves the existing projection module's ports and
            # cluster instance path. It contains one executor and one existing cluster.
            # No original physical-flow source is edited or extra core instantiated.
            original = (root/'verilog/tri_oracle_cluster_projection.sv').read_text()
            header = original[:original.index('\n);')+4]
            declarations = original[original.index('  logic cluster_load_valid, cluster_load_error;'):
                                    original.index('\n  always_comb begin')]
            declarations += '\n  logic [1:0] cluster_load_core;\n  logic cluster_cmd_accumulate;\n'
            start = original.index('  tri_oracle_compute_cluster cluster (')
            end = original.index('  always_ff @(posedge clk or negedge rst_n)', start)
            cluster = original[start:end].replace('.load_core(core_index)', '.load_core(cluster_load_core)')
            cluster = cluster.replace('.cmd_accumulate(1\'b0)', '.cmd_accumulate(cluster_cmd_accumulate)')
            adapter = folder_path/'reserved_projection_adapter.sv'
            adapter_body = header + declarations + '\n  tri_oracle_cluster_projection_executor executor (.*);\n' + cluster + 'endmodule\n'
            adapter.write_text(adapter_body)
            assert adapter_body.count('tri_oracle_compute_cluster cluster (') == 1
            compiled_sources = [adapter if item.name == 'tri_oracle_cluster_projection.sv' else item for item in sources]
            save(experimental_adapter_source=adapter_body, experimental_adapter_sha256=digest(adapter),
                 original_projection_source_sha256=digest(root/'verilog/tri_oracle_cluster_projection.sv'))
            text += ''.join('`include "'+str(p.resolve())+'"\n' for p in [*compiled_sources[:-1],
                           *vendor, sources[-1]])
            bundle.write_text(text)
            log = root/'records'/(args.label+'_native.log')
            assert not log.exists()
            command = [str(executable), '-64bit', '-sv', '-top', 'tri_oracle_predicted_gated_fabric_tb',
                       '-xmlibdirname', str(folder_path/'xcelium.d'), '-l',
                       str(folder_path/'xrun.log'), '-history_file', str(folder_path/'history'),
                       str(bundle)]
            if args.negative_reference:
                command.extend(['+CORRUPT_DOT_REFERENCE', '+SMOKE'])
            native_started = time.monotonic()
            with log.open('w') as output:
                child = subprocess.Popen(command, cwd=folder_path, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                pressure = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3, anonymous_limit_bytes=21*1024**3)
                pause_controller = OwnedProcessPause(child, str(folder_path/'xrun.log'))
                save(state='native_source_fabric_simulation_running', native_process_group=child.pid,
                     command=command, compiled_bundle=text, compiled_bundle_sha256=digest(bundle))
                try:
                    last_save = 0
                    while child.poll() is None:
                        available, anonymous = memory()
                        action = pressure.observe(available, anonymous, time.monotonic())
                        if action in ('pause', 'resume'):
                            groups = pause_controller.pause() if action == 'pause' else pause_controller.resume()
                            events = record.get('memory_pressure_events', []) + [{
                                'action': action, 'owned_process_groups': groups,
                                'host_available_bytes': available,
                                'combined_anonymous_bytes': anonymous}]
                            save(memory_pressure_events=events)
                        assert time.monotonic()-native_started < args.seconds
                        if time.monotonic()-last_save > 2:
                            content = log.read_text(errors='replace')
                            save(cases_seen=content.count('PREDICTED_GATED_FABRIC_CASE_PASS '),
                                 native_elapsed_seconds=time.monotonic()-native_started,
                                 current_host_available_bytes=available,
                                 current_combined_anonymous_bytes=anonymous)
                            last_save = time.monotonic()
                        time.sleep(.1)
                finally:
                    pause_controller.resume()
                    terminate_process_group(child)
            content = log.read_text(errors='replace')
            if args.negative_reference:
                assert child.returncode != 0 and 'exact predicted gated dot mismatch' in content
                assert 'PREDICTED_GATED_FABRIC_PASS cases=' not in content
                assert all(digest(p) == expected for p, expected in identities.items())
                save(state='expected_wrong_dot_reference_rejected',
                     native_exit_status=child.returncode,
                     native_elapsed_seconds=time.monotonic()-native_started,
                     native_console_sha256=digest(log), wrong_dot_reference_rejected=True,
                     original_sources_and_models_unchanged=True)
                return
            assert child.returncode == 0, content[-4000:]
            assert 'PREDICTED_GATED_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            assert 'PREDICTED_GATED_FABRIC_PASS cases=60' in content
            assert content.count('PREDICTED_GATED_FABRIC_CASE_PASS ') == 60
            assert content.count('PREDICTED_GATED_FABRIC_CASE_PASS reset=') == 3
            exact = re.search(r'PREDICTED_GATED_EXACT_DOTS_PASS values=(\d+)', content)
            assert exact and int(exact.group(1)) >= 11264
            assert all(digest(p) == expected for p, expected in identities.items())
            save(state='passed', cases_seen=60, native_exit_status=child.returncode,
                 native_elapsed_seconds=time.monotonic()-native_started,
                 native_console_sha256=digest(log), actual_compiled_core_instances=20, reserved_slot_executor_instances=5,
                 actual_compiled_memory_instances=600, full_hidden_dimension_tested=2048,
                 selected_channels_from_dense_dimension=5632,
                 coordinated_reset_cases=3,
                 bit_exact_projection_sums_checked=int(exact.group(1)),
                 complete_dense_5632_channel_frame_tested=True,
                 original_sources_and_models_unchanged=True)
    except BaseException as error:
        save(state='yielded_to_physical_memory_reserve' if isinstance(error, MemoryError) else 'failed',
             exception=repr(error), native_exit_status=child.returncode if child is not None else None)
        raise
    finally:
        if folder_path is not None:
            save(temporary_build_removed=not folder_path.exists())


if __name__ == '__main__':
    main()
