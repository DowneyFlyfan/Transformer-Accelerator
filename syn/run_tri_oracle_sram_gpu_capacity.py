"""Compare CUDA/scalar golden words with source and actual mapped core behavior."""
from pathlib import Path
import datetime
import fcntl
import hashlib
import json
import os
import resource
import subprocess
import tempfile
import time

from test_tri_oracle_sram_memory_compute import models
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


fixture = Path('.cache/model_reference/sram_capacity_gpu')
manifest = json.loads((fixture/'manifest.json').read_text())
assert manifest['gpu_oracle_matches_independent_scalar']
for path, expected in manifest['vector_sha256'].items():
    assert sha(path) == expected, path
record_path = Path('records/sram_gpu_capacity_validation.json')
assert not record_path.exists()
record = {'state': 'prepared', 'parent_pid': os.getpid(), 'cases': [],
          'fixture_manifest_sha256': sha(fixture/'manifest.json'),
          'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'scope': 'Full memory-address arithmetic reference, source/mapped typical-corner '
                   'UNIT_DELAY simulation only; no full-model accuracy or physical signoff.'}
started = time.monotonic()


def bounds():
    resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (900, 900))


def run(command, phase):
    lock = None
    if phase.endswith('compile'):
        record['state'] = 'waiting_for_physical_compile_lock'
        record_path.write_text(json.dumps(record, indent=2)+'\n')
        lock = open('.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock', 'a')
        fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        record['state'] = phase
        log = Path('records')/('sram_gpu_capacity_'+phase+'.log')
        with log.open('w') as output:
            child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, preexec_fn=bounds, start_new_session=True)
            record['child_pid'] = child.pid
            record_path.write_text(json.dumps(record, indent=2)+'\n')
            try:
                code = child.wait(timeout=900)
            finally:
                terminate_process_group(child, grace_seconds=2)
        return code, log.read_text()
    finally:
        if lock is not None:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()


try:
    for mode in ['source', 'mapped']:
        with tempfile.TemporaryDirectory(prefix='sram_gpu_capacity_', dir='.cache') as directory:
            binary = Path(directory)/'sim.vvp'
            units = ['verilog/tri_oracle_sram_memory_compute.sv',
                     'verilog/tri_oracle_pe_array.sv'] if mode == 'source' else [
                '.cache/physical/synthesis/tri_oracle_sram_memory_compute/netlist.v',
                '.cache/physical/library/tcbn28hpcplusbwp12t40p140.v']
            code, output = run(['iverilog', '-g2012', '-DUNIT_DELAY', '-s',
                'tri_oracle_sram_gpu_capacity_tb', '-o', str(binary), *units,
                *models('tt1v25c'), 'verilog/tri_oracle_sram_gpu_capacity_tb.sv'], mode+'_compile')
            assert code == 0, output[-3000:]
            code, output = run(['vvp', '-i', str(binary)], mode+'_run')
            assert code == 0 and 'GPU_CORE_CAPACITY_PASS commands=1024' in output, output[-3000:]
            record['cases'].append({'mode': mode, 'positive_run_passed': True})
            if mode == 'source':
                code, output = run(['vvp', '-i', str(binary), '+CORRUPT_REFERENCE'], 'bad_golden_run')
                assert code != 0 and 'GPU_CORE_REFERENCE_MISMATCH' in output, output[-3000:]
                record['wrong_golden_rejected'] = True
    record.update(state='passed', exit_status=0)
except BaseException as exception:
    record.update(state='failed', exit_status=1, exception=repr(exception))
    raise
finally:
    record['elapsed_seconds'] = time.monotonic()-started
    record_path.write_text(json.dumps(record, indent=2)+'\n')
