"""Inspect mapped boundary constants without changing the saved native design."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from tri_oracle_row_guard173_variants import sha
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from run_tri_oracle_row_guard175_synthesis import memory


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / '.cache/physical/synthesis/tri_oracle_postopt205_probe'
    result = root / 'records/postopt205_probe_result.json'
    assert not output.exists() and not result.exists()
    entry = root / 'syn/tri_oracle_probe_postopt205.tcl'
    manifest_path = root / 'records/optimized199_candidate_checkpoint_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['state'] == 'native_optimization_returned_candidate_saved_wiring_qualification_failed'
    assert artifact_fingerprint(manifest['checkpoint_path']) == manifest['checkpoint_fingerprint']
    prior_path = root/'records/postopt204_probe_result.json'
    prior = json.loads(prior_path.read_text())
    assert prior['state']=='native_boundary_diagnostic_completed'
    undriven = root/'.cache/physical/synthesis/tri_oracle_postopt204_probe/undriven.rpt'
    assert sha(undriven)==prior['native_evidence_sha256'][str(undriven)]
    paths = [Path(__file__).resolve(), entry, manifest_path, root/'syn/tri_oracle_process_guard.py',
        root/'syn/tri_oracle_memory_pressure_guard.py', root/'syn/tri_oracle_artifact_fingerprint.py',
        root/'syn/run_tri_oracle_row_guard175_synthesis.py', root/'syn/tri_oracle_row_guard173_variants.py']
    paths += [prior_path, undriven]
    identities = {**manifest['source_sha256'], **{str(p): sha(p) for p in paths}}
    assert all(sha(p) == h for p, h in identities.items())
    started = time.monotonic()
    child = pause = None
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    record = dict(state='preflight', supervisor_pid=os.getpid(), source_sha256=identities,
        output_directory=str(output), full_mapped_function_qualified=False, routed_timing_qualified=False,
        scope='Native read-only mapped boundary/constant diagnostic; no optimization or hardware-functional qualification.')
    def save(**changes):
        record.update(changes, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp'); temporary.write_text(json.dumps(record, indent=2)+'\n'); temporary.replace(result)
    save()
    try:
        available, anonymous = memory()
        assert available > 14*1024**3 and anonymous < 3*1024**3
        output.mkdir()
        console = output / 'console.log'
        with console.open('w') as stream:
            child = subprocess.Popen(['genus','-no_gui','-batch','-log',str(output/'native'),'-files',str(entry)],
                cwd=root, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                env=dict(os.environ, TRI_ORACLE_POSTOPT205_OUTPUT=str(output)))
            pause = OwnedProcessPause(child, str(output/'native'))
            policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3, anonymous_limit_bytes=10*1024**3)
            save(state='native_boundary_probe_running', native_process_group=child.pid)
            while child.poll() is None:
                assert not stopped and time.monotonic()-started < 600, 'Probe wall/external stop guard'
                available, anonymous = memory(); action = policy.observe(available, anonymous, time.monotonic())
                if action == 'pause': pause.pause()
                elif action == 'resume': pause.resume()
                time.sleep(.2)
            pause.resume(); terminate_process_group(child, log_argument=str(output/'native'))
        assert child.returncode == 0 and '\nTRI_ORACLE_POSTOPT205_PROBE_COMPLETED\n' in console.read_text(errors='replace')
        assert all(sha(p) == h for p, h in identities.items())
        assert artifact_fingerprint(manifest['checkpoint_path']) == manifest['checkpoint_fingerprint']
        save(state='native_boundary_diagnostic_completed', native_exit_status=0,
            native_evidence_sha256={str(output/name):sha(output/name) for name in
                ['console.log','wrapper_cones.tsv','unresolved.rpt','wiring.rpt','restored.sdc','mapped.v']})
    except BaseException as error:
        save(state='failed', exception=repr(error)); raise
    finally:
        if child is not None:
            if pause is not None: pause.resume()
            terminate_process_group(child, log_argument=str(output/'native'))


if __name__ == '__main__': main()
