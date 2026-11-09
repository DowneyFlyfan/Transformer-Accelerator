"""Prepare unique parent definitions; cold-verify all original core models."""
import datetime
import filecmp
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_frame202_preservation import read_ready_prerequisite,require_reset_topology
from tri_oracle_parent_candidate_acceptance import process_identity
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands

from tri_oracle_native_diagnostics import require_clean_native

TRAINED_STATE='complete_archived_real_layer_source_functional_passed'


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/unique235_parent_result.json'
    out=root/'.cache/physical/pnr/tri_oracle_predicted_feedforward_unique235'
    assert not result.exists() and not out.exists()
    placement_path=root/'records/frame202_placement_result.json'
    placement=json.loads(placement_path.read_text())
    assert placement['state']=='full_core_geometric_placement_and_corner_diagnostics_completed'
    assert placement['native_exit_status']==0 and placement['all_original_core_cells_preserved']==1889420
    assert placement['compiled_memory_macros']==600 and placement['all3_original_corners_diagnosed']
    full_path=root/'records/sram_core_hierarchy68_full_control_validation.json'
    assert sha(full_path)==placement['source_sha256'][str(full_path)]
    full=json.loads(full_path.read_text())
    models=root/'.cache/physical/pnr/tri_oracle_sram_memory_compute/hierarchy_full_control_68'
    model_fingerprint=full['output_artifact_fingerprint']
    dependencies={models/'ilm':{'type':'directory','files':{n[4:]:v for n,v in model_fingerprint['files'].items() if n.startswith('ilm/')}}}
    canary_path=root/'records/unique215_canary_complete_result.json'
    canary=json.loads(canary_path.read_text())
    assert canary['state']=='native_uniquification_preserved_graph_and_wiring_constant_faults_rejected'
    assert canary['temporary_build_removed'] is True and canary['constant_driver_swap_rejected'] is True
    control_path=root/'records/unique216_constraint_control.json'
    control=json.loads(control_path.read_text())
    assert control['state']=='native_constraint_export_preserved_and_nonperiod_drift_rejected'
    assert control['temporary_build_removed'] is True and control['changed_input_transition_rejected'] is True
    preservation_path=root/'records/preservation234_native_control.json'
    preservation_control=json.loads(preservation_path.read_text())
    assert preservation_control['state']=='hierarchical_preservation_loss_rejected_before_reference_reload'
    assert preservation_control['temporary_build_removed'] is True and preservation_control['hierarchical_flag_loss_rejected'] is True
    assert preservation_control['selector_negative_controls']==5
    physical_path=root/'records/preservation232_diagnosis_result.json'
    physical=json.loads(physical_path.read_text())
    assert physical['state']=='full_model_preservation_properties_collected' and not physical['native_error_diagnostics']
    assert physical['source_database_unchanged'] is True
    entry=root/'syn/tri_oracle_unique_frame235.tcl'
    names=['tri_oracle_native_diagnostics.py','tri_oracle_preservation233.tcl','run_tri_oracle_preservation234_control.py','run_tri_oracle_unique_frame235.py','tri_oracle_unique_frame235.tcl','tri_oracle_unique215_snapshot.tcl',
           'run_tri_oracle_unique215_canary.py','tri_oracle_row_guard173_variants.py','run_tri_oracle_row_guard175_synthesis.py',
           'tri_oracle_artifact_fingerprint.py','tri_oracle_hierarchy_fingerprint.py','tri_oracle_core_preservation.py',
           'tri_oracle_frame202_preservation.py','tri_oracle_parent_candidate_acceptance.py',
           'tri_oracle_memory_pressure_guard.py','tri_oracle_process_guard.py',
           'tri_oracle_registered_reset_trace102.tcl','tri_oracle_check_registered_reset_fabric.tcl',
           'tri_oracle_mapped_restore199.py','tri_oracle_row_guard175_checkpoint.py','run_tri_oracle_unique216_constraint_control.py']
    identities={}
    for mapping in [placement['source_sha256'],placement['native_evidence_sha256'],canary['source_sha256'],canary['native_evidence_sha256'],control['source_sha256'],control['native_evidence_sha256'],preservation_control['source_sha256'],preservation_control['native_evidence_sha256'],physical['source_sha256'],physical['native_evidence_sha256']]:
        for name,digest in mapping.items():
            assert name not in identities or identities[name]==digest,'Conflicting qualified input identity '+name
            identities[name]=digest
    for p in [placement_path,full_path,canary_path,control_path,preservation_path,physical_path,*[root/'syn'/n for n in names],
              root/'records/registered_reset34_sequential_masters.json',Path('/opt/cadence/bin/innovus')]:
        digest=sha(p);assert str(p) not in identities or identities[str(p)]==digest
        identities[str(p)]=digest
    assert identities[str(root/'syn/tri_oracle_unique215_snapshot.tcl')]==canary['source_sha256'][str(root/'syn/tri_oracle_unique215_snapshot.tcl')]
    checkpoint=Path(placement['output_database'])
    baseline=Path(placement['output_directory'])
    started=time.monotonic();child=pause=None;stopped=False;log_token=None
    evidence={};unique_checkpoint=None;unique_fingerprint=None
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),native_workers=8,
        anonymous_limit_bytes=16*1024**3,host_reserve_bytes=5*1024**3,
        parent_timing_closed=False,parent_routing_completed=False,full_paper_results_matched=False,
        scope='Unique module definitions on the actual placed prepared parent. Exact parent cell identities/geometry, top ports, direct pin constants and full driver/load graph must remain. Cold restore must preserve all1889420 original core cells and600 memories. Electrical/timing optimization remains separate.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def immutable():
        assert all(sha(p)==h for p,h in identities.items()),'Unique preparation input changed'
        assert artifact_fingerprint(models)==model_fingerprint
        assert hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies)==placement['output_database_fingerprint']
        assert all(sha(p)==h for p,h in evidence.items()),'Unique preparation evidence changed'
        if unique_checkpoint is not None:
            assert hierarchy_fingerprint(unique_checkpoint,directory_dependencies=dependencies)==unique_fingerprint
    def native(directory,mode,input_database,marker):
        nonlocal child,pause,log_token
        directory.mkdir();console=directory/'console.log';log_token=str(directory/'native')
        command=['innovus','-stylus','-no_gui','-batch','-log',log_token,'-files',str(entry)]
        began=time.monotonic()
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                start_new_session=True,env=dict(os.environ,TRI235_OUT=str(directory),TRI235_INPUT=str(input_database),
                    TRI235_MODE=mode,TRI235_WARM=str(out/'warm'),TRI235_PREFIXES=str(baseline/'core_prefixes.txt')))
            pause=OwnedProcessPause(child,log_token)
            policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=16*1024**3)
            save(state='native_parent_uniquification_running' if mode=='warm' else 'native_unique_parent_cold_validation_running',
                 native_process_group=child.pid,command=command,phase=mode)
            last=0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-began<3600,'Unique preparation wall/stop guard'
                    available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                    if action=='pause':pause.pause()
                    elif action=='resume':pause.resume()
                    record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                    if time.monotonic()-last>5:
                        save(native_elapsed_seconds=time.monotonic()-began,current_host_available_bytes=available,
                             current_combined_anonymous_bytes=anonymous);last=time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume();terminate_process_group(child,log_argument=log_token)
        text=console.read_text(errors='replace');require_clean_native(text)
        assert child.returncode==0 and '\n'+marker+'\n' in text,str(console)
        files=[p for p in directory.iterdir() if p.is_file() and (p.suffix in ['.tsv','.sorted','.rpt','.sdc'] or p.name=='console.log')]
        if mode=='warm':files += [directory/'unique_parent.v',directory/'unique_parent.def']
        for p in files:evidence[str(p)]=sha(p)
        return dict(native_exit_status=0,elapsed_seconds=time.monotonic()-began,console_sha256=sha(console))
    save()
    try:
        immutable()
        # Treat published success without cleanup as still pending. The existing
        # owner-transition checker then re-reads an atomic terminal update.
        training_path=root/'records/real190_full_result.json';owners={}
        def read_training():
            data=json.loads(training_path.read_text())
            if data['state']==TRAINED_STATE and data.get('temporary_build_removed') is not True:
                data['state']='completed_native_training_cleanup_pending'
            return data
        while True:
            trained=read_ready_prerequisite(read_training,process_identity,owners,'real190_full',TRAINED_STATE)
            if trained is not None:break
            assert not stopped and time.monotonic()-started<21600,'Trained simulation serialization deadline'
            save(state='waiting_for_actual_trained_layer_simulation_completion');time.sleep(2)
        assert trained['exact_integer_outputs_checked']==2048 and trained['actual_cores']==20 and trained['actual_compiled_memories']==600
        assert trained['groups_sent']==176 and trained['strips_sent']==45056
        identities[str(training_path)]=sha(training_path)
        for p,h in trained['source_sha256'].items():
            assert sha(p)==h and (p not in identities or identities[p]==h)
            identities[p]=h
        training_log=root/'records/real190_full_native.log'
        assert sha(training_log)==trained['native_console_sha256'];identities[str(training_log)]=sha(training_log)
        immutable()
        while True:
            available,anonymous=memory()
            if available>18*1024**3 and anonymous<1024**3:break
            assert not stopped and time.monotonic()-started<25200,'Unique preparation headroom deadline'
            save(state='waiting_for_serial_physical_headroom');time.sleep(2)
        assert shutil.disk_usage(root/'.cache').free>12*1024**3
        out.mkdir();revision=out/'input_revision.json'
        revision.write_text(json.dumps(dict(source_sha256=identities,input_database_fingerprint=placement['output_database_fingerprint']),indent=2)+'\n')
        identities[str(revision)]=sha(revision);immutable();save(source_sha256=identities,output_directory=str(out))
        warm=out/'warm';warm_run=native(warm,'warm',checkpoint,'TRI_ORACLE_FRAME235_UNIQUE_PARENT_SAVED')
        status=dict(line.split('\t') for line in (warm/'unique_status.tsv').read_text().splitlines())
        assert status=={'unique_before':'0','unique_after':'1','parent_cells':'673622'}
        for kind in ['cells','ports','nets','pins']:
            assert filecmp.cmp(warm/f'before_{kind}.tsv.sorted',warm/f'after_{kind}.tsv.sorted',shallow=False)
        for view in ['setup_slow','setup_typ','hold_fast']:
            assert constraints_equivalent(commands(warm/f'before_{view}.sdc'),commands(warm/f'after_{view}.sdc')),'Native constraints changed on uniquification '+view
        reset=require_reset_topology(baseline/'registered_reset_roots.tsv',warm/'registered_reset_roots.tsv')
        placement_text=(warm/'placement.rpt').read_text()
        assert 'Finished check_place' in placement_text and re.search(r'Unplaced\s*=\s*0\b',placement_text)
        assert not re.search(r'\b(overlap|violation|illegal|warning|error)s?\b',placement_text,re.I)
        unique_checkpoint=warm/'unique.db'
        unique_fingerprint=hierarchy_fingerprint(unique_checkpoint,directory_dependencies=dependencies)
        immutable();save(state='unique_parent_saved_cold_validation_pending',warm_native=warm_run,
            output_database=str(unique_checkpoint),output_database_fingerprint=unique_fingerprint,native_evidence_sha256=evidence)
        cold=out/'cold';cold_run=native(cold,'cold',unique_checkpoint,'TRI_ORACLE_FRAME235_UNIQUE_PARENT_COLD_VERIFIED')
        for kind in ['cells','ports','nets','pins']:
            assert filecmp.cmp(warm/f'before_{kind}.tsv.sorted',cold/f'cold_{kind}.tsv.sorted',shallow=False)
        for view in ['setup_slow','setup_typ','hold_fast']:
            assert constraints_equivalent(commands(warm/f'before_{view}.sdc'),commands(cold/f'cold_{view}.sdc')),'Native constraints changed on cold restore '+view
        source_sdc=root/'.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc'
        expected_preservation=sum(line.strip().startswith('set_dont_touch ') for line in source_sdc.read_text().splitlines())
        ledgers=[]
        for directory,tag in [(warm,'before'),(warm,'after'),(cold,'cold'),(cold,'expected')]:
            rows=[line.split('\t') for line in (directory/f'{tag}_preservation.tsv').read_text().splitlines()[1:]]
            assert len(rows)==expected_preservation==86 and len({row[0] for row in rows})==86
            assert all(len(row)==3 and row[0]==row[1] and row[2] in ['true','1'] for row in rows)
            ledgers.append(rows)
        assert all(rows==ledgers[0] for rows in ledgers),'Original preservation properties differ across native stages'
        source_counts={command:sum(line.strip().startswith(command+' ') for line in source_sdc.read_text().splitlines())
            for command in ['set_input_delay','set_output_delay','set_input_transition','set_load']}
        for view in ['setup_slow','setup_typ','hold_fast']:
            expected=commands(cold/f'expected_{view}.sdc')
            assert expected and any(line.startswith('create_clock ') for line in expected)
            for command,count in source_counts.items():assert sum(line.startswith(command+' ') for line in expected)>=count,(view,command)
            for command in ['set_clock_uncertainty','set_false_path']:
                assert any(line.startswith(command+' ') for line in expected),(view,command)
            for directory,tag in [(warm,'before'),(warm,'after'),(cold,'cold')]:
                assert constraints_equivalent(expected,commands(directory/f'{tag}_{view}.sdc')),'Original native reference constraints differ '+view+' '+tag
        cold_reset=require_reset_topology(baseline/'registered_reset_roots.tsv',cold/'registered_reset_roots.tsv')
        preservation=verify_core_snapshots(baseline/'core_after.tsv',cold/'core_after.tsv',(baseline/'core_prefixes.txt').read_text().splitlines())
        assert preservation['total_original_cells']==1889420
        model=(cold/'model_status.rpt').read_text()
        assert len(re.findall(r'\bAll\s+ILM\s+post-cts\s+',model))==20 and 'current ilm data is for si mode' in model.lower()
        immutable();save(state='unique_parent_connectivity_and_cold_full_core_preservation_verified',native_exit_status=0,
            warm_native=warm_run,cold_native=cold_run,parent_signal_graph_and_constants_preserved=True,
            all3_view_native_constraints_preserved=True,all3_views_match_reapplied_original_sdc=True,all_original_preservation_targets_active=86,pre_reference_preservation_ledgers_verified=True,parent_cells_preserved=673622,reset_preservation=reset,cold_reset_preservation=cold_reset,
            original_core_preservation=preservation,native_evidence_sha256=evidence,
            electrical_repair_completed=False,parent_clock_tree_and_power_grid_pending=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=log_token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
