"""Prove slot-zero projection and retained contexts on one real compiled cluster."""
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
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--negative-reference', action='store_true')
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--legacy-slots', action='store_true')
    args = parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    assert 30 <= args.seconds <= 1800
    assert sum([args.negative_reference, args.baseline, args.legacy_slots]) <= 1
    root = Path(__file__).resolve().parents[1]
    result = root/'records'/(args.label+'_result.json')
    assert not result.exists()
    executable = Path('/opt/cadence/bin/xrun')
    assert executable.is_file()
    units = ['pe_array', 'sram_memory_compute', 'sram_activation_cache',
             'sram_compute_cluster', 'cluster_projection', 'sparse_weight_dma', 'word_bank']
    if not args.baseline:
        units.append('cluster_projection_executor')
    units.append('cluster_projection_executor_tb')
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
              'negative_reference': args.negative_reference, 'baseline': args.baseline,
              'legacy_slots': args.legacy_slots,
              'source_sha256': identities, 'cases_seen': 0,
              'scope': 'Projection executor on one shared four-core cluster and120 actual '
                       'compiled memories. Tests exact signed dot products, retained down-context '
                       'slots1,7,15, memory faults, configuration, reset and backpressure. '
                       'Not down-projection integration or whole-chip physical qualification.',
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
            if args.baseline:
                text += '`define SLOT0_BASELINE\n'
            compiled_sources = list(sources)
            if args.legacy_slots:
                legacy = folder_path/'legacy_executor.sv'
                body = (root/'verilog/tri_oracle_cluster_projection_executor.sv').read_text()
                replacements = {
                    'cluster_cmd_output = 0;': 'cluster_cmd_output = issue_index;',
                    'cluster_cmd_accumulate = tile_start != 0 || issue_index != 0;': 'cluster_cmd_accumulate = 0;',
                    'cluster_out_output != 0': 'cluster_out_output != retired_count[3:0]',
                    'sums[row*SumBits+:SumBits] <= cluster_out_data[row*SumBits+:SumBits];':
                    'sums[row*SumBits+:SumBits] <= sums[row*SumBits+:SumBits] + cluster_out_data[row*SumBits+:SumBits];'}
                for old, new in replacements.items():
                    assert body.count(old) == 1, old
                    body = body.replace(old, new)
                legacy.write_text(body)
                compiled_sources = [legacy if item.name == 'tri_oracle_cluster_projection_executor.sv' else item for item in sources]
            text += ''.join('`include "'+str(p.resolve())+'"\n' for p in [*compiled_sources[:-1],
                           *vendor, sources[-1]])
            bundle.write_text(text)
            log = root/'records'/(args.label+'_native.log')
            assert not log.exists()
            command = [str(executable), '-64bit', '-sv', '-top', 'tri_oracle_cluster_projection_executor_tb',
                       '-xmlibdirname', str(folder_path/'xcelium.d'), '-l',
                       str(folder_path/'xrun.log'), '-history_file', str(folder_path/'history'),
                       str(bundle)]
            if args.negative_reference:
                command.append('+CORRUPT_DOT_REFERENCE')
            if args.legacy_slots:
                command.extend(['+ALLOW_DESTRUCTIVE_SLOTS', '+LEGACY_PRESERVATION_ONLY'])
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
                            save(cases_seen=content.count('CLUSTER_PROJECTION_CASE_PASS '),
                                 native_elapsed_seconds=time.monotonic()-native_started,
                                 current_host_available_bytes=available,
                                 current_combined_anonymous_bytes=anonymous)
                            last_save = time.monotonic()
                        time.sleep(.1)
                finally:
                    pause_controller.resume()
                    terminate_process_group(child)
            content = log.read_text(errors='replace')
            failure_marker = ('PROJECTION_OVERWRITES_RESERVED_DOWN_CONTEXT' if args.baseline else
                              'DOWN_CONTEXT_CORRUPTED' if args.legacy_slots else
                              'PROJECTION_SUM_MISMATCH' if args.negative_reference else None)
            if failure_marker:
                assert child.returncode != 0 and failure_marker in content, content[-4000:]
                assert 'CLUSTER_PROJECTION_EXECUTOR_PASS cases=' not in content
                assert all(digest(p) == expected for p, expected in identities.items())
                save(state='expected_negative_control_rejected', native_exit_status=child.returncode,
                     rejected_failure_marker=failure_marker,
                     native_elapsed_seconds=time.monotonic()-native_started,
                     native_console_sha256=digest(log), original_sources_and_models_unchanged=True)
                return
            assert child.returncode == 0, content[-5000:]
            assert 'SLOT0_ACTUAL_HIERARCHY cores=4 clusters=1 compiled_memories=120' in content
            assert 'CLUSTER_PROJECTION_EXECUTOR_PASS cases=47' in content
            assert content.count('CLUSTER_PROJECTION_CASE_PASS ') == 47
            assert content.count('DOWN_CONTEXT_PRESERVATION_PASS ') == 18
            assert 'SLOT0_PRESERVATION_PASS slots_checked=18 values=576' in content
            assert all(digest(p) == expected for p, expected in identities.items())
            save(state='passed', cases_seen=47, native_exit_status=child.returncode,
                 native_elapsed_seconds=time.monotonic()-native_started,
                 native_console_sha256=digest(log), actual_compiled_core_instances=4,
                 actual_compiled_memory_instances=120, maximum_feature_strips=512,
                 retained_context_slots=[1,7,15], retained_context_values_checked=576,
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
