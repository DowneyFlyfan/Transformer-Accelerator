"""Validate fabric gate/up sequencing with a transaction peer on native Xcelium."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from tri_oracle_process_guard import terminate_process_group


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    root = Path(__file__).resolve().parents[1]
    result = root/'records'/(args.label+'_result.json')
    assert not result.exists()
    executable = Path('/opt/cadence/bin/xrun')
    assert executable.is_file(), 'Run in the installed Cadence Docker container'
    sources = [root/'verilog'/name for name in ['tri_oracle_silu_gate.sv',
               'tri_oracle_fabric_gated_executor.sv', 'tri_oracle_fabric_gated_executor_tb.sv']]
    hashes = {str(p): digest(p) for p in [Path(__file__).resolve(), *sources]}
    attempts = {}
    record = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'state': 'running', 'source_sha256': hashes,
              'scope': 'Standalone gate/up controller and the existing nonlinear pipeline. '
                       'An independent transaction peer supplies full projection sums. '
                       'No twenty-core execution, synthesis, physical or paper-metric claim.',
              'full_paper_results_matched': False}
    started = time.monotonic()
    try:
        for name in ['positive', 'negative_reference']:
            log = root/'records'/(args.label+'_'+name+'_native.log')
            assert not log.exists()
            available = lambda: int(next(s.split()[1] for s in
                Path('/proc/meminfo').read_text().splitlines()
                if s.startswith('MemAvailable:')))*1024
            assert available() > 5*1024**3, 'Small-controller simulation startup headroom'
            with tempfile.TemporaryDirectory(prefix=args.label+'_'+name+'_',
                                             dir=root/'.cache/physical') as folder:
                folder = Path(folder)
                command = [str(executable), '-64bit', '-sv', '-top',
                           'tri_oracle_fabric_gated_executor_tb', '-xmlibdirname',
                           str(folder/'xcelium.d'), '-l', str(folder/'xrun.log'),
                           '-history_file', str(folder/'history'), *map(str, sources)]
                if name == 'negative_reference':
                    command.append('+CORRUPT_REFERENCE')
                phase_started = time.monotonic()
                with log.open('w') as output:
                    child = subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL,
                        stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        while child.poll() is None:
                            anonymous = int(dict(line.split() for line in
                                Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
                            assert available() > 4*1024**3 and anonymous < 21*1024**3
                            assert time.monotonic()-phase_started < 120
                            time.sleep(.1)
                    finally:
                        terminate_process_group(child)
                text = log.read_text(errors='replace')
                if name == 'positive':
                    assert child.returncode == 0, text[-4000:]
                    assert 'FABRIC_GATED_CONTROLLER_PASS cases=31 projection_requests=38' in text
                    assert 'FABRIC_GATED_EXACT_QUANTIZATION_PASS checks=' in text
                else:
                    assert child.returncode != 0 and 'gated mathematical mismatch' in text
                    assert 'FABRIC_GATED_CONTROLLER_PASS' not in text
                assert all(digest(p) == expected for p, expected in hashes.items())
                attempts[name] = {'native_exit_status': child.returncode,
                    'native_elapsed_seconds': time.monotonic()-phase_started,
                    'native_console_sha256': digest(log), 'command': command,
                    'corrupted_mathematical_reference_rejected': name == 'negative_reference'}
            attempts[name]['temporary_build_removed'] = True
        record.update(state='passed', cases_passed=31, projection_requests=38,
                      original_sources_unchanged=True)
    except BaseException as error:
        record.update(state='failed', exception=repr(error))
        raise
    finally:
        record.update(attempts=attempts, elapsed_seconds=time.monotonic()-started)
        result.write_text(json.dumps(record, indent=2)+'\n')
        print(str(result), record['state'], flush=True)


if __name__ == '__main__':
    main()
