"""Native shared-fabric feedforward, including acknowledged scratch writes.

Literal mode checks complete small frames and six recovery paths. Trained mode
requires all original layer0 inputs, weights, intermediate and output rows for
sixteen tokens. Prepared masks/normalization remain external. Neither mode
establishes mapped timing, whole-model accuracy or paper performance.
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
    assert sys.argv[1:] in [['literal'],['trained']]
    mode=sys.argv[1];trained=mode=='trained'
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    output=root/f'records/batch393_{mode}_result.json';directory=root/f'.cache/physical/simulation/batch393_{mode}'
    assert not output.exists() and not directory.exists(),'Preserve each run'
    prior_path=root/'records/batch359_source_result.json';prior=json.loads(prior_path.read_text())
    paths=[root/'verilog'/(name+'.sv') for name in [
        'tri_oracle_pe_array','tri_oracle_sram_memory_compute','tri_oracle_sram_compute_cluster',
        'tri_oracle_compute_fabric','tri_oracle_batched_projection356','tri_oracle_silu_gate',
        'tri_oracle_batched_tensor390','tri_oracle_batched_nonlinear391','tri_oracle_batched_shared392',
        'tri_oracle_batched_frame393','tri_oracle_batched393_tb','tri_oracle_batch357_hierarchy']]
    models=[Path(p) for p in prior['source_sha256'] if '/VERILOG/' in p and Path(p).suffix=='.v'];assert len(models)==3
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',prior_path,
        root/'records/batch393_missing_frame.json',*paths,*models]}
    for p in paths+models:
        if str(p) in prior['source_sha256']:assert sha(p)==prior['source_sha256'][str(p)]
    fixture=None
    if trained:
        fixture_path=root/'records/batch389_fixture_preparation.json';guard_path=root/'records/batch389_gpu_guard_result.json'
        fixture=json.loads(fixture_path.read_text());guard=json.loads(guard_path.read_text())
        assert fixture['state']=='complete_trained_layer_fixture_scalar_cuda_equal'
        assert (fixture['tokens'],fixture['input_features'],fixture['intermediate_features'],fixture['output_features'])==(16,2048,5632,2048)
        assert guard['state']=='completed' and guard['native_exit_status']==0 and guard['input_drift']==[]
        assert guard['summary_sha256']==sha(fixture_path)
        inputs.update(fixture['files_sha256']);inputs[str(fixture_path)]=sha(fixture_path);inputs[str(guard_path)]=sha(guard_path)
    assert all(sha(p)==h for p,h in inputs.items())
    bundle='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'
    bundle+=''.join('`include "'+str(p)+'"\n' for p in paths+models)
    started=time.monotonic();stopped=False;lock=threading.RLock()
    record=dict(state='starting',mode=mode,supervisor_pid=os.getpid(),source_sha256=inputs,runs=[],scope=__doc__,
                current_mapped_candidate_verified=False,whole_model_verified=False,full_paper_results_matched=False)
    def save(**changes):
        with lock:
            record.update(changes,elapsed_seconds=time.monotonic()-started)
            p=output.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(output)
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def memory():
        available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
        anonymous=int(dict(l.split() for l in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3 and not stopped,'Native memory/stop guard'
        return available,anonymous
    assert memory()[0]>(14 if trained else 12)*1024**3
    directory.mkdir();save(state='native_joined_frames_running')
    def run(fault):
        work=directory/str(fault);work.mkdir();(work/'bundle.sv').write_text(bundle)
        log=directory/(str(fault)+'.log');child=None;began=time.monotonic()
        entry=dict(fault=fault,state='starting')
        with lock:record['runs'].append(entry);save()
        try:
            top='tri_oracle_batched393_tb'
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
                '-top',top,'-top','tri_oracle_batch357_hierarchy','-defparam',top+f'.FAULT={fault}',
                '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),
                '-history_file',str(work/'history'),str(work/'bundle.sv')]
            if trained:
                for key,value in [('TOKENS',16),('HIDDEN',2048),('INTERMEDIATE',5632),('OUTPUTS',2048),('TRAINED',1)]:
                    command+=['-defparam',top+f'.{key}={value}']
                command+=['+FIXTURE='+fixture['fixture']]
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stream,
                    stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid,command=command);save()
                last=0
                while child.poll() is None:
                    available,anonymous=memory()
                    assert time.monotonic()-began<(7200 if trained else 600),'Native deadline'
                    if time.monotonic()-last>10:
                        with lock:entry.update(native_elapsed_seconds=time.monotonic()-began,
                            host_available_bytes=available,anonymous_bytes=anonymous);save()
                        last=time.monotonic()
                    time.sleep(.5)
            content=log.read_text()
            with lock:entry.update(native_exit_status=child.returncode,log=str(log),log_sha256=sha(log),elapsed_seconds=time.monotonic()-began);save()
            assert child.returncode==0,'Native joined frame failed: '+str(log)
            assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600')==1
            found=re.search(r'BATCH393_PASS tokens=(\d+) hidden=(\d+) intermediate=(\d+) outputs=(\d+) exact_outputs=(\d+) intermediate_bytes=(\d+) output_packets=(\d+) read_requests=(\d+) read_bytes=(\d+) fault=(\d+) trained=(\d+)',content)
            assert found
            actual=dict(zip(['tokens','hidden','intermediate','outputs','exact_outputs','intermediate_bytes',
                'output_packets','read_requests','read_bytes','fault','trained'],map(int,found.groups())))
            n,h,d,o=(16,2048,5632,2048) if trained else (3,64,96,173)
            assert (actual['tokens'],actual['hidden'],actual['intermediate'],actual['outputs'])==(n,h,d,o)
            assert actual['exact_outputs']==n*o and actual['intermediate_bytes']==n*d
            assert actual['output_packets']==n*((o+159)//160) and actual['fault']==fault and actual['trained']==int(trained)
            gate_packets=[tuple(map(int,x)) for x in re.findall(r'BATCH393_MASK_ACCEPTED start=(\d+) count=(\d+)',content)]
            out_tiles=[tuple(map(int,x)) for x in re.findall(r'BATCH393_OUTPUT_TILE start=(\d+) count=(\d+)',content)]
            wanted_gate=[(i,min(80,d-i)) for i in range(0,d,80)];wanted_out=[(i,min(160,o-i)) for i in range(0,o,160)]
            assert gate_packets[-len(wanted_gate):]==wanted_gate and out_tiles[-len(wanted_out):]==wanted_out
            if fault:assert f'BATCH393_FAULT_DRAINED fault={fault} output_prefix_packets={3 if fault==3 else 0}' in content
            else:assert gate_packets==wanted_gate and out_tiles==wanted_out
            with lock:entry.update(state='joined_feedforward_frame_passed',inventory=actual,
                successful_gate_groups=len(wanted_gate),successful_down_groups=len(wanted_out));save()
        finally:
            if child is not None:terminate_process_group(child)
            shutil.rmtree(work)
    try:
        if trained:run(0)
        else:
            run(0)
            with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,range(1,7)))
        assert all(sha(p)==h for p,h in inputs.items())
        save(state='complete_trained_batched_feedforward_source_passed' if trained else 'literal_joined_feedforward_and_six_recoveries_passed',
             exact_output_comparisons=32768 if trained else 3633,temporary_builds_removed=True)
        print('BATCH393_'+mode.upper()+'_VERIFIED',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
