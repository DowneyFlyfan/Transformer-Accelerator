"""Validate four down-control engines on one externally connected real cluster."""
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
    args = parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    assert 30 <= args.seconds <= 1800
    root = Path(__file__).resolve().parents[1]
    result = root/'records'/(args.label+'_result.json')
    assert not result.exists()
    executable = Path('/opt/cadence/bin/xrun')
    assert executable.is_file()
    units = ['pe_array', 'sram_memory_compute', 'sram_compute_cluster',
             'down_executor_staged', 'cluster_down_executor', 'word_bank', 'cluster_down_executor_tb']
    sources = [root/'verilog'/('tri_oracle_'+unit+'.sv') for unit in units]
    vendor = [Path(p) for p in models('tt1v25c')]
    bank_path = root/'records/sram_activation_cache_bank_views.json'
    metadata = json.loads(bank_path.read_text())['banks']['metadata']
    model = Path(metadata['models']['tt1v25c'])
    assert digest(model) == metadata['sha256'][str(model)]
    vendor.append(model)
    inputs = [Path(__file__).resolve(), executable, *sources, *vendor, bank_path,
              root/'verilog/tri_oracle_down_executor.sv',root/'records/down115_functional_qualification.json',
              root/'records/sram_core_bank_views.json',
              root/'syn/test_tri_oracle_sram_memory_compute.py',
              root/'syn/tri_oracle_process_guard.py',
              root/'syn/tri_oracle_memory_pressure_guard.py']
    identities = {str(p): digest(p) for p in dict.fromkeys(inputs)}
    prerequisite=json.loads((root/'records/down115_functional_qualification.json').read_text())
    assert prerequisite['state']=='fully_staged_down_controller_source_functional_qualified'
    assert all(digest(p)==h for p,h in prerequisite['current_source_sha256'].items())
    original=(root/'verilog/tri_oracle_down_executor.sv').read_text()
    first=original.index('module tri_oracle_down_executor (');last=original.index('\n);',first)+4
    adapter='`timescale 1ns/1ps\n'+original[first:last]+'\n    tri_oracle_down_executor_staged implementation (.*);\nendmodule\n'
    record = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'state': 'prepared', 'supervisor_pid': __import__('os').getpid(),
              'negative_reference': args.negative_reference,
              'source_sha256': identities, 'cases_seen': 0,
              'scope': 'Four staged down-control engines on one actual compiled four-core '
                       'cluster with120 real memories. Checks selected column gathers, signed '
                       'scalar products, slot append/finalize, burst faults and reset. '
                       'Joined-frame integration and whole-chip physical validation remain pending.',
              'explicit_legacy_interface_adapter': adapter, 'full_paper_results_matched': False}
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
            diagnostic_bench=sources[-1].read_text()
            observer_changes={}
            for index in range(4):
                for field in ['state','fault']:
                    old=f'dut.engines[{index}].{field}';new=f'dut.engines[{index}].implementation.{field}'
                    assert diagnostic_bench.count(old)==1
                    diagnostic_bench=diagnostic_bench.replace(old,new);observer_changes[old]=new
            bench=folder_path/'observer_adjusted_bench.sv';bench.write_text(diagnostic_bench)
            text += adapter
            text += ''.join('`include "'+str(p.resolve())+'"\n' for p in [*sources[:-1],
                           *vendor, bench])
            bundle.write_text(text)
            log = root/'records'/(args.label+'_native.log')
            assert not log.exists()
            command = [str(executable), '-64bit', '-sv', '-top', 'tri_oracle_cluster_down_executor_tb',
                       '-xmlibdirname', str(folder_path/'xcelium.d'), '-l',
                       str(folder_path/'xrun.log'), '-history_file', str(folder_path/'history'),
                       str(bundle)]
            if args.negative_reference:
                command.append('+CORRUPT_REFERENCE')
            native_started = time.monotonic()
            with log.open('w') as output:
                child = subprocess.Popen(command, cwd=folder_path, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                pressure = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3, anonymous_limit_bytes=21*1024**3)
                pause_controller = OwnedProcessPause(child, str(folder_path/'xrun.log'))
                save(state='native_source_fabric_simulation_running', native_process_group=child.pid,
                     command=command, compiled_bundle=text, compiled_bundle_sha256=digest(bundle),observer_only_changes=observer_changes,compiled_bench_sha256=digest(bench))
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
                            save(cases_seen=content.count('CLUSTER_DOWN_CASE_PASS '),
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
                assert child.returncode != 0 and 'down reference matrix product mismatch' in content, content[-4000:]
                assert 'CLUSTER_DOWN_PASS cases=' not in content
                assert all(digest(p) == expected for p, expected in identities.items())
                save(state='expected_wrong_scalar_reference_rejected', native_exit_status=child.returncode,
                     native_elapsed_seconds=time.monotonic()-native_started,
                     native_console_sha256=digest(log), original_sources_and_models_unchanged=True)
                return
            assert child.returncode == 0, content[-5000:]
            assert 'CLUSTER_DOWN_ACTUAL_HIERARCHY cores=4 clusters=1 compiled_memories=120' in content
            match = __import__('re').search(r'CLUSTER_DOWN_PASS cases=(\d+) exact_values=(\d+)',content)
            assert match and int(match.group(1)) == 46 and int(match.group(2)) == 1472
            assert content.count('CLUSTER_DOWN_CASE_PASS ') == 46
            assert all(digest(p) == expected for p, expected in identities.items())
            save(state='passed', cases_seen=46, native_exit_status=child.returncode,
                 native_elapsed_seconds=time.monotonic()-native_started,
                 native_console_sha256=digest(log), actual_compiled_core_instances=4,
                 actual_compiled_memory_instances=120, exact_scalar_outputs_checked=1472,
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
