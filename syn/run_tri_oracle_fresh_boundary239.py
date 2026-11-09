"""Freshly import a one-core boundary guide; full restoration remains separate."""
import datetime
import filecmp
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause
from tri_oracle_native_diagnostics import require_clean_native

def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/fresh239_probe_result.json'
    out=root/'.cache/physical/pnr/tri_oracle_fresh_boundary239'
    assert not result.exists() and not out.exists()
    original_path=root/'records/core_model_switch84_result.json'
    original=json.loads(original_path.read_text());assert original['state']=='passed'
    input_db=Path(original['output_database']);input_fp=original['output_database_fingerprint']
    dependencies={Path(p):f for p,f in input_fp.get('directory_dependencies',{}).items()}
    assert hierarchy_fingerprint(input_db,directory_dependencies=dependencies)==input_fp
    mapping_path=root/'records/finish213_synthesis_result.json';mapping=json.loads(mapping_path.read_text())
    assert mapping['state']=='native_parent_mapping_completed_pending_report_review'
    model_path=root/'records/sram_core_timing_model80_export_validation.json'
    comparison_path=root/'records/sram_core_timing_model81_comparison.json'
    for p in [model_path,comparison_path]:assert sha(p)==mapping['source_sha256'][str(p)]
    model=json.loads(model_path.read_text());assert model['native_export_completed'] and not model['timing_equivalence_qualified']
    model_dir=root/'.cache/physical/pnr/tri_oracle_sram_memory_compute/hierarchy_timing_model_80'
    assert artifact_fingerprint(model_dir)==model['output_artifact_fingerprint']
    full_path=root/'records/sram_core_hierarchy68_full_control_validation.json'
    assert sha(full_path)==original['source_sha256'][str(full_path)]
    full=json.loads(full_path.read_text())
    full_dir=root/'.cache/physical/pnr/tri_oracle_sram_memory_compute/hierarchy_full_control_68'
    assert artifact_fingerprint(full_dir)==full['output_artifact_fingerprint']
    old_snapshot_sources=original['cold_complete_cell_preservation']['input_sha256']
    reference=next(Path(p) for p in old_snapshot_sources if '/cold/' in p)
    assert sha(reference)==old_snapshot_sources[str(reference)]
    entry=root/'syn/tri_oracle_fresh_boundary239.tcl'
    names=['run_tri_oracle_fresh_boundary239.py','tri_oracle_fresh_boundary239.tcl',
           'tri_oracle_unique215_snapshot.tcl','tri_oracle_artifact_fingerprint.py',
           'tri_oracle_hierarchy_fingerprint.py','tri_oracle_core_preservation.py',
           'tri_oracle_mapped_restore199.py','tri_oracle_row_guard175_checkpoint.py',
           'tri_oracle_row_guard173_variants.py','run_tri_oracle_row_guard175_synthesis.py',
           'tri_oracle_process_guard.py','tri_oracle_memory_pressure_guard.py','tri_oracle_native_diagnostics.py']
    static=[original_path,mapping_path,model_path,comparison_path,full_path,reference,*[root/'syn'/n for n in names],Path('/opt/cadence/bin/innovus')]
    identities={str(p):sha(p) for p in static}
    base=root/'.cache/physical'
    libraries=[base/'library/tcbn28hpcplusbwp12t40p140tt1v25c.lib',
        base/'sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/NLDM/ts5n28hpcpsvta32x128m2fw_130a_tt1v25c.lib',
        base/'sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/NLDM/ts6n28hpcpsvta16x128m2f_130a_tt1v25c.lib',
        base/'sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/NLDM/ts5n28hpcpsvta512x64m4f_130a_tt1v25c.lib',
        model_dir/'core_typ.lib']
    for p in libraries:
        assert sha(p)==mapping['source_sha256'][str(p)];identities[str(p)]=sha(p)
    imported_path=root/'records/frame207_import_result.json'
    imported=json.loads(imported_path.read_text())
    canonical=root/'.cache/physical/pnr/tri_oracle_sram_memory_compute/hierarchy_twenty_core_75_inputs/wrapper.v'
    assert sha(canonical)==imported['source_sha256'][str(canonical)]
    lefs=[base/'routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef',
        base/'library/tcbn28hpcplusbwp12t40p140.lef',
        base/'sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/LEF/ts5n28hpcpsvta32x128m2fw_130a.lef',
        base/'sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/LEF/ts6n28hpcpsvta16x128m2f_130a.lef',
        base/'sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/LEF/ts5n28hpcpsvta512x64m4f_130a.lef',
        base/'pnr/tri_oracle_sram_memory_compute/hierarchy_export_58/core.lef',base/'rc/qrc_typical']
    preserve_doc=Path('/opt/cadence/INNOVUS251/doc/DBcom/inst.html')
    identities[str(preserve_doc)]=sha(preserve_doc)
    for p in [imported_path,canonical,*lefs]:
        if p not in [imported_path,canonical]:assert sha(p)==imported['source_sha256'][str(p)]
        identities[str(p)]=sha(p)
    started=time.monotonic();child=pause=None;token=None;stopped=False;evidence={};generated={}
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),native_workers=2,
        anonymous_limit_bytes=6*1024**3,host_reserve_bytes=8*1024**3,
        guidance_model_timing_equivalent=False,full_parent_electrical_repair_completed=False,full_paper_results_matched=False,
        scope='Fresh one-core boundary-library80 guidance import from accepted84 netlist/DEF with explicit leaf-protection transfer. Exact parent geometry/graph/constants,3158externalpins and warm TT constraints required. No in-place ILM switch, optimization, full-model restoration or final timing claim.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def immutable():
        assert all(sha(p)==h for p,h in identities.items())
        assert hierarchy_fingerprint(input_db,directory_dependencies=dependencies)==input_fp
        assert artifact_fingerprint(model_dir)==model['output_artifact_fingerprint']
        assert artifact_fingerprint(full_dir)==full['output_artifact_fingerprint']
        assert all(sha(p)==h for p,h in evidence.items())
        assert all(sha(p)==h for p,h in generated.items())
    def native(directory,mode,marker):
        nonlocal child,pause,token
        directory.mkdir();token=str(directory/'native');console=directory/'console.log'
        command=['innovus','-stylus','-no_gui','-batch','-log',token,'-files',str(entry)]
        began=time.monotonic()
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=directory,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                start_new_session=True,env=dict(os.environ,TRI239_OUT=str(directory),TRI239_MODE=mode,TRI239_INPUT=str(input_db),TRI239_PARENT=str(out)))
            pause=OwnedProcessPause(child,token)
            policy=MemoryPressurePolicy(host_reserve_bytes=8*1024**3,resume_bytes=10*1024**3,anonymous_limit_bytes=6*1024**3)
            save(state='native_reference_export_running' if mode=='export' else 'native_fresh_boundary_import_running',native_process_group=child.pid,phase=mode,command=command)
            last=0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-began<600,'Fresh-import wall/stop guard'
                    available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                    if action=='pause':pause.pause()
                    elif action=='resume':pause.resume()
                    record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                    if time.monotonic()-last>5:save(native_elapsed_seconds=time.monotonic()-began);last=time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume();terminate_process_group(child,log_argument=token)
        text=console.read_text(errors='replace');require_clean_native(text)
        assert child.returncode==0 and '\n'+marker+'\n' in text,str(console)
        for p in directory.iterdir():
            if p.is_file() and (p.suffix in ['.tsv','.sorted','.sdc','.rpt','.v','.def'] or p.name=='console.log'):evidence[str(p)]=sha(p)
        return dict(native_exit_status=0,elapsed_seconds=time.monotonic()-began,console_sha256=sha(console))
    save()
    try:
        available,anonymous=memory();assert available>18*1024**3 and anonymous<1024**3
        immutable();out.mkdir();save(output_directory=str(out))
        exported=native(out/'export','export','TRI_ORACLE_FRESH239_REFERENCE_EXPORTED')
        verify_core_snapshots(reference,out/'export/full_before.tsv',['core0'])
        original_sdc=commands(out/'export/setup_typ.sdc')
        assert original_sdc and sum(line.startswith('set_propagated_clock ') for line in original_sdc)==1
        # Native source-clock latency is corner-specific; retain each reference
        # separately and compare guidance only with its matching typical view.
        source_constraint_references={view:sha(out/'export'/f'{view}.sdc') for view in ['setup_slow','setup_typ','hold_fast']}
        assert all(any(line.startswith('create_clock ') for line in commands(out/'export'/f'{view}.sdc')) for view in source_constraint_references)
        mapped=(out/'export/parent.v').read_text();canonical_text=canonical.read_text()
        pattern=re.compile(r'^\s*module\s+tri_oracle_sram_memory_compute\s*\(',re.M)
        if not pattern.search(mapped):
            starts=list(pattern.finditer(canonical_text));assert len(starts)==1
            end=re.search(r'^\s*endmodule\s*$',canonical_text[starts[0].start():],re.M);assert end
            mapped += '\n'+canonical_text[starts[0].start():starts[0].start()+end.end()]+'\n'
        p=out/'parent_import.v';p.write_text(mapped);generated[str(p)]=sha(p)
        mmmc='set parent $::env(TRI239_PARENT)\ncreate_library_set -name ls_typ -timing [list '+ ' '.join('{'+str(p)+'}' for p in libraries)+']\n'
        mmmc+='create_rc_corner -name rc_typ -qrc_tech {'+str(base/'rc/qrc_typical')+'} -temperature 25\ncreate_timing_condition -name tc_typ -library_sets {ls_typ}\ncreate_delay_corner -name dc_typ -timing_condition tc_typ -rc_corner rc_typ\ncreate_constraint_mode -name functional -sdc_files [list $parent/export/setup_typ.sdc]\ncreate_analysis_view -name setup_typ -constraint_mode functional -delay_corner dc_typ\nset_analysis_view -setup {setup_typ} -hold {setup_typ}\n'
        p=out/'guide_mmmc.tcl';p.write_text(mmmc);generated[str(p)]=sha(p)
        immutable();save(generated_sha256=generated,native_evidence_sha256=evidence,export_native=exported)
        guide=out/'guide';guided=native(guide,'guide','TRI_ORACLE_FRESH239_GUIDANCE_IMPORTED')
        for kind in ['cells','ports','nets','pins']:
            paths=[]
            for folder,tag in [(out/'export','original'),(guide,'guidance')]:
                p=folder/f'{tag}_{kind}.tsv';ordered=p.with_suffix('.tsv.sorted')
                subprocess.run(['sort','-S','64M','-T',str(folder),'-o',str(ordered),str(p)],check=True,env=dict(os.environ,LC_ALL='C'),timeout=120)
                evidence[str(ordered)]=sha(ordered);paths.append(ordered)
            assert filecmp.cmp(*paths,shallow=False),'Fresh parent changed '+kind
        assert constraints_equivalent(original_sdc,commands(guide/'guidance_setup_typ.sdc')),'Fresh guidance timing constraints changed'
        def pins(p):
            lines=[line.split('\t') for line in p.read_text().splitlines()[1:]];assert len(lines)==len({row[0] for row in lines})
            return {row[0]:row for row in lines}
        a=pins(out/'export/original_core_pins.tsv');b=pins(guide/'guidance_core_pins.tsv')
        assert len(a)==3158 and all(b.get(name)==row for name,row in a.items())
        assert {name:row for name,row in b.items() if name not in a}=={'core0/_INT_clk_src_data_check_clk':['core0/_INT_clk_src_data_check_clk','internal','','no_constant']}
        assert 'core0/' in (guide/'guidance_path.rpt').read_text()
        output_db=guide/'guidance.db';output_fp=hierarchy_fingerprint(output_db)
        immutable();save(state='fresh_one_core_boundary_guidance_import_verified',native_exit_status=0,export_native=exported,guide_native=guided,native_evidence_sha256=evidence,generated_sha256=generated,output_database=str(output_db),output_database_fingerprint=output_fp,source_full_core_cells=94471,original_external_pins_preserved=3158,extra_unconnected_internal_guidance_pin_accounted=True,parent_signal_graph_constants_geometry_and_leaf_flags_preserved=True,original_typical_constraints_preserved=True,leaf_protection_explicitly_transferred=True,source_constraint_reference_sha256=source_constraint_references,cold_guidance_and_full_model_restoration_pending=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
