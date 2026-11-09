"""Validate joined prepared-strip prediction and production numeric frames on actual memories."""
import argparse
import datetime
import hashlib
import json
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
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--negative-reference', action='store_true')
    parser.add_argument('--negative-duplicate-source', action='store_true')
    parser.add_argument('--expect-missing', action='store_true')
    args = parser.parse_args()
    assert sum([args.negative_reference,args.negative_duplicate_source,args.expect_missing])<=1
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    assert 30 <= args.seconds <= 3600
    root = Path(__file__).resolve().parents[1]
    result = root/'records'/(args.label+'_result.json')
    assert not result.exists()
    executable = Path('/opt/cadence/bin/xrun')
    assert executable.is_file()
    units = ['pe_array', 'sram_memory_compute', 'sram_compute_cluster', 'down_executor_staged',
             'cluster_down_executor', 'cluster_projection_executor', 'sparse_weight_dma_pipelined',
             'shared_cluster_executor', 'word_bank', 'shared_fabric', 'silu_gate', 'fabric_gated_executor', 'gated_down_fabric', 'feedforward_frame', 'strip_predictor', 'channel_compactor', 'predicted_dispatch', 'prediction_packet_stream', 'predicted_feedforward_frame', 'predicted_feedforward_frame_tb']
    sources = [root/'verilog'/('tri_oracle_'+unit+'.sv') for unit in units]
    production = root/'verilog/tri_oracle_predicted_feedforward_frame.sv'
    assert production.exists()
    sources = [path for path in sources if path != production or not args.expect_missing]
    vendor = [Path(p) for p in models('tt1v25c')]
    bank_path = root/'records/sram_activation_cache_bank_views.json'
    metadata = json.loads(bank_path.read_text())['banks']['metadata']
    model = Path(metadata['models']['tt1v25c'])
    assert digest(model) == metadata['sha256'][str(model)]
    vendor.append(model)
    inputs = [Path(__file__).resolve(), executable, *sources, *vendor, bank_path,
              root/'verilog/tri_oracle_sparse_weight_dma.sv',root/'records/pipeline105_functional_qualification.json',
              root/'verilog/tri_oracle_down_executor.sv',root/'records/cluster117_functional_qualification.json',
              root/'records/sram_core_bank_views.json',
              root/'syn/test_tri_oracle_sram_memory_compute.py',
              root/'syn/tri_oracle_process_guard.py',
              root/'syn/tri_oracle_memory_pressure_guard.py']
    identities = {str(p): digest(p) for p in dict.fromkeys(inputs)}
    pipeline_q=json.loads((root/'records/pipeline105_functional_qualification.json').read_text())
    assert pipeline_q['state']=='staged_sparse_address_generator_source_functional_qualified'
    assert all(digest(p)==h for p,h in pipeline_q['current_source_sha256'].items())
    old_header=(root/'verilog/tri_oracle_sparse_weight_dma.sv').read_text()
    first=old_header.index('module tri_oracle_sparse_weight_dma (')
    last=old_header.index('\n);',first)+4
    adapter='`timescale 1ns/1ps\n'+old_header[first:last]+'\n    tri_oracle_sparse_weight_dma_pipelined implementation (.*);\n    initial $display("JOINED_STAGED_DMA_BOUND %m");\nendmodule\n'
    down_q=json.loads((root/'records/cluster117_functional_qualification.json').read_text())
    assert down_q['state']=='fully_staged_down_actual_cluster_source_functional_qualified'
    assert all(digest(p)==h for p,h in down_q['current_source_sha256'].items())
    down_original=(root/'verilog/tri_oracle_down_executor.sv').read_text()
    first=down_original.index('module tri_oracle_down_executor (');last=down_original.index('\n);',first)+4
    down_adapter='`timescale 1ns/1ps\n'+down_original[first:last]+'\n    tri_oracle_down_executor_staged implementation (.*);\n    initial $display("JOINED_STAGED_DOWN_BOUND %m");\nendmodule\n'
    record = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'state': 'prepared', 'supervisor_pid': __import__('os').getpid(),
              'negative_reference': args.negative_reference, 'negative_duplicate_source':args.negative_duplicate_source,
              'source_sha256': identities, 'cases_seen': 0,
              'scope': 'Joined prepared-strip prediction/numeric frames with tested staged projection DMA and sparse down controllers behind explicit legacy-interface adapters. Exactly20 cores/600 actual memory models; analytic saturated arithmetic fixture. Routed integration and paper metrics remain pending.',
                            'staged_address_generator_composition': True, 'staged_down_controller_composition': True, 'down_interface_adapter': down_adapter, 'legacy_interface_adapter': adapter, 'full_paper_results_matched': False}
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
            if available > 7*1024**3 and anonymous < 17*1024**3:
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
            text += adapter+down_adapter
            text += ''.join('`include "'+str(p.resolve())+'"\n' for p in [*sources[:-1],
                           *vendor, sources[-1]])
            assert root/'verilog/tri_oracle_down_executor.sv' not in sources
            assert root/'verilog/tri_oracle_sparse_weight_dma.sv' not in sources
            assert sources.count(root/'verilog/tri_oracle_down_executor_staged.sv')==1
            assert sources.count(root/'verilog/tri_oracle_sparse_weight_dma_pipelined.sv')==1
            if args.negative_duplicate_source:
                text+='`include "'+str(root/'verilog/tri_oracle_down_executor.sv')+'"\n'
            bundle.write_text(text)
            log = root/'records'/(args.label+'_native.log')
            assert not log.exists()
            command = [str(executable), '-64bit', '-sv', '-xmerror', 'RECOME', '-top', 'tri_oracle_predicted_feedforward_frame_tb',
                       '-xmlibdirname', str(folder_path/'xcelium.d'), '-l',
                       str(folder_path/'xrun.log'), '-history_file', str(folder_path/'history'),
                       str(bundle)]
            if args.negative_reference:
                command.extend(['+CORRUPT_JOINED_REFERENCE'])
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
                            save(cases_seen=content.count('JOINED_CASE_PASS '),
                                 native_elapsed_seconds=time.monotonic()-native_started,
                                 current_host_available_bytes=available,
                                 current_combined_anonymous_bytes=anonymous)
                            last_save = time.monotonic()
                        time.sleep(.1)
                finally:
                    pause_controller.resume()
                    terminate_process_group(child)
            content = log.read_text(errors='replace')
            if args.negative_duplicate_source:
                assert child.returncode!=0 and '*E,RECOME' in content
                assert 'JOINED_STAGED_DOWN_BOUND' not in content and 'JOINED_PASS cases=' not in content
                assert all(digest(p)==expected for p,expected in identities.items())
                save(state='expected_duplicate_implementation_rejected',native_exit_status=child.returncode,native_console_sha256=digest(log))
                return
            if args.expect_missing:
                assert child.returncode!=0 and 'CUVMUR' in content and 'tri_oracle_predicted_feedforward_frame' in content
                assert 'JOINED_PASS cases=' not in content
                assert all(digest(p)==expected for p,expected in identities.items())
                save(state='expected_missing_production_module_rejected',native_exit_status=child.returncode,native_console_sha256=digest(log))
                return
            assert 'RECOME' not in '\n'.join(line for line in content.splitlines() if '*W,' in line or '*E,' in line)
            assert content.count('JOINED_STAGED_DOWN_BOUND ')==20, 'Actual staged down adapter instances missing'
            assert content.count('JOINED_STAGED_DMA_BOUND ')==5, 'Actual staged projection adapter instances missing'
            save(actual_staged_down_adapter_instances=20,actual_staged_projection_adapter_instances=5)
            if args.negative_reference:
                failure_marker = 'JOINED_HIDDEN_SUM'
                assert child.returncode != 0 and failure_marker in content, content[-4000:]
                assert 'JOINED_PASS cases=' not in content
                assert all(digest(p) == expected for p, expected in identities.items())
                save(state='expected_wrong_reference_rejected', rejected_reference_mode='joined_final_output', native_exit_status=child.returncode,
                     native_elapsed_seconds=time.monotonic()-native_started,
                     native_console_sha256=digest(log), original_sources_and_models_unchanged=True)
                return
            assert child.returncode == 0, content[-5000:]
            assert 'JOINED_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            match = __import__('re').search(r'JOINED_PASS cases=12 hidden_outputs=4420 success_stalls=(\d+) error_stalls=(\d+)',content)
            assert match and int(match.group(1))>0 and int(match.group(2))>=9
            assert content.count('JOINED_CASE_PASS ')==12
            assert all(digest(p) == expected for p, expected in identities.items())
            save(state='passed', cases_seen=12, native_exit_status=child.returncode,
                 native_elapsed_seconds=time.monotonic()-native_started,
                 native_console_sha256=digest(log), actual_compiled_core_instances=20,
                 actual_compiled_memory_instances=600,returned_hidden_outputs_checked=4420,
                 production_prediction_batching_and_frame_scheduling_executed=True,
                 successful_output_stall_cycles=int(match.group(1)),error_output_stall_cycles=int(match.group(2)),
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
