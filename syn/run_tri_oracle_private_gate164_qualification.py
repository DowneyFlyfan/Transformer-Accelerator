"""Qualify privately named mapped modules before importing them into the parent."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

from tri_oracle_hierarchical_controller_adapter155 import checked_hierarchical_controller_adapter
from tri_oracle_memory_pressure_guard import MemoryPressurePolicy, OwnedProcessPause
from tri_oracle_namespace_mapped160 import namespace_mapped_netlist, masked_code
from tri_oracle_compact_tag164 import compact_unused_activation_tags
from tri_oracle_process_guard import terminate_process_group


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def memory():
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:')))*1024
    anonymous = int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])
    return available, anonymous


def main():
    root = Path(__file__).resolve().parents[1]
    result = root/'records/gate164_private_qualification_result.json'
    output = root/'.cache/physical/synthesis/tri_oracle_private_gate164'
    assert not result.exists() and not output.exists()
    started = time.monotonic()
    child = pause = None
    active_token = None
    stop_requested = False
    executable = Path('/opt/cadence/bin/xrun')
    original_top = 'tri_oracle_fabric_gated_executor'
    imported_top = original_top+'_mapped153'
    bench = root/'verilog/tri_oracle_fabric_gated_executor_tb.sv'
    standard = root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140.v'
    entry = root/'syn/tri_oracle_import_private_gate164.tcl'
    static_paths = [Path(__file__).resolve(), entry, executable, Path('/opt/cadence/bin/genus'), bench, standard,
        root/'verilog/tri_oracle_fabric_gated_executor.sv',
        root/'syn/tri_oracle_hierarchical_controller_adapter155.py', root/'syn/tri_oracle_namespace_mapped160.py',
        root/'syn/tri_oracle_compact_tag164.py', root/'records/compact164_tag_validation.json',
        root/'syn/tri_oracle_named_controller_adapters137.py', root/'syn/tri_oracle_checked_controller_adapters138.py',
        root/'syn/tri_oracle_memory_pressure_guard.py', root/'syn/tri_oracle_process_guard.py',
        root/'records/namespace160_validation.json', root/'records/adapter155_link158_qualification.json',
        root/'.cache/physical/library/tcbn28hpcplusbwp12t40p140tt1v25c.lib']
    # Freeze imported Python code and native inputs before any prerequisite wait.
    static_hashes = {str(path): sha(path) for path in static_paths}
    record = dict(state='preflight', supervisor_pid=os.getpid(), static_source_sha256=static_hashes,
        started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        full_paper_results_matched=False, routed_timing_qualified=False,
        scope='All mapped gate-controller modules receive private names, then undergo isolated native import and '
              'the unchanged31-case peer test. The resulting netlist/cell ledger are inputs for later full-parent relinking; '
              'no full20-core integration or physical timing claim.')

    def save(**updates):
        record.update(updates, elapsed_seconds=time.monotonic()-started)
        temporary = result.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(result)

    def unchanged(hashes):
        assert all(sha(path) == expected for path, expected in hashes.items()), 'Queued or running source input changed'

    def stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    def headroom():
        while True:
            available, anonymous = memory()
            if available > 14*1024**3 and anonymous < 3*1024**3:
                return
            assert not stop_requested and time.monotonic()-started < 18000, 'Isolated import/simulation headroom wait expired'
            save(state='waiting_for_native_phase_memory_headroom')
            time.sleep(2)

    def run(command, phase, cwd, log, token, identities, environment=None):
        nonlocal child, pause, active_token
        headroom()
        unchanged(identities)
        native_started = time.monotonic()
        active_token = token
        with log.open('w') as stream:
            child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stream,
                                     stderr=subprocess.STDOUT, start_new_session=True, env=environment)
            pause = OwnedProcessPause(child, token)
            policy = MemoryPressurePolicy(host_reserve_bytes=5*1024**3, resume_bytes=6*1024**3, anonymous_limit_bytes=12*1024**3)
            save(state='native_private_gate_qualification_running', phase=phase, native_process_group=child.pid, command=command)
            last_save = 0
            try:
                while child.poll() is None:
                    assert not stop_requested and time.monotonic()-native_started < 900, 'Private gate phase runtime limit'
                    available, anonymous = memory()
                    record.update(peak_combined_anonymous_bytes=max(record.get('peak_combined_anonymous_bytes', 0), anonymous),
                                  current_host_available_bytes=available, current_combined_anonymous_bytes=anonymous)
                    action = policy.observe(available, anonymous, time.monotonic())
                    if action in ['pause', 'resume']:
                        groups = pause.pause() if action == 'pause' else pause.resume()
                        save(memory_pressure_events=record.get('memory_pressure_events', [])+
                             [dict(action=action, groups=groups, available=available, anonymous=anonymous)])
                    if time.monotonic()-last_save > 5:
                        save(native_phase_elapsed_seconds=time.monotonic()-native_started)
                        last_save = time.monotonic()
                    time.sleep(.1)
            finally:
                pause.resume()
                terminate_process_group(child, log_argument=token)
        unchanged(identities)
        return child.returncode, log.read_text(errors='replace'), time.monotonic()-native_started

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    save()
    try:
        gate_path = root/'records/gated154_mapped_result.json'
        while True:
            assert not stop_requested and time.monotonic()-started < 14400, 'Original mapped gate proof wait expired'
            if gate_path.exists():
                gate = json.loads(gate_path.read_text())
                assert gate['state'] != 'failed', 'Original mapped gate proof failed'
                if gate['state'] == 'original_gate_controller_mapped_functional_qualified':
                    break
            save(state='waiting_for_original_mapped_gate_functionality')
            time.sleep(2)
        unchanged(static_hashes)
        assert gate['cases_passed'] == 31 and gate['projection_requests'] == 38 and gate['wrong_mathematical_reference_rejected']
        unchanged(gate['source_sha256'])
        mapping_path = root/'records/gated153_synthesis_result.json'
        mapping = json.loads(mapping_path.read_text())
        assert mapping['state'] == 'native_small_block_mapping_completed_pending_report_review' and mapping['native_exit_status'] == 0
        unchanged(mapping['source_sha256'])
        original_netlist = Path(mapping['output_directory'])/'netlist.v'
        assert sha(original_netlist) == mapping['output_netlist_sha256'] == gate['source_sha256'][str(original_netlist)]
        namespace_proof = json.loads((root/'records/namespace160_validation.json').read_text())
        assert namespace_proof['state'] == 'mapped_module_namespace_controls_passed'
        unchanged(namespace_proof['source_sha256'])
        identities = {**mapping['source_sha256'], **gate['source_sha256'],
                      str(mapping_path): sha(mapping_path), str(gate_path): sha(gate_path), **static_hashes}
        unchanged(identities)
        renamed, aliases = namespace_mapped_netlist(original_netlist.read_text(), original_top, imported_top, 'tri_oracle_gated160_')
        rtl=(root/'verilog/tri_oracle_fabric_gated_executor.sv').read_text()
        assert re.search(r'localparam\s+int\s+Rows\s*=\s*160\s*;',rtl)
        assert ".in_tag(16'(issue_index))" in rtl
        renamed, normalization = compact_unused_activation_tags(renamed, imported_top, aliases['tri_oracle_silu_gate'])
        headroom()
        unchanged(identities)
        output.mkdir()
        (output/'tag_normalization.json').write_text(json.dumps(normalization,indent=2)+'\n')
        identities[str(output/'tag_normalization.json')]=sha(output/'tag_normalization.json')
        record['tag_normalization']=normalization
        candidate = output/'private_candidate.v'
        candidate.write_text(renamed)
        identities[str(candidate)] = sha(candidate)
        (output/'input_revision.json').write_text(json.dumps(dict(source_sha256=identities, module_aliases=aliases), indent=2)+'\n')
        native_log = output/'isolated_import.log'
        code, text, elapsed = run(['genus', '-no_gui', '-batch', '-log', str(output/'native'), '-files', str(entry)],
            'isolated_import', root, native_log, str(output/'native'), identities,
            dict(os.environ, TRI_ORACLE_GATE164_OUTPUT=str(output)))
        assert code == 0 and '\nTRI_ORACLE_GATE164_PRIVATE_NATIVE_IMPORT_EXPORTED\n' in text, text[-4000:]
        exported = output/'qualified_import.v'
        _, interface = checked_hierarchical_controller_adapter(root/'verilog/tri_oracle_fabric_gated_executor.sv', exported, imported_top)
        declarations = re.findall(r'^\s*module\s+([A-Za-z_][A-Za-z_0-9$]*)\s*\(', masked_code(exported.read_text()), re.M)
        assert len(declarations) == len(set(declarations)) and set(declarations) <= set(aliases.values())
        assert imported_top in declarations
        cells_path = output/'isolated_cells.tsv'
        cells = cells_path.read_text().splitlines()
        assert len(cells) >= 1000 and len({line.split('\t')[0] for line in cells}) == len(cells)
        identities.update({str(path): sha(path) for path in [exported, cells_path, output/'isolated_hierarchy.tsv', output/'isolated_wiring.rpt']})
        attempts = dict(isolated_import=dict(native_exit_status=0, elapsed_seconds=elapsed, console_sha256=sha(native_log)))
        marker = original_top+' dut (.*);'
        stimulus = bench.read_text()
        assert stimulus.count(marker) == 1
        stimulus = stimulus.replace(marker, imported_top+' dut (.*);')
        assert stimulus.count('\nendmodule')==1
        stimulus=stimulus.replace('\nendmodule','\n  integer private_known_inputs_checks=0;\n  always @(posedge clk) begin\n    if (rst_n && dut.activation_unit.in_valid && dut.activation_unit.in_ready) begin\n      if ($isunknown({dut.activation_unit.in_tag,dut.activation_unit.in_gate,dut.activation_unit.in_up}))\n        $fatal(1,"PRIVATE_GATE_UNKNOWN_ACTIVATION_INPUT");\n      private_known_inputs_checks++;\n    end\n  end\n  final $display("PRIVATE_GATE_KNOWN_INPUTS_PASS checks=%0d",private_known_inputs_checks);\n'+'\nendmodule')
        private_bench = output/'private_bench.sv'
        private_bench.write_text(stimulus)
        identities[str(private_bench)] = sha(private_bench)
        for phase in ['wrong_reference', 'positive']:
            with tempfile.TemporaryDirectory(prefix='gate160_'+phase+'_', dir=root/'.cache/physical') as folder:
                work = Path(folder)
                log = output/(phase+'.log')
                command = [str(executable), '-64bit', '-sv', '-xmerror', 'RECOME', '-sequdp_nba_delay',
                    '-top', 'tri_oracle_fabric_gated_executor_tb', '-xmlibdirname', str(work/'xcelium.d'),
                    '-l', str(work/'xrun.log'), '-history_file', str(work/'history'), str(standard), str(exported), str(private_bench)]
                if phase == 'wrong_reference':
                    command.append('+CORRUPT_REFERENCE')
                code, text, elapsed = run(command, phase, work, log, str(work/'xrun.log'), identities)
                if phase == 'wrong_reference':
                    assert code != 0 and 'gated mathematical mismatch' in text and 'FABRIC_GATED_CONTROLLER_PASS' not in text, text[-4000:]
                else:
                    assert code == 0 and 'FABRIC_GATED_CONTROLLER_PASS cases=31 projection_requests=38' in text, text[-4000:]
                    match = re.search(r'FABRIC_GATED_EXACT_QUANTIZATION_PASS checks=(\d+)', text)
                    assert match and int(match.group(1)) == 525
                    record['exact_quantization_checks'] = int(match.group(1))
                    known=re.search(r'PRIVATE_GATE_KNOWN_INPUTS_PASS checks=(\d+)',text)
                    assert known and int(known.group(1))==525
                    record['known_activation_input_checks']=int(known.group(1))
                attempts[phase] = dict(native_exit_status=code, elapsed_seconds=elapsed, console_sha256=sha(log))
            attempts[phase]['temporary_build_removed'] = not work.exists()
            assert attempts[phase]['temporary_build_removed']
            save(attempts=attempts)
        unchanged(identities)
        save(state='private_gate_import_and_mapped_functional_qualified', source_sha256=identities, output_directory=str(output),
             qualified_import_sha256=sha(exported), isolated_cell_inventory_sha256=sha(cells_path),
             mapped_gate_standard_cells=len(cells), module_aliases=aliases, exported_module_names=declarations,
             interface=interface, cases_passed=31, projection_requests=38, wrong_mathematical_reference_rejected=True)
    except BaseException as error:
        if child is not None:
            if pause is not None:
                pause.resume()
            terminate_process_group(child, log_argument=active_token)
        save(state='failed', exception=repr(error))
        raise


if __name__ == '__main__':
    main()
