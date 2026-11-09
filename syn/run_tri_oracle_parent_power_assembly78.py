"""Check native macro supply access before attempting parent standard-cell power."""
from pathlib import Path
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
root = Path('/home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator')
os.chdir(root)
sys.path.insert(0, str(root/'syn'))
from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_hierarchy_fingerprint import hierarchy_fingerprint
from tri_oracle_process_guard import terminate_process_group

out = root/'.cache/physical/pnr/tri_oracle_parent_power_assembly78'
input_db = root/'.cache/physical/pnr/tri_oracle_parent_power74/parent_power_grid.db'
result = root/'records/parent_power_assembly78_result.json'
assert not out.exists() and not result.exists()

def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

def available():
    return int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                    if line.startswith('MemAvailable:')))*1024

def anonymous():
    return int(dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())['anon'])

assert available() > 16*1024**3 and anonymous() < 8*1024**3
assert shutil.disk_usage(root).free > 12*1024**3
lock = (root/'.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
model_record = Path('records/sram_core_hierarchy68_full_control_validation.json')
model = json.loads(model_record.read_text())
base = root/'.cache/physical/pnr/tri_oracle_sram_memory_compute'
assert artifact_fingerprint(base/'hierarchy_full_control_68') == model['output_artifact_fingerprint']
dependency = {'type':'directory', 'files':{k[4:]:v for k,v in model['output_artifact_fingerprint']['files'].items() if k.startswith('ilm/')}}
dependencies = {base/'hierarchy_full_control_68/ilm':dependency}
input_fingerprint = hierarchy_fingerprint(input_db, directory_dependencies=dependencies)
qualification_path = Path('records/parent_power74_result.json')
qualification = json.loads(qualification_path.read_text())
assert qualification['state'] == 'bounded_parent_grid_constructed_physical_assembly_required'
assert qualification['special_route_drc_violations'] == 0 and qualification['native_exit_status'] == 0
assert input_fingerprint == qualification['output_database_fingerprint']
interface_path = Path('records/core_power_access42_interface_qualification.json')
interface = json.loads(interface_path.read_text())
assert interface['all_3158_signal_pin_definitions_including_antenna_metadata_exactly_preserved']
assert interface['each_original_m9_supply_bar_connected_to_real_top_boundary_metal']
assert all(sha(p) == expected for p,expected in interface['source_sha256'].items())
physical_path = Path('records/core_power_access41_physical_qualification.json')
physical = json.loads(physical_path.read_text())
assert physical['state'] == 'supply_terminal_core_physical_checks_passed'
assert hierarchy_fingerprint(physical['output_database'], directory_dependencies=dependencies) == physical['output_database_fingerprint']
revision = json.loads(Path('.cache/physical/synthesis/tri_oracle_predicted_fabric_registered_reset30/input_revision.json').read_text())
hardware = revision['candidate_rtl_inventory']
assert len(hardware) == 37 and all(sha(p) == expected for p,expected in hardware.items())
entry = Path('syn/tri_oracle_probe_assembled_parent_power.tcl')
guard_source = Path('syn/tri_oracle_restore_core_m9_signal_guards.tcl')
inputs = [Path(__file__).resolve(), model_record, qualification_path, interface_path, physical_path,
          Path('records/core_power_access42_result.json'), Path('records/parent_macro_power46_qualification.json'), Path('records/parent_power49_region_coverage_preflight.json'), Path(interface['new_abstract']), entry, guard_source,
          Path('syn/tri_oracle_require_clean_placement.tcl'), Path('syn/tri_oracle_core_preservation.py'),
          root/'rc_model.bin', base/'hierarchy_export_58/core.lef',
          Path('.cache/physical/pnr/tri_oracle_parent_pg37_candidate/console.log')]
physical_def = Path('.cache/physical/pnr/tri_oracle_core_power_access41/after.def')
assert sha(physical_def) == physical['source_sha256'][str(physical_def)]
netlist = base/'qualification_typical_repair_44/routed_netlist.v'
core_record = Path('records/sram_core_checkpoint44_qualification.json')
core_qualification = json.loads(core_record.read_text())
candidate_record = Path(core_qualification['physical_candidate'])
assert sha(candidate_record) == core_qualification['physical_candidate_sha256']
candidate = json.loads(candidate_record.read_text())
assert sha(netlist) == candidate['report_sha256'][str(netlist.relative_to(root))]
inputs.extend([core_record, candidate_record])
inputs.extend([physical_def, netlist])
identities = {str(p):sha(p) for p in inputs}
original_log = Path('.cache/physical/pnr/tri_oracle_parent_pg37_candidate/console.log').read_text(errors='replace')
original_routes = re.findall(r'Number of Block ports routed:\s*([0-9]+)\s+open:\s*([0-9]+)', original_log)
assert original_routes == [('0','4')], 'Expected actual failed original macro-contact control'
out.mkdir()
started = time.monotonic()
child = None
record = dict(started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              state='prepared', supervisor_pid=os.getpid(), source_sha256=identities,
              input_database=str(input_db), input_database_fingerprint=input_fingerprint,
              physical_core_database=physical['output_database'],
              original_native_control={'routed_macro_ports':0, 'open_macro_ports':4},
              peak_combined_anonymous_bytes=0, minimum_host_available_bytes=None,
              full_parent_power_qualified=False, full_paper_results_matched=False,
              scope='Actual one-core parent assembly with the complete routed core44 netlist and core41 power geometry, then unfiltered supply connectivity, special-route geometry, placement and original-cell preservation. Whole20-core grid/timing remains unqualified.12GiB anonymous ceiling and8GiB host reserve.')

def save(**updates):
    record.update(updates, elapsed_seconds=time.monotonic()-started)
    temporary = result.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2)+'\n')
    temporary.replace(result)

