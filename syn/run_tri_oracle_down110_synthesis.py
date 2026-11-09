"""Diagnose the existing sparse down controller at the actual slow library corner."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def main():
    root=Path(__file__).resolve().parents[1]
    result=root/'records/down110_synthesis_result.json'
    output=root/'.cache/physical/synthesis/tri_oracle_down_executor110'
    assert not result.exists() and not output.exists()
    started=time.monotonic();child=None;pause=None;lock=None;stop_requested=False
    qpath=root/'records/predicted101_functional_qualification.json'
    entry=root/'syn/tri_oracle_synthesize_down110.tcl'
    library=root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib'
    record=dict(state='preflight',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                supervisor_pid=os.getpid(),requested_maximum_cpu_workers=18,full_paper_results_matched=False,
                scope='Existing sparse down controller mapped against slow0.9V125C standard cells. No compiled-memory/full-parent integration, routed parasitics or routed timing acceptance.')
    def sha(path):
        with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    def save(**updates):
        record.update(updates,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    def memory():
        available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
        anonymous=int(dict(x.split() for x in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
        return available,anonymous
    def stop(signum,frame):
        nonlocal stop_requested
        stop_requested=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    save()
    try:
        prerequisite=json.loads(qpath.read_text());assert prerequisite['state']=='joined_prepared_prediction_numeric_frame_source_functional_qualified'
        assert all(sha(p)==h for p,h in prerequisite['current_source_sha256'].items())
        identities={str(p):sha(p) for p in [Path(__file__).resolve(),entry,library,qpath,
            root/'verilog/tri_oracle_down_executor.sv',root/'syn/tri_oracle_memory_pressure_guard.py',root/'syn/tri_oracle_process_guard.py']}
        while True:
            available,anonymous=memory()
            if available>14*1024**3 and anonymous<3*1024**3:break
            assert not stop_requested and time.monotonic()-started<7200,'Synthesis initial headroom wait expired'
            save(state='waiting_for_initial_memory_headroom');time.sleep(2)
        output.mkdir()
        lock=(output/'guard.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        log_argument=str(output/'native');console=output/'console.log'
        command=['genus','-no_gui','-batch','-log',log_argument,'-files',str(entry)]
        native_started=time.monotonic()
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                start_new_session=True,env=dict(os.environ,TRI_ORACLE_DOWN110_OUTPUT=str(output)))
            pause=OwnedProcessPause(child,log_argument)
            policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=8*1024**3)
            save(state='native_small_block_synthesis_running',source_sha256=identities,native_process_group=child.pid,command=command,output_directory=str(output))
            last_save=0
            while child.poll() is None:
                assert not stop_requested,'External stop requested'
                assert time.monotonic()-native_started<3600,'Small-block synthesis wall budget'
                available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                if action in ('pause','resume'):
                    groups=pause.pause() if action=='pause' else pause.resume()
                    save(memory_pressure_events=record.get('memory_pressure_events',[])+[dict(action=action,groups=groups,available_bytes=available,anonymous_bytes=anonymous)])
                record['peak_combined_anonymous_bytes']=max(record.get('peak_combined_anonymous_bytes',0),anonymous)
                if time.monotonic()-last_save>5:save(native_elapsed_seconds=time.monotonic()-native_started);last_save=time.monotonic()
                time.sleep(.1)
            pause.resume();terminate_process_group(child,log_argument=log_argument)
        text=console.read_text(errors='replace')
        assert child.returncode==0 and '\nTRI_ORACLE_DOWN110_SLOW_MAPPING_FINISHED_REQUIRES_REPORT_REVIEW\n' in text,console
        assert all(sha(p)==h for p,h in identities.items()),'Changed synthesis input'
        save(state='native_small_block_mapping_completed_pending_report_review',native_exit_status=0,
             console_sha256=sha(console),native_elapsed_seconds=time.monotonic()-native_started,
             output_netlist_sha256=sha(output/'netlist.v'),routed_timing_qualified=False)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=str(output/'native'))
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child else None);raise
    finally:
        if lock is not None:lock.close()


if __name__=='__main__':main()
