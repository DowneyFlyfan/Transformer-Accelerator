"""Check actual compiled-memory arithmetic for1/3/8-token trained batches.

One token covers decode; eight covers600-prefill modulo16; three checks a
non-power-of-two queue wrap. Same full2048-feature,160-original-row fixture,
unchanged356controller and600 actual memory models. Resident/prepared-mask
functional proof only; memory-transfer and full-model integration remain open.
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
    with Path(path).open('rb') as s:return hashlib.file_digest(s,'sha256').hexdigest()


def main():
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    result=root/'records/batch365_tail_result.json';directory=root/'.cache/physical/simulation/batch365'
    assert not result.exists() and not directory.exists();directory.mkdir()
    prior=json.loads((root/'records/batch359_source_result.json').read_text())
    assert prior['state']=='trained_batched_projection_source_functional_passed'
    fixture_record=json.loads((root/'records/batch358_fixture_preparation.json').read_text());fixture=Path(fixture_record['fixture'])
    paths=[root/'verilog'/(name+'.sv') for name in ['tri_oracle_pe_array','tri_oracle_sram_memory_compute',
        'tri_oracle_sram_compute_cluster','tri_oracle_compute_fabric','tri_oracle_batched_projection356',
        'tri_oracle_batched365_tb','tri_oracle_batch357_hierarchy']]
    models=[Path(p) for p in prior['source_sha256'] if '/VERILOG/' in p and Path(p).suffix=='.v']
    assert len(models)==3
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',*paths,*models,
        root/'records/batch359_source_result.json',root/'records/batch358_fixture_preparation.json']}
    inputs.update(fixture_record['files_sha256'])
    for p in paths+models:
        if p.name!='tri_oracle_batched365_tb.sv' and str(p) in prior['source_sha256']:assert sha(p)==prior['source_sha256'][str(p)]
    assert all(sha(p)==h for p,h in inputs.items())
    bundle_text='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'+''.join('`include "'+str(p)+'"\n' for p in [*paths,*models])
    started=time.monotonic();lock=threading.RLock();stopped=False
    record=dict(state='starting',supervisor_pid=os.getpid(),source_sha256=inputs,runs=[],scope=__doc__,
        current_mapped_candidate_verified=False,full_model_verified=False,full_paper_results_matched=False)
    def save(**changes):
        with lock:
            record.update(changes,elapsed_seconds=time.monotonic()-started)
            temp=result.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(result)
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def memory():
        available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
        anonymous=int(dict(l.split() for l in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3 and not stopped,'Tail simulation resource/stop guard'
        return available,anonymous
    assert memory()[0]>12*1024**3;save()
    def run(tokens):
        work=directory/str(tokens);work.mkdir();bundle=work/'bundle.sv';bundle.write_text(bundle_text)
        log=directory/(str(tokens)+'.log');child=None;began=time.monotonic()
        entry=dict(tokens=tokens,state='starting')
        with lock:record['runs'].append(entry);save()
        try:
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
                '-top','tri_oracle_batched365_tb','-top','tri_oracle_batch357_hierarchy',
                '-defparam',f'tri_oracle_batched365_tb.TOKENS={tokens}',
                '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),
                '-history_file',str(work/'history'),str(bundle),'+FIXTURE='+str(fixture)]
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid,command=command);save()
                last=0
                while child.poll() is None:
                    available,anonymous=memory();assert time.monotonic()-began<600,'Tail simulation deadline'
                    if time.monotonic()-last>5:
                        with lock:entry.update(elapsed_seconds=time.monotonic()-began,host_available_bytes=available,main_anonymous_bytes=anonymous);save()
                        last=time.monotonic()
                    time.sleep(.5)
            text=log.read_text();marker=f'BATCH365_PASS tokens={tokens} hidden=2048 rows=160 exact_outputs={tokens*160} commands={tokens*64} stalls='
            passed=child.returncode==0 and marker in text and 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in text
            with lock:entry.update(state='passed' if passed else 'failed',native_exit_status=child.returncode,log=str(log),log_sha256=sha(log),elapsed_seconds=time.monotonic()-began);save()
            assert passed,'Native tail failed: '+str(log)
            assert int(re.search(re.escape(marker)+r'(\d+)',text)[1])>0
        finally:
            if child is not None:terminate_process_group(child)
            shutil.rmtree(work)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,[1,3,8]))
        assert all(sha(p)==h for p,h in inputs.items())
        save(state='decode_tail_and_nonpower_batches_source_passed',token_counts=[1,3,8],exact_output_comparisons=1920,temporary_builds_removed=True)
        print('BATCH365_TAILS_VERIFIED',flush=True)
    except BaseException as error:save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
