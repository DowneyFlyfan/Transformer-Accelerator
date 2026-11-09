"""Run original full-shape frame stimulus with only row-address guards reduced."""
import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from tri_oracle_row_guard173_variants import build_variants, sha
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def memory():
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024
    anonymous = int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available, anonymous


def main():
    root = Path(__file__).resolve().parents[1]
    result = root/'records/rowguard182_full_frame_result.json'
    assert not result.exists()
    reference = root/'records/staged119_fullshape_result.json'
    passed = json.loads(reference.read_text())
    assert passed['state'] == 'passed' and passed['returned_hidden_outputs_checked'] == 4420
    assert passed['actual_staged_down_adapter_instances'] == 20 and passed['actual_staged_projection_adapter_instances'] == 5
    unit_path = root/'records/rowguard177_validation.json'
    unit = json.loads(unit_path.read_text())
    assert unit['state'] == 'maximum_active_row_guard_equivalence_simulations_passed'
    assert any(step['label'] == 'wrong_first_row_rejected' for step in unit['steps'])
    assert all(sha(p) == h for p, h in unit['source_sha256'].items())
    assert all(sha(p) == h for p, h in passed['source_sha256'].items())
    inputs = [Path(__file__).resolve(), reference, unit_path, Path('/opt/cadence/bin/xrun'),
              root/'syn/tri_oracle_row_guard173_variants.py', root/'syn/tri_oracle_memory_pressure_guard.py',
              root/'syn/tri_oracle_process_guard.py']
    identities = {**passed['source_sha256'], **unit['source_sha256'], **{str(p): sha(p) for p in inputs}}
    started = time.monotonic()
    child = pause = folder_path = None
    stop_requested = False
    def stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    record = dict(state='preparing', supervisor_pid=os.getpid(),
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), source_sha256=identities,
        full_paper_results_matched=False, routed_timing_qualified=False, passive_time_output_observer=True,
        unobserved_simulation_qualified=False,
        scope='Original full20-core/600-memory,12-case,4420-output prepared feed-forward fixture. Only shared '
              'fabric and cluster projection input weight-address overflow checks changed; original arithmetic peer '
              'and all37 frozen sources remain unchanged. No whole-model accuracy or physical signoff claim.')
    def save(**changes):
        record.update(changes, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)
    def unchanged():
        assert all(sha(p) == h for p, h in identities.items()), 'Static or generated consumed input changed'
    save()
    try:
        variants = json.loads((root/'.cache/physical/rtl/rowguard173/variants.json').read_text())
        assert variants['state'] == 'frozen_controller_row_guard_variants_generated'
        assert all(sha(p) == h for p, h in variants['source_sha256'].items())
        assert all(sha(p) == h for p, h in variants['generated_sha256'].items())
        identities.update(variants['source_sha256'])
        identities.update(variants['generated_sha256'])
        variant_manifest = root/'.cache/physical/rtl/rowguard173/variants.json'
        identities[str(variant_manifest)] = sha(variant_manifest)
        compiled = passed['compiled_bundle']
        for original, replacement in variants['replacements'].items():
            old = '`include "'+original+'"'
            assert compiled.count(old) == 1
            compiled = compiled.replace(old, '`include "'+replacement+'"')
        compiled = '`include "'+str(root/'verilog/tri_oracle_row_address_guard.sv')+'"\n'+compiled
        compiled += '\nmodule tri_oracle_guard182_observer;\n  integer ticks=0;\n  integer previous_completed=-1;\n  initial begin\n    forever begin\n      #10000;\n      ticks++;\n      if (ticks <=20 || $root.tri_oracle_predicted_feedforward_frame_tb.completed != previous_completed) begin\n      $display("GUARD182_TIME time=%0t cycle=%0d completed=%0d seen=%0d", $time,\n        $root.tri_oracle_predicted_feedforward_frame_tb.cycle,\n        $root.tri_oracle_predicted_feedforward_frame_tb.completed,\n        $root.tri_oracle_predicted_feedforward_frame_tb.seen);\n      $fflush();\n      end\n      previous_completed=$root.tri_oracle_predicted_feedforward_frame_tb.completed;\n    end\n  end\n  always @(negedge $root.tri_oracle_predicted_feedforward_frame_tb.clk)\n    if ($root.tri_oracle_predicted_feedforward_frame_tb.out_valid) begin\n      $display("GUARD182_OUTPUT time=%0t ready=%b last=%b count=%0d", $time,\n        $root.tri_oracle_predicted_feedforward_frame_tb.out_ready,\n        $root.tri_oracle_predicted_feedforward_frame_tb.out_last,\n        $root.tri_oracle_predicted_feedforward_frame_tb.out_count);\n      $fflush();\n    end\nendmodule\nbind tri_oracle_predicted_feedforward_frame_tb tri_oracle_guard182_observer progress ();\n'
        # Every include is absolute, including vendor memory models.
        for path in re.findall(r'^`include "([^"]+)"$', compiled, re.M):
            assert Path(path).is_absolute() and Path(path).is_file()
            identities[path] = sha(path)
        while True:
            available, anonymous = memory()
            if available > 14*1024**3 and anonymous < 3*1024**3:
                break
            assert not stop_requested and time.monotonic()-started < 7200, 'Initial headroom wait expired'
            save(state='waiting_for_initial_memory_headroom')
            time.sleep(2)
        unchanged()
        with tempfile.TemporaryDirectory(prefix='rowguard182_', dir=root/'.cache/physical') as folder:
            folder_path = Path(folder)
            bundle = folder_path/'canonical_sources.sv'
            bundle.write_text(compiled)
            identities[str(bundle)] = sha(bundle)
            save(source_sha256=identities, compiled_bundle=compiled, compiled_bundle_sha256=sha(bundle),
                 variants_manifest_sha256=sha(variant_manifest))
            steps = []
            for negative in [True, False]:
                phase = 'wrong_reference' if negative else 'positive'
                log = root/'records'/('rowguard182_'+phase+'_native.log')
                assert not log.exists()
                command = ['/opt/cadence/bin/xrun', '-64bit', '-sv', '-xmerror', 'RECOME',
                    '-top', 'tri_oracle_predicted_feedforward_frame_tb',
                    '-xmlibdirname', str(folder_path/('xcelium_'+phase+'.d')), '-l', str(folder_path/'xrun.log'),
                    '-history_file', str(folder_path/'history'), str(bundle)]
                if negative:
                    command.append('+CORRUPT_JOINED_REFERENCE')
                unchanged()
                phase_started = time.monotonic()
                with log.open('w') as stream:
                    child = subprocess.Popen(command, cwd=folder_path, stdin=subprocess.DEVNULL,
                        stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                    pause = OwnedProcessPause(child, str(folder_path/'xrun.log'))
                    policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3,
                                                  anonymous_limit_bytes=16*1024**3)
                    save(state='native_guard_frame_simulation_running', phase=phase,
                         native_process_group=child.pid, command=command)
                    last_save = 0
                    try:
                        while child.poll() is None:
                            assert not stop_requested and time.monotonic()-phase_started < 2400, 'Frame phase runtime limit'
                            available, anonymous = memory()
                            action = policy.observe(available, anonymous, time.monotonic())
                            if action in ['pause', 'resume']:
                                groups = pause.pause() if action == 'pause' else pause.resume()
                                save(memory_pressure_events=record.get('memory_pressure_events', [])+
                                     [dict(action=action, groups=groups, available=available, anonymous=anonymous)])
                            record['peak_combined_anonymous_bytes'] = max(record.get('peak_combined_anonymous_bytes', 0), anonymous)
                            if time.monotonic()-last_save > 5:
                                text = log.read_text(errors='replace')
                                save(native_phase_elapsed_seconds=time.monotonic()-phase_started,
                                     cases_seen=text.count('JOINED_CASE_PASS '), current_host_available_bytes=available,
                                     current_combined_anonymous_bytes=anonymous)
                                last_save = time.monotonic()
                            time.sleep(.2)
                    finally:
                        pause.resume()
                        terminate_process_group(child, log_argument=str(folder_path/'xrun.log'))
                unchanged()
                text = log.read_text(errors='replace')
                assert 'JOINED_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in text
                assert text.count('JOINED_STAGED_DOWN_BOUND ') == 20 and text.count('JOINED_STAGED_DMA_BOUND ') == 5
                if negative:
                    assert child.returncode != 0 and 'JOINED_HIDDEN_SUM' in text and 'JOINED_PASS cases=' not in text
                else:
                    match = re.search(r'JOINED_PASS cases=12 hidden_outputs=4420 success_stalls=(\d+) error_stalls=(\d+)', text)
                    assert child.returncode == 0 and text.count('JOINED_CASE_PASS ') == 12 and match, text[-5000:]
                    assert int(match[1]) > 0 and int(match[2]) >= 9
                steps.append(dict(phase=phase, native_exit_status=child.returncode,
                    native_elapsed_seconds=time.monotonic()-phase_started, console_sha256=sha(log),
                    console_path=str(log), cases_seen=text.count('JOINED_CASE_PASS ')))
                save(steps=steps)
            # Keep the identities of persistent inputs; the deleted temporary
            # bundle is independently bound by its text and prelaunch digest.
            del identities[str(bundle)]
        unchanged()
        frozen=json.loads((root/'.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/input_revision.json').read_text())['candidate_rtl_inventory']
        assert all(sha(root/p)==h for p,h in frozen.items())
        save(state='row_guard_full_frame_source_functional_qualified', source_sha256=identities,
             cases_seen=12, hidden_outputs_checked=4420, actual_cores=20, actual_clusters=5,
             actual_compiled_memories=600, wrong_mathematical_reference_rejected=True,
             frozen_original_files_unchanged=True, temporary_build_removed=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=str(folder_path/'xrun.log') if folder_path else None)
        save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None)
        raise


if __name__ == '__main__':
    main()
