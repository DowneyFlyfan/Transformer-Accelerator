"""Cold-read the qualified guide, then fresh-import and cold-read full models."""
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
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_core_preservation import verify_core_snapshots
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group

def main():
    root=Path(__file__).resolve().parents[1];base=root/'.cache/physical'
    result=root/'records/fresh241_roundtrip_result.json';out=base/'pnr/tri_oracle_fresh_roundtrip241'
    assert not result.exists() and not out.exists()
    source_path=root/'records/fresh239_probe_result.json';source=json.loads(source_path.read_text())
    assert source['state']=='fresh_one_core_boundary_guidance_import_verified'
    assert source['source_full_core_cells']==94471 and source['original_external_pins_preserved']==3158
    guide_db=Path(source['output_database']);guide_fp=source['output_database_fingerprint'];reference=Path(source['output_directory'])
    assert hierarchy_fingerprint(guide_db)==guide_fp
    identities={str(source_path):sha(source_path)}
    for mapping in [source['source_sha256'],source['native_evidence_sha256'],source['generated_sha256']]:
        for name,digest in mapping.items():
            assert sha(name)==digest and (name not in identities or identities[name]==digest)
            identities[name]=digest
    imported_path=root/'records/frame207_import_result.json';imported=json.loads(imported_path.read_text())
    canonical=base/'pnr/tri_oracle_sram_memory_compute/hierarchy_twenty_core_75_inputs/wrapper.v'
    assert sha(canonical)==imported['source_sha256'][str(canonical)]
    full_path=root/'records/sram_core_hierarchy68_full_control_validation.json';full=json.loads(full_path.read_text())
    full_dir=base/'pnr/tri_oracle_sram_memory_compute/hierarchy_full_control_68'
    assert artifact_fingerprint(full_dir)==full['output_artifact_fingerprint']
    deps={full_dir/'ilm':{'type':'directory','files':{name[4:]:value for name,value in full['output_artifact_fingerprint']['files'].items() if name.startswith('ilm/')}}}
    libraries={};rcs={}
    for corner,suffix,rc in [('slow','ssg0p9v125c','qrc_rcworst'),('typ','tt1v25c','qrc_typical'),('fast','ffg1p05vm40c','qrc_rcbest')]:
        libraries[corner]=[base/f'library/tcbn28hpcplusbwp12t40p140{suffix}.lib',base/f'sram/core_weights_masks_01/ts5n28hpcpsvta32x128m2fw_130a/NLDM/ts5n28hpcpsvta32x128m2fw_130a_{suffix}.lib',base/f'sram/core_outputs_01/ts6n28hpcpsvta16x128m2f_130a/NLDM/ts6n28hpcpsvta16x128m2f_130a_{suffix}.lib',base/f'sram/activation_cache_banks_01/ts5n28hpcpsvta512x64m4f_130a/NLDM/ts5n28hpcpsvta512x64m4f_130a_{suffix}.lib']
        rcs[corner]=base/'rc'/rc
        for p in libraries[corner]+[rcs[corner]]:
            assert sha(p)==imported['source_sha256'][str(p)];identities[str(p)]=sha(p)
    entry=root/'syn/tri_oracle_fresh_roundtrip241.tcl'
    for p in [Path(__file__),entry,full_path,imported_path,canonical]:identities[str(p)]=sha(p)
    names=['tri_oracle_unique215_snapshot.tcl','tri_oracle_row_guard173_variants.py','run_tri_oracle_row_guard175_synthesis.py','tri_oracle_artifact_fingerprint.py','tri_oracle_hierarchy_fingerprint.py','tri_oracle_core_preservation.py','tri_oracle_mapped_restore199.py','tri_oracle_row_guard175_checkpoint.py','tri_oracle_native_diagnostics.py','tri_oracle_memory_pressure_guard.py','tri_oracle_process_guard.py']
    for name in names:identities[str(root/'syn'/name)]=sha(root/'syn'/name)
    started=time.monotonic();child=pause=None;token=None;stopped=False;evidence={};generated={};restored_db=restored_fp=None
    record=dict(state='preflight',supervisor_pid=os.getpid(),started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=identities,native_workers=8,anonymous_limit_bytes=8*1024**3,host_reserve_bytes=8*1024**3,guidance_model_timing_equivalent=False,parent_electrical_repair_completed=False,full_paper_results_matched=False,scope='One-core cold guidance and separate fresh full68 import/cold restore. Per-corner source constraints remain separate. Exact original94471 cells/28memories, parent graph/geometry/leaf attributes and3158physicalpins required. No optimization or routed-parent timing claim.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def immutable():
        assert all(sha(p)==h for p,h in identities.items())
        assert all(sha(p)==h for p,h in evidence.items()) and all(sha(p)==h for p,h in generated.items())
        assert hierarchy_fingerprint(guide_db)==guide_fp
        assert artifact_fingerprint(full_dir)==full['output_artifact_fingerprint']
        if restored_db is not None:assert hierarchy_fingerprint(restored_db,directory_dependencies=deps)==restored_fp
    def native(mode,input_db,marker):
        nonlocal child,pause,token
        directory=out/mode;directory.mkdir();console=directory/'console.log';token=str(directory/'native')
        cmd=['innovus','-stylus','-no_gui','-batch','-log',token,'-files',str(entry)];began=time.monotonic()
        with console.open('w') as stream:
            child=subprocess.Popen(cmd,cwd=directory,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,TRI241_OUT=str(directory),TRI241_PARENT=str(out),TRI241_MODE=mode,TRI241_INPUT=str(input_db)))
            pause=OwnedProcessPause(child,token);policy=MemoryPressurePolicy(host_reserve_bytes=8*1024**3,resume_bytes=10*1024**3,anonymous_limit_bytes=8*1024**3)
            save(state='native_'+mode+'_running',phase=mode,native_process_group=child.pid,command=cmd);last=0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-began<600,'Fresh roundtrip wall/stop guard'
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
            if p.is_file() and (p.suffix in ['.tsv','.sdc','.rpt','.v','.def'] or p.name=='console.log'):evidence[str(p)]=sha(p)
        return dict(native_exit_status=0,elapsed_seconds=time.monotonic()-began,console_sha256=sha(console))
    def parent_equal(directory,tag):
        for kind in ['cells','ports','nets','pins']:
            paths=[]
            for folder,prefix in [(reference/'export','original'),(directory,tag)]:
                p=folder/f'{prefix}_{kind}.tsv';ordered=p.with_suffix('.tsv.sorted')
                if folder==directory:
                    subprocess.run(['sort','-S','64M','-T',str(out),'-o',str(ordered),str(p)],env=dict(os.environ,LC_ALL='C'),check=True,timeout=120);evidence[str(ordered)]=sha(ordered)
                paths.append(ordered)
            assert filecmp.cmp(*paths,shallow=False),'Restored parent differs '+tag+' '+kind
    def check_pins(path,guidance=False):
        def table(p):
            rows=[line.split('\t') for line in p.read_text().splitlines()[1:]];assert len(rows)==len({row[0] for row in rows});return {row[0]:row for row in rows}
        a=table(reference/'export/original_core_pins.tsv');b=table(path);assert len(a)==3158 and all(b.get(name)==row for name,row in a.items())
        extra={name:row for name,row in b.items() if name not in a};assert extra==({'core0/_INT_clk_src_data_check_clk':['core0/_INT_clk_src_data_check_clk','internal','','no_constant']} if guidance else {})
    save()
    try:
        available,anonymous=memory();assert available>18*1024**3 and anonymous<1024**3
        immutable();out.mkdir();save(output_directory=str(out))
        cold_guide=native('cold_guide',guide_db,'TRI_ORACLE_FRESH241_COLD_GUIDANCE_EXPORTED')
        parent_equal(out/'cold_guide','cold_guide');check_pins(out/'cold_guide/cold_guide_core_pins.tsv',True)
        assert constraints_equivalent(commands(reference/'export/setup_typ.sdc'),commands(out/'cold_guide/setup_typ.sdc'))
        mapped=(out/'cold_guide/parent.v').read_text();pattern=re.compile(r'^\s*module\s+tri_oracle_sram_memory_compute\s*\(',re.M)
        if not pattern.search(mapped):
            canonical_text=canonical.read_text();starts=list(pattern.finditer(canonical_text));assert len(starts)==1
            end=re.search(r'^\s*endmodule\s*$',canonical_text[starts[0].start():],re.M);assert end
            mapped+='\n'+canonical_text[starts[0].start():starts[0].start()+end.end()]+'\n'
        p=out/'parent_import.v';p.write_text(mapped);generated[str(p)]=sha(p)
        mmmc=''
        for corner,view,temp in [('slow','setup_slow',125),('typ','setup_typ',25),('fast','hold_fast',-40)]:
            mmmc+='create_library_set -name ls_'+corner+' -timing [list '+' '.join('{'+str(p)+'}' for p in libraries[corner])+']\n'
            mmmc+=f'create_rc_corner -name rc_{corner} -qrc_tech {{{rcs[corner]}}} -temperature {temp}\ncreate_timing_condition -name tc_{corner} -library_sets {{ls_{corner}}}\ncreate_delay_corner -name dc_{corner} -timing_condition tc_{corner} -rc_corner rc_{corner}\n'
            mmmc+=f'create_constraint_mode -name functional_{corner} -sdc_files [list {{{reference}/export/{view}.sdc}}]\nupdate_constraint_mode -name functional_{corner} -ilm_sdc_files [list {{{reference}/export/{view}.sdc}}]\ncreate_analysis_view -name {view} -constraint_mode functional_{corner} -delay_corner dc_{corner}\n'
        mmmc+='set_analysis_view -setup {setup_slow setup_typ} -hold {hold_fast}\n';assert 'core_typ.lib' not in mmmc
        p=out/'full_mmmc.tcl';p.write_text(mmmc);generated[str(p)]=sha(p);immutable();save(generated_sha256=generated,native_evidence_sha256=evidence,cold_guide_native=cold_guide)
        fresh=native('fresh_full',guide_db,'TRI_ORACLE_FRESH241_FULL_MODEL_VERIFIED fresh_full')
        parent_equal(out/'fresh_full','before_full');parent_equal(out/'fresh_full','restored_parent')
        check_pins(out/'fresh_full/before_full_core_pins.tsv');check_pins(out/'fresh_full/restored_core_pins.tsv')
        restored_db=out/'fresh_full/restored_full.db';restored_fp=hierarchy_fingerprint(restored_db,directory_dependencies=deps)
        immutable();save(state='fresh_full_model_restored_cold_validation_pending',output_database=str(restored_db),output_database_fingerprint=restored_fp,fresh_full_native=fresh,native_evidence_sha256=evidence)
        cold=native('cold_full',restored_db,'TRI_ORACLE_FRESH241_FULL_MODEL_VERIFIED cold_full')
        parent_equal(out/'cold_full','restored_parent');check_pins(out/'cold_full/restored_core_pins.tsv')
        preserves={}
        for phase in ['fresh_full','cold_full']:
            preserves[phase]=verify_core_snapshots(reference/'export/full_before.tsv',out/phase/'core_cells.tsv',['core0']);assert preserves[phase]['total_original_cells']==94471
            for view in ['setup_slow','setup_typ','hold_fast']:assert constraints_equivalent(commands(reference/'export'/f'{view}.sdc'),commands(out/phase/f'{view}.sdc')),'Full original corner constraints differ '+phase+' '+view
            status=(out/phase/'model_status.rpt').read_text();assert len(re.findall(r'\bAll\s+ILM\s+post-cts\s+',status))==1 and 'current ilm data is for si mode' in status.lower()
        immutable();save(state='cold_guidance_fresh_full_import_and_cold_original_core_restore_verified',native_exit_status=0,cold_guide_native=cold_guide,fresh_full_native=fresh,cold_full_native=cold,original_core_preservation=preserves,all3_original_corner_constraints_preserved=True,all_original3158_pin_rows_restored=True,parent_graph_geometry_constants_and_leaf_flags_preserved=True,native_evidence_sha256=evidence,generated_sha256=generated,full_parent_guided_optimization_pending=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
