"""Run canonical functional benches on native Xcelium with compiler memory models."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

from test_tri_oracle_sram_memory_compute import models
from tri_oracle_process_guard import terminate_process_group


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', choices=['pe', 'core', 'hazards', 'capacity', 'fabric', 'predicted'])
    parser.add_argument('--corner', choices=['tt1v25c', 'ssg0p9v125c', 'ffg1p05vm40c'],
                        default='tt1v25c')
    parser.add_argument('--label', required=True)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--implementation', choices=['source', 'routed44'], default='source')
    parser.add_argument('--negative-reference', action='store_true')
    parser.add_argument('--elaborate-only', action='store_true',
                        help='Check native compilation/elaboration without running a simulation')
    parser.add_argument('--seconds', type=int, default=21600)
    args = parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    assert 1 <= args.seconds <= 172800
    assert not args.smoke or args.profile == 'predicted'
    assert not args.negative_reference or args.profile == 'capacity'
    assert args.implementation == 'source' or args.profile == 'capacity'
    root = Path('/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator')
    os.chdir(root)
    result_path = Path('records')/(args.label+'_result.json')
    assert not result_path.exists(), 'Refusing to replace an earlier simulator attempt'
    executable = Path('/opt/cadence/bin/xrun')
    if not executable.is_file():
        executable = Path('/opt/cadence/XCELIUM2503/tools/bin/xrun')
    if not executable.is_file():
        executable = Path('/opt/cadence/XCELIUM2503/tools.lnx86/bin/xrun')
    assert executable.is_file(), 'Xcelium installation has not produced xrun yet'
    version = subprocess.run([str(executable), '-64bit', '-version'], text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
    assert version.returncode == 0 and '25.03' in version.stdout, version.stdout
    top = {'pe': 'tri_oracle_pe_array', 'core': 'tri_oracle_memory_compute',
           'hazards': 'tri_oracle_memory_compute', 'fabric': 'tri_oracle_fabric_projection',
           'capacity': 'tri_oracle_sram_gpu_capacity',
           'predicted': 'tri_oracle_predicted_fabric'}[args.profile]
    bench = Path('verilog')/(('tri_oracle_sram_memory_hazards' if args.profile == 'hazards'
                            else top)+'_tb.sv')
    units = ['pe_array']
    if args.profile != 'pe':
        units += ['sram_memory_compute']
    if args.profile in ['fabric', 'predicted']:
        units += ['sram_activation_cache', 'sram_compute_cluster', 'cluster_projection',
                  'sparse_weight_dma', 'word_bank', 'fabric_projection']
    if args.profile == 'predicted':
        units += ['strip_predictor', 'channel_compactor', 'predicted_dispatch', 'predicted_fabric']
    sources = [Path('verilog')/('tri_oracle_'+unit+'.sv') for unit in units]
    producer_inputs = []
    if args.implementation == 'routed44':
        qualification_path = Path('records/sram_core_typical44_capacity46_qualification.json')
        qualification = json.loads(qualification_path.read_text())
        raw_path = Path(qualification['raw_record'])
        assert digest(raw_path) == qualification['raw_record_sha256']
        raw = json.loads(raw_path.read_text())
        sources = [Path('.cache/physical/pnr/tri_oracle_sram_memory_compute/'
                        'qualification_typical_repair_44/routed_netlist.v'),
                   Path('.cache/physical/library/tcbn28hpcplusbwp12t40p140.v')]
        for path in sources:
            assert digest(path) == raw['source_sha256'][str(path)]
        producer_inputs = [qualification_path, raw_path]
    inputs = [Path(__file__).resolve(), executable, bench, *sources,
              Path('syn/tri_oracle_process_guard.py')]
    inputs += producer_inputs
    if args.profile == 'capacity':
        fixture = Path('.cache/model_reference/sram_capacity_gpu/manifest.json')
        manifest = json.loads(fixture.read_text())
        assert manifest['gpu_oracle_matches_independent_scalar']
        inputs.append(fixture)
        for path, expected_sha in manifest['vector_sha256'].items():
            assert digest(path) == expected_sha
            inputs.append(Path(path))
    vendor_models = []
    if args.profile != 'pe':
        vendor_models = [Path(p) for p in models(args.corner)]
        bank_manifest = Path('records/sram_activation_cache_bank_views.json')
        metadata = json.loads(bank_manifest.read_text())['banks']['metadata']
        model = Path(metadata['models'][args.corner])
        assert digest(model) == metadata['sha256'][str(model)]
        vendor_models.append(model)
        inputs += [Path('records/sram_core_bank_views.json'), bank_manifest,
                   Path('syn/test_tri_oracle_sram_memory_compute.py'), *vendor_models]
    identities = {str(p): digest(p) for p in dict.fromkeys(inputs)}
    case_marker = {'fabric': 'FABRIC_PROJECTION_CASE_PASS',
                   'predicted': 'PREDICTED_FABRIC_CASE_PASS'}.get(args.profile)
    expected = 43 if args.profile == 'fabric' else 1 if args.smoke else 51
    final_marker = ('FABRIC_PROJECTION_PASS cases=43' if args.profile == 'fabric' else
                    f'PREDICTED_FABRIC_PASS cases={expected}' if args.profile == 'predicted' else
                    'GPU_CORE_REFERENCE_MISMATCH slot=0' if args.negative_reference else
                    'GPU_CORE_CAPACITY_PASS commands=1024 sums=512 input_addresses=1024'
                    if args.profile == 'capacity' else 'PASS:')
    started = time.monotonic()
    record = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'state': 'prepared', 'simulator': 'Cadence Xcelium', 'version': version.stdout.strip(),
              'profile': args.profile, 'corner': args.corner if vendor_models else None,
              'implementation': args.implementation, 'negative_reference': args.negative_reference,
              'elaborate_only': args.elaborate_only,
              'raw_routed_clock_connections_preserved': args.implementation == 'routed44',
              'smoke_only': args.smoke, 'source_sha256': identities,
              'parent_pid': os.getpid(), 'cases_seen': 0,
              'expected_cases': expected if case_marker else None,
              'peak_combined_anonymous_bytes': 0, 'minimum_host_available_bytes': None,
              'full_chip_paper_results_matched': False,
              'scope': 'Canonical functional bench, original RTL and compiler model bytes. '
                       'Compiled memories use UNIT_DELAY. No delay-annotated or paper-result claim.'}

    def save(**changes):
        record.update(changes, elapsed_seconds=time.monotonic()-started)
        temporary = result_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result_path)

    def available():
        return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                        if line.startswith('MemAvailable:')))*1024

    def bounds():
        resource.setrlimit(resource.RLIMIT_AS, (16*1024**3, 16*1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (args.seconds, args.seconds))

    save()
    log = None
    native_started = None
    child = None
    try:
        synthesis_guard = Path('.cache/physical/synthesis/tri_oracle_predicted_fabric/guard_result.json')
        wait_started = time.monotonic()
        while synthesis_guard.exists():
            try:
                synthesis = json.loads(synthesis_guard.read_text())
            except json.JSONDecodeError:
                assert time.monotonic()-wait_started < 10800, 'Synthesis resource wait budget'
                time.sleep(1)
                continue
            if synthesis.get('state') not in ['preparing', 'running']:
                break
            assert time.monotonic()-wait_started < 10800, 'Synthesis resource wait budget'
            save(state='waiting_for_synthesis_memory_release',
                 resource_wait_seconds=time.monotonic()-wait_started)
            time.sleep(2)
        assert available() > 8*1024**3
        with tempfile.TemporaryDirectory(prefix='xcelium_'+args.label+'_', dir='.cache/physical') as folder:
            build = Path(folder)
            bundle = build/'canonical_sources.sv'
            defines = [] if args.profile == 'pe' else ['UNIT_DELAY', 'TRI_ORACLE_SRAM_CORE_BIND_PUBLIC',
                        'TRI_ORACLE_SRAM_CACHE_BIND_PUBLIC', 'TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC']
            bundle.write_text(''.join('`define '+name+'\n' for name in defines) +
                              ''.join('`include "'+str(p.resolve())+'"\n'
                                      for p in [*sources, *vendor_models, bench]))
            command = [str(executable), '-64bit', '-sv', '-top', top+'_tb',
                       '-timescale', '1ns/1ps',
                       '-xmlibdirname', str(build/'xcelium.d'), '-l', str(build/'xrun.log'),
                       '-history_file', str(build/'xrun.history'),
                       str(bundle)] + (['+SMOKE'] if args.smoke else []) + (
                       ['+CORRUPT_REFERENCE'] if args.negative_reference else [])
            if args.elaborate_only:
                command.append('-elaborate')
            record.update(command=command, compiled_bundle=bundle.read_text(),
                          compiled_bundle_sha256=digest(bundle))
            log = Path('records')/(args.label+'_native.log')
            with log.open('w') as output:
                native_started = time.monotonic()
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                         stderr=subprocess.STDOUT, start_new_session=True,
                                         preexec_fn=bounds)
                save(state='native_compile_elaborate_simulate', child_pid=child.pid)
                try:
                    while child.poll() is None:
                        memory = available()
                        anonymous = int(dict(line.split() for line in
                            Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
                        record['peak_combined_anonymous_bytes'] = max(
                            record['peak_combined_anonymous_bytes'], anonymous)
                        previous = record['minimum_host_available_bytes']
                        record['minimum_host_available_bytes'] = min(previous or memory, memory)
                        assert memory > 4*1024**3, 'Host memory reserve'
                        assert anonymous < 20*1024**3, 'Container anonymous memory reserve'
                        assert time.monotonic()-native_started < args.seconds, 'Native runtime budget'
                        text = log.read_text(errors='replace')
                        save(cases_seen=text.count(case_marker) if case_marker else 0)
                        time.sleep(1)
                    if args.negative_reference and not args.elaborate_only:
                        assert child.returncode != 0, 'Corrupted reference was accepted'
                    else:
                        assert child.returncode == 0, f'xrun exited {child.returncode}; see {log}'
                finally:
                    terminate_process_group(child, grace_seconds=2)
            text = log.read_text(errors='replace')
            if args.elaborate_only:
                assert 'Writing initial simulation snapshot: worklib.'+top+'_tb:sv' in text
                assert final_marker not in text, 'Unexpected simulation execution during elaboration'
            else:
                assert final_marker in text, 'Missing canonical final marker; see '+str(log)
                if args.negative_reference:
                    assert 'GPU_CORE_CAPACITY_PASS' not in text
                if case_marker:
                    assert text.count(case_marker) == expected, 'Wrong canonical case count'
            for path, expected_sha in identities.items():
                assert digest(path) == expected_sha, 'Source changed: '+path
            save(state='elaborated_runtime_pending' if args.elaborate_only else 'passed',
                 functional_simulation_completed=not args.elaborate_only,
                 exit_status=0, cases_seen=text.count(case_marker) if case_marker else 0,
                 native_elapsed_seconds=time.monotonic()-native_started,
                 native_exit_status=child.returncode,
                 wrong_reference_rejected=args.negative_reference and not args.elaborate_only,
                 native_log_sha256=digest(log), original_sources_and_models_unchanged=True)
    except BaseException as error:
        terminal = {}
        if log is not None and log.is_file():
            final_text = log.read_text(errors='replace')
            terminal.update(cases_seen=final_text.count(case_marker) if case_marker else 0,
                            native_log_sha256=digest(log))
        if native_started is not None:
            terminal['native_elapsed_seconds'] = time.monotonic()-native_started
        if child is not None:
            terminal['native_exit_status'] = child.poll()
        save(state='failed', exit_status=1, exception=repr(error), **terminal)
        raise
    finally:
        save(temporary_build_removed=True)


if __name__ == '__main__':
    main()
