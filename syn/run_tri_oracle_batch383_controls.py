"""Verify conversion boundaries and deliberate removal of wrapper fault checks.

The production files remain immutable. Two temporary compile overlays disable
only raw-count or activation-tag validation; each must fail the queued-fault
bench at its first published output. The arithmetic-only native case checks
all64 shifts and signed extrema/ties against a separate64-bit scalar formula.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
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
    output=root/'records/batch383_controls_result.json';directory=root/'.cache/physical/simulation/batch383'
    assert not output.exists() and not directory.exists()
    prior_path=root/'records/batch380_source_result.json';prior=json.loads(prior_path.read_text())
    assert prior['state']=='trained_batched_paired_projection_and_nonlinear_source_passed'
    later_path=root/'records/batch381_source_result.json';later=json.loads(later_path.read_text())
    assert later['state']=='queued_raw_and_activation_fault_drain_and_recovery_passed'
    paths=[root/'verilog'/(name+'.sv') for name in [
        'tri_oracle_pe_array','tri_oracle_sram_memory_compute','tri_oracle_sram_compute_cluster',
        'tri_oracle_compute_fabric','tri_oracle_batched_projection356','tri_oracle_batched_paired379',
        'tri_oracle_batched_gated380','tri_oracle_silu_gate','tri_oracle_batched381_tb',
        'tri_oracle_batched382_quant_tb','tri_oracle_batch357_hierarchy']]
    models=[Path(p) for p in prior['source_sha256'] if '/VERILOG/' in p and Path(p).suffix=='.v']
    assert len(models)==3
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',prior_path,later_path,*paths,*models]}
    for p in paths+models:
        for record in [prior,later]:
            if str(p) in record['source_sha256']:assert sha(p)==record['source_sha256'][str(p)]
    started=time.monotonic();lock=threading.RLock();stopped=False
    record=dict(state='native_controls_running',supervisor_pid=os.getpid(),source_sha256=inputs,runs=[],
                scope=__doc__,current_mapped_candidate_verified=False,full_paper_results_matched=False)
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
        assert available>6*1024**3 and anonymous<18*1024**3 and not stopped
    memory();directory.mkdir();save()
    original=(root/'verilog/tri_oracle_batched_gated380.sv').read_text()
    def run(label):
        work=directory/label;work.mkdir();log=directory/(label+'.log');child=None;began=time.monotonic()
        entry=dict(label=label,state='starting')
        with lock:record['runs'].append(entry);save()
        try:
            compile_paths=list(paths)
            if label!='quantization':
                if label=='raw_count':
                    old='raw_fault=projection_tag!=tag || projection_count!=count || projection_channels!=channels ||\n      projection_token!=4\'(completed_tokens) || projection_last!=(completed_tokens+5\'d1==tokens) || completed_tokens>=tokens;'
                    changed=original.replace(old,"raw_fault=1'b0;")
                else:
                    old="activation_fault=activation_valid && (activation_tag!=16'(completed) || completed>=count);"
                    changed=original.replace(old,"activation_fault=1'b0;")
                assert original.count(old)==1 and changed!=original
                overlay=work/'controller.sv';overlay.write_text(changed)
                compile_paths=[overlay if p.name=='tri_oracle_batched_gated380.sv' else p for p in compile_paths]
                entry['compile_overlay_sha256']=sha(overlay)
                entry['one_replacement']={'before':old,'after':"raw_fault=1'b0;" if label=='raw_count' else "activation_fault=1'b0;"}
            bundle='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'
            bundle+=''.join('`include "'+str(p)+'"\n' for p in compile_paths+models)
            (work/'bundle.sv').write_text(bundle)
            top='tri_oracle_batched382_quant_tb' if label=='quantization' else 'tri_oracle_batched381_tb'
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
                '-top',top,'-top','tri_oracle_batch357_hierarchy',
                '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),
                '-history_file',str(work/'history'),str(work/'bundle.sv')]
            if label!='quantization':command+=['-defparam',top+'.TOKENS=3','-defparam',top+'.CASE='+('4' if label=='raw_count' else '5'),
                '+FIXTURE='+str(root/'.cache/model_reference/batch379')]
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stream,
                    stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid,command=command);save()
                while child.poll() is None:
                    memory();assert time.monotonic()-began<300;time.sleep(.5)
            content=log.read_text()
            with lock:entry.update(native_exit_status=child.returncode,log=str(log),log_sha256=sha(log),elapsed_seconds=time.monotonic()-began);save()
            assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            if label=='quantization':
                assert child.returncode==0 and 'BATCH382_QUANT_PASS shifts=64 exact_comparisons=2324 signed_minima_rounding_ties_saturation=1' in content
            else:
                assert child.returncode==2 and 'BATCH381_OUTPUT_METADATA' in content and 'BATCH381_PASS tokens=' not in content
            with lock:entry['state']='passed' if label=='quantization' else 'omitted_fault_check_rejected';save()
        finally:
            if child is not None:terminate_process_group(child)
            shutil.rmtree(work)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,['quantization','raw_count','activation_tag']))
        assert all(sha(p)==h for p,h in inputs.items())
        save(state='all_shift_boundaries_and_omitted_wrapper_checks_verified',
             quantization_comparisons=2324,native_fault_check_counterfactuals=2,temporary_builds_removed=True)
        print('BATCH383_CONTROLS_VERIFIED',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
