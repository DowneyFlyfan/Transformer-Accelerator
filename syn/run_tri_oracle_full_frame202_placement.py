"""Place the qualified prepared parent with all original full core models.

This is geometry and three independent process-corner diagnostics, followed
later by timing optimization, clock-tree construction and complete routing.
"""
import csv
import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_frame202_preservation import require_macro_poses, require_reset_topology, read_ready_prerequisite, CORES
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_parent_candidate_acceptance import process_identity
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/frame202_placement_result.json'
    output=root/'.cache/physical/pnr/tri_oracle_predicted_feedforward_placement202'
    assert not result.exists() and not output.exists()
    placement_entry=root/'syn/tri_oracle_place_full_frame202.tcl'
    corner_entry=root/'syn/tri_oracle_report_full_frame203_corner.tcl'
    old_path=root/'records/predicted_fabric_placement79_result.json'
    old=json.loads(old_path.read_text())
    full_path=root/'records/sram_core_hierarchy68_full_control_validation.json'
    core_path=root/'records/sram_core_checkpoint44_qualification.json'
    assert sha(full_path)==old['source_sha256'][str(full_path)]
    assert sha(core_path)==old['source_sha256'][str(core_path)]
    full=json.loads(full_path.read_text());core=json.loads(core_path.read_text())
    assert full['native_export_completed'] and full['native_keep_all'] and full['full_control_all_original_instances_preserved']
    base=root/'.cache/physical/pnr/tri_oracle_sram_memory_compute'
    models=base/'hierarchy_full_control_68'
    model_fingerprint=full['output_artifact_fingerprint']
    assert artifact_fingerprint(models)==model_fingerprint
    model_dependencies={models/'ilm':{'type':'directory','files':{
        name[4:]:value for name,value in model_fingerprint['files'].items() if name.startswith('ilm/')}}}
    static=[Path(__file__).resolve(),placement_entry,corner_entry,old_path,full_path,core_path,
        *[root/'syn'/name for name in ['tri_oracle_artifact_fingerprint.py','tri_oracle_hierarchy_fingerprint.py',
        'tri_oracle_core_preservation.py','tri_oracle_frame202_preservation.py','test_tri_oracle_frame202_preservation.py',
        'tri_oracle_parent_candidate_acceptance.py','tri_oracle_memory_pressure_guard.py','tri_oracle_process_guard.py',
        'tri_oracle_registered_reset_trace102.tcl','tri_oracle_check_registered_reset_fabric.tcl',
        'tri_oracle_row_guard173_variants.py','run_tri_oracle_row_guard175_synthesis.py']],
        root/'records/registered_reset34_sequential_masters.json',Path('/opt/cadence/bin/innovus')]
    identities={str(p):sha(p) for p in static}
    started=time.monotonic();child=pause=None;active_log_argument=None;stopped=False
    source_database=None;source_database_fingerprint=None
    native_evidence={};native_report_directories={}
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),maximum_requested_cpu_workers=8,
        native_anonymous_limit_bytes=16*1024**3,host_reserve_bytes=5*1024**3,
        routed_timing_qualified=False,full_paper_results_matched=False,
        scope='Prepared20-core prediction/feed-forward parent. Full original68 core models, geometric parent placement and three fresh process-corner diagnostics. '
              'No compact guidance model used for acceptance; timing optimization, clock tree, power grid, routing, trained-layer/whole-model and paper results remain separate.')
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    def immutable():
        assert all(sha(p)==h for p,h in identities.items()),'Consumed physical source/evidence changed'
        assert artifact_fingerprint(models)==model_fingerprint,'Full original core models changed'
        assert artifact_fingerprint(root/core['output_database'])==core['output_database_fingerprint']
        if source_database is not None:
            assert hierarchy_fingerprint(source_database)==source_database_fingerprint,'Imported native database changed'
        assert all(sha(p)==h for p,h in native_evidence.items()),'Accepted native physical evidence changed'
        assert all(hierarchy_fingerprint(p)==h for p,h in native_report_directories.items()),'Accepted native timing report directory changed'
    def bind_evidence(paths, directories=()):
        for path in paths:
            assert Path(path).is_file(),str(path)
            native_evidence[str(path)]=sha(path)
        for path in directories:native_report_directories[str(path)]=hierarchy_fingerprint(path)
    def native(directory,entry,marker,environment,seconds):
        nonlocal child,pause,active_log_argument
        directory.mkdir(exist_ok=True)
        console=directory/'console.log';assert not console.exists()
        log_argument=str(directory/'native');command=['innovus','-stylus','-no_gui','-batch','-log',log_argument,'-files',str(entry)]
        active_log_argument=log_argument
        began=time.monotonic()
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                start_new_session=True,env=dict(os.environ,**environment))
            pause=OwnedProcessPause(child,log_argument)
            policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=16*1024**3)
            save(native_process_group=child.pid,native_entry=str(entry),command=command)
            last=0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-began<seconds,'Physical stage wall/external-stop guard'
                    available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                    if action=='pause':pause.pause()
                    elif action=='resume':pause.resume()
                    record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                    if time.monotonic()-last>5:
                        save(native_elapsed_seconds=time.monotonic()-began,current_combined_anonymous_bytes=anonymous,current_host_available_bytes=available);last=time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume();terminate_process_group(child,log_argument=log_argument)
        assert child.returncode==0 and '\n'+marker+'\n' in console.read_text(errors='replace'),console
        return dict(native_exit_status=0,elapsed_seconds=time.monotonic()-began,console_sha256=sha(console),output_directory=str(directory))
    save()
    try:
        prerequisites=[('finish213_synthesis','native_parent_mapping_completed_pending_report_review'),
            ('frame207_import','native_parent_macro_import_completed_pending_report_review'),
            ('mapped208_wrong_sum','expected_wrong_mapped_reference_rejected'),('mapped208_full','full_mapped_frame_functional_passed')]
        owners={};records={}
        while True:
            ready=True
            for label,state in prerequisites:
                path=root/'records'/(label+'_result.json')
                assert path.exists(),'Missing explicitly scheduled prerequisite: '+label
                data=read_ready_prerequisite(lambda:json.loads(path.read_text()),process_identity,owners,label,state)
                if data is None:ready=False
                else:records[label]=data
            if ready:break
            assert not stopped and time.monotonic()-started<28800,'Prerequisite wait expired'
            save(state='waiting_for_full_mapped_parent_functional_qualification');time.sleep(2)
        imported=records['frame207_import'];functional=records['mapped208_full']
        assert functional['actual_cores']==20 and functional['actual_compiled_memories']==600 and functional['hidden_outputs_checked']==4420
        assert functional['source_sha256'][str(root/'records/frame207_import_result.json')]==sha(root/'records/frame207_import_result.json')
        source_database=Path(imported['output_database'])
        source_database_fingerprint=imported['output_database_fingerprint']
        assert hierarchy_fingerprint(source_database)==imported['output_database_fingerprint']
        for label,data in records.items():
            path=root/'records'/(label+'_result.json');identities[str(path)]=sha(path)
            for name,digest in data['source_sha256'].items():
                assert sha(name)==digest;assert name not in identities or identities[name]==digest;identities[name]=digest
        assert all(sha(p)==h for p,h in imported['native_evidence_sha256'].items())
        identities.update(imported['native_evidence_sha256'])
        synthesis=records['finish213_synthesis'];synthesis_output=Path(synthesis['output_directory'])
        topology=synthesis_output/'optimized_topology_qualification.json'
        assert sha(topology)==synthesis['optimized_topology_validation_sha256']
        topology_data=json.loads(topology.read_text());assert all(sha(p)==h for p,h in topology_data['native_evidence_sha256'].items())
        identities[str(topology)]=sha(topology);identities.update(topology_data['native_evidence_sha256'])
        immutable()
        while True:
            available,anonymous=memory()
            if available>18*1024**3 and anonymous<1024**3:break
            assert not stopped and time.monotonic()-started<32400,'Physical headroom wait expired'
            save(state='waiting_for_serial_physical_memory_headroom');time.sleep(2)
        assert shutil.disk_usage(root/'.cache').free>12*1024**3,'Physical disk reserve'
        immutable();assert hierarchy_fingerprint(source_database)==imported['output_database_fingerprint']
        output.mkdir();expected=output/'expected_controller_cells.tsv'
        controls=synthesis_output/'reused_controls_after.tsv.sorted';gate=synthesis_output/'gate_cells_after.tsv'
        with expected.open('w') as stream:
            stream.write(controls.read_text())
            for row in gate.read_text().splitlines():stream.write('numeric/engine/gated/implementation/'+row+'\n')
        subprocess.run(['sort','-S','64M','-T',str(output),'-o',str(expected),str(expected)],check=True,env=dict(os.environ,LC_ALL='C'),timeout=120)
        assert sum(1 for row in expected.open())==382490
        identities[str(expected)]=sha(expected)
        revision=output/'input_revision.json';revision.write_text(json.dumps(dict(source_sha256=identities,input_database_fingerprint=imported['output_database_fingerprint'],full_core_model_fingerprint=model_fingerprint),indent=2)+'\n')
        identities[str(revision)]=sha(revision);immutable()
        save(state='native_full_core_geometric_placement_running',source_sha256=identities,output_directory=str(output))
        run=native(output,placement_entry,'TRI_ORACLE_FRAME202_FULL_MODEL_GEOMETRIC_PLACEMENT_FINISHED',
            dict(TRI_ORACLE_FRAME202_OUTPUT=str(output),TRI_ORACLE_FRAME202_EXPECTED_CONTROLS=str(expected)),7200)
        placement_files=['console.log','placement.rpt','placement_settings.rpt','model_before.rpt','model_after.rpt',
            'full_inventory.rpt','core_prefixes.txt','core_before.tsv','core_after.tsv','core_preservation.json',
            'controller_cells_before.tsv.sorted','controller_cells_after.tsv.sorted','macros_before.tsv','macros_after.tsv',
            'registered_reset_roots.tsv','registered_reset_roots.tsv.summary.rpt','registered_reset_roots.tsv.edges.tsv',
            'parent_area.rpt','placed_parent.v','placed_parent.def']
        bind_evidence([output/name for name in placement_files])
        assert native_evidence[str(output/'console.log')]==run['console_sha256']
        immutable()
        prefixes=(output/'core_prefixes.txt').read_text().splitlines();assert set(prefixes)==CORES and len(prefixes)==20
        preservation=verify_core_snapshots(output/'core_before.tsv',output/'core_after.tsv',prefixes)
        assert preservation['total_original_cells']==1889420
        macro=require_macro_poses(source_database.parent/'macro_inventory.tsv',output/'macros_before.tsv',output/'macros_after.tsv')
        resets=require_reset_topology(source_database.parent/'registered_reset_roots.tsv',output/'registered_reset_roots.tsv')
        placement=(output/'placement.rpt').read_text()
        assert 'Finished check_place' in placement and re.search(r'Unplaced\s*=\s*0\b',placement)
        assert not re.search(r'\b(overlap|violation|illegal|warning|error)s?\b',placement,re.I),placement
        checkpoint=output/'placed.db';fingerprint=hierarchy_fingerprint(checkpoint,directory_dependencies=model_dependencies)
        for name in ['model_before.rpt','model_after.rpt']:
            status=(output/name).read_text()
            assert 'current ilm data is for si mode' in status.lower()
            assert len(re.findall(r'\bAll\s+ILM\s+post-cts\s+',status))==20
        immutable()
        save(state='geometric_placement_completed_corner_diagnostics_pending',native_placement=run,
            original_core_preservation=preservation,macro_preservation=macro,reset_preservation=resets,
            output_database=str(checkpoint),output_database_fingerprint=fingerprint,
            native_evidence_sha256=native_evidence,native_report_directory_fingerprints=native_report_directories)
        corners={}
        for view in ['setup_slow','setup_typ','hold_fast']:
            directory=output/('corner_'+view);save(state='full_core_original_corner_diagnostics_running',diagnostic_view=view)
            run=native(directory,corner_entry,'TRI_ORACLE_FRAME203_CORNER_DIAGNOSTIC_FINISHED '+view,
                dict(TRI_ORACLE_PARENT_DIAGNOSTIC_CHECKPOINT=str(checkpoint),TRI_ORACLE_PARENT_DIAGNOSTIC_DIRECTORY=str(directory),TRI_ORACLE_PARENT_DIAGNOSTIC_VIEW=view),3600)
            files=['console.log','slack_properties.tsv','core_counts.tsv','worst_path.rpt','clocks.rpt','model_status.rpt']
            bind_evidence([directory/name for name in files],[directory/'timing'])
            assert native_evidence[str(directory/'console.log')]==run['console_sha256']
            with (directory/'slack_properties.tsv').open() as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
            assert len(rows)==1 and rows[0]['view']==view and math.isfinite(float(rows[0]['slack_ns']))
            with (directory/'core_counts.tsv').open() as stream:counts=list(csv.DictReader(stream,delimiter='\t'))
            assert len(counts)==20 and {int(row['full_original_cells']) for row in counts}=={94471}
            assert {row['core'] for row in counts}==CORES
            immutable();assert hierarchy_fingerprint(checkpoint,directory_dependencies=model_dependencies)==fingerprint
            corners[view]=dict(run,slack_ns=float(rows[0]['slack_ns']),startpoint=rows[0]['startpoint'],endpoint=rows[0]['endpoint'],
                input_checkpoint=str(checkpoint),input_checkpoint_fingerprint=fingerprint,
                native_evidence_sha256={str(directory/name):native_evidence[str(directory/name)] for name in files},
                timing_reports_fingerprint=native_report_directories[str(directory/'timing')])
            save(separate_corner_diagnostics=corners,native_evidence_sha256=native_evidence,native_report_directory_fingerprints=native_report_directories)
        save(state='full_core_geometric_placement_and_corner_diagnostics_completed',native_exit_status=0,
            all_original_core_cells_preserved=1889420,compiled_memory_macros=600,
            all3_original_corners_diagnosed=True,all3_pre_clock_slacks_nonnegative=all(c['slack_ns']>=0 for c in corners.values()),
            timing_driven_placement_optimization_completed=False,clock_tree_power_grid_and_routing_pending=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=active_log_argument)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise


if __name__=='__main__':main()
