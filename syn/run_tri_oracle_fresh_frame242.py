"""Fresh-import and cold-verify the unique twenty-core parent boundary guide."""
import datetime
import filecmp
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_frame202_preservation import require_reset_topology
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group

def main():
    root=Path(__file__).resolve().parents[1];base=root/'.cache/physical'
    result=root/'records/frame242_guidance_result.json';out=base/'pnr/tri_oracle_fresh_frame242'
    assert not result.exists() and not out.exists()
    unique_path=root/'records/unique235_parent_result.json';unique=json.loads(unique_path.read_text())
    assert unique['state']=='unique_parent_connectivity_and_cold_full_core_preservation_verified'
    assert unique['original_core_preservation']['total_original_cells']==1889420 and unique['all_original_preservation_targets_active']==86
    proof_path=root/'records/fresh241_roundtrip_result.json';proof=json.loads(proof_path.read_text())
    assert proof['state']=='cold_guidance_fresh_full_import_and_cold_original_core_restore_verified'
    assert proof['all3_original_corner_constraints_preserved'] is True
    one_path=root/'records/fresh239_probe_result.json';one=json.loads(one_path.read_text());assert one['state']=='fresh_one_core_boundary_guidance_import_verified'
    design_control_path=root/'records/design243_native_control.json'
    design_control=json.loads(design_control_path.read_text())
    assert design_control['state']=='native_inherited_design_flag_loss_rejected_and_exactly_restored' and design_control['temporary_build_removed'] is True
    checkpoint=Path(unique['output_database']);source_fp=unique['output_database_fingerprint'];reference=Path(unique['output_directory'])/'warm'
    deps={Path(name):value for name,value in source_fp.get('directory_dependencies',{}).items()}
    assert hierarchy_fingerprint(checkpoint,directory_dependencies=deps)==source_fp
    identities={str(p):sha(p) for p in [unique_path,proof_path,one_path,design_control_path]}
    for record in [unique,proof,one,design_control]:
        keys=['source_sha256','native_evidence_sha256']+([] if record.get('temporary_build_removed') else ['generated_sha256'])
        for key in keys:
            for name,digest in record.get(key,{}).items():
                assert sha(name)==digest and (name not in identities or identities[name]==digest),'Conflicting input '+name
                identities[name]=digest
    # The qualified tiny control deletes its build; verify its retained exact
    # generated sources instead of trying to reopen removed temporary files.
    assert len(design_control['generated_sha256'])==len(design_control['generated_sources'])
    for name,digest in design_control['generated_sha256'].items():
        assert hashlib.sha256(design_control['generated_sources'][Path(name).name].encode()).hexdigest()==digest
    model_path=root/'records/sram_core_timing_model80_export_validation.json';model=json.loads(model_path.read_text())
    model_dir=base/'pnr/tri_oracle_sram_memory_compute/hierarchy_timing_model_80';model_fp=model['output_artifact_fingerprint']
    assert artifact_fingerprint(model_dir)==model_fp and not model['timing_equivalence_qualified']
    imported_path=root/'records/frame207_import_result.json';imported=json.loads(imported_path.read_text())
    canonical=base/'pnr/tri_oracle_sram_memory_compute/hierarchy_twenty_core_75_inputs/wrapper.v';assert sha(canonical)==imported['source_sha256'][str(canonical)]
    libraries=[base/'library/tcbn28hpcplusbwp12t40p140tt1v25c.lib',base/'sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/NLDM/ts5n28hpcpsvta32x128m2fw_130a_tt1v25c.lib',base/'sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/NLDM/ts6n28hpcpsvta16x128m2f_130a_tt1v25c.lib',base/'sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/NLDM/ts5n28hpcpsvta512x64m4f_130a_tt1v25c.lib',model_dir/'core_typ.lib']
    for p in libraries:assert str(p) in identities and sha(p)==identities[str(p)]
    entry=root/'syn/tri_oracle_fresh_frame242.tcl'
    names=['run_tri_oracle_fresh_frame242.py','tri_oracle_fresh_frame242.tcl','tri_oracle_unique215_snapshot.tcl','tri_oracle_preservation233.tcl','tri_oracle_design242_metadata.tcl','tri_oracle_registered_reset_trace102.tcl','tri_oracle_check_registered_reset_fabric.tcl','tri_oracle_frame202_preservation.py','tri_oracle_row_guard173_variants.py','run_tri_oracle_row_guard175_synthesis.py','tri_oracle_artifact_fingerprint.py','tri_oracle_hierarchy_fingerprint.py','tri_oracle_mapped_restore199.py','tri_oracle_row_guard175_checkpoint.py','tri_oracle_native_diagnostics.py','tri_oracle_memory_pressure_guard.py','tri_oracle_process_guard.py']
    for p in [model_path,imported_path,canonical,*[root/'syn'/name for name in names],Path('/opt/cadence/INNOVUS251/doc/DBcom/design.html'),Path('/opt/cadence/INNOVUS251/doc/DBcom/hinst.html'),Path('/opt/cadence/INNOVUS251/doc/DBcom/module.html'),Path('/opt/cadence/INNOVUS251/doc/DBcom/port.html')]:
        digest=sha(p);assert str(p) not in identities or identities[str(p)]==digest;identities[str(p)]=digest
    started=time.monotonic();child=pause=None;token=None;stopped=False;evidence={};generated={};guide_db=guide_fp=None
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),native_workers=8,anonymous_limit_bytes=16*1024**3,host_reserve_bytes=5*1024**3,guidance_model_timing_equivalent=False,full600_memory_restore_pending=True,parent_electrical_repair_completed=False,parent_timing_closed=False,parent_routing_completed=False,full_paper_results_matched=False,scope='Fresh twenty-core boundary80 guidance import and cold reload of actual unique235 parent. Exact673622 physical leaves, all hierarchy/module flags,86 protected targets,60macroposes/halos,63160originalcorepinrows,ports,driver/load graph/constants,resetancestry and originaltypical constraints. Guidancecontains20abstractcores/40aggregatememorymacros;600fullmemories/finalcornersrequirelaterfreshfullrestore.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def immutable():
        assert all(sha(name)==digest for name,digest in identities.items()),'Whole-parent guide input changed'
        assert all(sha(name)==digest for name,digest in evidence.items()) and all(sha(name)==digest for name,digest in generated.items())
        assert hierarchy_fingerprint(checkpoint,directory_dependencies=deps)==source_fp
        assert artifact_fingerprint(model_dir)==model_fp
        if guide_db is not None:assert hierarchy_fingerprint(guide_db)==guide_fp
    def native(mode,input_db,marker):
        nonlocal child,pause,token
        directory=out/mode;directory.mkdir();console=directory/'console.log';token=str(directory/'native')
        cmd=['innovus','-stylus','-no_gui','-batch','-log',token,'-files',str(entry)];began=time.monotonic()
        with console.open('w') as stream:
            child=subprocess.Popen(cmd,cwd=directory,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,TRI242_OUT=str(directory),TRI242_PARENT=str(out),TRI242_MODE=mode,TRI242_INPUT=str(input_db),TRI242_REFERENCE=str(reference)))
            pause=OwnedProcessPause(child,token);policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=16*1024**3)
            save(state='native_'+mode+'_running',phase=mode,native_process_group=child.pid,command=cmd);last=0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-began<3600,'Whole-parent guide wall/stop guard'
                    available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                    if action=='pause':pause.pause()
                    elif action=='resume':pause.resume()
                    record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                    if time.monotonic()-last>5:save(native_elapsed_seconds=time.monotonic()-began,current_host_available_bytes=available,current_combined_anonymous_bytes=anonymous);last=time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume();terminate_process_group(child,log_argument=token)
        text=console.read_text(errors='replace');require_clean_native(text)
        assert child.returncode==0 and '\n'+marker+'\n' in text,str(console)
        for p in directory.iterdir():
            if p.is_file() and (p.suffix in ['.tsv','.rpt','.sdc'] or p.name=='console.log'):evidence[str(p)]=sha(p)
        return dict(native_exit_status=0,elapsed_seconds=time.monotonic()-began,console_sha256=sha(console))
    def equal_sorted(a,b):
        ordered=b.with_suffix(b.suffix+'.sorted');subprocess.run(['sort','-S','64M','-T',str(b.parent),'-o',str(ordered),str(b)],check=True,env=dict(os.environ,LC_ALL='C'),timeout=180)
        evidence[str(ordered)]=sha(ordered)
        return filecmp.cmp(a,ordered,shallow=False)
    def validate(directory):
        for kind in ['cells','ports','nets','pins']:assert equal_sorted(reference/f'before_{kind}.tsv.sorted',directory/f'candidate_{kind}.tsv'),'Whole parent changed '+kind
        for item in ['design','hierarchy','halos','port_poses']:
            source=out/'reference'/f'reference_{item}.tsv';ordered=source.with_suffix('.tsv.sorted')
            if not ordered.exists():subprocess.run(['sort','-S','64M','-T',str(source.parent),'-o',str(ordered),str(source)],check=True,env=dict(os.environ,LC_ALL='C'),timeout=180);evidence[str(ordered)]=sha(ordered)
            assert equal_sorted(ordered,directory/f'candidate_{item}.tsv'),'Whole parent changed '+item
        assert (out/'reference/reference_preservation.tsv').read_text()==(directory/'candidate_preservation.tsv').read_text()
        assert constraints_equivalent(commands(reference/'before_setup_typ.sdc'),commands(directory/'setup_typ.sdc')),'Original typical constraints changed'
        text=(directory/'placement.rpt').read_text();assert 'Finished check_place' in text and re.search(r'Unplaced\s*=\s*0\b',text)
        assert not re.search(r'\b(overlap|violation|illegal|warning|error)s?\b',text,re.I)
        require_reset_topology(reference/'registered_reset_roots.tsv',directory/'registered_reset_roots.tsv')
        def pins(p):
            rows=[line.split('\t') for line in p.read_text().splitlines()[1:]];assert len(rows)==len({row[0] for row in rows});return {row[0]:row for row in rows}
        a=pins(out/'reference/reference_core_pins.tsv');b=pins(directory/'candidate_core_pins.tsv');assert len(a)==63160 and all(b.get(name)==row for name,row in a.items())
        extra={name:row for name,row in b.items() if name not in a};assert len(extra)==20 and all(name.endswith('/_INT_clk_src_data_check_clk') and row[1:]==['internal','','no_constant'] for name,row in extra.items())
    save()
    try:
        available,anonymous=memory();assert available>18*1024**3 and anonymous<1024**3
        immutable();out.mkdir();save(output_directory=str(out))
        reference_run=native('reference',checkpoint,'TRI_ORACLE_FRESH242_REFERENCE_METADATA_EXPORTED')
        assert (out/'reference/reference_preservation.tsv').read_text()==(reference/'before_preservation.tsv').read_text()
        mapped=(reference/'unique_parent.v').read_text();pattern=re.compile(r'^\s*module\s+tri_oracle_sram_memory_compute\s*\(',re.M)
        if not pattern.search(mapped):
            canonical_text=canonical.read_text();starts=list(pattern.finditer(canonical_text));assert len(starts)==1
            end=re.search(r'^\s*endmodule\s*$',canonical_text[starts[0].start():],re.M);assert end
            mapped+='\n'+canonical_text[starts[0].start():starts[0].start()+end.end()]+'\n'
        p=out/'parent_import.v';p.write_text(mapped);generated[str(p)]=sha(p)
        mmmc='create_library_set -name ls_typ -timing [list '+' '.join('{'+str(p)+'}' for p in libraries)+']\n'
        mmmc+=f'create_rc_corner -name rc_typ -qrc_tech {{{base}/rc/qrc_typical}} -temperature 25\ncreate_timing_condition -name tc_typ -library_sets {{ls_typ}}\ncreate_delay_corner -name dc_typ -timing_condition tc_typ -rc_corner rc_typ\ncreate_constraint_mode -name functional -sdc_files [list {{{reference}/before_setup_typ.sdc}}]\ncreate_analysis_view -name setup_typ -constraint_mode functional -delay_corner dc_typ\nset_analysis_view -setup {{setup_typ}} -hold {{setup_typ}}\n'
        p=out/'guide_mmmc.tcl';p.write_text(mmmc);generated[str(p)]=sha(p)
        immutable();save(reference_native=reference_run,native_evidence_sha256=evidence,generated_sha256=generated)
        warm=native('guide',checkpoint,'TRI_ORACLE_FRESH242_WHOLE_PARENT_GUIDANCE_IMPORTED');validate(out/'guide')
        guide_db=out/'guide/guidance.db';guide_fp=hierarchy_fingerprint(guide_db)
        immutable();save(state='whole_parent_guidance_saved_cold_validation_pending',warm_native=warm,output_database=str(guide_db),output_database_fingerprint=guide_fp,native_evidence_sha256=evidence)
        cold=native('cold',guide_db,'TRI_ORACLE_FRESH242_COLD_WHOLE_PARENT_GUIDANCE_VERIFIED');validate(out/'cold')
        immutable();save(state='twenty_core_fresh_guidance_import_and_cold_preservation_verified',native_exit_status=0,reference_native=reference_run,warm_native=warm,cold_native=cold,original_parent_physical_leaves_preserved=673622,original_core_external_pins_preserved=63160,core_abstracts=20,aggregate_memory_macros=40,original_protected_targets_preserved=86,hierarchy_module_flags_and_macro_halos_preserved=True,original_typical_constraints_preserved=True,registered_reset_ancestry_preserved=True,native_evidence_sha256=evidence,generated_sha256=generated)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
