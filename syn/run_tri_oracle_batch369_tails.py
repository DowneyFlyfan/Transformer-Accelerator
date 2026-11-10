"""Reproduce missed short-batch stall coverage, then verify directed stalls.

The red control uses the original periodic ready schedule. Green holds the
first actual output for four cycles, then resumes that same schedule. No
production hardware, trained fixture, arithmetic or acceptance check changes.
Actual twenty-core/six-hundred-memory source hierarchy; no mapped, physical,
whole-model, transfer-latency or paper-performance qualification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['red', 'green'])
    mode = parser.parse_args().mode
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    result = root/f'records/batch369_{mode}_result.json'
    directory = root/f'.cache/physical/simulation/batch369_{mode}'
    assert not result.exists() and not directory.exists(), 'Preserve each attempt'
    prior_path = root/'records/batch359_source_result.json'
    prior = json.loads(prior_path.read_text())
    assert prior['state'] == 'trained_batched_projection_source_functional_passed'
    fixture_path = root/'records/batch358_fixture_preparation.json'
    fixture_record = json.loads(fixture_path.read_text())
    fixture = Path(fixture_record['fixture'])
    paths = [root/'verilog'/(name+'.sv') for name in [
        'tri_oracle_pe_array', 'tri_oracle_sram_memory_compute',
        'tri_oracle_sram_compute_cluster', 'tri_oracle_compute_fabric',
        'tri_oracle_batched_projection356', 'tri_oracle_batched369_tb',
        'tri_oracle_batch357_hierarchy']]
    models = [Path(p) for p in prior['source_sha256']
              if '/VERILOG/' in p and Path(p).suffix == '.v']
    assert len(models) == 3
    identities = {str(p): sha(p) for p in [Path(__file__).resolve(),
        root/'syn/tri_oracle_process_guard.py', prior_path, fixture_path,
        root/'records/batch365_tail_result.json', *paths, *models]}
    identities.update(fixture_record['files_sha256'])
    for p in paths+models:
        if p.name != 'tri_oracle_batched369_tb.sv':
            assert sha(p) == prior['source_sha256'][str(p)]
    assert all(sha(p) == h for p, h in identities.items())
    if mode == 'green':
        red_path = root/'records/batch369_red_result.json'
        red = json.loads(red_path.read_text())
        assert red['state'] == 'missed_backpressure_coverage_reproduced'
        assert all(identities[p] == h for p, h in red['source_sha256'].items())
        identities[str(red_path)] = sha(red_path)
    bundle_text = '`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'
    bundle_text += ''.join('`include "'+str(p)+'"\n' for p in paths+models)
    started = time.monotonic()
    lock = threading.RLock()
    stopped = False
    record = dict(state='starting', mode=mode, supervisor_pid=os.getpid(),
        source_sha256=identities, runs=[], scope=__doc__,
        production_hardware_unchanged=True, current_mapped_candidate_verified=False,
        full_model_verified=False, full_paper_results_matched=False)

    def save(**changes):
        with lock:
            record.update(changes, elapsed_seconds=time.monotonic()-started)
            temporary = result.with_suffix('.tmp')
            temporary.write_text(json.dumps(record, indent=2)+'\n')
            temporary.replace(result)

    def stop(number, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def memory():
        available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:')))*1024
        anonymous = int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available > 6*1024**3 and anonymous < 18*1024**3 and not stopped
        return available, anonymous

    assert memory()[0] > 12*1024**3
    directory.mkdir()
    save()

    def run(tokens):
        work = directory/str(tokens)
        work.mkdir()
        bundle = work/'bundle.sv'
        bundle.write_text(bundle_text)
        log = directory/(str(tokens)+'.log')
        child = None
        began = time.monotonic()
        entry = dict(tokens=tokens, state='starting')
        with lock:
            record['runs'].append(entry)
            save()
        try:
            command = ['/opt/cadence/bin/xrun', '-64bit', '-sv', '-xmerror', 'RECOME',
                '-notimingchecks', '-top', 'tri_oracle_batched369_tb',
                '-top', 'tri_oracle_batch357_hierarchy',
                '-defparam', f'tri_oracle_batched369_tb.TOKENS={tokens}',
                '-defparam', f'tri_oracle_batched369_tb.DIRECTED_STALL={int(mode == "green")}',
                '-xmlibdirname', str(work/'xcelium.d'), '-l', str(work/'native.log'),
                '-history_file', str(work/'history'), str(bundle), '+FIXTURE='+str(fixture)]
            with log.open('x') as stream:
                child = subprocess.Popen(command, cwd=work, stdin=subprocess.DEVNULL,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                with lock:
                    entry.update(state='running', process_group=child.pid, command=command)
                    save()
                while child.poll() is None:
                    memory()
                    assert time.monotonic()-began < 600, 'Native deadline'
                    time.sleep(.5)
            content = log.read_text()
            assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            match = re.search(r'BATCH369_INVENTORY tokens=(\d+) seen=(\d+) commands=(\d+) stalls=(\d+) directed=(\d+) first_hold_cycles=(\d+)', content)
            assert match, 'Missing actual inventory'
            observed = dict(zip(['tokens', 'seen', 'commands', 'stalls', 'directed', 'first_hold_cycles'],
                                map(int, match.groups())))
            assert observed['tokens'] == observed['seen'] == tokens
            assert observed['commands'] == 64*tokens
            if mode == 'red':
                assert child.returncode == 2 and observed['stalls'] == 0
                assert observed['directed'] == 0 and 'BATCH369_FINAL_INVENTORY' in content
                assert 'BATCH369_PASS tokens=' not in content
            else:
                marker = f'BATCH369_PASS tokens={tokens} hidden=2048 rows=160 exact_outputs={160*tokens} commands={64*tokens} stalls='
                assert child.returncode == 0 and marker in content
                assert observed['stalls'] >= 4 and observed['first_hold_cycles'] == 4
                assert observed['directed'] == 1
            with lock:
                entry.update(state='expected_failure_verified' if mode == 'red' else 'passed',
                    inventory=observed, native_exit_status=child.returncode,
                    log=str(log), log_sha256=sha(log), elapsed_seconds=time.monotonic()-began)
                save()
        finally:
            if child is not None:
                terminate_process_group(child)
            shutil.rmtree(work)
    try:
        tokens = [1, 3] if mode == 'red' else [1, 3, 8, 16]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, tokens))
        assert all(sha(p) == h for p, h in identities.items())
        save(state='missed_backpressure_coverage_reproduced' if mode == 'red'
             else 'decode_tail_and_full_batch_directed_stalls_source_passed',
             token_counts=tokens, exact_output_comparisons=160*sum(tokens),
             temporary_builds_removed=True)
        print('BATCH369_'+mode.upper()+'_VERIFIED', flush=True)
    except BaseException as error:
        save(state='failed', exception=repr(error))
        raise


if __name__ == '__main__':
    main()
