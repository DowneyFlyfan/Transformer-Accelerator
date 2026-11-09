"""Check the mapped original gate/up controller with its independent peer bench."""
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


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def memory():
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))) * 1024
    anonymous = int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available, anonymous


def main():
    root = Path(__file__).resolve().parents[1]
    result = root / 'records/gated154_mapped_result.json'
    prerequisite_path = root / 'records/gated153_synthesis_result.json'
    assert not result.exists()
    started = time.monotonic()
    child = pause = folder_path = None
    stop_requested = False
    record = dict(state='preflight', supervisor_pid=os.getpid(),
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  full_paper_results_matched=False, routed_timing_qualified=False,
                  scope='Original gate/up controller and activation unit mapped to standard cells, '
                        'with the unchanged independent projection peer bench. Raw-clock functional '
                        'checks only; no full20-core integration, delay annotation or physical timing proof.')

    def save(**updates):
        record.update(updates, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)

    def stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    save()
    try:
        while True:
            assert not stop_requested and time.monotonic()-started < 10800, 'Mapping wait expired'
            if prerequisite_path.exists():
                prerequisite = json.loads(prerequisite_path.read_text())
                assert prerequisite['state'] != 'failed', 'Gate/up mapping prerequisite failed'
                if prerequisite['state'] == 'native_small_block_mapping_completed_pending_report_review':
                    break
            save(state='waiting_for_native_gate_controller_mapping')
            time.sleep(2)
        assert prerequisite['native_exit_status'] == 0
        assert all(sha(path) == expected for path, expected in prerequisite['source_sha256'].items())
        netlist = Path(prerequisite['output_directory']) / 'netlist.v'
        assert sha(netlist) == prerequisite['output_netlist_sha256']
        bench = root / 'verilog/tri_oracle_fabric_gated_executor_tb.sv'
        standard = root / '.cache/physical/library/tcbn28hpcplusbwp12t40p140.v'
        executable = Path('/opt/cadence/bin/xrun')
        inputs = [Path(__file__).resolve(), prerequisite_path, netlist, bench, standard, executable,
                  root/'syn/tri_oracle_memory_pressure_guard.py', root/'syn/tri_oracle_process_guard.py']
        identities = {str(path): sha(path) for path in inputs}
        save(source_sha256=identities)
        attempts = {}
        for phase in ['wrong_reference', 'positive']:
            while True:
                available, anonymous = memory()
                if available > 10*1024**3 and anonymous < 3*1024**3:
                    break
                assert not stop_requested and time.monotonic()-started < 14400, 'Simulation headroom wait expired'
                save(state='waiting_for_mapped_simulation_memory_headroom')
                time.sleep(2)
            with tempfile.TemporaryDirectory(prefix='gated154_'+phase+'_', dir=root/'.cache/physical') as folder:
                folder_path = Path(folder)
                log = root / ('records/gated154_'+phase+'_native.log')
                assert not log.exists()
                command = [str(executable), '-64bit', '-sv', '-xmerror', 'RECOME', '-sequdp_nba_delay',
                           '-top', 'tri_oracle_fabric_gated_executor_tb', '-xmlibdirname', str(folder_path/'xcelium.d'),
                           '-l', str(folder_path/'xrun.log'), '-history_file', str(folder_path/'history'),
                           str(standard), str(netlist), str(bench)]
                if phase == 'wrong_reference':
                    command.append('+CORRUPT_REFERENCE')
                native_started = time.monotonic()
                with log.open('w') as output:
                    child = subprocess.Popen(command, cwd=folder_path, stdin=subprocess.DEVNULL,
                                             stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                    pause = OwnedProcessPause(child, str(folder_path/'xrun.log'))
                    policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3,
                                                  anonymous_limit_bytes=12*1024**3)
                    save(state='native_mapped_gate_controller_simulation_running', phase=phase,
                         native_process_group=child.pid, command=command)
                    try:
                        while child.poll() is None:
                            assert not stop_requested and time.monotonic()-native_started < 900, 'Simulation runtime limit'
                            available, anonymous = memory()
                            action = policy.observe(available, anonymous, time.monotonic())
                            if action == 'pause':
                                pause.pause()
                            elif action == 'resume':
                                pause.resume()
                            time.sleep(.1)
                    finally:
                        pause.resume()
                        terminate_process_group(child, log_argument=str(folder_path/'xrun.log'))
                text = log.read_text(errors='replace')
                assert all(sha(path) == expected for path, expected in identities.items()), 'Mapped simulation inputs changed'
                if phase == 'wrong_reference':
                    assert child.returncode != 0 and 'gated mathematical mismatch' in text, text[-4000:]
                    assert 'FABRIC_GATED_CONTROLLER_PASS' not in text
                else:
                    assert child.returncode == 0 and 'FABRIC_GATED_CONTROLLER_PASS cases=31 projection_requests=38' in text, text[-4000:]
                    match = re.search(r'FABRIC_GATED_EXACT_QUANTIZATION_PASS checks=(\d+)', text)
                    assert match and int(match.group(1)) >= 500
                    record['exact_quantization_checks'] = int(match.group(1))
                attempts[phase] = dict(native_exit_status=child.returncode,
                                       native_elapsed_seconds=time.monotonic()-native_started,
                                       console_sha256=sha(log))
            attempts[phase]['temporary_build_removed'] = not folder_path.exists()
            assert attempts[phase]['temporary_build_removed']
            save(attempts=attempts)
        save(state='original_gate_controller_mapped_functional_qualified', cases_passed=31,
             projection_requests=38, wrong_mathematical_reference_rejected=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=str(folder_path/'xrun.log'))
        save(state='failed', exception=repr(error))
        raise


if __name__ == '__main__':
    main()
