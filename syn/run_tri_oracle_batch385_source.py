"""Verify full5632-feature streamed projection without changing native memories.

The resident372 counterfactual must reject a sixteen-token full-width request.
The streamed owner checks trained decode, tail and sixteen-token batches, a
late read fault after two retained partial tiles, and zero-input weight-fetch
suppression. Every operand read and all six feature tiles are checked. No
complete feedforward, mapped timing, full-model or paper-performance claim.
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
    assert sys.argv[1:] in [['red'],['green']]
    mode=sys.argv[1];root=Path(__file__).resolve().parents[1];os.chdir(root)
    result=root/f'records/batch385_{mode}_result.json';directory=root/f'.cache/physical/simulation/batch385_{mode}'
    assert not result.exists() and not directory.exists()
    fixture_path=root/'records/batch386_fixture_preparation.json';fixture=json.loads(fixture_path.read_text())
    guard_path=root/'records/batch386_gpu_guard_result.json';guard=json.loads(guard_path.read_text())
    assert fixture['state']=='full_width_trained_down_fixture_scalar_cuda_equal'
    assert fixture['complete_canonical_output_reconstruction_equal'] and fixture['prior379_gated_and_down_subsets_equal']
    assert guard['state']=='completed' and guard['native_exit_status']==0 and guard['input_drift']==[]
    assert sha(fixture_path)==guard['summary_sha256']
    prior_path=root/'records/batch359_source_result.json';prior=json.loads(prior_path.read_text())
    names=['tri_oracle_pe_array','tri_oracle_sram_memory_compute','tri_oracle_sram_compute_cluster',
           'tri_oracle_compute_fabric','tri_oracle_batched_projection356',
           'tri_oracle_batched_dma372' if mode=='red' else 'tri_oracle_batched_stream385',
           'tri_oracle_batched385_tb','tri_oracle_batch357_hierarchy']
    paths=[root/'verilog'/(name+'.sv') for name in names]
    models=[Path(p) for p in prior['source_sha256'] if '/VERILOG/' in p and Path(p).suffix=='.v'];assert len(models)==3
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',
        fixture_path,guard_path,prior_path,root/'records/batch385_missing_stream_owner.json',*paths,*models]}
    inputs.update(fixture['files_sha256'])
    for p in paths+models:
        if str(p) in prior['source_sha256']:assert sha(p)==prior['source_sha256'][str(p)]
    assert all(sha(p)==h for p,h in inputs.items())
    if mode=='green':
        red_path=root/'records/batch385_red_result.json';red=json.loads(red_path.read_text())
        assert red['state']=='resident_full_width_batch_limit_reproduced';inputs[str(red_path)]=sha(red_path)
    bundle='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'
    if mode=='red':bundle+='`define BATCH385_RED_RESIDENT\n'
    bundle+=''.join('`include "'+str(p)+'"\n' for p in paths+models)
    started=time.monotonic();lock=threading.RLock();stopped=False
    record=dict(state='starting',mode=mode,supervisor_pid=os.getpid(),source_sha256=inputs,runs=[],scope=__doc__,
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
    assert memory()>12*1024**3;directory.mkdir();save(state='native_stream_checks_running')
    def run(case):
        tokens,fault=case;label=f't{tokens}_f{fault}';work=directory/label;work.mkdir()
        (work/'bundle.sv').write_text(bundle);log=directory/(label+'.log');child=None;began=time.monotonic()
        entry=dict(tokens=tokens,fault=fault,state='starting')
        with lock:record['runs'].append(entry);save()
        try:
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
                '-top','tri_oracle_batched385_tb','-top','tri_oracle_batch357_hierarchy',
                '-defparam',f'tri_oracle_batched385_tb.TOKENS={tokens}',
                '-defparam',f'tri_oracle_batched385_tb.FAULT={fault}',
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
            assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            if mode=='red':
                assert child.returncode==2 and 'BATCH385_DONE_METADATA' in content and 'BATCH385_PASS tokens=' not in content
                with lock:entry['state']='resident_capacity_limit_verified';save()
                return
            assert child.returncode==0,'Native full-width stream failed: '+str(log)
            match=re.search(r'BATCH385_PASS tokens=(\d+) hidden=5632 rows=160 exact_outputs=(\d+) requests=(\d+) activation_beats=(\d+) weight_beats=(\d+) stalls=(\d+) fault=(\d+)',content)
            tiles=re.search(r'BATCH385_STREAMED_INVENTORY tiles=(\d+) active_words=(\d+) weight_bursts_per_row=(\d+)',content)
            assert match and tiles
            actual=dict(zip(['tokens','exact_outputs','requests','activation_beats','weight_beats','stalls','fault'],map(int,match.groups())))
            tile_actual=dict(zip(['tiles','active_words','weight_bursts_per_row'],map(int,tiles.groups())))
            assert actual['tokens']==tokens and actual['fault']==fault and actual['exact_outputs']==tokens*160
            assert actual['activation_beats']==tokens*704 and actual['weight_beats']==160*tile_actual['active_words']
            assert tile_actual['tiles']==6 and actual['requests']==tokens*44+160*tile_actual['weight_bursts_per_row'] and actual['stalls']>=4
            if fault==6:assert actual['weight_beats']==0 and tile_actual['active_words']==0
            if fault==7:assert 'BATCH385_PARTIAL_TILES_BEFORE_ERROR completed=2' in content and 'BATCH385_FAULT_DRAINED fault=7 ' in content
            with lock:entry.update(state='streamed_down_projection_and_transfers_passed',inventory=actual,tile_inventory=tile_actual);save()
        finally:
            if child is not None:terminate_process_group(child)
            shutil.rmtree(work)
    try:
        if mode=='red':run((16,0))
        else:
            run((1,0))
            with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,[(16,0),(8,0),(3,7),(3,6)]))
        assert all(sha(p)==h for p,h in inputs.items())
        save(state='resident_full_width_batch_limit_reproduced' if mode=='red' else 'full_width_trained_streamed_down_projection_passed',
             exact_output_comparisons=0 if mode=='red' else 4960,temporary_builds_removed=True)
        print('BATCH385_'+mode.upper()+'_VERIFIED',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
