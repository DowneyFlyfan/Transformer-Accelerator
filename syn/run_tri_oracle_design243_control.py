"""Natively reject loss of inherited design-level preservation."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from run_tri_oracle_unique215_canary import VERILOG,MMMC
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group
WARM='set root $::env(TRI215_ROOT)\nset out $::env(TRI215_OUT)\nset_multi_cpu_usage -local_cpu 1\nset_db init_design_uniquify false\nread_mmmc $out/canary_mmmc.tcl\nread_physical -lefs [list \\\n $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \\\n $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef]\nread_netlist $out/canary.v -top unique215_canary_top\ninit_design\nsource $root/syn/tri_oracle_design242_metadata.tcl\nset_db [get_db current_design] .dont_touch true\ntri242_design_snapshot $out/source_design.tsv\nwrite_db $out/source.db\nputs TRI243_INHERITED_DESIGN_REFERENCE_SAVED\nexit\n'
COLD='set root $::env(TRI215_ROOT)\nset out $::env(TRI215_OUT)\nread_db $out/source.db\nset_multi_cpu_usage -local_cpu 1\nsource $root/syn/tri_oracle_unique215_snapshot.tcl\nsource $root/syn/tri_oracle_design242_metadata.tcl\ntri242_require_design $out/source_design.tsv $out/cold_design.tsv\ntri215_snapshot $out before_fault\nset_db [get_db current_design] .dont_touch none\ntri215_snapshot $out after_fault\nif {![catch {tri242_require_design $out/source_design.tsv $out/fault_design.tsv} reason] || $reason ne "TRI242_DESIGN_PRESERVATION_CHANGED"} {error TRI243_DESIGN_FLAG_LOSS_NOT_REJECTED}\nputs "TRI243_DESIGN_FLAG_LOSS_REJECTED $reason"\ntri242_restore_design $out/source_design.tsv\ntri242_require_design $out/source_design.tsv $out/restored_design.tsv\nforeach {name expected} {wrong TRI242_WRONG_DESIGN_METADATA_TARGET duplicate TRI242_BAD_DESIGN_LEDGER unsupported TRI242_UNSUPPORTED_DESIGN_FLAG} {\n    if {![catch {tri242_restore_design $out/$name.tsv} reason] || $reason ne $expected} {error "TRI243_BAD_LEDGER_NOT_REJECTED $name $reason"}\n    puts "TRI243_BAD_LEDGER_REJECTED $name $reason"\n}\ntri242_require_design $out/source_design.tsv $out/final_design.tsv\nputs TRI243_DESIGN_INHERITANCE_CONTROL_PASSED\nexit\n'

def main():
    root=Path(__file__).resolve().parents[1];result=root/'records/design243_native_control.json'
    assert not result.exists()
    producer_path=root/'records/preservation234_native_control.json'
    producer=json.loads(producer_path.read_text())
    assert producer['temporary_build_removed'] is True
    identities={str(producer_path):sha(producer_path)}
    for name,digest in producer['source_sha256'].items():assert sha(name)==digest;identities[name]=digest
    for p in [Path(__file__),root/'syn/tri_oracle_design242_metadata.tcl',Path('/opt/cadence/INNOVUS251/doc/DBcom/design.html')]:identities[str(p)]=sha(p)
    started=time.monotonic();child=pause=None;token=None;stopped=False
    record=dict(state='preflight',supervisor_pid=os.getpid(),started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=identities,generated_warm_tcl=WARM,generated_cold_tcl=COLD,native_workers=1,full_parent_qualified=False,full_paper_results_matched=False)
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop);save()
    try:
        available,anonymous=memory();assert available>18*1024**3 and anonymous<1024**3
        with tempfile.TemporaryDirectory(prefix='design243_',dir=root/'.cache/physical') as folder:
            out=Path(folder);generated={};evidence={}
            header='design\tdont_touch\n'
            sources={'canary.v':VERILOG,'canary_mmmc.tcl':MMMC,'canary.sdc':'# Structural inherited-preservation control.\n','warm.tcl':WARM,'cold.tcl':COLD,'wrong.tsv':header+'wrong_design\ttrue\n','duplicate.tsv':header+'unique215_canary_top\ttrue\nunique215_canary_top\ttrue\n','unsupported.tsv':header+'unique215_canary_top\tsize_ok\n'}
            for name,text in sources.items():
                p=out/name;p.write_text(text);generated[str(p)]=sha(p)
            save(generated_sources=sources,generated_sha256=generated)
            for phase,marker in [('warm','TRI243_INHERITED_DESIGN_REFERENCE_SAVED'),('cold','TRI243_DESIGN_INHERITANCE_CONTROL_PASSED')]:
                log=root/'records'/f'design243_{phase}_native.log';assert not log.exists();token=str(out/(phase+'_native'))
                command=['innovus','-stylus','-no_gui','-batch','-log',token,'-files',str(out/(phase+'.tcl'))];began=time.monotonic()
                with log.open('w') as stream:
                    child=subprocess.Popen(command,cwd=out,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,TRI215_ROOT=str(root),TRI215_OUT=str(out)))
                    pause=OwnedProcessPause(child,token);policy=MemoryPressurePolicy(host_reserve_bytes=8*1024**3,resume_bytes=10*1024**3,anonymous_limit_bytes=3*1024**3)
                    save(state='native_design_inheritance_control_running',phase=phase,native_process_group=child.pid,command=command)
                    try:
                        while child.poll() is None:
                            assert not stopped and time.monotonic()-began<240,'Design control wall/stop guard'
                            available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                            if action=='pause':pause.pause()
                            elif action=='resume':pause.resume()
                            record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                            time.sleep(.2)
                    finally:
                        pause.resume();terminate_process_group(child,log_argument=token)
                text=log.read_text(errors='replace');require_clean_native(text);assert child.returncode==0 and '\n'+marker+'\n' in text,text[-4000:]
                evidence[str(log)]=sha(log)
            for kind in ['cells','ports','nets','pins']:
                assert sorted((out/f'before_fault_{kind}.tsv').read_text().splitlines())==sorted((out/f'after_fault_{kind}.tsv').read_text().splitlines()),'Flag mutation changed other captured data '+kind
            ledgers=[(out/(tag+'_design.tsv')).read_text() for tag in ['source','cold','restored','final']];assert len(set(ledgers))==1
            assert (out/'fault_design.tsv').read_text()!=ledgers[0]
            assert all(sha(name)==digest for name,digest in identities.items()) and all(sha(name)==digest for name,digest in generated.items())
            for tag in ['source','cold','fault','restored','final']:
                p=root/'records'/f'design243_{tag}_design.tsv';assert not p.exists();p.write_bytes((out/(tag+'_design.tsv')).read_bytes());evidence[str(p)]=sha(p)
            save(state='native_inherited_design_flag_loss_rejected_and_exactly_restored',native_exit_status=0,design_level_true_to_none_loss_rejected=True,other_captured_metadata_and_graph_unchanged=True,exact_source_design_flag_restored=True,invalid_design_ledgers_rejected=3,native_evidence_sha256=evidence)
        save(temporary_build_removed=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
