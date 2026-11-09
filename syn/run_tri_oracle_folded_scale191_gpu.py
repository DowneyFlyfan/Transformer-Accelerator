"""Protect the live synthesis job while one bounded reference diagnostic uses CUDA."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def memory():
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    anonymous=int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available,anonymous


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/folded_scale191_guard.json';assert not result.exists()
    entry=root/'syn/tri_oracle_folded_scale191_gpu.py'
    paths=[Path(__file__).resolve(),entry,root/'syn/tri_oracle_integer_reference.py',root/'syn/tri_oracle_model_reference.py',root/'syn/tri_oracle_process_guard.py']
    identities={str(p):sha(p) for p in paths};started=time.monotonic();child=None;stop_requested=False
    def stop(signum,frame):
        nonlocal stop_requested
        stop_requested=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_hardware_changed=False,paper_results_matched=False)
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    save()
    try:
        while True:
            available,anonymous=memory()
            if available>10*1024**3 and anonymous<1024**3:break
            assert not stop_requested and time.monotonic()-started<3600,'Reference headroom wait expired'
            save(state='waiting_for_reference_memory_headroom');time.sleep(2)
        assert all(sha(p)==h for p,h in identities.items())
        environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
            HF_HOME=str(root/'.cache/huggingface'),TORCH_HOME=str(root/'.cache/torch'),CUDA_CACHE_PATH=str(root/'.cache/cuda'),
            XDG_CACHE_HOME=str(root/'.cache'),OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
        log=root/'records/folded_scale191_gpu_native.log';assert not log.exists()
        with log.open('w') as output:
            child=subprocess.Popen([str(root/'.cache/.venv-cadence/bin/python'),'-B','-u',str(entry)],cwd=root,
                stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True,env=environment)
            save(state='bounded_gpu_reference_running',native_process_group=child.pid)
            last_save=0
            while child.poll() is None:
                available,anonymous=memory()
                record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                assert not stop_requested and time.monotonic()-started<600,'Reference runtime or stop guard'
                assert available>8*1024**3 and anonymous<3*1024**3,'Reference memory reserve guard'
                if time.monotonic()-last_save>5:save(current_host_available_bytes=available,current_combined_anonymous_bytes=anonymous);last_save=time.monotonic()
                time.sleep(.2)
        terminate_process_group(child)
        assert child.returncode==0,log.read_text()[-3000:]
        assert all(sha(p)==h for p,h in identities.items())
        proof=root/'records/folded_scale191_gpu_result.json';d=json.loads(proof.read_text())
        assert d['state']=='paired_folded_scale_diagnostic_completed'
        save(state='bounded_gpu_reference_completed',native_exit_status=0,native_console_sha256=sha(log),result_sha256=sha(proof))
    except BaseException as error:
        if child is not None:terminate_process_group(child)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise


if __name__=='__main__':main()
