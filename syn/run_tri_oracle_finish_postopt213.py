"""Finalize the unchanged optimized graph with an exact dead-interface audit."""
import csv
import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_dead_wrapper206 import validate_dead_wrapper_pins
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_process_guard import terminate_process_group
from tri_oracle_row_guard173_variants import sha
from run_tri_oracle_row_guard175_synthesis import memory


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'.cache/physical/synthesis/tri_oracle_predicted_feedforward_finish213'
    result=root/'records/finish213_synthesis_result.json'
    assert not output.exists() and not result.exists()
    manifest_path=root/'records/optimized199_candidate_checkpoint_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    assert manifest['state']=='native_optimization_returned_candidate_saved_wiring_qualification_failed'
    candidate=Path(manifest['checkpoint_path'])
    assert artifact_fingerprint(candidate)==manifest['checkpoint_fingerprint']
    binding_path=root/'records/optimized199_candidate_inventory_binding.json'
    binding=json.loads(binding_path.read_text())
    assert binding['candidate_manifest_sha256']==sha(manifest_path)
    assert all(sha(p)==h for p,h in binding['native_post_inventory_sha256'].items())
    producer_path=Path(manifest['terminal_producer_record'])
    assert sha(producer_path)==manifest['terminal_producer_sha256']
    producer=json.loads(producer_path.read_text())
    assert producer['state']=='failed' and 'FRAME199_BAD_OPTIMIZED_PARENT_WIRING' in producer['exception']
    assert not Path('/proc',str(producer['native_process_group'])).exists()
    proof_path=root/'records/postopt205_probe_result.json'
    proof=json.loads(proof_path.read_text());assert proof['state']=='native_boundary_diagnostic_completed'
    assert all(sha(p)==h for p,h in proof['source_sha256'].items())
    assert all(sha(p)==h for p,h in proof['native_evidence_sha256'].items())
    audit=Path(proof['output_directory'])/'wrapper_cones.tsv'
    with audit.open() as stream:rows=list(csv.DictReader(stream,delimiter='\t'))
    report=root/'.cache/physical/synthesis/tri_oracle_postopt204_probe/undriven.rpt'
    flags=re.findall(r'^hpin:tri_oracle_predicted_feedforward_frame/([^\s]+)\s+\(fanout\s*:\s*(\d+)\)\s*$',report.read_text(),re.M)
    assert len(flags)==32106 and all(fanout=='0' for name,fanout in flags)
    previous=root/'.cache/physical/synthesis/tri_oracle_predicted_feedforward_rowguard175'
    controls=previous/'mapped_controller_boundaries.tsv';gate=previous/'gate_boundary_before.tsv'
    preserved={line.split('\t')[1] for line in controls.read_text().splitlines()[1:]}
    preserved.update(line.split('\t')[0] for line in gate.read_text().splitlines())
    targets=validate_dead_wrapper_pins(rows,{name for name,fanout in flags},preserved)
    mapped_path=root/'records/rowguard175_mapped_checkpoint_manifest.json'
    mapped=json.loads(mapped_path.read_text())
    assert sha(mapped_path)==manifest['source_sha256'][str(mapped_path)]
    identities={**manifest['source_sha256'],**proof['source_sha256'],**proof['native_evidence_sha256']}
    entry=root/'syn/tri_oracle_finish_postopt213.tcl'
    paths=[Path(__file__).resolve(),entry,root/'syn/tri_oracle_dead_wrapper206.py',
        root/'syn/test_tri_oracle_dead_wrapper206.py',manifest_path,binding_path,producer_path,proof_path,report,controls,gate,
        root/'syn/tri_oracle_audited_wiring213.py',root/'syn/test_tri_oracle_audited_wiring213.py',
        root/'syn/tri_oracle_mapped_restore199.py',root/'syn/tri_oracle_mapped_boundary199.tcl',
        root/'syn/tri_oracle_artifact_fingerprint.py',root/'syn/tri_oracle_process_guard.py',
        root/'syn/tri_oracle_memory_pressure_guard.py',root/'syn/tri_oracle_row_guard173_variants.py',
        root/'syn/run_tri_oracle_row_guard175_synthesis.py',
        Path('/opt/cadence/GENUS251/doc/genus_comref/delete_obj.html')]
    for name in ['gate_cells_after.tsv','gate_boundary_after.tsv','gate_preservation_after.tsv',
                 'reused_controls_after.tsv.sorted','preserved_banks_after.tsv','boundary_connections_after.tsv']:
        paths.append(candidate.parent/name)
    identities.update({str(p):sha(p) for p in paths})
    assert all(sha(p)==h for p,h in identities.items())
    child=pause=None;stopped=False;started=time.monotonic()
    def stop(signum,frame):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    record=dict(state='preflight',supervisor_pid=os.getpid(),source_sha256=identities,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        input_optimized_checkpoint_fingerprint=manifest['checkpoint_fingerprint'],
        audited_disconnected_wrapper_inputs=len(targets),optimization_repeated=False,
        full_mapped_function_qualified=False,routed_timing_qualified=False,full_paper_results_matched=False,
        scope='Finalize an already optimized full prepared20-core parent. Retain the optimized graph and classify only exhaustively proven, disconnected legacy wrapper inputs. '
              'All leaf cell names/types, original top ports, all26 preserved controllers and156712 protected boundary identities must remain. '
              'Native unresolved/multiple-driver/cross-hierarchy status and exact zero-cone wrapper-input report audit must pass; mapped function and physical results remain separate.')
    def save(**changes):
        record.update(changes,elapsed_seconds=time.monotonic()-started)
        temporary=result.with_suffix('.tmp');temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.replace(result)
    def unchanged():
        assert all(sha(p)==h for p,h in identities.items())
        assert artifact_fingerprint(candidate)==manifest['checkpoint_fingerprint']
    save()
    try:
        available,anonymous=memory();assert available>14*1024**3 and anonymous<3*1024**3
        output.mkdir()
        target_path=output/'cleanup_targets.txt';target_path.write_text('\n'.join(sorted(targets))+'\n')
        identities[str(target_path)]=sha(target_path)
        revision=output/'input_revision.json'
        revision.write_text(json.dumps(dict(source_sha256=identities,
            mapped_checkpoint_fingerprint=mapped['checkpoint_fingerprint'],
            optimized_input_fingerprint=manifest['checkpoint_fingerprint']),indent=2)+'\n')
        identities[str(revision)]=sha(revision);unchanged()
        console=output/'console.log';native_started=time.monotonic()
        command=['genus','-no_gui','-batch','-log',str(output/'native'),'-files',str(entry)]
        with console.open('w') as stream:
            child=subprocess.Popen(command,cwd=root,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                env=dict(os.environ,TRI_ORACLE_SYNTH_OUTPUT=str(output),TRI_ORACLE_RESUME199_REVISION_SHA256=sha(revision),
                    TRI_ORACLE_GATE175_ISOLATED_CELLS=str(root/'.cache/physical/synthesis/tri_oracle_private_gate164/isolated_cells.tsv')))
            pause=OwnedProcessPause(child,str(output/'native'))
            policy=MemoryPressurePolicy(host_reserve_bytes=5*1024**3,resume_bytes=6*1024**3,anonymous_limit_bytes=10*1024**3)
            save(state='native_optimized_graph_wiring_audit_running',native_process_group=child.pid,output_directory=str(output),source_sha256=identities,command=command)
            last_save=0
            while child.poll() is None:
                assert not stopped and time.monotonic()-native_started<1200,'Finalization wall/external-stop guard'
                available,anonymous=memory();action=policy.observe(available,anonymous,time.monotonic())
                if action=='pause':pause.pause()
                elif action=='resume':pause.resume()
                if time.monotonic()-last_save>5:
                    save(native_elapsed_seconds=time.monotonic()-native_started,current_combined_anonymous_bytes=anonymous,current_host_available_bytes=available);last_save=time.monotonic()
                time.sleep(.2)
            pause.resume();terminate_process_group(child,log_argument=str(output/'native'))
        assert child.returncode==0 and '\nTRI_ORACLE_POSTOPT213_AUDITED_FINALIZATION_COMPLETED\n' in console.read_text(errors='replace'),console.read_text(errors='replace')[-4000:]
        unchanged()
        topology=output/'optimized_topology_qualification.json'
        assert json.loads(topology.read_text())['state']=='source_bound_full_parent_optimized_topology_qualified'
        wiring=output/'audited_wiring.json'
        assert json.loads(wiring.read_text())['state']=='native_wiring_valid_with_exact_audited_dead_inputs'
        save(state='native_parent_mapping_completed_pending_report_review',native_exit_status=0,
            native_elapsed_seconds=time.monotonic()-native_started,console_sha256=sha(console),
            output_netlist_sha256=sha(output/'netlist.v'),output_constraints_sha256=sha(output/'constraints.sdc'),
            optimized_checkpoint_fingerprint=artifact_fingerprint(output/'optimized.db'),
            optimized_topology_validation_sha256=sha(topology),
            audited_wiring_validation_sha256=sha(wiring),
            all_leaf_cell_inventory_sha256=sha(output/'all_cells_after.tsv.sorted'),
            top_port_inventory_sha256=sha(output/'ports_after.tsv'),strict_native_wiring_status_passed=False,native_undriven_status=1,audited_unused_wrapper_inputs=32106,audited_no_live_wiring_issues=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:pause.resume()
            terminate_process_group(child,log_argument=str(output/'native'))
        save(state='failed',exception=repr(error),native_exit_status=child.returncode if child is not None else None);raise


if __name__=='__main__':main()
