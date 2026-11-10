"""Expose missing local initialization when all-zero words avoid weight reads.

One temporary compile overlay disables only385's CLEAR_WEIGHTS write. Fresh
native memories must then make the all-zero-input test fail; the unchanged
production case must pass separately. No source, library or fixture is edited.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    result=root/'records/batch387_clear_control.json';directory=root/'.cache/physical/simulation/batch387'
    assert not result.exists() and not directory.exists()
    prior=json.loads((root/'records/batch385_red_result.json').read_text())
    fixture_path=root/'records/batch386_fixture_preparation.json';fixture=json.loads(fixture_path.read_text())
    paths=[root/'verilog'/(name+'.sv') for name in ['tri_oracle_pe_array','tri_oracle_sram_memory_compute',
        'tri_oracle_sram_compute_cluster','tri_oracle_compute_fabric','tri_oracle_batched_projection356',
        'tri_oracle_batched_stream385','tri_oracle_batched385_tb','tri_oracle_batch357_hierarchy']]
    models=[Path(p) for p in prior['source_sha256'] if '/VERILOG/' in p and Path(p).suffix=='.v'];assert len(models)==3
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',
        root/'records/batch385_red_result.json',fixture_path,*paths,*models]}
    inputs.update(fixture['files_sha256'])
    assert all(sha(p)==h for p,h in inputs.items())
    stopped=False;started=time.monotonic();child=None
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def memory():
        available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
        anonymous=int(dict(l.split() for l in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3 and not stopped
    memory();directory.mkdir();work=directory/'build';work.mkdir()
    source=root/'verilog/tri_oracle_batched_stream385.sv';original=source.read_text()
    old="load_valid=!active_words[int'(weight_core%4)*32+int'(clear_word)];";new="load_valid=1'b0;"
    assert original.count(old)==1
    overlay=work/'without_local_clear.sv';overlay.write_text(original.replace(old,new))
    record=dict(state='starting',supervisor_pid=os.getpid(),source_sha256=inputs,
        one_replacement=dict(before=old,after=new),compile_overlay_sha256=sha(overlay),
        scope=__doc__,full_paper_results_matched=False)
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    compile_paths=[overlay if p==source else p for p in paths]
    bundle='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'+''.join('`include "'+str(p)+'"\n' for p in compile_paths+models)
    (work/'bundle.sv').write_text(bundle);log=directory/'native.log'
    command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
        '-top','tri_oracle_batched385_tb','-top','tri_oracle_batch357_hierarchy',
        '-defparam','tri_oracle_batched385_tb.TOKENS=3','-defparam','tri_oracle_batched385_tb.FAULT=6',
        '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),
        '-history_file',str(work/'history'),str(work/'bundle.sv'),'+FIXTURE='+fixture['fixture']]
    save()
    try:
        with log.open('x') as stream:
            child=subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stream,
                stderr=subprocess.STDOUT,start_new_session=True)
            save(state='native_running',process_group=child.pid,command=command)
            while child.poll() is None:
                memory();assert time.monotonic()-started<300;time.sleep(.5)
        content=log.read_text()
        assert child.returncode==2 and 'BATCH385_INTEGER_OUTPUT token=0 row=159 got=x' in content
        assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
        assert 'BATCH385_PASS tokens=' not in content
        assert all(sha(p)==h for p,h in inputs.items())
        terminate_process_group(child);shutil.rmtree(work)
        save(state='missing_local_clear_rejected_on_native_unknown_data',native_exit_status=child.returncode,
             log=str(log),log_sha256=sha(log),temporary_build_removed=True)
        print('BATCH387_MISSING_LOCAL_CLEAR_REJECTED',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child else None)
        raise
    finally:
        if child is not None:terminate_process_group(child)
        if work.exists():shutil.rmtree(work)


if __name__=='__main__':main()
