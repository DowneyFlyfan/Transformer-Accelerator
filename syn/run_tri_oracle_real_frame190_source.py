"""Check one complete archived trained-layer fixture on the actual20-core source."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_fixture190_integrity import validate_fixture_hashes


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def memory():
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024
    anonymous = int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available, anonymous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--seconds', type=int, default=14400)
    parser.add_argument('--compile-only', action='store_true')
    parser.add_argument('--negative-reference', action='store_true')
    args = parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    assert 30 <= args.seconds <= 14400
    root = Path(__file__).resolve().parents[1]
    result = root/'records'/(args.label+'_result.json')
    assert not result.exists()
    positive_path = root/'records/rowguard182_full_frame_result.json'
    positive = json.loads(positive_path.read_text())
    assert positive['state'] == 'row_guard_full_frame_source_functional_qualified'
    assert all(sha(p) == h for p, h in positive['source_sha256'].items())
    fixture = root/'.cache/model_reference/full_layer_fixture'
    manifest = json.loads((fixture/'manifest.json').read_text())
    audit_path = root/'records/full_layer_quantization_error_audit.json'
    audit = json.loads(audit_path.read_text())
    assert sha(fixture/'manifest.json') == audit['baseline_fixture_manifest_sha256']
    assert audit['baseline_hardware_fixture_2048_integer_outputs_reproduced']
    assert (manifest['hidden_features'], manifest['dense_intermediate_stride'], manifest['output_start'],
            manifest['output_count'], manifest['gate_shift'], manifest['up_shift'], manifest['down_shift']) == (2048,5632,0,2048,6,0,6)
    assert manifest['selected_groups'] == list(range(176)) and manifest['selected_channels'] == list(range(5632))
    assert manifest['skipped_channels'] == 0
    fixture_sizes = {'activation.hex':2048*3, 'gate.hex':5632*2048*3, 'up.hex':5632*2048*3,
                     'down.hex':2048*5632*3, 'norm.hex':2048*5, 'expected.hex':2048*9, 'configuration.hex':5*9}
    anchored_fixture_hashes = validate_fixture_hashes(fixture,manifest,audit['baseline_fixture_manifest_sha256'],
                                                     [*fixture_sizes,'prediction_source.json'])
    for name, size in fixture_sizes.items():
        assert (fixture/name).stat().st_size == size, 'Unexpected fixture layout '+name
    bench = root/'verilog/tri_oracle_real_feedforward_frame190_tb.sv'
    monitor = root/'verilog/tri_oracle_real_channel_sequence190_monitor.sv'
    executable = Path('/opt/cadence/bin/xrun')
    inputs = [Path(__file__).resolve(), positive_path, bench, monitor, executable, audit_path,
              fixture/'manifest.json', fixture/'prediction_source.json',
              *[fixture/name for name in fixture_sizes],
              root/'syn/tri_oracle_memory_pressure_guard.py', root/'syn/tri_oracle_process_guard.py',
              root/'syn/tri_oracle_fixture190_integrity.py']
    identities = {**positive['source_sha256'], **{str(p):sha(p) for p in inputs}}
    assert all(identities[p]==h for p,h in anchored_fixture_hashes.items())
    marker = '\nmodule tri_oracle_guard182_observer;'
    assert positive['compiled_bundle'].count(marker) == 1
    compiled, observer = positive['compiled_bundle'].split(marker)
    assert '`include' not in observer and observer.rstrip().endswith('progress ();')
    old = '`include "'+str(root/'verilog/tri_oracle_predicted_feedforward_frame_tb.sv')+'"'
    assert compiled.count(old) == 1
    compiled = compiled.replace(old, '`include "'+str(bench)+'"')
    compiled = '`include "'+str(monitor)+'"\n'+compiled
    if args.compile_only:
        # Parser-only checking needs this new bench; the unchanged production
        # modules already have their separate source-functional qualification.
        compiled = ''.join('`include "'+str(p)+'"\n' for p in [monitor,bench])
    started = time.monotonic()
    child = pause = folder_path = None
    stop_requested = False
    def stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    record = dict(state='preflight', supervisor_pid=os.getpid(), source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        negative_reference=args.negative_reference, compile_only=args.compile_only,
        native_anonymous_limit_bytes=4*1024**3, host_reserve_bytes=8*1024**3,
        full_paper_results_matched=False, mapped_function_qualified=False, routed_timing_qualified=False,
        scope='One complete archived first-language-layer trained fixture:2048 inputs,5632 intermediate channels, '
              '2048 exact integer outputs on20 source cores/600 actual memory models. Prepared normalized strips '
              'remain externally supplied. Not whole-model accuracy, hardware normalization, physical timing or paper metrics.')
    def save(**changes):
        record.update(changes, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)
    def unchanged():
        assert all(sha(p) == h for p, h in identities.items()), 'Changed static or generated input'
    save()
    try:
        while True:
            available, anonymous = memory()
            anonymous_start_limit = 12*1024**3 if args.compile_only else 1024**3
            if available > 14*1024**3 and anonymous < anonymous_start_limit:
                break
            assert not stop_requested and time.monotonic()-started < 21600, 'Initial model-fixture headroom wait expired'
            save(state='waiting_for_initial_memory_headroom')
            time.sleep(2)
        unchanged()
        with tempfile.TemporaryDirectory(prefix=args.label+'_', dir=root/'.cache/physical') as folder:
            folder_path = Path(folder)
            bundle = folder_path/'canonical_sources.sv'
            bundle.write_text(compiled)
            identities[str(bundle)] = sha(bundle)
            log = root/'records'/(args.label+'_native.log')
            progress = root/'records'/(args.label+'_progress.log')
            assert not log.exists() and not progress.exists()
            command = [str(executable), '-64bit', '-sv', '-xmerror', 'RECOME',
                '-top', 'tri_oracle_predicted_feedforward_frame_tb',
                '-xmlibdirname', str(folder_path/'xcelium.d'), '-l', str(folder_path/'xrun.log'),
                '-history_file', str(folder_path/'history'), str(bundle),
                '+FIXTURE='+str(fixture), '+PROGRESS_FILE='+str(progress)]
            if args.compile_only:
                command.insert(1, '-compile')
            if args.negative_reference:
                command.append('+CORRUPT_REAL_REFERENCE')
            unchanged()
            native_started = time.monotonic()
            with log.open('w') as output:
                child = subprocess.Popen(command, cwd=folder_path, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                pause = OwnedProcessPause(child, str(folder_path/'xrun.log'))
                # This source simulation may run in the separate existing EDA
                # container; the host reserve protects the main synthesis job.
                anonymous_limit = min(16*1024**3,anonymous+2*1024**3) if args.compile_only else 4*1024**3
                policy = MemoryPressurePolicy(host_reserve_bytes=8*1024**3, resume_bytes=10*1024**3,
                                              anonymous_limit_bytes=anonymous_limit)
                save(state='native_real_fixture_compile_running' if args.compile_only else 'native_real_fixture_source_running',
                    source_sha256=identities, native_process_group=child.pid, command=command,
                    compiled_bundle=compiled, compiled_bundle_sha256=sha(bundle),effective_anonymous_limit_bytes=anonymous_limit)
                last_save = 0
                try:
                    while child.poll() is None:
                        assert not stop_requested and time.monotonic()-native_started < args.seconds, 'Real fixture runtime limit'
                        available, anonymous = memory()
                        action = policy.observe(available, anonymous, time.monotonic())
                        if action in ['pause','resume']:
                            groups = pause.pause() if action == 'pause' else pause.resume()
                            save(memory_pressure_events=record.get('memory_pressure_events', [])+
                                 [dict(action=action, groups=groups, available=available, anonymous=anonymous)])
                        record['peak_combined_anonymous_bytes'] = max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                        if time.monotonic()-last_save > 5:
                            tail = ''
                            if progress.exists():
                                with progress.open('rb') as stream:
                                    stream.seek(max(0,progress.stat().st_size-3000));tail=stream.read().decode(errors='replace')
                            save(native_elapsed_seconds=time.monotonic()-native_started, progress_tail=tail,
                                 current_host_available_bytes=available, current_combined_anonymous_bytes=anonymous)
                            last_save = time.monotonic()
                        time.sleep(.2)
                finally:
                    pause.resume()
                    terminate_process_group(child, log_argument=str(folder_path/'xrun.log'))
            unchanged()
            text = log.read_text(errors='replace')
            if args.compile_only:
                assert child.returncode == 0 and 'errors: 0' in text and '*E,' not in text and '*F,' not in text, text[-4000:]
                assert 'REAL_FRAME_PASS outputs=' not in text
                state = 'complete_model_fixture_bench_compiled_only'
            elif args.negative_reference:
                assert child.returncode != 0 and 'REAL_FRAME_INTEGER_OUTPUT row=0' in text and 'REAL_FRAME_PASS outputs=' not in text
                state = 'expected_real_fixture_wrong_reference_rejected'
            else:
                assert child.returncode == 0, text[-4000:]
                assert 'REAL_FRAME_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in text
                match = re.search(r'REAL_FRAME_PASS outputs=2048 packets=13 groups=176 strips=45056 channels=5632 prediction_packets=36 stalls=(\d+) requests=(\d+)',text)
                assert match and int(match[1])>0 and int(match[2])>0, text[-4000:]
                state = 'complete_archived_real_layer_source_functional_passed'
                record.update(exact_integer_outputs_checked=2048, actual_cores=20, actual_clusters=5,
                              actual_compiled_memories=600, groups_sent=176, strips_sent=45056,
                              source_fixture_metadata=manifest)
            del identities[str(bundle)]
            save(state=state, source_sha256=identities, native_exit_status=child.returncode,
                 native_elapsed_seconds=time.monotonic()-native_started, native_console_sha256=sha(log))
        save(temporary_build_removed=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=str(folder_path/'xrun.log') if folder_path else None)
        save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None)
        raise


if __name__ == '__main__':
    main()
