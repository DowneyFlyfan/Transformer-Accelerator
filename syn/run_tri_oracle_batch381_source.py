"""Verify wrapper error drain while later native token packets are queued.

Corrupt one raw count or one nonlinear return tag on the unchanged380wrapper.
All three raw token packets must drain through owner completion; terminal error
must hold, then a full trained three-token run must recover without external
reset. These cases complement380 arithmetic/memory tests, not fullfeedforward.
"""
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
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    result=root/'records/batch381_source_result.json';directory=root/'.cache/physical/simulation/batch381'
    assert not result.exists() and not directory.exists(),'Preserve each native attempt'
    fixture_path=root/'records/batch379_fixture_preparation.json'
    fixture=json.loads(fixture_path.read_text());guard_path=root/'records/batch379_gpu_guard_result.json'
    guard=json.loads(guard_path.read_text())
    assert fixture['state']=='trained_paired_gated_fixture_scalar_cuda_equal'
    assert guard['state']=='completed' and guard['native_exit_status']==0 and guard['input_drift']==[]
    assert sha(fixture_path)==guard['summary_sha256']
    prior_path=root/'records/batch359_source_result.json';prior=json.loads(prior_path.read_text())
    names=['tri_oracle_pe_array','tri_oracle_sram_memory_compute','tri_oracle_sram_compute_cluster',
           'tri_oracle_compute_fabric','tri_oracle_batched_projection356','tri_oracle_batched_paired379',
           'tri_oracle_batched_gated380','tri_oracle_silu_gate','tri_oracle_batched381_tb','tri_oracle_batch357_hierarchy']
    paths=[root/'verilog'/(name+'.sv') for name in names]
    models=[Path(p) for p in prior['source_sha256'] if '/VERILOG/' in p and Path(p).suffix=='.v']
    assert len(models)==3
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',
        fixture_path,guard_path,prior_path,root/'records/batch380_missing_gated_owner.json',*paths,*models]}
    inputs.update(fixture['files_sha256'])
    for p in paths+models:
        if str(p) in prior['source_sha256']:assert sha(p)==prior['source_sha256'][str(p)]
    assert all(sha(p)==h for p,h in inputs.items())
    bundle='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'
    bundle+=''.join('`include "'+str(p)+'"\n' for p in paths+models)
    started=time.monotonic();stopped=False;lock=threading.RLock()
    record=dict(state='starting',supervisor_pid=os.getpid(),source_sha256=inputs,runs=[],scope=__doc__,
                current_mapped_candidate_verified=False,complete_feedforward_verified=False,
                whole_model_verified=False,full_paper_results_matched=False)
    def save(**changes):
        with lock:
            record.update(changes,elapsed_seconds=time.monotonic()-started)
            p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def memory():
        available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
        anonymous=int(dict(l.split() for l in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3 and not stopped,'Memory/stop guard'
        return available
    assert memory()>12*1024**3;directory.mkdir();save(state='native_paired_gating_checks_running')
    def run(case):
        tokens,kind=case;label=f't{tokens}_c{kind}'
        work=directory/label;work.mkdir();(work/'bundle.sv').write_text(bundle)
        log=directory/(label+'.log');child=None;began=time.monotonic()
        entry=dict(tokens=tokens,case=kind,state='starting')
        with lock:record['runs'].append(entry);save()
        try:
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
                '-top','tri_oracle_batched381_tb','-top','tri_oracle_batch357_hierarchy',
                '-defparam',f'tri_oracle_batched381_tb.TOKENS={tokens}',
                '-defparam',f'tri_oracle_batched381_tb.CASE={kind}',
                '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),
                '-history_file',str(work/'history'),str(work/'bundle.sv'),'+FIXTURE='+fixture['fixture']]
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stream,
                    stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid,command=command);save()
                while child.poll() is None:
                    memory();assert time.monotonic()-began<900;time.sleep(.5)
            content=log.read_text()
            with lock:entry.update(native_exit_status=child.returncode,log=str(log),log_sha256=sha(log),elapsed_seconds=time.monotonic()-began);save()
            assert child.returncode==0,'Native paired gating failed: '+str(log)
            assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            match=re.search(r'BATCH381_PASS tokens=(\d+) hidden=2048 rows=80 gated_words=(\d+) down_words=(\d+) requests=(\d+) activation_beats=(\d+) gate_beats=(\d+) up_beats=(\d+) stalls=(\d+) case=(\d+)',content)
            assert match,'Missing native paired inventory'
            actual=dict(zip(['tokens','gated_words','down_words','requests','activation_beats','gate_beats','up_beats','stalls','case'],map(int,match.groups())))
            assert actual['tokens']==tokens and actual['case']==kind and actual['gated_words']==actual['down_words']==tokens*80
            assert actual['activation_beats']==tokens*256 and actual['gate_beats']==actual['up_beats'] and actual['stalls']>=4
            assert actual['requests']*16==actual['activation_beats']+actual['gate_beats']+actual['up_beats']
            if kind in [1,2,4,5]:assert f'BATCH381_FAULT_DRAINED case={kind} ' in content
            if kind in [4,5]:assert f'BATCH381_RAW_OWNER_DRAINED packets=3 case={kind}' in content
            if kind==3:assert actual['gate_beats']==actual['up_beats']==0
            with lock:entry.update(state='paired_projection_nonlinear_and_transfers_passed',inventory=actual);save()
        finally:
            if child is not None:terminate_process_group(child)
            shutil.rmtree(work)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[(3,4),(3,5)]))
        assert all(sha(p)==h for p,h in inputs.items())
        save(state='queued_raw_and_activation_fault_drain_and_recovery_passed',
             raw_projection_comparisons=960,gated_word_comparisons=480,
             down_input_word_comparisons=480,temporary_builds_removed=True)
        print('BATCH381_QUEUED_FAULT_RECOVERY_VERIFIED',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
