"""Bound the independent GPU diagnostic without disturbing mapped simulation."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def available():
    return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith('MemAvailable:')))*1024


def anonymous():
    return int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/format350_gpu_guard_result.json'
    assert not result.exists()
    entry=root/'syn/prepare_tri_oracle_format350_fixtures.py'
    architecture_path=root/'records/format350_architecture_validation.json'
    architecture=json.loads(architecture_path.read_text())
    assert architecture['source_sha256'][str(entry)]==sha(entry)
    assert architecture['source_audits_completed']==3 and architecture['render_visually_verified'] is True
    assert sha(architecture['pdf'])==architecture['pdf_sha256']
    inputs={str(path):sha(path) for path in [Path(__file__),entry,architecture_path,
        Path(architecture['pdf']),root/'syn/tri_oracle_process_guard.py',
        root/'syn/tri_oracle_integer_reference.py',root/'syn/tri_oracle_model_reference.py']}
    for path,digest in architecture['source_sha256'].items():
        assert sha(path)==digest
        inputs[path]=digest
    assert available()>14*1024**3 and anonymous()<1024**3,'GPU diagnostic admission'
    stopped=False
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    started=time.monotonic()
    log=root/'.cache/format350_gpu_native.log'
    assert not log.exists()
    record=dict(state='starting',supervisor_pid=os.getpid(),source_sha256=inputs,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        host_reserve_bytes=6*1024**3,auxiliary_anonymous_limit_bytes=10*1024**3,
        gpu_allocator_fraction=.84,maximum_wall_seconds=3600,
        peak_auxiliary_anonymous_bytes=anonymous(),minimum_host_available_bytes=available())
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(root/'.cache/huggingface'),
        TORCH_HOME=str(root/'.cache/torch'),CUDA_CACHE_PATH=str(root/'.cache/cuda'),XDG_CACHE_HOME=str(root/'.cache'))
    command=[str(root/'.cache/.venv-cadence/bin/python'),'-u',str(entry)]
    save()
    with log.open('w') as stream:
        child=subprocess.Popen(command,cwd=root,env=environment,stdin=subprocess.DEVNULL,
                               stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        save(state='native_running',child_pid=child.pid,command=command)
        last=0
        try:
            while child.poll() is None:
                host,anon=available(),anonymous()
                record['peak_auxiliary_anonymous_bytes']=max(record['peak_auxiliary_anonymous_bytes'],anon)
                record['minimum_host_available_bytes']=min(record['minimum_host_available_bytes'],host)
                assert not stopped and time.monotonic()-started<3600,'GPU diagnostic wall/stop guard'
                assert host>6*1024**3 and anon<10*1024**3,'GPU diagnostic resource guard'
                if time.monotonic()-last>5:save();last=time.monotonic()
                time.sleep(.2)
        except BaseException as error:
            terminate_process_group(child)
            save(state='failed',exception=repr(error),native_exit_status=child.returncode,native_log_sha256=sha(log))
            raise
        finally:
            terminate_process_group(child)
    drift=[path for path,digest in inputs.items() if sha(path)!=digest]
    summary_path=root/'records/format350_fixture_preparation.json'
    summary=json.loads(summary_path.read_text()) if summary_path.exists() else {}
    passed=child.returncode==0 and not drift and summary.get('state')=='all44_protected_prefix_fixtures_prepared_scalar_cuda_equal'
    save(state='completed' if passed else 'failed',native_exit_status=child.returncode,
         input_drift=drift,native_log_sha256=sha(log),summary_sha256=sha(summary_path) if summary_path.exists() else None)
    assert passed,'GPU diagnostic did not qualify; inspect native log and summary'
    print('FORMAT350_GPU_DIAGNOSTIC_COMPLETED',round(record['elapsed_seconds'],3),flush=True)


if __name__=='__main__':
    main()
