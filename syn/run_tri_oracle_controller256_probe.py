"""Test transparent buffer insertion on a protected controller without saving it."""
import datetime
import filecmp
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_native_diagnostics import require_clean_native
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group


def main():
    root = Path(__file__).resolve().parents[1]
    out = root/'.cache/physical/pnr/tri_oracle_controller256_probe'
    result = root/'records/controller256_probe_result.json'
    assert not out.exists() and not result.exists()
    producer_path = root/'records/frame251_electrical_result.json'
    producer = json.loads(producer_path.read_text())
    assert producer['state'] == 'guidance_electrical_optimization_completed_pending_full_restore_and_function'
    # The whole-parent timing job must be terminal before opening another native process.
    timing_path = root/'records/frame247_restore_result.json'
    timing = json.loads(timing_path.read_text())
    assert timing['state'] == 'full_original_models_cold_verified_and_three_corner_diagnostics_completed'
    checkpoint = Path(producer['output_database'])
    input_fp = producer['output_database_fingerprint']
    assert hierarchy_fingerprint(checkpoint) == input_fp
    entry = root/'syn/tri_oracle_controller256_probe.tcl'
    names = ['run_tri_oracle_controller256_probe.py', 'tri_oracle_controller256_probe.tcl', 'tri_oracle_unique215_snapshot.tcl', 'tri_oracle_preservation233.tcl', 'tri_oracle_design242_metadata.tcl', 'tri_oracle_row_guard173_variants.py', 'run_tri_oracle_row_guard175_synthesis.py', 'tri_oracle_hierarchy_fingerprint.py', 'tri_oracle_artifact_fingerprint.py', 'tri_oracle_native_diagnostics.py', 'tri_oracle_memory_pressure_guard.py', 'tri_oracle_process_guard.py']
    identities = {str(producer_path): sha(producer_path), str(timing_path): sha(timing_path)}
    for key in ['source_sha256', 'native_evidence_sha256']:
        for name, digest in producer[key].items():
            assert sha(name) == digest
            identities[name] = digest
    for path in [*[root/'syn'/name for name in names], Path('/opt/cadence/INNOVUS251/doc/TCRcom/eco_add_repeater.html'), Path('/opt/cadence/INNOVUS251/doc/TCRcom/eco_Category_Attributes.html'), Path('/opt/cadence/INNOVUS251/doc/DBcom/base_cell.html')]:
        digest = sha(path)
        assert str(path) not in identities or identities[str(path)] == digest
        identities[str(path)] = digest
    started = time.monotonic()
    child = pause = None
    token = str(out/'native')
    stopped = False
    record = dict(state='preflight', supervisor_pid=os.getpid(), started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), source_sha256=identities, native_workers=4, anonymous_limit_bytes=12*1024**3, host_reserve_bytes=8*1024**3, candidate_saved=False, placement_qualified=False, timing_qualified=False, functional_simulation_qualified=False, scope='Discarded logical capability control on the251 guidance parent:32 of998 control-net loads pass through exactly one proven noninverting buffer. All other canonical leaf connections, original cells/geometry/attributes, ports, constants, hierarchy and86protections must match. No physical/timing/functional success claim.')

    def save(**updates):
        record.update(updates, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)

    def stop(signum, frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    save()
    try:
        available, anonymous = memory()
        assert available > 20*1024**3 and anonymous < 1024**3
        out.mkdir()
        console = out/'console.log'
        command = ['/opt/cadence/bin/innovus', '-stylus', '-no_gui', '-batch', '-log', token, '-files', str(entry)]
        with console.open('w') as stream:
            child = subprocess.Popen(command, cwd=out, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, env=dict(os.environ, TRI256_OUT=str(out), TRI256_INPUT=str(checkpoint)))
            pause = OwnedProcessPause(child, token)
            policy = MemoryPressurePolicy(host_reserve_bytes=8*1024**3, resume_bytes=10*1024**3, anonymous_limit_bytes=12*1024**3)
            save(state='native_protected_net_buffer_probe_running', native_process_group=child.pid, output_directory=str(out), command=command)
            last = 0
            try:
                while child.poll() is None:
                    assert not stopped and time.monotonic()-started < 900, 'Buffer probe wall/stop guard'
                    available, anonymous = memory()
                    record.update(peak_combined_anonymous_bytes=max(record.get('peak_combined_anonymous_bytes', 0), anonymous), current_host_available_bytes=available, current_combined_anonymous_bytes=anonymous)
                    action = policy.observe(available, anonymous, time.monotonic())
                    if action == 'pause':
                        pause.pause()
                    elif action == 'resume':
                        pause.resume()
                    if time.monotonic()-last > 5:
                        save()
                        last = time.monotonic()
                    time.sleep(.2)
            finally:
                pause.resume()
                terminate_process_group(child, log_argument=token)
        text = console.read_text(errors='replace')
        require_clean_native(text)
        assert child.returncode == 0 and '\nTRI_ORACLE_CONTROLLER256_BUFFER_BRANCH_AND_PROTECTION_VERIFIED\n' in text
        pairs = [('before_cells', 'after_original_cells'), ('before_other_nets', 'after_other_nets')]+[(f'before_{kind}', f'after_{kind}') for kind in ['ports', 'pins', 'design', 'hierarchy', 'preservation']]
        evidence = {str(path): sha(path) for path in out.iterdir() if path.is_file() and path.suffix in ['.tsv', '.log']}
        for before, after in pairs:
            ordered = []
            for name in [before, after]:
                path = out/(name+'.tsv')
                target = path.with_suffix('.tsv.sorted')
                subprocess.run(['sort', '-S', '64M', '-T', str(out), '-o', str(target), str(path)], check=True, env=dict(os.environ, LC_ALL='C'), timeout=180)
                ordered.append(target)
            assert filecmp.cmp(*ordered, shallow=False), 'Unrelated design data changed '+before
            for path in ordered:
                evidence[str(path)] = sha(path)
        assert all(sha(path) == digest for path, digest in identities.items())
        assert hierarchy_fingerprint(checkpoint) == input_fp
        summary = dict(line.split('\t') for line in (out/'probe_summary.tsv').read_text().splitlines())
        assert summary['original_loads'] == '998' and summary['buffered_loads'] == '32' and summary['input_loads_after'] == '967' and summary['noninverting'] == 'true'
        # The large comparison ledgers are temporary; preserve hashes and the small summary.
        for path in out.glob('*.tsv*'):
            if path.name != 'probe_summary.tsv':
                path.unlink()
        save(state='transparent_buffer_branch_on_protected_net_connectivity_verified', native_exit_status=0, summary=summary, native_evidence_sha256={str(out/'console.log'): sha(out/'console.log'), str(out/'probe_summary.tsv'): sha(out/'probe_summary.tsv')}, consumed_comparison_sha256=evidence, temporary_comparison_ledgers_removed=True, original_input_database_unchanged=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=token)
        for path in out.glob('*.tsv*'):
            if path.name != 'probe_summary.tsv':
                path.unlink()
        save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None, temporary_comparison_ledgers_removed=True)
        raise


if __name__ == '__main__':
    main()
