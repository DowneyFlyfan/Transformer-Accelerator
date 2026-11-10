"""Verify batched transfer ownership against native memories and trained data.

One and sixteen-token cases measure every operand read. Five three-token
controls inject response errors, early/missing LAST and invalid descriptors,
then require recovery into a complete trained transfer/arithmetic run without
external reset. This is one raw affine tile with prepared masks, not complete
feedforward, model execution, mapped hardware or paper-performance evidence.
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
    assert sys.argv[1:] in [["red"],["green"]]
    mode=sys.argv[1]
    result=root/f'records/batch372_{mode}_result.json'
    directory=root/f'.cache/physical/simulation/batch372_{mode}'
    assert not result.exists() and not directory.exists(),'Preserve every attempt'
    prior_path=root/'records/batch359_source_result.json'
    prior=json.loads(prior_path.read_text());assert prior['state']=='trained_batched_projection_source_functional_passed'
    fixture_path=root/'records/batch358_fixture_preparation.json'
    fixture_record=json.loads(fixture_path.read_text());fixture=Path(fixture_record['fixture'])
    names=['tri_oracle_pe_array','tri_oracle_sram_memory_compute','tri_oracle_sram_compute_cluster',
           'tri_oracle_compute_fabric','tri_oracle_batched_projection356',('tri_oracle_batched_dma366' if mode=='red' else 'tri_oracle_batched_dma372'),
           'tri_oracle_batched372_tb','tri_oracle_batch357_hierarchy']
    paths=[root/'verilog'/(name+'.sv') for name in names]
    models=[Path(p) for p in prior['source_sha256'] if '/VERILOG/' in p and Path(p).suffix=='.v']
    assert len(models)==3
    identities={str(p):sha(p) for p in [Path(__file__).resolve(),root/'syn/tri_oracle_process_guard.py',
                prior_path,fixture_path,root/'records/batch366_missing_owner.json',*paths,*models]}
    identities.update(fixture_record['files_sha256'])
    for p in paths+models:
        if p.name not in ['tri_oracle_batched_dma366.sv','tri_oracle_batched_dma372.sv','tri_oracle_batched372_tb.sv']:
            assert sha(p)==prior['source_sha256'][str(p)],'Existing hardware changed'
    assert all(sha(p)==h for p,h in identities.items())
    bundle_text='`define UNIT_DELAY\n`define TRI_ORACLE_SRAM_CLUSTER_BIND_PUBLIC\n'
    if mode=='red':bundle_text+='`define BATCH372_RED_OWNER\n'
    bundle_text+=''.join('`include "'+str(p)+'"\n' for p in paths+models)
    started=time.monotonic();lock=threading.RLock();stopped=False
    record=dict(state='waiting_for_memory_admission',supervisor_pid=os.getpid(),source_sha256=identities,
        runs=[],mode=mode,scope='Internal-load-error burst ownership regression; '+__doc__,current_mapped_candidate_verified=False,
        full_model_verified=False,full_paper_results_matched=False)

    def save(**changes):
        with lock:
            record.update(changes,elapsed_seconds=time.monotonic()-started)
            temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    def stop(number,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def memory():
        available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
        anonymous=int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3 and not stopped,'Resource or stop guard'
        return available,anonymous
    save()
    while True:
        available,anonymous=memory()
        if available>12*1024**3 and anonymous<8*1024**3:break
        assert time.monotonic()-started<1800,'Admission deadline'
        time.sleep(2)
    assert all(sha(p)==h for p,h in identities.items())
    directory.mkdir();save(state='native_transfer_checks_running')

    def run(case):
        tokens,fault=case;label=f't{tokens}_f{fault}'
        work=directory/label;work.mkdir();(work/'bundle.sv').write_text(bundle_text)
        log=directory/(label+'.log');child=None;began=time.monotonic()
        entry=dict(tokens=tokens,fault=fault,state='starting')
        with lock:record['runs'].append(entry);save()
        try:
            command=['/opt/cadence/bin/xrun','-64bit','-sv','-xmerror','RECOME','-notimingchecks',
                '-top','tri_oracle_batched372_tb','-top','tri_oracle_batch357_hierarchy',
                '-defparam',f'tri_oracle_batched372_tb.TOKENS={tokens}',
                '-defparam',f'tri_oracle_batched372_tb.FAULT={fault}',
                '-xmlibdirname',str(work/'xcelium.d'),'-l',str(work/'native.log'),
                '-history_file',str(work/'history'),str(work/'bundle.sv'),'+FIXTURE='+str(fixture)]
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=work,stdin=subprocess.DEVNULL,stdout=stream,
                    stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid,command=command);save()
                while child.poll() is None:
                    memory();assert time.monotonic()-began<900,'Native simulation deadline'
                    time.sleep(.5)
            content=log.read_text()
            with lock:entry.update(native_exit_status=child.returncode,log=str(log),log_sha256=sha(log),elapsed_seconds=time.monotonic()-began);save()
            if mode=='red':
                assert child.returncode==2 and 'BATCH372_FAULT_NOT_DRAINED active=1 rsp_valid=1 accepted_beats=1' in content
                assert 'BATCH372_PASS tokens=' not in content
                with lock:entry.update(state='internal_load_error_undrained_burst_reproduced');save()
                return
            assert child.returncode==0,'Native batched transfer failed: '+str(log)
            assert content.count('BATCH357_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600')==1
            marker=re.search(r'BATCH372_PASS tokens=(\d+) hidden=2048 rows=160 exact_outputs=(\d+) requests=(\d+) activation_beats=(\d+) weight_beats=(\d+) stalls=(\d+) fault=(\d+)',content)
            assert marker,'Missing native transfer inventory'
            actual=dict(zip(['tokens','exact_outputs','requests','activation_beats','weight_beats','stalls','fault'],map(int,marker.groups())))
            assert actual['tokens']==tokens and actual['fault']==fault
            assert actual['exact_outputs']==tokens*160 and actual['activation_beats']==tokens*256 and actual['stalls']>=4
            assert actual['requests']*16==actual['activation_beats']+actual['weight_beats']
            if fault:assert f'BATCH372_FAULT_DRAINED fault={fault} ' in content
            with lock:entry.update(state='transfer_and_arithmetic_passed',inventory=actual);save()
        finally:
            if child is not None:terminate_process_group(child)
            shutil.rmtree(work)
    try:
        if mode=='red':
            run((3,6))
            assert all(sha(p)==h for p,h in identities.items())
            save(state='internal_load_error_undrained_burst_reproduced',temporary_builds_removed=True)
        else:
            red_path=root/'records/batch372_red_result.json'
            red=json.loads(red_path.read_text())
            assert red['state']=='internal_load_error_undrained_burst_reproduced'
            run((1,0))
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(run,[(16,0),*[(3,fault) for fault in range(1,7)]]))
            assert all(sha(p)==h for p,h in identities.items())
            save(state='trained_batched_operand_transfers_and_internal_fault_recovery_passed',
                 red_control_sha256=sha(red_path),exact_output_comparisons=5600,
                 fault_and_recovery_cases=6,activation_and_weight_words_read_once_verified=True,
                 original_channel_addressing_verified=True,temporary_builds_removed=True)
        print('BATCH372_'+mode.upper()+'_VERIFIED',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