save()
log_argument = str(out/'innovus')
try:
    command = ['/usr/bin/time', '-v', '/opt/cadence/INNOVUS251/bin/innovus', '-stylus', '-no_gui',
               '-batch', '-log', log_argument, '-files', str(entry.resolve())]
    console = out/'console.log'
    with console.open('w') as output:
        child = subprocess.Popen(command, cwd=out, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, start_new_session=True,
                                 env=dict(os.environ, TRI_ORACLE_PLACEMENT_PROBE_DIRECTORY=str(out), TRI_ORACLE_ASSEMBLY_PARENT_DATABASE=str(input_db)), preexec_fn=lambda: os.nice(15))
        save(state='running', command=command, native_process_group=child.pid)
        while child.poll() is None:
            memory, combined = available(), anonymous()
            record['peak_combined_anonymous_bytes'] = max(record['peak_combined_anonymous_bytes'], combined)
            record['minimum_host_available_bytes'] = min(record['minimum_host_available_bytes'] or memory, memory)
            assert combined < 12*1024**3 and memory > 8*1024**3, 'Yield before synthesis memory reserve'
            assert time.monotonic()-started < 1800, 'Bounded power-grid wall limit'
            assert shutil.disk_usage(root).free > 12*1024**3, 'Disk reserve'
            time.sleep(.5)
        terminate_process_group(child, log_argument=log_argument)
    text = console.read_text(errors='replace')
    assert child.returncode == 0 and '\nTRI_ORACLE_PARENT_POWER48_ASSEMBLED_GRID_CHECKED\n' in text
    assert not re.search(r'^\*\*ERROR:', text, re.M), 'Native tool logged an error'
    assert 'TRI_ORACLE_PARENT_POWER48_PHYSICAL_CORE_ASSEMBLED' in text
    preservation = json.loads((out/'core_preservation.json').read_text())
    assert preservation['total_original_cells'] == 94471 and preservation['all_original_cell_names_masters_and_geometry_preserved']
    drc = (out/'special_drc.rpt').read_text()
    violations = re.findall(r'Total Violations\s*:\s*([0-9]+)\s+Viols',drc)
    if 'No DRC violations were found' in drc:
        assert not violations
        count = 0
    else:
        assert len(violations) == 1, 'Incomplete special-route geometry report'
        count = int(violations[0])
    connectivity = (out/'supply_after_trim.rpt').read_text()
    assert 'Begin Summary' in connectivity and 'End Summary' in connectivity
    diagnostics = {code:int(number) for number,code in re.findall(r'(\d+) Problem\(s\) \((IMPVFC-\d+)\)',connectivity)}
    record.update(special_route_drc_violations=count, diagnostic_supply_connectivity=diagnostics,
                  full_power_connectivity_passed=False, physical_block_assembly_completed=True,
                  core_preservation=preservation)
    assert count == 0, 'Assembled special-route geometry requires repair'
    assert not any(diagnostics.values()), 'Assembled supply connectivity requires repair'
    assert all(sha(p) == expected for p,expected in identities.items())
    assert all(sha(p) == expected for p,expected in hardware.items())
    assert hierarchy_fingerprint(input_db, directory_dependencies=dependencies) == input_fingerprint
    assert artifact_fingerprint(base/'hierarchy_full_control_68') == model['output_artifact_fingerprint']
    assert hierarchy_fingerprint(physical['output_database'], directory_dependencies=dependencies) == physical['output_database_fingerprint']
    fingerprint = hierarchy_fingerprint(out/'assembled_parent.db', directory_dependencies=dependencies)
    save(state='one_core_assembled_parent_supply_connectivity_and_geometry_passed', native_exit_status=child.returncode,
         native_console_sha256=sha(console), output_database=str(out/'assembled_parent.db'),
         output_database_fingerprint=fingerprint, original_inputs_and_models_unchanged=True, full_power_connectivity_passed=True)
except BaseException as error:
    if child is not None:
        terminate_process_group(child, log_argument=log_argument)
    save(state='failed', exception=repr(error), native_exit_status=child.returncode if child is not None else None)
    raise
finally:
    lock.close()
    record['archived_sources'] = {str(path):path.read_text() for path in [Path(__file__).resolve(),entry,guard_source]}
    save()
