"""Natively test module uniqueness and complete signal-graph preservation."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group

VERILOG = "module unique215_leaf(input a,b,output y);\nXOR2D1BWP12T40P140 u(.A1(a),.A2(b),.Z(y));\nendmodule\nmodule unique215_canary_top(input [2:0] a,b,output [4:0] y);\nunique215_leaf clone0(.a(a[0]),.b(b[0]),.y(y[0]));\nunique215_leaf clone1(.a(a[1]),.b(b[1]),.y(y[1]));\nXOR2D1BWP12T40P140 probe(.A1(a[0]),.A2(b[0]),.Z(y[2]));\nXOR2D1BWP12T40P140 const0_probe(.A1(1'b0),.A2(a[2]),.Z(y[3]));\nXOR2D1BWP12T40P140 const1_probe(.A1(1'b1),.A2(b[2]),.Z(y[4]));\nendmodule\n"
MMMC = 'set root $::env(TRI215_ROOT)\nset out $::env(TRI215_OUT)\ncreate_library_set -name tiny -timing [list $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140tt1v25c.lib]\ncreate_rc_corner -name rc -temperature 25\ncreate_timing_condition -name tc -library_sets {tiny}\ncreate_delay_corner -name dc -timing_condition tc -rc_corner rc\ncreate_constraint_mode -name functional -sdc_files [list $out/canary.sdc]\ncreate_analysis_view -name view -constraint_mode functional -delay_corner dc\nset_analysis_view -setup {view} -hold {view}\n'
BASE_TCL = 'set root $::env(TRI215_ROOT)\nset out $::env(TRI215_OUT)\nset_multi_cpu_usage -local_cpu 1\nset_db init_design_uniquify false\nread_mmmc $out/canary_mmmc.tcl\nread_physical -lefs [list \\\n $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \\\n $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef]\nread_netlist $out/canary.v -top unique215_canary_top\ninit_design\nsource $root/syn/tri_oracle_unique215_snapshot.tcl\nif {[check_unique -verbose] != 0} {error TRI215_CANARY_DID_NOT_EXPOSE_CLONES}\nif {[tri215_snapshot $out before] != 5} {error TRI215_CANARY_WRONG_LEAF_COUNT}\nuniquify unique215_canary_top -verbose\nif {[check_unique -verbose] != 1} {error TRI215_CANARY_UNIQUIFY_FAILED}\ntri215_snapshot $out after\ntri215_require_equal $out before after\nconnect_pin -inst probe -pin A1 -net {a[1]}\ntri215_snapshot $out fault\nif {![catch {tri215_require_equal $out before fault} message] ||\n    $message ne "TRI215_SIGNAL_GRAPH_CHANGED nets"} {error TRI215_CANARY_WRONG_WIRING_NOT_REJECTED}\nconnect_pin -inst probe -pin A1 -net {a[0]}\ntri215_snapshot $out restored\ntri215_require_equal $out before restored\nset found 0\nforeach instance [get_db insts] {\n if {![regexp {^const([01])_probe$} [get_db $instance .name] -> expected]} {continue}\n foreach pin [get_db $instance .pins] {\n  if {[file tail [get_db $pin .base_pin.name]] ne "A1"} {continue}\n  if {[get_db $pin .constant] ne $expected} {error TRI215_DIRECT_CONSTANT_FIXTURE_MISSING}\n  incr found\n }\n}\nif {$found != 2} {error TRI215_CONSTANT_PIN_COUNT}\nputs TRI215_BASE_READY\nexit\n'
FAULT_TCL = 'set root $::env(TRI215_ROOT)\nset out $::env(TRI215_OUT)\nset_multi_cpu_usage -local_cpu 1\nset_db init_design_uniquify false\nread_mmmc $out/canary_mmmc.tcl\nread_physical -lefs [list \\\n $root/.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef \\\n $root/.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef]\nread_netlist $out/canary.v -top unique215_canary_top\ninit_design\nsource $root/syn/tri_oracle_unique215_snapshot.tcl\nuniquify unique215_canary_top -verbose\nif {[check_unique] != 1} {error TRI215_FAULT_TOP_NOT_UNIQUE}\nset baseline $::env(TRI215_BASELINE)\ntri215_snapshot $baseline constant_fault\nif {![catch {tri215_require_equal $baseline before constant_fault} message] ||\n    $message ni {"TRI215_SIGNAL_GRAPH_CHANGED nets" "TRI215_SIGNAL_GRAPH_CHANGED pins"}} {\n error TRI215_CANARY_WRONG_CONSTANT_NOT_REJECTED\n}\nputs TRI215_DIFFERENT_CONSTANTS_REJECTED\nexit\n'

def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/unique215_canary_complete_result.json'
    assert not result.exists()
    names=['run_tri_oracle_unique215_canary.py','tri_oracle_unique215_snapshot.tcl','tri_oracle_row_guard173_variants.py',
           'run_tri_oracle_row_guard175_synthesis.py','tri_oracle_memory_pressure_guard.py','tri_oracle_process_guard.py']
    inputs=[root/'syn'/n for n in names]+[
        root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140tt1v25c.lib',
        root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140.lef',
        root/'.cache/physical/routing_kit/N28_PRTF_Cad_v1d5a/PR_tech/Cadence/LefHeader/VHV/tsmcn28_10lm5X2Y2ZUTRDL.tlef',
        Path('/opt/cadence/bin/innovus')]
    identities={str(p):sha(p) for p in inputs}
    available,anonymous=memory();assert available>16*1024**3 and anonymous<1024**3
    started=time.monotonic();child=pause=None;stopped=False;log_token=None
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),generated_verilog=VERILOG,
        generated_tcl=BASE_TCL,generated_fault_tcl=FAULT_TCL,generated_mmmc=MMMC,
        full_parent_uniquified=False,full_paper_results_matched=False,native_workers=1)
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    save()
    try:
        with tempfile.TemporaryDirectory(prefix='unique215_pair_',dir=root/'.cache/physical') as folder:
            parent=Path(folder);baseline=parent/'baseline';evidence={};generated={}
            for phase,source,entry,marker in [
                ('baseline',VERILOG,BASE_TCL,'TRI215_BASE_READY'),
                ('constant_fault',VERILOG.replace("1'b0",'CONST_SWAP').replace("1'b1","1'b0").replace('CONST_SWAP',"1'b1"),
                 FAULT_TCL,'TRI215_DIFFERENT_CONSTANTS_REJECTED')]:
                out=parent/phase;out.mkdir()
                for n,text in [('canary.v',source),('canary.tcl',entry),('canary_mmmc.tcl',MMMC),('canary.sdc','# Clockless structural canary.\n')]:
                    p=out/n;p.write_text(text);generated[str(p)]=sha(p)
                log=root/'records'/('unique215_canary_complete_'+phase+'_native.log');assert not log.exists()
                log_token=str(out/'native');command=['innovus','-stylus','-no_gui','-batch','-log',log_token,'-files',str(out/'canary.tcl')]
                began=time.monotonic()
                with log.open('w') as stream:
                    child=subprocess.Popen(command,cwd=out,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                        start_new_session=True,env=dict(os.environ,TRI215_ROOT=str(root),TRI215_OUT=str(out),TRI215_BASELINE=str(baseline)))
                    pause=OwnedProcessPause(child,log_token)
                    policy=MemoryPressurePolicy(host_reserve_bytes=8*1024**3,resume_bytes=10*1024**3,anonymous_limit_bytes=3*1024**3)
                    save(state='native_canary_running',phase=phase,native_process_group=child.pid,command=command)
                    last=0
                    try:
                        while child.poll() is None:
                            assert not stopped and time.monotonic()-began<240,'Canary wall/stop guard'
                            available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                            if action=='pause':pause.pause()
                            elif action=='resume':pause.resume()
                            record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                            if time.monotonic()-last>5:save(native_elapsed_seconds=time.monotonic()-began);last=time.monotonic()
                            time.sleep(.2)
                    finally:
                        pause.resume();terminate_process_group(child,log_argument=log_token)
                text=log.read_text(errors='replace')
                assert child.returncode==0 and '\n'+marker+'\n' in text,text[-5000:]
                evidence[str(log)]=sha(log)
                assert all(sha(p)==h for p,h in identities.items()) and all(sha(p)==h for p,h in generated.items())
            save(state='native_uniquification_preserved_graph_and_wiring_constant_faults_rejected',
                native_exit_status=0,native_evidence_sha256=evidence,flat_leaf_cells=5,
                positive_graph_preservation=True,wrong_driver_connection_rejected=True,constant_driver_swap_rejected=True,
                restored_graph_preservation=True)
        save(temporary_build_removed=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=log_token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
