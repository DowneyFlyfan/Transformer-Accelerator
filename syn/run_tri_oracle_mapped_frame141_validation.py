"""Simulate the full mapped parent with the qualified original routed core netlist."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from test_tri_oracle_sram_memory_compute import models
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def memory():
    available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
    anon=int(dict(x.split() for x in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available,anon


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',required=True)
    parser.add_argument('--seconds',type=int,default=14400)
    parser.add_argument('--workers',type=int,default=8,choices=[1,4,8])
    parser.add_argument('--negative-reference',action='store_true')
    args=parser.parse_args()
    assert args.label and all(c.isalnum() or c in '_-' for c in args.label)
    assert 300<=args.seconds<=28800
    root=Path(__file__).resolve().parents[1]
    result=root/'records'/(args.label+'_result.json');assert not result.exists()
    started=time.monotonic();child=None;pause=None;folder_path=None
    record=dict(state='preparing',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        supervisor_pid=os.getpid(),requested_simulation_workers=args.workers,negative_reference=args.negative_reference,
        full_paper_results_matched=False,routed_timing_qualified=False,
        scope='Full standard-cell mapped prepared prediction/FFN parent and20 qualified original core44 routed netlists,600 compiled memory models. Same12-case analytic saturated fixture. Sequential UDP nonblocking scheduling; no delay annotation or paper-performance claim.')
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        temp=result.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(result)
    save()
    try:
        # Serialize heavy compilation behind the native floorplan import.
        while True:
            assert time.monotonic()-started<14400,'Mapping/import prerequisite wait expired'
            ready=True
            for label,state in [('frame139_synthesis','native_parent_mapping_completed_pending_report_review'),('frame140_import','native_parent_macro_import_completed_pending_report_review')]:
                p=root/'records'/(label+'_result.json')
                if not p.exists():ready=False;continue
                d=json.loads(p.read_text());assert d['state']!='failed',label+' prerequisite failed'
                if d['state']!=state:ready=False
            if ready:break
            save(state='waiting_for_native_parent_mapping_and_import');time.sleep(2)
        mapping=root/'records/frame139_synthesis_result.json';mapped=json.loads(mapping.read_text())
        assert all(sha(p)==h for p,h in mapped['source_sha256'].items())
        parent=Path(mapped['output_directory'])/'netlist.v'
        assert sha(parent)==mapped['output_netlist_sha256']
        core=root/'.cache/physical/pnr/tri_oracle_sram_memory_compute/qualification_typical_repair_44/routed_netlist.v'
        accepted_path=root/'records/predicted_fabric_placement79_result.json'
        accepted=json.loads(accepted_path.read_text());assert sha(core)==accepted['source_sha256'][str(core)]
        positive_path=root/'records/staged119_121_functional_qualification.json'
        positive=json.loads(positive_path.read_text());assert positive['state']=='fully_staged_prepared_frame_actual_20core_functional_qualified'
        assert all(sha(p)==h for p,h in positive['current_source_sha256'].items())
        if args.workers==8:
            p=root/'records/down128_multicore_result.json';canary=json.loads(p.read_text())
            assert canary['state']=='staged_down_mapped_eight_worker_functional_passed' and canary['cases_seen']==34
            assert all(sha(p)==h for p,h in canary['source_sha256'].items())
        bench=root/'verilog/tri_oracle_predicted_feedforward_frame_tb.sv'
        text=parent.read_text()
        assert not re.search(r'^\s*module\s+tri_oracle_sram_memory_compute\b',text,re.M),'Mapped parent embeds an unexpected core body'
        clusters=sorted(set(re.findall(r'^\s*module\s+(tri_oracle_sram_compute_cluster(?:_[A-Za-z0-9_$]+)?)\s*\(',text,re.M)))
        assert clusters,'Mapped cluster module declarations not found'
        observer='bind tri_oracle_sram_compute_cluster tri_oracle_joined_instance_count #(.KIND(1)) count_joined_cluster ();'
        stimulus=bench.read_text();assert stimulus.count(observer)==1
        stimulus=stimulus.replace(observer,'\n'.join('bind '+name+' tri_oracle_joined_instance_count #(.KIND(1)) count_joined_cluster ();' for name in clusters))
        vendor=[Path(p) for p in models('tt1v25c')]
        bank_path=root/'records/sram_activation_cache_bank_views.json'
        metadata=json.loads(bank_path.read_text())['banks']['metadata'];model=Path(metadata['models']['tt1v25c'])
        assert sha(model)==metadata['sha256'][str(model)];vendor.append(model)
        standard=root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140.v'
        executable=Path('/opt/cadence/bin/xrun')
        inputs=[Path(__file__).resolve(),executable,parent,core,standard,bench,*vendor,mapping,accepted_path,positive_path,bank_path,
            root/'records/frame140_import_result.json',root/'syn/test_tri_oracle_sram_memory_compute.py',
            root/'syn/tri_oracle_memory_pressure_guard.py',root/'syn/tri_oracle_process_guard.py']
        if args.workers==8:inputs.append(root/'records/down128_multicore_result.json')
        identities={str(p):sha(p) for p in dict.fromkeys(inputs)}
        while True:
            available,anon=memory()
            if available>14*1024**3 and anon<3*1024**3:break
            assert time.monotonic()-started<18000,'Mapped simulation memory-headroom wait expired'
            save(state='waiting_for_mapped_simulation_memory_headroom');time.sleep(2)
        with tempfile.TemporaryDirectory(prefix=args.label+'_',dir=root/'.cache/physical') as folder:
            folder_path=Path(folder);private_bench=folder_path/'mapped_observer_bench.sv';private_bench.write_text(stimulus)
            bundle=folder_path/'canonical_sources.sv'
            compiled='`define UNIT_DELAY\n'+''.join('`include "'+str(p)+'"\n' for p in [standard,core,parent,*vendor,private_bench])
            bundle.write_text(compiled)
            log=root/'records'/(args.label+'_native.log');assert not log.exists()
            command=[str(executable),'-64bit','-sv','-xmerror','RECOME','-sequdp_nba_delay',
                '-top','tri_oracle_predicted_feedforward_frame_tb','-xmlibdirname',str(folder_path/'xcelium.d'),
                '-l',str(folder_path/'xrun.log'),'-history_file',str(folder_path/'history'),str(bundle)]
            if args.workers!=1:command[1:1]=['-mce','-mce_sim_thread_count',str(args.workers),'-mce_build_thread_count',str(args.workers)]
            if args.negative_reference:command.append('+CORRUPT_JOINED_REFERENCE')
            native_started=time.monotonic()
            with log.open('w') as output:
                child=subprocess.Popen(command,cwd=folder_path,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                pause=OwnedProcessPause(child,str(folder_path/'xrun.log'))
                policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=16*1024**3)
                save(state='native_full_mapped_frame_simulation_running',source_sha256=identities,native_process_group=child.pid,command=command,
                    cluster_bind_targets=clusters,observer_only_changes={observer:stimulus.split('bind tri_oracle_sram_memory_compute',1)[-1]},
                    compiled_bundle=compiled,compiled_bundle_sha256=sha(bundle),compiled_bench_sha256=sha(private_bench))
                last_save=0
                try:
                    while child.poll() is None:
                        assert time.monotonic()-native_started<args.seconds,'Full mapped simulation wall budget'
                        available,anon=memory();action=policy.observe(available,anon,time.monotonic())
                        if action in ['pause','resume']:
                            groups=pause.pause() if action=='pause' else pause.resume()
                            save(memory_pressure_events=record.get('memory_pressure_events',[])+[dict(action=action,groups=groups,available=available,anon=anon)])
                        if time.monotonic()-last_save>5:
                            content=log.read_text(errors='replace')
                            save(native_elapsed_seconds=time.monotonic()-native_started,cases_seen=content.count('JOINED_CASE_PASS '),current_host_available_bytes=available,current_combined_anonymous_bytes=anon)
                            last_save=time.monotonic()
                        time.sleep(.2)
                finally:
                    pause.resume();terminate_process_group(child,log_argument=str(folder_path/'xrun.log'))
            content=log.read_text(errors='replace')
            assert all(sha(p)==h for p,h in identities.items()),'Changed mapped simulation input'
            assert 'JOINED_ACTUAL_HIERARCHY cores=20 clusters=5 compiled_memories=600' in content
            if args.negative_reference:
                assert child.returncode!=0 and 'JOINED_HIDDEN_SUM' in content and 'JOINED_PASS cases=' not in content
                save(state='expected_wrong_mapped_reference_rejected',native_exit_status=child.returncode,native_console_sha256=sha(log));return
            assert child.returncode==0 and content.count('JOINED_CASE_PASS ')==12,content[-4000:]
            match=re.search(r'JOINED_PASS cases=12 hidden_outputs=4420 success_stalls=(\d+) error_stalls=(\d+)',content)
            assert match and int(match.group(1))>0 and int(match.group(2))>=9
            save(state='full_mapped_frame_functional_passed',cases_seen=12,hidden_outputs_checked=4420,
                actual_cores=20,actual_clusters=5,actual_compiled_memories=600,
                native_exit_status=0,native_console_sha256=sha(log),native_elapsed_seconds=time.monotonic()-native_started)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=str(folder_path/'xrun.log'))
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise
    finally:
        if folder_path is not None:save(temporary_build_removed=not folder_path.exists())


if __name__=='__main__':main()
