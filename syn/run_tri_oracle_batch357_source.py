"""Bound resident batched-projection checks without advancing physical design.

Twenty cores, sixteen tokens,2048 input features,160 output rows, two resident
weight tiles. Inferred Icarus and actual600-model Xcelium arithmetic checks,
three exact scalar mutations and the sequencer error/recovery boundary test.
Operand transfer, complete model scheduling and paper performance remain open.
"""
from concurrent.futures import ThreadPoolExecutor
import datetime
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
    result=root/'records/batch357_source_result.json';assert not result.exists()
    directory=root/'.cache/physical/simulation/batch357';assert not directory.exists();directory.mkdir()
    source=json.loads((root/'records/real190_full_result.json').read_text())
    names=['tri_oracle_batched_projection356','tri_oracle_batched356_tb','tri_oracle_batched356_boundary_tb',
           'tri_oracle_batch357_hierarchy','tri_oracle_pe_array','tri_oracle_word_bank',
           'tri_oracle_memory_compute','tri_oracle_compute_cluster','tri_oracle_compute_fabric',
           'tri_oracle_sram_memory_compute','tri_oracle_sram_compute_cluster']
    paths=[root/'verilog'/(name+'.sv') for name in names]
    models=[]
    for kind in ['ts5n28hpcpsvta32x128m2fw','ts5n28hpcpsvta512x64m4f','ts6n28hpcpsvta16x128m2f']:
        candidates={str(Path(p).resolve()):digest for p,digest in source['source_sha256'].items()
                    if '/VERILOG/' in p and Path(p).name.startswith(kind) and p.endswith('.v')}
        assert len(candidates)==1
        path,digest=next(iter(candidates.items()));assert sha(path)==digest;models.append(Path(path))
    inputs={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',*paths,*models]}
    for path in [root/'verilog/tri_oracle_pe_array.sv',root/'verilog/tri_oracle_sram_memory_compute.sv',root/'verilog/tri_oracle_sram_compute_cluster.sv']:
        assert sha(path)==source['source_sha256'][str(path)],'Production arithmetic changed'
    controller=root/'verilog/tri_oracle_batched_projection356.sv'
    inferred=[root/'verilog'/(name+'.sv') for name in ['tri_oracle_batched_projection356','tri_oracle_pe_array',
        'tri_oracle_word_bank','tri_oracle_memory_compute','tri_oracle_compute_cluster','tri_oracle_compute_fabric','tri_oracle_batched356_tb']]
    native=[root/'verilog'/(name+'.sv') for name in ['tri_oracle_pe_array','tri_oracle_sram_memory_compute',
        'tri_oracle_sram_compute_cluster','tri_oracle_compute_fabric','tri_oracle_batched_projection356',
        'tri_oracle_batched356_tb','tri_oracle_batch357_hierarchy']]
    template='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'+''.join('`include "'+str(p)+'"\n' for p in [*native,*models])
    started=time.monotonic();lock=threading.RLock();stopped=False
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=inputs,runs=[],
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),host_reserve_bytes=6*1024**3,
        main_anonymous_limit_bytes=18*1024**3,whole_model_verified=False,current_mapped_candidate_verified=False,
        physical_advancement_authorized=False,full_paper_results_matched=False,scope=__doc__)
    def save(**changes):
        with lock:
            record.update(changes,elapsed_seconds=time.monotonic()-started)
            p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def memory():
        available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
        anonymous=int(dict(l.split() for l in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3,'Batch source memory guard'
        assert not stopped and time.monotonic()-started<3600,'Batch source stop/wall guard'
        return available,anonymous
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    assert memory()[0]>12*1024**3
    save()

    def execute(label,command,cwd,seconds=900):
        log=directory/(label+'.log');entry=dict(label=label,command=command,state='starting');child=None;began=time.monotonic()
        with lock:record['runs'].append(entry);save()
        try:
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,stdout=stream,
                    stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid);save()
                last=0
                while child.poll() is None:
                    available,anonymous=memory();assert time.monotonic()-began<seconds,'Batch case deadline'
                    if time.monotonic()-last>5:
                        with lock:entry.update(elapsed_seconds=time.monotonic()-began,host_available_bytes=available,main_anonymous_bytes=anonymous);save()
                        last=time.monotonic()
                    time.sleep(.5)
            with lock:entry.update(state='terminal',native_exit_status=child.returncode,log=str(log),log_sha256=sha(log),elapsed_seconds=time.monotonic()-began);save()
            return entry,log.read_text()
        except BaseException as error:
            with lock:entry.update(state='failed',exception=repr(error));save()
            raise
        finally:
            if child is not None:terminate_process_group(child)

    def icarus():
        work=directory/'icarus';work.mkdir()
        try:
            for top,files in [('tri_oracle_batched356_boundary_tb',[controller,root/'verilog/tri_oracle_batched356_boundary_tb.sv']),
                              ('tri_oracle_batched356_tb',inferred)]:
                binary=work/(top+'.vvp')
                entry,text=execute('icarus_compile_'+top,['/usr/local/bin/iverilog','-g2012','-s',top,'-o',str(binary),*[str(p) for p in files]],work,60)
                assert entry['native_exit_status']==0,'Icarus compile failed'
                entry,text=execute('icarus_run_'+top,['/usr/local/bin/vvp',str(binary)],work)
                marker='BATCH356_BOUNDARY_PASS' if 'boundary' in top else 'BATCH356_PASS tokens=16 hidden=2048 rows=160 exact_outputs=2560 commands=1024 weight_tile_token_reuse=16'
                assert entry['native_exit_status']==0 and marker in text,'Icarus functional check failed'
                with lock:entry['state']='functional_passed';save()
                binary.unlink()
        finally:shutil.rmtree(work)

    mutations={
        'wrong_token_activation':("27'(issue_token)*27'(activation_stride)","27'd0"),
        'lost_accumulation':('backend_cmd_accumulate=accumulate || issue_strip!=0;','backend_cmd_accumulate=0;'),
        'wrong_token_mask':("backend_cmd_mask=mask_base+5'(issue_token);",'backend_cmd_mask=mask_base;')}

    def counterfactual(kind):
        for token in range(16):
            for row in range(160):
                keep=(token*3+row)%5!=0
                def dot(t,features):return sum(((t*11+f*5)%17-8)*((row*7+f*3)%15-7) for f in features)
                expected=dot(token,range(2048)) if keep else 0
                if kind=='wrong_token_activation':observed=dot(0,range(2048)) if keep else 0
                elif kind=='wrong_token_mask':observed=dot(token,range(2048)) if row%5!=0 else 0
                else:observed=dot(token,[part*512+504+lane for part in range(4) for lane in range(8)]) if keep else 0
                if observed!=expected:return token,row,observed,expected
        raise AssertionError('Mutation has no informative output')

    def xcelium(kind):
        work=directory/('xcelium_'+kind);work.mkdir()
        try:
            bundle_text=template;wanted=None
            if kind!='positive':
                before,after=mutations[kind];original=controller.read_text();assert original.count(before)==1
                changed=original.replace(before,after);mutant=work/'mutant.sv';mutant.write_text(changed)
                bundle_text=bundle_text.replace(str(controller),str(mutant));wanted=counterfactual(kind)
                with lock:record.setdefault('scalar_counterfactuals',{})[kind]=wanted;save()
            bundle=work/'bundle.sv';bundle.write_text(bundle_text)
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
                '-top','tri_oracle_batched356_tb','-top','tri_oracle_batch357_hierarchy',
                '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),'-history_file',str(work/'history'),str(bundle)]
            entry,text=execute('xcelium_'+kind,command,work)
            if wanted:
                found=re.findall(r'BATCH356_INTEGER_OUTPUT token=(\d+) row=(\d+) got=(-?\d+) expected=(-?\d+)',text)
                assert entry['native_exit_status']==2 and len(found)==1 and tuple(map(int,found[0]))==wanted,'Native mutation did not reject at exact scalar word'
            else:
                assert entry['native_exit_status']==0 and 'BATCH356_PASS tokens=16 hidden=2048 rows=160 exact_outputs=2560 commands=1024 weight_tile_token_reuse=16' in text,'Native positive failed'
            assert 'BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in text
            with lock:entry['state']='exact_mutation_rejected' if wanted else 'functional_passed';save()
        finally:shutil.rmtree(work)

    try:
        save(state='native_checks_running')
        with ThreadPoolExecutor(max_workers=5) as pool:
            jobs=[pool.submit(icarus),*[pool.submit(xcelium,kind) for kind in ['positive',*mutations]]]
            for job in jobs:job.result()
        assert all(sha(p)==h for p,h in inputs.items()),'Frozen batch inputs changed'
        save(state='resident_batched_projection_source_functional_passed',
            inferred_integer_outputs=2560,compiled_memory_integer_outputs=2560,exact_native_mutations=3,
            invalid_live_context_recovery_verified=True,temporary_builds_removed=True)
        print('BATCH357_SOURCE_VERIFIED',flush=True)
    except BaseException as error:save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
