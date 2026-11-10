"""Validate nonlinear/down ownership and retained2048-row sums on actual compiled clusters."""
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
    parser.add_argument('--negative-dot-reference', action='store_true')
    parser.add_argument('--expect-missing', action='store_true')
    parser.add_argument('--ready-isolation', action='store_true')
    args = parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    assert 30 <= args.seconds <= 3600
    assert not (args.negative_reference and args.negative_dot_reference)
    assert not args.ready_isolation or not (args.negative_reference or args.negative_dot_reference or args.expect_missing)
    root = Path(__file__).resolve().parents[1]
    result = root/'records'/(args.label+'_result.json')
    assert not result.exists()
    executable = Path('/opt/cadence/bin/xrun')
    assert executable.is_file()
    units = ['pe_array', 'sram_memory_compute', 'sram_compute_cluster', 'down_executor',
             'cluster_down_executor', 'cluster_projection_executor', 'sparse_weight_dma',
             'shared_cluster_executor', 'word_bank', 'shared_fabric', 'silu_gate', 'fabric_gated_executor', 'gated_down_fabric', 'gated_down_fabric_tb']
    sources = [root/'verilog'/('tri_oracle_'+unit+'.sv') for unit in units]
    production = root/'verilog/tri_oracle_gated_down_fabric.sv'
    assert production.exists() != args.expect_missing
    sources = [path for path in sources if path != production or path.exists()]
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
              'negative_dot_reference': args.negative_dot_reference,
              'ready_isolation': args.ready_isolation,
              'source_sha256': identities, 'cases_seen': 0,
              'scope': (
                  'Two cases on 20 actual cores and 600 compiled memories. Check idle readiness, '
                  'a stalled three-row gate/up command, and a stalled seven-output empty down command.'
                  if args.ready_isolation else
                  'One nonlinear/down owner shares 20 actual cores and 600 compiled memories. '
                  'Check 13 retained contexts for 2,048 rows, 160-value subgroup use, faults and reset. '
                  'Production full-frame scheduling, integrated physical and paper metrics remain pending.'
              ),
              'expected_missing_production_module': args.expect_missing,
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
            text += ''.join('`include "'+str(p.resolve())+'"\n' for p in [*sources[:-1],
                           *vendor, sources[-1]])
            bundle.write_text(text)
            log = root/'records'/(args.label+'_native.log')
            assert not log.exists()
            command = [str(executable), '-64bit', '-sv', '-top', 'tri_oracle_gated_down_fabric_tb',
                       '-xmlibdirname', str(folder_path/'xcelium.d'), '-l',
                       str(folder_path/'xrun.log'), '-history_file', str(folder_path/'history'),
                       str(bundle)]
            if args.negative_reference:
                command.extend(['+CORRUPT_DOWN_REFERENCE', '+DOWN_SMOKE'])
            if args.negative_dot_reference:
                command.extend(['+CORRUPT_DOT_REFERENCE', '+DOT_SMOKE'])
            if args.ready_isolation:
                command.append('+OWNER_READY_ISOLATION')
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
                            save(cases_seen=content.count('GATED_DOWN_GATED_CASE_PASS ')+content.count('GATED_DOWN_DOWN_CASE_PASS '),
                                 native_elapsed_seconds=time.monotonic()-native_started,
                                 current_host_available_bytes=available,
                                 current_combined_anonymous_bytes=anonymous)
                            last_save = time.monotonic()
                        time.sleep(.1)
                finally:
                    pause_controller.resume()
                    terminate_process_group(child)
            content = log.read_text(errors='replace')
            if args.expect_missing:
                assert child.returncode != 0 and 'CUVMUR' in content, content[-4000:]
                assert 'tri_oracle_gated_down_fabric' in content and not production.exists()
                assert all(digest(p) == expected for p, expected in identities.items())
                save(state='expected_missing_production_module_rejected', native_exit_status=child.returncode,
                     native_console_sha256=digest(log), original_sources_and_models_unchanged=True)
                return
            if args.negative_reference or args.negative_dot_reference:
                failure_marker = 'GATED_DOWN_EXACT_DOT_MISMATCH' if args.negative_dot_reference else 'GATED_DOWN_DOWN_REFERENCE'
                assert child.returncode != 0 and failure_marker in content, content[-4000:]
                assert 'GATED_DOWN_PASS cases=' not in content
                assert all(digest(p) == expected for p, expected in identities.items())
                save(state='expected_wrong_reference_rejected', rejected_reference_mode='dot' if args.negative_dot_reference else 'down', native_exit_status=child.returncode,
                     native_elapsed_seconds=time.monotonic()-native_started,
                     native_console_sha256=digest(log), original_sources_and_models_unchanged=True)
                return
            assert child.returncode == 0, content[-5000:]
            assert 'GATED_DOWN_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            if args.ready_isolation:
                assert 'OWNER_READY_ISOLATION_PASS cases=2 exact_dots=6 nonlinear_codes=3 down_outputs=7' in content
                assert all(digest(p) == expected for p, expected in identities.items())
                save(state='ready_isolation_verified', cases_seen=2, native_exit_status=child.returncode,
                     native_elapsed_seconds=time.monotonic()-native_started, native_console_sha256=digest(log),
                     actual_compiled_core_instances=20, actual_compiled_memory_instances=600,
                     exact_raw_projection_dots_checked=6, bounded_nonlinear_outputs_checked=3,
                     returned_hidden_outputs_checked=7, original_sources_and_models_unchanged=True)
                return
            match = __import__('re').search(r'GATED_DOWN_PASS cases=70 hidden_outputs=2048 exact_dots=(\d+) nonlinear_codes=(\d+)',content)
            assert match and int(match.group(1))>=448 and int(match.group(2))>=224
            assert content.count('GATED_DOWN_GATED_CASE_PASS ')+content.count('GATED_DOWN_DOWN_CASE_PASS ')==70
            assert all(digest(p) == expected for p, expected in identities.items())
            save(state='passed', cases_seen=70, native_exit_status=child.returncode,
                 native_elapsed_seconds=time.monotonic()-native_started,
                 native_console_sha256=digest(log), actual_compiled_core_instances=20,
                 actual_compiled_memory_instances=600,returned_hidden_outputs_checked=2048,
                 exact_raw_projection_dots_checked=int(match.group(1)),
                 bounded_nonlinear_outputs_checked=int(match.group(2)),
                 producer_round_loop_is_testbench_only=True,
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
