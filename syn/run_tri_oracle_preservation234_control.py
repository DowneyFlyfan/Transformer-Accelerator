"""Check actual Innovus constraint export and non-period drift rejection."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from run_tri_oracle_unique215_canary import VERILOG,MMMC,BASE_TCL
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause

WARM='set root $::env(TRI215_ROOT)\nset out $::env(TRI215_OUT)\nset_multi_cpu_usage -local_cpu 1\nset_db init_design_uniquify false\nread_mmmc $out/canary_mmmc.tcl\nread_physical -lefs [list \\\n $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \\\n $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef]\nread_netlist $out/canary.v -top unique215_canary_top\ninit_design\nsource $root/syn/tri_oracle_preservation233.tcl\ntri233_preservation $out/canary.sdc $out/before_targets.tsv 2\nuniquify unique215_canary_top -verbose\ntri233_preservation $out/canary.sdc $out/after_targets.tsv 2\nwrite_sdc -view view $out/before.sdc\nwrite_db $out/canary.db\nputs TRI234_WARM_PRESERVATION_SAVED\nexit\n'
COLD='set root $::env(TRI215_ROOT)\nset out $::env(TRI215_OUT)\nread_db $out/canary.db\nset_multi_cpu_usage -local_cpu 1\nsource $root/syn/tri_oracle_unique215_snapshot.tcl\nsource $root/syn/tri_oracle_preservation233.tcl\ntri233_preservation $out/canary.sdc $out/cold_targets.tsv 2\ntri215_snapshot $out before_fault\nset_interactive_constraint_modes {functional}\nset_dont_touch [get_cells clone0] false\ntri215_snapshot $out after_fault\nwrite_sdc -view view $out/mutated.sdc\nif {![catch {tri233_preservation $out/canary.sdc $out/fault_targets.tsv 2} reason] ||\n    $reason ne "TRI223_PRESERVATION_TARGET_NOT_PROTECTED clone0"} {error TRI234_HIERARCHICAL_FAULT_NOT_REJECTED}\nputs "TRI234_HIERARCHICAL_FAULT_REJECTED $reason"\nupdate_constraint_mode -name functional -sdc_files [list $out/canary.sdc]\nif {![catch {tri233_preservation $out/canary.sdc $out/after_reload_fault_targets.tsv 2} reason] ||\n    $reason ne "TRI223_PRESERVATION_TARGET_NOT_PROTECTED clone0"} {error TRI234_RELOAD_BEHAVIOR_CHANGED}\nputs "TRI234_FAULT_STILL_REJECTED_AFTER_MODE_RELOAD $reason"\nset_dont_touch [get_cells clone0] true\ntri233_preservation $out/canary.sdc $out/restored_targets.tsv 2\nforeach {name expected} {\n    duplicate TRI223_DUPLICATE_PRESERVATION_TARGET\n    missing TRI223_PRESERVATION_TARGET_COUNT\n    wrong TRI223_PRESERVATION_TARGET_NOT_UNIQUE\n    pattern TRI223_PRESERVATION_TARGET_NAME_CHANGED\n    unsupported TRI223_UNSUPPORTED_PRESERVATION_SELECTOR\n} {\n    if {![catch {tri233_preservation $out/$name.sdc $out/[set name]_targets.tsv 2} reason] ||\n        [lindex $reason 0] ne $expected} {error "TRI234_SELECTOR_FAULT_NOT_REJECTED $name $reason"}\n    puts "TRI234_SELECTOR_FAULT_REJECTED $name $reason"\n}\nputs TRI234_COLD_PRESERVATION_CONTROL_PASSED\nexit\n'

def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/preservation234_native_control.json'
    assert not result.exists()
    names=['run_tri_oracle_preservation234_control.py','tri_oracle_preservation233.tcl',
           'run_tri_oracle_unique215_canary.py','tri_oracle_unique215_snapshot.tcl',
           'tri_oracle_native_diagnostics.py','tri_oracle_row_guard173_variants.py',
           'run_tri_oracle_row_guard175_synthesis.py','tri_oracle_memory_pressure_guard.py',
           'tri_oracle_process_guard.py','tri_oracle_mapped_restore199.py','tri_oracle_row_guard175_checkpoint.py']
    green=json.loads((root/'records/unique215_canary_complete_result.json').read_text())
    identities=dict(green['source_sha256'])
    for name in names:identities[str(root/'syn'/name)]=sha(root/'syn'/name)
    assert all(sha(p)==h for p,h in green['source_sha256'].items())
    guard_path=root/'records/native233_error_controls.json'
    guard=json.loads(guard_path.read_text())
    assert guard['state']=='shared_native_error_guard_preserved_actual_clean_and_failure_classification'
    for name,digest in guard['source_sha256'].items():assert sha(name)==digest
    for check in guard['after_checks']:
        assert sha(check['console'])==check['sha256'];identities[check['console']]=check['sha256']
    identities[str(guard_path)]=sha(guard_path)
    available,anonymous=memory();assert available>18*1024**3 and anonymous<1024**3
    started=time.monotonic();child=pause=None;token=None;stopped=False
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),native_workers=1,
        generated_verilog=VERILOG,generated_mmmc=MMMC,generated_warm_tcl=WARM,generated_cold_tcl=COLD,
        full_parent_preservation_qualified=False,full_paper_results_matched=False)
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop);save()
    try:
        with tempfile.TemporaryDirectory(prefix='preservation234_',dir=root/'.cache/physical') as folder:
            out=Path(folder);generated={};evidence={}
            sdc='set_input_transition 0.05 [get_ports {a[0]}]\nset_load 0.01 [all_outputs]\nset_dont_touch [get_cells clone0]\nset_dont_touch [get_cells probe]\n'
            sources={'canary.v':VERILOG,'canary_mmmc.tcl':MMMC,'canary.sdc':sdc,'warm.tcl':WARM,'cold.tcl':COLD,
                'duplicate.sdc':'set_dont_touch [get_cells clone0]\nset_dont_touch [get_cells clone0]\n',
                'missing.sdc':'set_dont_touch [get_cells clone0]\n',
                'wrong.sdc':'set_dont_touch [get_cells clone0]\nset_dont_touch [get_cells missing_target]\n',
                'pattern.sdc':'set_dont_touch [get_cells clone0]\nset_dont_touch [get_cells {prob?}]\n',
                'unsupported.sdc':'set_dont_touch [get_cells clone0] false\nset_dont_touch [get_cells probe]\n'}
            for name,text in sources.items():
                p=out/name;p.write_text(text);generated[str(p)]=sha(p)
            save(generated_sources=sources,generated_sha256=generated)
            for phase,marker in [('warm','TRI234_WARM_PRESERVATION_SAVED'),('cold','TRI234_COLD_PRESERVATION_CONTROL_PASSED')]:
                log=root/'records'/f'preservation234_{phase}_native.log';assert not log.exists()
                token=str(out/(phase+'_native'))
                command=['innovus','-stylus','-no_gui','-batch','-log',token,'-files',str(out/(phase+'.tcl'))]
                began=time.monotonic()
                with log.open('w') as stream:
                    child=subprocess.Popen(command,cwd=out,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                        start_new_session=True,env=dict(os.environ,TRI215_ROOT=str(root),TRI215_OUT=str(out)))
                    pause=OwnedProcessPause(child,token)
                    policy=MemoryPressurePolicy(host_reserve_bytes=8*1024**3,resume_bytes=10*1024**3,anonymous_limit_bytes=3*1024**3)
                    save(state='native_hierarchical_preservation_control_running',phase=phase,native_process_group=child.pid,command=command)
                    try:
                        while child.poll() is None:
                            assert not stopped and time.monotonic()-began<240,'Preservation control wall/stop guard'
                            available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                            if action=='pause':pause.pause()
                            elif action=='resume':pause.resume()
                            record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                            time.sleep(.2)
                    finally:
                        pause.resume();terminate_process_group(child,log_argument=token)
                text=log.read_text(errors='replace');require_clean_native(text)
                assert child.returncode==0 and '\n'+marker+'\n' in text,text[-4000:]
                evidence[str(log)]=sha(log)
            ledgers=[(out/(n+'_targets.tsv')).read_text() for n in ['before','after','cold','restored']]
            assert len(set(ledgers))==1
            before,mutated=commands(out/'before.sdc'),commands(out/'mutated.sdc')
            assert before and constraints_equivalent(before,mutated),'Unexpected timing export change on dont_touch mutation'
            for kind in ['ports','nets','pins']:
                assert sorted((out/f'before_fault_{kind}.tsv').read_text().splitlines())==sorted((out/f'after_fault_{kind}.tsv').read_text().splitlines())
            leaf=lambda tag:sorted('\t'.join(line.split('\t')[:5]) for line in (out/(tag+'_cells.tsv')).read_text().splitlines())
            assert leaf('before_fault')==leaf('after_fault')
            assert all(sha(p)==h for p,h in identities.items()) and all(sha(p)==h for p,h in generated.items())
            for name in ['before_targets.tsv','after_targets.tsv','cold_targets.tsv','fault_targets.tsv','after_reload_fault_targets.tsv','restored_targets.tsv','before.sdc','mutated.sdc']:
                target=root/'records'/('preservation234_'+name);assert not target.exists();target.write_bytes((out/name).read_bytes());evidence[str(target)]=sha(target)
            save(state='hierarchical_preservation_loss_rejected_before_reference_reload',native_exit_status=0,
                 native_evidence_sha256=evidence,hierarchical_flag_loss_rejected=True,reference_reload_restored_flag=False,explicit_restore_passed=True,
                 unchanged_timing_export_and_leaf_geometry=True,selector_negative_controls=5)
        save(temporary_build_removed=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
