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
from tri_oracle_mapped_restore199 import constraints_equivalent
from tri_oracle_row_guard175_checkpoint import commands
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause

def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/unique216_constraint_control.json';log=root/'records/unique216_constraint_native.log'
    assert not result.exists() and not log.exists()
    green=json.loads((root/'records/unique215_canary_complete_result.json').read_text())
    assert green['temporary_build_removed'] is True and green['constant_driver_swap_rejected'] is True
    inputs=[Path(__file__).resolve(),root/'syn/tri_oracle_mapped_restore199.py',
            root/'syn/tri_oracle_row_guard175_checkpoint.py',root/'records/unique215_canary_complete_result.json']
    identities=dict(green['source_sha256'])
    identities.update({str(p):sha(p) for p in inputs})
    assert all(sha(p)==h for p,h in green['source_sha256'].items())
    tcl=BASE_TCL.replace('uniquify unique215_canary_top -verbose','write_sdc -view view $out/before.sdc\nuniquify unique215_canary_top -verbose')
    tcl=tcl.replace('tri215_require_equal $out before after','tri215_require_equal $out before after\nwrite_sdc -view view $out/after.sdc')
    tcl=tcl.replace('puts TRI215_BASE_READY\nexit','set_interactive_constraint_modes {functional}\nset_input_transition 0.123 [get_ports {a[0]}]\nwrite_sdc -view view $out/mutated.sdc\nputs TRI216_CONSTRAINT_CONTROL_EXPORTED\nexit')
    sdc='set_input_transition 0.05 [get_ports {a[0]}]\nset_load 0.01 [all_outputs]\n'
    available,anonymous=memory();assert available>16*1024**3 and anonymous<1024**3
    started=time.monotonic();child=pause=None;stopped=False;token=None
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),generated_tcl=tcl,generated_sdc=sdc,
        full_parent_constraints_qualified=False,full_paper_results_matched=False)
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    save()
    try:
        with tempfile.TemporaryDirectory(prefix='unique216_constraints_',dir=root/'.cache/physical') as folder:
            out=Path(folder);generated={}
            for name,text in [('canary.v',VERILOG),('canary_mmmc.tcl',MMMC),('canary.tcl',tcl),('canary.sdc',sdc)]:
                p=out/name;p.write_text(text);generated[str(p)]=sha(p)
            token=str(out/'native')
            command=['innovus','-stylus','-no_gui','-batch','-log',token,'-files',str(out/'canary.tcl')]
            with log.open('w') as stream:
                child=subprocess.Popen(command,cwd=out,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                    start_new_session=True,env=dict(os.environ,TRI215_ROOT=str(root),TRI215_OUT=str(out)))
                pause=OwnedProcessPause(child,token)
                policy=MemoryPressurePolicy(host_reserve_bytes=8*1024**3,resume_bytes=10*1024**3,anonymous_limit_bytes=3*1024**3)
                save(state='native_constraint_control_running',native_process_group=child.pid,command=command,generated_sha256=generated)
                try:
                    while child.poll() is None:
                        assert not stopped and time.monotonic()-started<240,'Constraint control wall/stop guard'
                        available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                        if action=='pause':pause.pause()
                        elif action=='resume':pause.resume()
                        record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                        time.sleep(.2)
                finally:
                    pause.resume();terminate_process_group(child,log_argument=token)
            text=log.read_text(errors='replace')
            assert child.returncode==0 and '\nTRI216_CONSTRAINT_CONTROL_EXPORTED\n' in text,text[-5000:]
            before,after,mutated=[commands(out/(name+'.sdc')) for name in ['before','after','mutated']]
            assert before and any(line.startswith('set_input_transition ') for line in before)
            assert constraints_equivalent(before,after),'Uniquification changed the actual canary constraints'
            assert not constraints_equivalent(before,mutated),'Non-period constraint drift was not rejected'
            assert all(sha(p)==h for p,h in identities.items()) and all(sha(p)==h for p,h in generated.items())
            evidence={str(log):sha(log)}
            for name in ['before','after','mutated']:
                p=root/'records'/('unique216_constraints_'+name+'.sdc');assert not p.exists()
                p.write_bytes((out/(name+'.sdc')).read_bytes());evidence[str(p)]=sha(p)
            save(state='native_constraint_export_preserved_and_nonperiod_drift_rejected',native_exit_status=0,
                native_evidence_sha256=evidence,actual_constraint_commands_preserved=True,
                changed_input_transition_rejected=True,before_commands=before,after_commands=after,mutated_commands=mutated)
        save(temporary_build_removed=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
