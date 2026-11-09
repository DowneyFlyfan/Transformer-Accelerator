"""Serialize the graphics model check with memory-heavy physical jobs."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, 'syn')
from tri_oracle_process_guard import terminate_process_group

root = Path.cwd()
record = Path('records/all_layer_integer_model_guard.json')
assert not record.exists(), 'Refusing to replace earlier guard evidence'
entry = 'syn/tri_oracle_all_layer_integer_model_validation.py'
inputs = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in
          [entry, __file__, 'syn/tri_oracle_integer_reference.py', 'syn/tri_oracle_model_reference.py']}
def status(**fields):
    record.write_text(json.dumps(fields, indent=2) + '\n')
status(state='waiting_for_physical_lock', supervisor_pid=os.getpid(), source_sha256=inputs)
stop = False
def request_stop(number, frame):
    global stop
    stop = True
signal.signal(signal.SIGTERM, request_stop)
signal.signal(signal.SIGINT, request_stop)
with Path('.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock').open('a') as lock:
    while True:
        if stop:
            status(state='stopped_before_launch', supervisor_pid=os.getpid())
            raise SystemExit(143)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(1)
    available = int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines()
                         if l.startswith('MemAvailable:'))) * 1024
    assert available > 12 * 1024**3
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1',
                       OPENBLAS_NUM_THREADS='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                       HF_HOME=str(root/'.cache/huggingface'), TORCH_HOME=str(root/'.cache/torch'),
                       CUDA_CACHE_PATH=str(root/'.cache/cuda'), XDG_CACHE_HOME=str(root/'.cache'))
    started = time.monotonic()
    peak = 0
    minimum = available
    reason = None
    with Path('records/all_layer_integer_model_native.log').open('w') as log:
        child = subprocess.Popen(['.cache/.venv-cadence/bin/python', '-u', entry],
                                 stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 env=environment, start_new_session=True)
        status(state='running', supervisor_pid=os.getpid(), child_pid=child.pid,
               started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
               source_sha256=inputs)
        try:
            while child.poll() is None:
                stats = dict(x.split() for x in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())
                peak = max(peak, int(stats['anon']))
                available = int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines()
                                     if l.startswith('MemAvailable:'))) * 1024
                minimum = min(minimum, available)
                if stop:
                    reason = 'external stop request'
                elif peak > 20 * 1024**3 or available < 4 * 1024**3:
                    reason = 'memory reserve guard'
                elif time.monotonic() - started > 1800:
                    reason = 'runtime guard'
                if reason:
                    terminate_process_group(child)
                    break
                time.sleep(1)
            code = child.wait()
        finally:
            terminate_process_group(child)
    drift = [p for p, h in inputs.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest() != h]
    if reason or drift:
        code = code or 1
    status(state='finished' if code == 0 else 'failed', exit_status=code, stop_reason=reason,
           elapsed_seconds=time.monotonic()-started, peak_container_anonymous_bytes=peak,
           minimum_host_available_bytes=minimum, source_sha256=inputs, input_drift=drift,
           scope='Full model with integer feed-forward arithmetic at all22 language layers; '
                 'not integer attention/vision, dataset accuracy or hardware validation.')
    print('ALL_LAYER_INTEGER_MODEL_FINISHED', code, flush=True)
    raise SystemExit(code)
