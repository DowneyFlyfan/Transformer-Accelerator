"""Verify protected-format programming on production20-core/600-memory source.

Two selected original groups and35 original output rows per token; two tokens
per layer without external reset. Prepared normalization inputs and local
number formats remain explicit. No mapped, whole-model or paper qualification.
Independent native failures must match their exact scalar counterfactual words.
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
from tri_oracle_cached_feedforward_model_validation import read_signed,scalar_outputs
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def negative_matches(log,status,frame,row,observed,expected):
    """Require the exact scalar negative result and earlier first-frame success."""
    if status!=2 or observed==expected:return False
    matches=re.findall(r'FORMAT351_INTEGER_OUTPUT frame=(\d+) row=(\d+) got=(-?\d+) expected=(-?\d+)',log)
    if len(matches)!=1 or tuple(map(int,matches[0]))!=(frame,row,observed,expected):return False
    if frame==1 and not re.search(r'FORMAT351_FRAME_PASS frame=0 outputs=35\b',log):return False
    return True


def main():
    root=Path(__file__).resolve().parents[1];os.chdir(root)
    result=root/'records/format352_source_result.json';assert not result.exists()
    folder=root/'.cache/physical/simulation/format352';assert not folder.exists();folder.mkdir()
    fixtures_path=root/'records/format350_fixture_preparation.json'
    guard_path=root/'records/format350_gpu_guard_result.json'
    fixtures=json.loads(fixtures_path.read_text());guard=json.loads(guard_path.read_text())
    assert guard['state']=='completed' and guard['native_exit_status']==0 and guard['input_drift']==[]
    assert sha(fixtures_path)==guard['summary_sha256']
    assert fixtures['state']=='all44_protected_prefix_fixtures_prepared_scalar_cuda_equal' and fixtures['fixture_count']==44
    source_path=root/'records/real190_full_result.json';source=json.loads(source_path.read_text())
    assert source['state']=='complete_archived_real_layer_source_functional_passed'
    inputs=dict(source['source_sha256'])
    inputs.update(fixtures['source_sha256'])
    for layer in fixtures['layers']:
        for fixture in layer['fixtures']:inputs.update(fixture['files_sha256'])
    bench=root/'verilog/tri_oracle_format351_feedforward_tb.sv'
    for path in [Path(__file__).resolve(),root/'syn/test_tri_oracle_format352_classification.py',
                 bench,fixtures_path,guard_path,source_path,root/'syn/tri_oracle_process_guard.py']:
        inputs[str(path)]=sha(path)
    assert all(sha(path)==digest for path,digest in inputs.items()),'Frozen source/fixture drift'
    old='`include "'+str(root/'verilog/tri_oracle_real_feedforward_frame190_tb.sv')+'"'
    assert source['compiled_bundle'].count(old)==1
    compiled=source['compiled_bundle'].replace(old,'`include "'+str(bench)+'"')
    bundle=folder/'canonical_sources.sv';bundle.write_text(compiled);inputs[str(bundle)]=sha(bundle)
    base=folder/'base';base.mkdir()
    started=time.monotonic();stop_requested=False;lock=threading.RLock()
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=inputs,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),runs=[],compiled_bundle=compiled,
        max_concurrent_jobs=4,cpu_affinity=list(os.sched_getaffinity(0)),
        host_reserve_bytes=6*1024**3,main_anonymous_limit_bytes=18*1024**3,
        whole_model_integer=False,current_mapped_candidate_verified=False,routed_timing_qualified=False,
        full_paper_results_matched=False,scope=__doc__)

    def save(**changes):
        with lock:
            record.update(changes,elapsed_seconds=time.monotonic()-started)
            temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)

    def resources():
        available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                           if line.startswith('MemAvailable:')))*1024
        anonymous=int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        assert available>6*1024**3 and anonymous<18*1024**3,'Native resource guard'
        assert not stop_requested and time.monotonic()-started<14400,'Native wall/stop guard'
        return available,anonymous

    def stop(number,frame):
        nonlocal stop_requested
        stop_requested=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    assert resources()[0]>12*1024**3,'Initial native memory headroom'
    save()

    def execute(label,command,cwd,metadata,seconds=1200):
        entry=dict(label=label,state='starting',command=command,**metadata)
        with lock:record['runs'].append(entry);save()
        log=folder/(label+'.log');began=time.monotonic();child=None
        try:
            with log.open('x') as stream:
                child=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,stdout=stream,
                    stderr=subprocess.STDOUT,start_new_session=True)
                with lock:entry.update(state='running',process_group=child.pid);save()
                last=0
                while child.poll() is None:
                    available,anonymous=resources()
                    assert time.monotonic()-began<seconds,'Native job wall guard'
                    if time.monotonic()-last>5:
                        with lock:
                            entry.update(elapsed_seconds=time.monotonic()-began,current_host_available_bytes=available,
                                         current_main_anonymous_bytes=anonymous);save()
                        last=time.monotonic()
                    time.sleep(.5)
            text=log.read_text()
            with lock:
                entry.update(state='native_terminal',native_exit_status=child.returncode,
                             elapsed_seconds=time.monotonic()-began,log=str(log),log_sha256=sha(log));save()
            return entry,text
        except BaseException as error:
            with lock:entry.update(state='failed',exception=repr(error));save()
            raise
        finally:
            if child is not None:terminate_process_group(child)

    executable='/opt/cadence/bin/xrun'
    try:
        save(state='elaborating')
        command=[executable,'-64bit','-sv','-xmerror','RECOME','-elaborate','-notimingchecks',
            '-top','tri_oracle_predicted_feedforward_frame_tb','-xmlibdirname',str(base/'xcelium.d'),
            '-l',str(base/'elaborate.log'),'-history_file',str(base/'history'),str(bundle)]
        entry,text=execute('elaborate',command,base,dict(phase='elaborate'),seconds=600)
        assert entry['native_exit_status']==0,'Native elaboration failed; inspect '+entry['log']
        entry['state']='elaboration_passed';save()
        cases=[]
        for role,key,flag in [('first','wrong_up_shift','WRONG_FIRST_UP'),
                              ('ordinary','wrong_up_shift','WRONG_SECOND_UP'),
                              ('ordinary','wrong_down_shift','WRONG_SECOND_DOWN')]:
            control=fixtures['selected_negative_controls'][role+'_'+key]
            cases.append(dict(label='negative_'+role+'_'+key,layer=control['layer'],role=role,key=key,flag=flag))
        cases.append(dict(label='negative_second_reference',layer=0,role='ordinary',key='corrupt_reference',flag='CORRUPT_SECOND_REFERENCE'))

        def run_case(case):
            layer=fixtures['layers'][case['layer']];assert layer['layer']==case['layer']
            by_role={fixture['role']:fixture for fixture in layer['fixtures']}
            work=folder/case['label'];assert not work.exists();shutil.copytree(base,work)
            try:
                command=[executable,'-64bit','-R','-notimingchecks','-xmlibdirname',str(work/'xcelium.d'),
                    '-l',str(work/'native.log'),'-history_file',str(work/'history'),
                    '+FIRST_FIXTURE='+by_role['first']['fixture'],'+ORDINARY_FIXTURE='+by_role['ordinary']['fixture']]
                counterfactual=None
                if case.get('flag'):
                    command.append('+'+case['flag']);fixture=Path(by_role[case['role']]['fixture'])
                    expected=read_signed(fixture/'expected.hex',32)
                    if case['key']=='corrupt_reference':
                        row=0;observed=expected[0];golden=expected[0]^1
                    else:
                        shifts=read_signed(fixture/'configuration.hex',32)[:3]
                        shifts[1 if case['key']=='wrong_up_shift' else 2]+=1
                        wrong=scalar_outputs(read_signed(fixture/'activation.hex',8),read_signed(fixture/'gate.hex',8),
                            read_signed(fixture/'up.hex',8),read_signed(fixture/'down.hex',8),
                            by_role[case['role']]['selected_channels'],read_signed(fixture/'skip.hex',8),shifts)
                        row=next(i for i,(a,b) in enumerate(zip(wrong,expected)) if a!=b)
                        observed,golden=wrong[row],expected[row]
                    counterfactual=dict(frame=int(case['role']=='ordinary'),row=row,observed=observed,expected=golden)
                entry,text=execute(case['label'],command,work,dict(case=case,scalar_counterfactual=counterfactual))
                if counterfactual:
                    passed=negative_matches(text,entry['native_exit_status'],**counterfactual)
                    assert passed,'Exact native counterfactual failed: '+entry['log']
                else:
                    passed=(entry['native_exit_status']==0 and
                        'FORMAT351_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in text and
                        'FORMAT351_PAIR_PASS outputs=70 frames=2 external_reset_releases=1' in text and
                        len(re.findall(r'FORMAT351_FRAME_PASS frame=[01] outputs=35\b',text))==2)
                    assert passed,'Native positive failed: '+entry['log']
                with lock:entry.update(state='negative_control_rejected' if counterfactual else 'paired_source_passed');save()
                print('FORMAT352_CASE_PASS',case['label'],round(entry['elapsed_seconds'],2),flush=True)
                return entry
            finally:
                shutil.rmtree(work)

        save(state='negative_controls_running')
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(run_case,cases))
        save(state='positive_layers_running')
        cases=[dict(label=f'layer{layer:02d}_paired',layer=layer) for layer in range(22)]
        for first in range(0,22,4):
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(run_case,cases[first:first+4]))
        assert all(sha(path)==digest for path,digest in inputs.items()),'Frozen native input drift'
        assert sum(run['state']=='paired_source_passed' for run in record['runs'])==22
        assert sum(run['state']=='negative_control_rejected' for run in record['runs'])==4
        shutil.rmtree(base)
        save(state='all22_protected_pairs_source_functional_passed',exact_integer_outputs_checked=1540,
            positive_pairs=22,negative_controls=4,actual_cores=20,actual_compiled_memories=600,temporary_snapshots_removed=True)
        print('FORMAT352_ALL22_PAIRS_PASS',flush=True)
    except BaseException as error:
        save(state='failed',exception=repr(error));raise


if __name__=='__main__':main()
