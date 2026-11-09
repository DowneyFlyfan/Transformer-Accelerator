"""Monitored long integration runs using unchanged canonical system benches."""
import argparse
import ast
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

from tri_oracle_process_guard import terminate_process_group
from test_tri_oracle_sram_integration import SramFabricTest, SramFeedforwardTest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('kind', choices=['feedforward', 'fabric'])
parser.add_argument('--corner', default='tt1v25c')
arguments = parser.parse_args()
os.environ['TRI_ORACLE_TEST_CORNER'] = arguments.corner
fabric = arguments.kind == 'fabric'
top = 'tri_oracle_fabric_projection' if fabric else 'tri_oracle_memory_feedforward_core'
base_test = 'syn/test_tri_oracle_fabric_projection.py' if fabric else (
    'syn/test_tri_oracle_memory_feedforward.py')
expected = 43 if fabric else 34
marker = 'FABRIC_PROJECTION' if fabric else 'MEMORY_FF'
final_marker = 'FABRIC_PROJECTION_PASS cases=43' if fabric else 'MEMORY_FEEDFORWARD_PASS cases=34'
label = f'sram_{arguments.kind}_{arguments.corner}'
record_path = Path('records') / (label + '_result.json')
assert not record_path.exists(), 'Refusing to replace an earlier integration attempt'
runner = SramFabricTest() if fabric else SramFeedforwardTest()
runner.setUp()
tree = ast.parse(Path(base_test).read_text())
units = next(ast.literal_eval(node.value) for node in ast.walk(tree)
             if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
             and target.id == 'units' for target in node.targets))
sources = [f'verilog/{top}.sv'] + [runner.dependency_overrides.get(
    unit, f'verilog/tri_oracle_{unit}.sv') for unit in units]
bench = f'verilog/{top}_tb.sv'
inputs = [base_test, bench, 'verilog/tri_oracle_sram_memory_compute.sv',
          'verilog/tri_oracle_sram_activation_cache.sv',
          'syn/run_tri_oracle_sram_integration.py', 'syn/test_tri_oracle_sram_integration.py',
          'records/sram_core_bank_views.json', 'records/sram_activation_cache_bank_views.json']
inputs += [path for path in sources if not path.startswith(runner.directory.name)]


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def available():
    return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith('MemAvailable:'))) * 1024


assert available() > 10 * 1024**3
revision = {path: sha(path) for path in set(inputs)}
record = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'state': 'prepared', 'kind': arguments.kind, 'corner': arguments.corner,
          'expected_cases': expected, 'source_sha256': revision,
          'parent_pid': os.getpid(), 'full_chip_paper_results_matched': False,
          'scope': 'Unchanged canonical integration bench with actual compiled memory models. '
                   'UNIT_DELAY functional mode only; no physical or full-model/paper claim.'}
started = time.monotonic()
peak = 0
minimum = available()


def bounds():
    resource.setrlimit(resource.RLIMIT_AS, (3*1024**3, 3*1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (21600, 21600))


def run(command, seconds, phase):
    global peak, minimum
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, preexec_fn=bounds,
                             start_new_session=True)
    record.update(state=phase, child_pid=child.pid)
    record_path.write_text(json.dumps(record, indent=2) + '\n')
    phase_started = time.monotonic()
    stop = None
    output = ''
    try:
        while True:
            memory = available()
            anonymous = int(dict(line.split() for line in
                Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
            minimum = min(minimum, memory)
            peak = max(peak, anonymous)
            if memory < 4*1024**3 or anonymous > 20*1024**3:
                stop = 'memory reserve'
            elif time.monotonic() - phase_started > seconds:
                stop = 'runtime limit'
            if stop:
                terminate_process_group(child, grace_seconds=2)
                output, _ = child.communicate()
                break
            try:
                output, _ = child.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired as pending:
                output = pending.output or b''
                if isinstance(output, bytes):
                    output = output.decode(errors='replace')
                Path('records', label + '_live.log').write_text(output)
                record.update(elapsed_seconds=time.monotonic()-started,
                              cases_seen=output.count(marker + '_CASE_PASS'),
                              peak_container_anonymous_bytes=peak,
                              minimum_host_available_bytes=minimum)
                record_path.write_text(json.dumps(record, indent=2) + '\n')
    finally:
        terminate_process_group(child, grace_seconds=2)
    Path('records', label + '_' + phase + '.log').write_text(output)
    return child.returncode, output, stop


try:
    with tempfile.TemporaryDirectory(prefix='sram_integrated_', dir='.cache') as directory:
        binary = Path(directory) / 'sim.vvp'
        code, output, stop = run(['iverilog', '-g2012', '-s', top+'_tb', '-o', str(binary),
                                 *sources, bench], 120, 'compile')
        assert code == 0 and stop is None, output[-3000:]
        code, output, stop = run(['vvp', str(binary)], 21600 if fabric else 7200, 'simulate')
        assert code == 0 and stop is None, str(stop) + output[-3000:]
        assert output.count(marker + '_CASE_PASS') == expected and final_marker in output
        for path, expected_sha in revision.items():
            assert sha(path) == expected_sha, 'Source changed during integration: ' + path
        record.update(state='passed', exit_status=0, cases_seen=expected)
except BaseException as exception:
    record.update(state='failed', exit_status=1, exception=repr(exception))
    raise
finally:
    runner.doCleanups()
    record.update(elapsed_seconds=time.monotonic()-started,
                  peak_container_anonymous_bytes=peak, minimum_host_available_bytes=minimum)
    record_path.write_text(json.dumps(record, indent=2) + '\n')
