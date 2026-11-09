"""Repair whole-parent electrical violations using cold-qualified boundary guidance."""
import datetime
import filecmp
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_frame202_preservation import require_reset_topology
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group

def main():
    root=Path(__file__).resolve().parents[1];out=root/'.cache/physical/pnr/tri_oracle_repair_frame251';result=root/'records/frame251_electrical_result.json'
    assert not out.exists() and not result.exists()
    producer_path=root/'records/frame242_guidance_result.json';producer=json.loads(producer_path.read_text())
    assert producer['state']=='twenty_core_fresh_guidance_import_and_cold_preservation_verified'
    assert producer['original_parent_physical_leaves_preserved']==673622 and producer['original_protected_targets_preserved']==86
    assert producer['hierarchy_module_flags_and_macro_halos_preserved'] is True
    checkpoint=Path(producer['output_database']);input_fp=producer['output_database_fingerprint'];reference=Path(producer['output_directory'])/'cold'
    assert hierarchy_fingerprint(checkpoint)==input_fp
    identities={str(producer_path):sha(producer_path)}
    for key in ['source_sha256','native_evidence_sha256','generated_sha256']:
        for name,digest in producer[key].items():assert sha(name)==digest;identities[name]=digest
    controller_baseline=root/'.cache/physical/pnr/tri_oracle_predicted_feedforward_placement202/controller_cells_after.tsv.sorted'
    assert str(controller_baseline) in identities and sha(controller_baseline)==identities[str(controller_baseline)]
    entry=root/'syn/tri_oracle_repair_frame251.tcl'
    names=['run_tri_oracle_repair_frame251.py','tri_oracle_repair_frame251.tcl','tri_oracle_design242_metadata.tcl','tri_oracle_preservation233.tcl','tri_oracle_registered_reset_trace102.tcl','tri_oracle_check_registered_reset_fabric.tcl','tri_oracle_row_guard173_variants.py','run_tri_oracle_row_guard175_synthesis.py','tri_oracle_hierarchy_fingerprint.py','tri_oracle_artifact_fingerprint.py','tri_oracle_frame202_preservation.py','tri_oracle_mapped_restore199.py','tri_oracle_row_guard175_checkpoint.py','tri_oracle_native_diagnostics.py','tri_oracle_memory_pressure_guard.py','tri_oracle_process_guard.py']
    for p in [*[root/'syn'/name for name in names],Path('/opt/cadence/INNOVUS251/doc/TCRcom/opt_design.html'),Path('/opt/cadence/INNOVUS251/doc/TCRcom/report_rc_factors.html'),Path('/opt/cadence/INNOVUS251/doc/DBcom/rc_corner.html')]:
        digest=sha(p);assert str(p) not in identities or identities[str(p)]==digest;identities[str(p)]=digest
    started=time.monotonic();child=pause=None;token=str(out/'native');stopped=False
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),native_workers=4,anonymous_limit_bytes=18*1024**3,host_reserve_bytes=5*1024**3,guidance_model_timing_equivalent=False,full600_memory_restoration_pending=True,post_eco_mapped_functional_verification_pending=True,parent_timing_closed=False,parent_routing_completed=False,full_paper_results_matched=False,scope='Native pre-clock electrical optimization of actual20-core prepared parent using boundary80 guidance. Max-capacitance/transition/fanout repair only; native return is not zero-violation proof. Original580MHz clock/IOconstraints,60fixedmacroposes/halos,86protectedtargets,portsandresetancestrymustremain. Originalreset-sourceFFmastersaretemporarilyprotectedthenexactuserflagsrestored. Full600-memorymodels,all3originalcorners,postECOfunctionandparentroutingremaindownstreamgates.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def immutable():
        assert all(sha(name)==digest for name,digest in identities.items())
        assert hierarchy_fingerprint(checkpoint)==input_fp
    def same_rows(a,b):
        target=b.with_suffix(b.suffix+'.sorted')
        subprocess.run(['sort','-S','64M','-T',str(out),'-o',str(target),str(b)],check=True,env=dict(os.environ,LC_ALL='C'),timeout=180)
        return sorted(a.read_text().splitlines())==target.read_text().splitlines()
    save()
    try:
        available,anonymous=memory();assert available>18*1024**3 and anonymous<1024**3
        immutable();out.mkdir();console=out/'console.log';command=['/opt/cadence/bin/innovus','-stylus','-no_gui','-batch','-log',token,'-files',str(entry)]
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=out,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,TRI251_OUT=str(out),TRI251_INPUT=str(checkpoint),TRI251_REFERENCE=str(reference)))
            pause=OwnedProcessPause(child,token);policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=18*1024**3)
            save(state='native_whole_parent_guidance_electrical_repair_running',native_process_group=child.pid,command=command,output_directory=str(out));last=0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-started<7200,'Electrical repair wall/stop guard'
                    available,anonymous=memory();record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous);record['current_host_available_bytes']=available;record['current_combined_anonymous_bytes']=anonymous;action=policy.observe(available,anonymous,time.monotonic())
                    if action=='pause':pause.pause()
                    elif action=='resume':pause.resume()
                    record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                    if time.monotonic()-last>5:save(native_elapsed_seconds=time.monotonic()-started,current_host_available_bytes=available,current_combined_anonymous_bytes=anonymous);last=time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume();terminate_process_group(child,log_argument=token)
        text=console.read_text(errors='replace');require_clean_native(text)
        assert child.returncode==0 and '\nTRI_ORACLE_FRAME251_BOUNDARY_ELECTRICAL_REPAIR_FINISHED_PENDING_FULL_RESTORE\n' in text,str(console)
        for tag in ['before','after']:
            assert (out/f'{tag}_design.tsv').read_text()==(reference/'candidate_design.tsv').read_text()
            assert (out/f'{tag}_preservation.tsv').read_text()==(reference/'candidate_preservation.tsv').read_text()
            for source,suffix in [('candidate_hierarchy.tsv','hierarchy'),('candidate_halos.tsv','halos'),('candidate_port_poses.tsv','port_poses')]:assert same_rows(reference/source,out/f'{tag}_{suffix}.tsv'),'Preserved native metadata changed '+tag+' '+suffix
            assert constraints_equivalent(commands(reference/'setup_typ.sdc'),commands(out/f'{tag}_setup_typ.sdc')),'Original timing constraints changed '+tag
        for tag in ['before','after']:
            inventory=out/f'{tag}_controller_cells.tsv'
            ordered=inventory.with_suffix('.tsv.sorted')
            subprocess.run(['sort','-S','64M','-T',str(out),'-o',str(ordered),str(inventory)],check=True,env=dict(os.environ,LC_ALL='C'),timeout=180)
            assert filecmp.cmp(controller_baseline,ordered,shallow=False),'Protected382490 controller cell inventory changed '+tag
        assert (out/'original_rc_factors.tsv').read_text()==(out/'after_rc_factors.tsv').read_text(),'Original pre-route RC scale factors changed'
        reset=require_reset_topology(reference/'registered_reset_roots.tsv',out/'after_reset_roots.tsv')
        def rows(p):return [line.split('\t') for line in p.read_text().splitlines()[1:]]
        temporary=rows(out/'temporary_reset_protection.tsv');restored=rows(out/'restored_reset_source_flags.tsv')
        assert temporary and len(temporary)==len(restored)==len({row[0] for row in temporary})
        assert {tuple(row[:4]) for row in temporary}=={tuple(row) for row in restored} and all(row[4]=='true' for row in temporary)
        def interface(p):
            data=rows(p);assert len(data)==len({row[0] for row in data});return {(row[0],row[1]) for row in data}
        assert interface(out/'before_core_pins.tsv')==interface(out/'after_core_pins.tsv')
        placement=(out/'placement.rpt').read_text();assert 'Finished check_place' in placement and re.search(r'Unplaced\s*=\s*0\b',placement)
        assert not re.search(r'\b(overlap|violation|illegal|warning|error)s?\b',placement,re.I)
        fields=(out/'guidance_slack.tsv').read_text().splitlines();assert len(fields)==2;slack=float(fields[1].split('\t')[1])
        candidate=out/'repaired_candidate.db';candidate_fp=hierarchy_fingerprint(candidate)
        immutable();evidence={str(p):sha(p) for p in out.iterdir() if p.is_file() and (p.suffix in ['.tsv','.sorted','.sdc','.rpt','.v','.def','.txt'] or p.name=='console.log')}
        for directory in ['before_timing','repair_reports','after_timing']:
            for p in (out/directory).rglob('*'):
                if p.is_file() and p.suffix not in ['.bin','.db']:evidence[str(p)]=sha(p)
        save(state='guidance_electrical_optimization_completed_pending_full_restore_and_function',native_exit_status=0,output_database=str(candidate),output_database_fingerprint=candidate_fp,native_evidence_sha256=evidence,original86_protected_targets_retained=True,all382490_protected_controller_cell_names_and_masters_retained=True,original_macro_halos_hierarchy_and_port_poses_preserved=True,original_typical_constraints_preserved=True,registered_reset_preservation=reset,temporary_reset_source_protections=len(temporary),temporary_reset_flags_exactly_restored=True,guidance_worst_setup_slack_ns=slack,original_pre_route_rc_scale_factors_preserved=True,pre_route_calibration_detailed_routing_not_invoked=True,electrical_zero_violation_status_unqualified=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
