#!/usr/bin/env bash
# A small-block run may share tri-oracle-eda with the baseline core profile.
# Both jobs share the container's 18-processor quota. This run yields first
# if combined anonymous memory exceeds its conservative guard threshold.
set -euo pipefail
exec python3 - <<'PY'
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
sys.dont_write_bytecode=True
sys.path.insert(0,"syn")
from tri_oracle_process_guard import terminate_process_group

top = os.environ['TRI_ORACLE_TOP']
if not re.fullmatch(r'tri_oracle_[a-z_]+', top):
    raise ValueError('Invalid synthesis top')
output = Path('.cache/physical/synthesis') / top
output.mkdir(parents=True, exist_ok=True)
lock = (output / 'guard.lock').open('w')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
start = time.monotonic()
# Invalidate prior success before writing any new source inventory. A failed
# preparation must never pair old successful artifacts with new provenance.
(output / 'guard_result.json').write_text(json.dumps({
    'exit_status': None, 'state': 'preparing', 'supervisor_pid': os.getpid()
}, indent=2) + '\n')
(output / 'exit_status').write_text('preparing\n')

def file_digest(path):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as source_file:
        for chunk in iter(lambda:source_file.read(1024*1024),b''):
            checksum.update(chunk)
    return checksum.hexdigest()
