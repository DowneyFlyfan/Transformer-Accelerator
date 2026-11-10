"""Native boundary tests for short bursts, partial rows and address extremes.

Literal160-feature/35-row arithmetic covers original channel IDs0/65535,
five-word bursts, padded output lanes and a globally masked row. Four invalid
descriptors independently exercise64-bit activation/weight overflow, alignment
and input-store capacity; each must recover without external reset. Reduced
boundary tests complement the full2048-feature trained366/372 tests.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import threading
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
    attempt=os.environ.get('TRI375_ATTEMPT','full')
    assert attempt in ['full','stop_control']
    result=root/f'records/batch375_{attempt}_result.json'
    directory=root/f'.cache/physical/simulation/batch375_{attempt}'
    assert not result.exists() and not directory.exists()
    prior=json.loads((root/'records/batch359_source_result.json').read_text())
    names=['tri_oracle_pe_array','tri_oracle_sram_memory_compute','tri_oracle_sram_compute_cluster',
           'tri_oracle_compute_fabric','tri_oracle_batched_projection356','tri_oracle_batched_dma372',
           'tri_oracle_batched371_tb','tri_oracle_batch357_hierarchy']
    paths=[root/'verilog'/(name+'.sv') for name in names]
    models=[Path(p) for p in prior['source_sha256'] if '/VERILOG/' in p and Path(p).suffix=='.v']
    assert len(models)==3
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',*paths,*models]}
    for p in paths+models:
        if str(p) in prior['source_sha256']:assert sha(p)==prior['source_sha256'][str(p)]
    stopped=False
    lock=threading.RLock()
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def memory():
        available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
        anonymous=int(dict(l.split() for l in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3 and not stopped,'Memory or requested-stop guard'
    memory();directory.mkdir();started=time.monotonic()
    record=dict(state='native_boundary_checks_running',supervisor_pid=os.getpid(),source_sha256=inputs,
                runs=[],scope=__doc__,current_mapped_candidate_verified=False,full_paper_results_matched=False)
    def save():
        with lock:
            record['elapsed_seconds']=time.monotonic()-started
            temporary=result.with_suffix('.tmp')
            temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    save()
    bundle='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'
    bundle+=''.join('`include "'+str(p)+'"\n' for p in paths+models)
    def run(fault):
        work=directory/str(fault);work.mkdir();(work/'bundle.sv').write_text(bundle)
        log=directory/(str(fault)+'.log');child=None;began=time.monotonic()
        command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
            '-top','tri_oracle_batched371_tb','-top','tri_oracle_batch357_hierarchy',
            '-defparam',f'tri_oracle_batched371_tb.FAULT={fault}',
            '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),
            '-history_file',str(work/'history'),str(work/'bundle.sv')]
        entry=dict(fault=fault,state='starting',command=command)
        with lock:record['runs'].append(entry);save()
        try:
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stream,
                    stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid);save()
                while child.poll() is None:
                    memory();assert time.monotonic()-began<300;time.sleep(.5)
            content=log.read_text()
            assert child.returncode==0,'Native boundary failed: '+str(log)
            assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            marker=re.search(r'BATCH371_PASS tokens=3 hidden=160 rows=35 exact_outputs=105 requests=148 activation_beats=60 weight_beats=680 stalls=(\d+) fault='+str(fault),content)
            assert marker and int(marker[1])>=4
            if fault:assert f'BATCH371_FAULT_DRAINED fault={fault} requests=0 beats=0' in content
            with lock:
                entry.update(state='passed',native_exit_status=child.returncode,log=str(log),
                             log_sha256=sha(log),elapsed_seconds=time.monotonic()-began);save()
            return entry
        finally:
            if child is not None:terminate_process_group(child)
            with lock:
                entry.update(native_exit_status=child.returncode if child is not None else None,
                             owned_process_group_cleaned=True);save()
            shutil.rmtree(work)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[0,7,8,9,10]))
        assert all(sha(p)==h for p,h in inputs.items())
        record.update(state='short_burst_partial_rows_and_address_boundaries_passed',
                      exact_output_comparisons=525,temporary_builds_removed=True)
        print('BATCH375_BOUNDARIES_VERIFIED',flush=True)
    except BaseException as error:
        record.update(state='failed',exception=repr(error));raise
    finally:
        save()


if __name__=='__main__':main()
