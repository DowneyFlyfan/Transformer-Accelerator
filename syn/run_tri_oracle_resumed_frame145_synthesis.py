"""Resume full-parent synthesis from the verified connected pre-optimization snapshot."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def memory():
    available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
    anon=int(dict(x.split() for x in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available,anon


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/frame145_synthesis_result.json';assert not result.exists()
    output=root/'.cache/physical/synthesis/tri_oracle_predicted_feedforward_resumed145';assert not output.exists()
    producer_path=root/'records/frame144_preparation_result.json'
    producer=json.loads(producer_path.read_text());assert producer['state']=='native_parent_preoptimization_checkpoint_saved_pending_validation'
    prepared=Path(producer['output_directory']);mp=prepared/'elaborated_checkpoint_manifest.json';manifest=json.loads(mp.read_text())
    assert sha(mp)==producer['output_checkpoint_manifest_sha256']
    assert artifact_fingerprint(prepared/'elaborated.db')==manifest['checkpoint_fingerprint']
    assert all(sha(p)==h for p,h in manifest['source_sha256'].items())
    assert all(sha(p)==h for p,h in manifest['native_evidence_sha256'].items())
    assert sha(prepared/'compiled_cluster_sources.sv')==manifest['consumed_bundle_sha256']==producer['compiled_bundle_sha256']
    entry=root/'syn/tri_oracle_synthesize_resumed_frame145.tcl'
    inputs=[Path(__file__).resolve(),entry,producer_path,mp,prepared/'input_revision.json',prepared/'compiled_cluster_sources.sv',
        root/'syn/tri_oracle_validate_cold_restore145.py',root/'syn/tri_oracle_artifact_fingerprint.py',
        root/'syn/tri_oracle_memory_pressure_guard.py',root/'syn/tri_oracle_process_guard.py',
        root/'records/genus144_control_query.log',Path('/opt/cadence/GENUS251/doc/genus_attref/control_logic_optimization.html')]
    identities=dict(manifest['source_sha256']);identities.update({str(p):sha(p) for p in inputs})
    started=time.monotonic();child=None;pause=None;lock=None;stop_requested=False
    record=dict(state='preflight',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),supervisor_pid=os.getpid(),
        source_sha256=identities,producer_checkpoint_fingerprint=manifest['checkpoint_fingerprint'],
        control_logic_optimization='none',generic_optimization_effort='low',technology_mapping_effort='medium',final_optimization_effort='medium',
        maximum_requested_cpu_workers=18,native_anonymous_limit_bytes=16*1024**3,host_reserve_bytes=5*1024**3,
        full_paper_results_matched=False,routed_timing_qualified=False,
        scope='Cold-resumed full20-core parent with25 mapped controllers and40 aggregate memories, supported control-logic optimization disabled. Same original1.72414ns clock and IO constraints. Core80 timing model remains provisional; full physical models and mapped-function checks are still required.')
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        temp=result.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(result)
    def stop(signum,frame):
        nonlocal stop_requested
        stop_requested=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    save()
    try:
        while True:
            available,anon=memory()
            if available>14*1024**3 and anon<3*1024**3:break
            assert not stop_requested and time.monotonic()-started<7200,'Resume memory headroom wait expired'
            save(state='waiting_for_initial_memory_headroom');time.sleep(2)
        output.mkdir();lock=(output/'guard.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        (output/'input_revision.json').write_text(json.dumps(dict(source_sha256=identities,producer_checkpoint_fingerprint=manifest['checkpoint_fingerprint'],prepared_output=str(prepared)),indent=2)+'\n')
        console=output/'console.log';log_argument=str(output/'native');native_started=time.monotonic()
        command=['genus','-no_gui','-batch','-log',log_argument,'-files',str(entry)]
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                env=dict(os.environ,TRI_ORACLE_SYNTH_OUTPUT=str(output),TRI_ORACLE_PREOPT_SOURCE=str(prepared)))
            pause=OwnedProcessPause(child,log_argument)
            policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=16*1024**3)
            save(state='native_resumed_parent_synthesis_running',native_process_group=child.pid,command=command,output_directory=str(output))
            last_save=0
            while child.poll() is None:
                assert not stop_requested,'External stop requested'
                assert time.monotonic()-native_started<7200,'Resumed synthesis wall budget'
                available,anon=memory();action=policy.observe(available,anon,time.monotonic())
                if action in ['pause','resume']:
                    groups=pause.pause() if action=='pause' else pause.resume()
                    save(memory_pressure_events=record.get('memory_pressure_events',[])+[dict(action=action,groups=groups,available=available,anon=anon)])
                record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anon)
                if time.monotonic()-last_save>5:
                    save(native_elapsed_seconds=time.monotonic()-native_started,current_host_available_bytes=available,current_combined_anonymous_bytes=anon);last_save=time.monotonic()
                time.sleep(.2)
            pause.resume();terminate_process_group(child,log_argument=log_argument)
        text=console.read_text(errors='replace')
        assert child.returncode==0 and '\nTRI_ORACLE_FRAME145_SYNTHESIS_PASS tri_oracle_predicted_feedforward_frame\n' in text,console
        assert all(sha(p)==h for p,h in identities.items()),'Changed resume input'
        assert artifact_fingerprint(prepared/'elaborated.db')==manifest['checkpoint_fingerprint']
        save(state='native_parent_mapping_completed_pending_report_review',native_exit_status=0,native_elapsed_seconds=time.monotonic()-native_started,
            console_sha256=sha(console),output_netlist_sha256=sha(output/'netlist.v'),cold_restore_validation_sha256=sha(output/'cold_restore_validation.json'))
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=str(output/'native'))
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise
    finally:
        if lock is not None:lock.close()


if __name__=='__main__':main()