def prepare_inputs():
    source = Path('verilog') / (top + '.sv')
    flow = Path('syn/tri_oracle_synthesize.tcl')
    libraries = os.environ['TRI_ORACLE_LIBS']
    shutil.copyfile(source, output / 'input_source.sv')
    shutil.copyfile(flow, output / 'input_flow.tcl')
    entry = os.environ.get('TRI_ORACLE_SYNTH_ENTRY')
    inventory = {}
    rtl_snapshot = output / 'input_rtl'
    rtl_snapshot.mkdir(exist_ok=True)
    for path in Path('verilog').glob('tri_oracle_*.sv'):
        if '_tb' not in path.stem:
            inventory[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            shutil.copyfile(path, rtl_snapshot / path.name)
    if entry:
        shutil.copyfile(entry, output / 'input_entry.tcl')
    revision = {
        'source': str(source), 'sha256': file_digest(source),
        'flow_sha256': file_digest(flow), 'library_list': libraries,
        'entry': entry, 'candidate_rtl_inventory': inventory,
        'supervisor_sha256': file_digest('syn/run_tri_oracle_guarded_synthesis.sh'),
        'scope': 'Top and candidate RTL snapshotted; actual dependencies selected by the saved entry/common flow'
    }
    if os.environ.get('TRI_ORACLE_REUSE_PE') == '1':
        mapped_pe = '.cache/physical/synthesis/tri_oracle_pe_array/netlist.v'
        revision['mapped_processing_array_dependency'] = {'path':mapped_pe,'sha256':file_digest(mapped_pe)}
    checkpoint = os.environ.get('TRI_ORACLE_CORE_CHECKPOINT')
    if checkpoint:
        provenance_path = os.environ['TRI_ORACLE_CHECKPOINT_REVISION']
        prior = json.loads(Path(provenance_path).read_text())
        for name in ['tri_oracle_memory_compute.sv','tri_oracle_word_bank.sv','tri_oracle_pe_array.sv']:
            source_name = 'verilog/' + name
            if file_digest(source_name) != prior['candidate_rtl_inventory'][source_name]:
                raise ValueError('Checkpoint source is stale: ' + source_name)
        prior_pe = prior.get('mapped_processing_array_dependency')
        if not prior_pe or file_digest(prior_pe['path']) != prior_pe['sha256']:
            raise ValueError('Checkpoint mapped processing-array dependency is stale/missing')
        revision['mapped_processing_array_dependency'] = prior_pe
        revision['native_checkpoint_dependency'] = {
            'path':checkpoint,'sha256':file_digest(checkpoint),
            'phase':os.environ['TRI_ORACLE_RESUME_PHASE'],
            'input_revision_path':provenance_path,'input_revision':prior
        }
    imported_core = os.environ.get('TRI_ORACLE_IMPORTED_CORE_NETLIST')
    if imported_core:
        revision['mapped_core_dependency'] = {'path':imported_core,'sha256':file_digest(imported_core)}
    (output / 'input_revision.json').write_text(json.dumps(revision,indent=2) + '\n')
    return entry
reason = None
peak = 0
minimum_available = None
requested_stop = False
def stop(signum, frame):
    global requested_stop
    requested_stop = True
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
child = None
console = None
code = 1
failure = None
try:
    limit = int(float(os.environ.get('TRI_ORACLE_GUARD_ANON_GIB', '8')) * 1024**3)
    seconds = int(os.environ.get('TRI_ORACLE_GUARD_SECONDS', '3600'))
    if limit <= 0 or seconds <= 0:
        raise ValueError('Synthesis guard limits must be positive')
    entry = prepare_inputs()
    if requested_stop:
        reason = 'external stop request'
        raise InterruptedError('Stop requested before native synthesis launch')
    if entry:
        console = (output / 'console.log').open('w')
        command = ['/usr/bin/time', '-v', 'genus', '-no_gui', '-batch', '-log',
                   str(output / 'genus'), '-files', entry]
        child = subprocess.Popen(command, stdout=console, stderr=subprocess.STDOUT, start_new_session=True)
    else:
        child = subprocess.Popen(['bash', 'syn/run_tri_oracle_synthesis.sh'], start_new_session=True)
    (output / 'guard_child.pid').write_text(str(child.pid) + '\n')
    (output / 'guard_result.json').write_text(json.dumps({
        'exit_status': None, 'state': 'running', 'supervisor_pid': os.getpid(),
        'native_process_group': child.pid
    }, indent=2) + '\n')
    print(f'Started {top}, process group {child.pid}', flush=True)
    while child.poll() is None:
        stats = dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())
        anonymous = int(stats['anon'])
        peak = max(peak, anonymous)
        memory = dict((line.split(':',1)[0], line.split(':',1)[1].split()[0])
                      for line in Path('/proc/meminfo').read_text().splitlines())
        available = int(memory['MemAvailable']) * 1024
        minimum_available = available if minimum_available is None else min(minimum_available, available)
        if requested_stop:
            reason = 'external stop request'
        elif anonymous > limit:
            reason = 'combined anonymous-memory guard'
        elif available < 4 * 1024**3:
            reason = 'host available-memory guard'
        elif time.monotonic() - start >= seconds:
            reason = 'runtime guard'
        if reason:
            print(f'Stopping this block only: {reason}', flush=True)
            terminate_process_group(child, log_argument=str(output/'genus'))
            break
        time.sleep(2)
    code = child.wait()
    if reason:
        code = 143 if reason == 'external stop request' else (124 if reason == 'runtime guard' else 75)
except BaseException as exception:
    failure = repr(exception)
    code = 143 if reason == 'external stop request' else 1
finally:
    # A completed launcher can leave detached native workers. Retain all run
    # locks through owned-process cleanup, including monitor-read exceptions.
    try:
        if child is not None:
            terminate_process_group(child, log_argument=str(output/'genus'))
    finally:
        if console is not None:
            console.close()
if code == 0:
    text = (output / 'console.log').read_text()
    if not re.search(r'^TRI_ORACLE_SYNTHESIS_PASS '+re.escape(top)+r'$', text, re.M):
        code = 1
(output / 'exit_status').write_text(str(code) + '\n')
(output / 'guard_result.json').write_text(json.dumps({
    'exit_status': code, 'stop_reason': reason,
    'state': 'finished' if code == 0 else 'failed',
    'elapsed_seconds': time.monotonic() - start,
    'peak_combined_anonymous_bytes': peak,
    'minimum_host_available_bytes': minimum_available,
    'supervisor_exception': failure,
    'scope': 'Process/positive-marker completion only; reports and artifact provenance require separate qualification'
}, indent=2) + '\n')
print(f'Finished {top}: exit {code}', flush=True)
sys.exit(code)
PY
