"""Observe native preservation properties on the complete full-model design."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy,OwnedProcessPause

def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/preservation232_diagnosis_result.json';out=root/'.cache/physical/pnr/tri_oracle_preservation232_diagnosis'
    assert not result.exists() and not out.exists()
    path=root/'records/frame202_placement_result.json';source=json.loads(path.read_text())
    assert source['state']=='full_core_geometric_placement_and_corner_diagnostics_completed'
    checkpoint=Path(source['output_database']);fingerprint=source['output_database_fingerprint']
    dependencies={Path(p):f for p,f in fingerprint.get('directory_dependencies',{}).items()}
    assert hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies)==fingerprint
    names=['run_tri_oracle_preservation232_diagnosis.py','tri_oracle_preservation232_diagnosis.tcl',
           'tri_oracle_row_guard173_variants.py','run_tri_oracle_row_guard175_synthesis.py',
           'tri_oracle_hierarchy_fingerprint.py','tri_oracle_artifact_fingerprint.py',
           'tri_oracle_process_guard.py','tri_oracle_memory_pressure_guard.py']
    identities={str(p):sha(p) for p in [path,*[root/'syn'/n for n in names],Path('/opt/cadence/bin/innovus')]}
    original_sdc=root/'.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213/constraints.sdc'
    assert sha(original_sdc)==source['source_sha256'][str(original_sdc)];identities[str(original_sdc)]=sha(original_sdc)
    started=time.monotonic();child=pause=None;stopped=False
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),scope='Read-only full-model preservation property diagnosis; no optimization or parent/paper qualification.',
        parent_timing_closed=False,full_paper_results_matched=False)
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        p=result.with_suffix('.tmp');p.write_text(json.dumps(record,indent=2)+'\n');p.replace(result)
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop);save()
    token=str(out/'native')
    try:
        available,anonymous=memory();assert available>18*1024**3 and anonymous<1024**3
        out.mkdir();console=out/'console.log'
        command=['innovus','-stylus','-no_gui','-batch','-log',token,'-files',str(root/'syn/tri_oracle_preservation232_diagnosis.tcl')]
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=out,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                start_new_session=True,env=dict(os.environ,TRI232_OUT=str(out),TRI232_INPUT=str(checkpoint)))
            pause=OwnedProcessPause(child,token)
            policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=16*1024**3)
            save(state='native_full_model_preservation_property_diagnosis_running',native_process_group=child.pid,output_directory=str(out),command=command)
            last=0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-started<600,'Clock diagnosis wall/stop guard'
                    available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                    if action=='pause':pause.pause()
                    elif action=='resume':pause.resume()
                    record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                    if time.monotonic()-last>5:save(native_elapsed_seconds=time.monotonic()-started);last=time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume();terminate_process_group(child,log_argument=token)
        text=console.read_text(errors='replace')
        assert child.returncode==0 and '\nTRI_ORACLE_RAW232_PROPERTIES_COLLECTED\n' in text,text[-4500:]
        assert all(sha(p)==h for p,h in identities.items())
        assert hierarchy_fingerprint(checkpoint,directory_dependencies=dependencies)==fingerprint
        evidence={str(p):sha(p) for p in out.iterdir() if p.is_file() and (p.suffix in ['.tsv','.sdc'] or p.name=='console.log')}
        diagnostics=[line for line in text.splitlines() if line.startswith('**ERROR:')]
        save(state='full_model_preservation_properties_collected',native_exit_status=0,native_error_diagnostics=diagnostics,
            native_evidence_sha256=evidence,source_database_unchanged=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=token)
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise

if __name__=='__main__':
    main()
