#!/usr/bin/env bash
# Launch one physical stage of the qualified integrated feed-forward design.
set -euo pipefail
command -v innovus >/dev/null || { echo 'Innovus is not on PATH; use the Cadence login shell.' >&2; exit 127; }
cd /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
exec 200>.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock
if ! flock -n 200; then
    echo 'A large synthesis, physical or gate-simulation job is active; this physical stage must wait.' >&2
    exit 75
fi
exec python3 - "$@" <<'PY_CHECK'
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import sys
sys.dont_write_bytecode=True
sys.path.insert(0,"syn")
from tri_oracle_artifact_fingerprint import artifact_fingerprint

stages={
 'initialize':('initialization','syn/tri_oracle_initialize_physical.tcl','TRI_ORACLE_PHYSICAL_INITIALIZATION_FINISHED',None,None),
 'place':('placement','syn/tri_oracle_place.tcl','TRI_ORACLE_PLACEMENT_FINISHED','initialization','initialized.db'),
 'optimize_place':('placement_optimization','syn/tri_oracle_optimize_feedforward_placement.tcl','TRI_ORACLE_FEEDFORWARD_PLACEMENT_REPAIR_FINISHED','placement','placed.db'),
 'route':('clock_route','syn/tri_oracle_clock_and_route_feedforward.tcl','TRI_ORACLE_CLOCK_AND_ROUTE_COMMANDS_FINISHED','placement_optimization','placed_unfrozen.db'),
 'resume_hold':('postroute_hold_pass','syn/tri_oracle_finish_feedforward_hold.tcl','TRI_ORACLE_FEEDFORWARD_HOLD_PASS_COMMANDS_FINISHED','initial_route_checkpoint','routed_before_optimization.db'),
 'resume_setup':('postroute_setup_pass','syn/tri_oracle_finish_feedforward_setup.tcl','TRI_ORACLE_FEEDFORWARD_SETUP_PASS_COMMANDS_FINISHED','postroute_hold_pass','postroute_hold_pass.db'),
 'refine_hold':('postroute_hold_refine','syn/tri_oracle_refine_feedforward_hold.tcl','TRI_ORACLE_FEEDFORWARD_HOLD_REFINEMENT_COMMANDS_FINISHED','postroute_setup_pass','routed.db'),
 'qualify_refined':('qualification_hold_refine','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_hold_refine','routed.db'),
 'repair_si':('postroute_si_fix','syn/tri_oracle_fix_feedforward_signal_integrity.tcl','TRI_ORACLE_FEEDFORWARD_SI_REPAIR_COMMANDS_FINISHED','postroute_hold_refine','routed.db'),
 'qualify_si':('qualification_si_fix','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_si_fix','routed.db'),
 'repair_endpoint_hold':('postroute_endpoint_hold','syn/tri_oracle_fix_feedforward_endpoint_hold.tcl','TRI_ORACLE_FEEDFORWARD_ENDPOINT_HOLD_COMMANDS_FINISHED','postroute_si_fix','routed.db'),
 'qualify_endpoint_hold':('qualification_endpoint_hold','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_endpoint_hold','routed.db'),
 'repair_final_input_hold':('postroute_final_input_hold','syn/tri_oracle_fix_feedforward_endpoint_hold.tcl','TRI_ORACLE_FEEDFORWARD_ENDPOINT_HOLD_COMMANDS_FINISHED','postroute_typical_si_fix','routed.db'),
 'qualify_final_input_hold':('qualification_final_input_hold','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_final_input_hold','routed.db'),
 'repair_short_input_hold':('postroute_short_input_hold','syn/tri_oracle_fix_feedforward_endpoint_hold.tcl','TRI_ORACLE_FEEDFORWARD_ENDPOINT_HOLD_COMMANDS_FINISHED','postroute_typical_si_fix','routed.db'),
 'qualify_short_input_hold':('qualification_short_input_hold','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_short_input_hold','routed.db'),
 'repair_short_eco_hold':('postroute_short_eco_hold','syn/tri_oracle_fix_feedforward_endpoint_hold.tcl','TRI_ORACLE_FEEDFORWARD_ENDPOINT_HOLD_COMMANDS_FINISHED','postroute_typical_si_fix','routed.db'),
 'qualify_short_eco_hold':('qualification_short_eco_hold','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_short_eco_hold','routed.db'),
 'resize_slew_drivers':('postroute_driver_slew_fix','syn/tri_oracle_resize_feedforward_slew_drivers.tcl','TRI_ORACLE_FEEDFORWARD_DRIVER_SIZING_COMMANDS_FINISHED','postroute_short_eco_hold','routed.db'),
 'qualify_slew_drivers':('qualification_driver_slew_fix','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_driver_slew_fix','routed.db'),
 'resize_slew_local':('postroute_driver_slew_local','syn/tri_oracle_resize_feedforward_slew_drivers.tcl','TRI_ORACLE_FEEDFORWARD_DRIVER_SIZING_COMMANDS_FINISHED','postroute_short_eco_hold','routed.db'),
 'qualify_slew_local':('qualification_driver_slew_local','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_driver_slew_local','routed.db'),
 'repair_selected_routes':('postroute_selected_route_fix','syn/tri_oracle_repair_feedforward_selected_routes.tcl','TRI_ORACLE_FEEDFORWARD_SELECTED_ROUTE_REPAIR_COMMANDS_FINISHED','postroute_endpoint_hold','routed.db'),
 'qualify_selected_routes':('qualification_selected_route_fix','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_selected_route_fix','routed.db'),
 'repair_typical_si':('postroute_typical_si_fix','syn/tri_oracle_fix_feedforward_typical_signal_integrity.tcl','TRI_ORACLE_FEEDFORWARD_TYPICAL_SI_REPAIR_COMMANDS_FINISHED','postroute_selected_route_fix','routed.db'),
 'qualify_typical_si':('qualification_typical_si_fix','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_typical_si_fix','routed.db'),
 'spread_wires':('postroute_wire_spread','syn/tri_oracle_spread_feedforward_signal_wires.tcl','TRI_ORACLE_FEEDFORWARD_WIRE_SPREAD_COMMANDS_FINISHED','postroute_typical_si_fix','routed.db'),
 'qualify_spread_wires':('qualification_wire_spread','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_wire_spread','routed.db'),
 'spread_wires_timed':('postroute_wire_spread_timed','syn/tri_oracle_spread_feedforward_signal_wires.tcl','TRI_ORACLE_FEEDFORWARD_WIRE_SPREAD_COMMANDS_FINISHED','postroute_typical_si_fix','routed.db'),
 'qualify_spread_wires_timed':('qualification_wire_spread_timed','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_wire_spread_timed','routed.db'),
 'qualify_resumed':('qualification_resumed','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','postroute_setup_pass','routed.db'),
 'qualify':('qualification','syn/tri_oracle_qualify_core_route.tcl','TRI_ORACLE_CORE_ROUTED_QUALIFICATION_COMMANDS_FINISHED','clock_route','routed.db'),
}
if len(sys.argv)!=2 or sys.argv[1] not in stages:
    raise SystemExit('Usage: run_tri_oracle_feedforward_physical.sh '+ '|'.join(stages))
stage,entry,marker,previous,checkpoint=stages[sys.argv[1]]
if sys.argv[1] in ('resume_hold','resume_setup','refine_hold','repair_si','repair_endpoint_hold','repair_final_input_hold','repair_short_input_hold','repair_short_eco_hold','resize_slew_drivers','resize_slew_local','repair_selected_routes','repair_typical_si','spread_wires','spread_wires_timed'):
    # Fresh phase execution needs working headroom before native startup. This
    # is separate from, and does not replace, the unchanged18GiB anonymous
    # limit and4GiB host-available runtime reserve enforced by the supervisor.
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    if available<20*1024**3:
        print('Insufficient startup headroom for a new post-route phase; no native job launched.',file=sys.stderr)
        raise SystemExit(75)
top='tri_oracle_feedforward_core'
synthesis=Path('.cache/physical/synthesis')/top
output=Path('.cache/physical/pnr')/top

def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()

def require_independent_backup(database,backup):
    database=Path(database).resolve();backup=Path(backup).resolve()
    if database==backup or database.is_relative_to(backup) or backup.is_relative_to(database):
        raise ValueError('Recovery database must be a distinct, non-nested copy')
    source_inodes={(p.stat().st_dev,p.stat().st_ino) for p in database.rglob('*')
                   if p.is_file() and not p.is_symlink()}
    if not source_inodes:raise ValueError('Source database has no ordinary state files')
    for path in backup.rglob('*'):
        if path.is_symlink() and path.resolve().is_relative_to(database):
            raise ValueError('Recovery copy points into the mutable source database')
        if path.is_file() and (path.stat().st_dev,path.stat().st_ino) in source_inodes:
            raise ValueError('Recovery copy shares source database storage')

# Preserve the qualified synthesized input through the entire native stage.
with (synthesis/'guard.lock').open('r') as lock:
    fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
    os.set_inheritable(lock.fileno(),True)
    result=json.loads((synthesis/'guard_result.json').read_text())
    if result.get('exit_status')!=0 or not re.search(r'^TRI_ORACLE_SYNTHESIS_PASS '+top+r'$',(synthesis/'console.log').read_text(),re.M):
        raise SystemExit('Completed positive feed-forward synthesis is required.')
    revision=json.loads((synthesis/'input_revision.json').read_text())
    units=['strip_predictor','channel_compactor','predicted_dispatch','sparse_weight_dma','tile_executor','silu_gate','gated_executor','down_executor','feedforward_core','memory_compute','word_bank','pe_array']
    for unit in units:
        source='verilog/tri_oracle_'+unit+'.sv'
        if digest(source)!=revision['candidate_rtl_inventory'][source]:
            raise SystemExit('Synthesized source is stale: '+source)
    if digest(revision['entry'])!=digest(synthesis/'input_entry.tcl'):
        raise SystemExit('Synthesis entry changed since its qualified snapshot.')
    imported=revision['mapped_core_dependency']
    if digest(imported['path'])!=imported['sha256']:
        raise SystemExit('Imported mapped core changed.')
    required=[synthesis/'netlist.v',synthesis/'constraints.sdc']
    if any(not p.is_file() or p.stat().st_size==0 for p in required):
        raise SystemExit('Missing synthesized netlist or constraints.')
    qualified=json.loads(Path('records/feedforward_synthesis_result.json').read_text())
    if not qualified.get('synthesis_completed'):
        raise SystemExit('Feed-forward synthesis outputs require independent qualification.')
    for p in required:
        if artifact_fingerprint(p)!=qualified['output_artifacts'].get(str(p)):
            raise SystemExit('Synthesized output differs from qualified producer artifact: '+str(p))
    if previous=='initial_route_checkpoint':
        # A completed intermediate database remains usable when a later phase
        # of the same native process was stopped by a resource guard.
        captured=json.loads(Path('records/feedforward_initial_route_checkpoint.json').read_text())
        database=output/checkpoint
        if not captured.get('route_design_commands_completed') or captured['pre_optimization_checkpoint']!=str(database):
            raise SystemExit('Initial routed checkpoint lacks a qualified producer boundary.')
        if artifact_fingerprint(database)!=captured['pre_optimization_checkpoint_fingerprint']:
            raise SystemExit('Initial routed checkpoint differs from its qualified producer artifact.')
        console=(output/'clock_route_console.log').read_text()
        if 'Generated self-contained design routed_before_optimization.db' not in console.splitlines():
            raise SystemExit('Native intermediate checkpoint completion marker is missing.')
        prior_inputs=json.loads((output/'clock_route_guard_inputs.json').read_text())
        for name,expected in prior_inputs['sha256'].items():
            if digest(name)!=expected:
                raise SystemExit('Initial routed checkpoint source changed: '+name)
    elif previous:
        prior=json.loads((output/(previous+'_guard_result.json')).read_text())
        prior_inputs=json.loads((output/(previous+'_guard_inputs.json')).read_text())
        if prior.get('exit_status')!=0:
            raise SystemExit('Previous physical stage did not complete successfully.')
        for p in required:
            if digest(p)!=prior_inputs['sha256'][str(p)]:
                raise SystemExit('Physical checkpoint has different synthesized input: '+str(p))
        database=output/checkpoint
        if not database.exists() or (database.is_dir() and not any(database.iterdir())) or (database.is_file() and not database.stat().st_size):
            raise SystemExit('Previous native checkpoint is missing or empty.')
        if artifact_fingerprint(database)!=prior.get('output_artifacts',{}).get(str(database)):
            raise SystemExit('Native checkpoint differs from its completed producer artifact.')
        if sys.argv[1] in ('refine_hold','repair_si','repair_endpoint_hold','repair_final_input_hold','repair_short_input_hold','repair_short_eco_hold','resize_slew_drivers','resize_slew_local','repair_selected_routes','repair_typical_si','spread_wires','spread_wires_timed'):
            backup=output/(stage+'_input_exact.db')
            if artifact_fingerprint(backup)!=prior['output_artifacts'][str(database)]:
                raise SystemExit('Physical repair requires an exact, independently preserved predecessor backup.')
            require_independent_backup(database,backup)
    produced={'initialization':'initialized.db','placement':'placed.db','placement_optimization':'placed_unfrozen.db','clock_route':'routed.db','postroute_hold_pass':'postroute_hold_pass.db','postroute_setup_pass':'routed.db','postroute_hold_refine':'routed.db','postroute_si_fix':'routed.db','postroute_endpoint_hold':'routed.db','postroute_final_input_hold':'routed.db','postroute_short_input_hold':'routed.db','postroute_short_eco_hold':'routed.db','postroute_driver_slew_fix':'routed.db','postroute_driver_slew_local':'routed.db','postroute_selected_route_fix':'routed.db','postroute_typical_si_fix':'routed.db','postroute_wire_spread':'routed.db','postroute_wire_spread_timed':'routed.db','qualification':'routed_netlist.v','qualification_resumed':'routed_netlist.v','qualification_hold_refine':'routed_netlist.v','qualification_si_fix':'routed_netlist.v','qualification_endpoint_hold':'routed_netlist.v','qualification_final_input_hold':'routed_netlist.v','qualification_short_input_hold':'routed_netlist.v','qualification_short_eco_hold':'routed_netlist.v','qualification_driver_slew_fix':'routed_netlist.v','qualification_driver_slew_local':'routed_netlist.v','qualification_selected_route_fix':'routed_netlist.v','qualification_typical_si_fix':'routed_netlist.v','qualification_wire_spread':'routed_netlist.v','qualification_wire_spread_timed':'routed_netlist.v'}[stage]
    os.environ.update({
      'TRI_ORACLE_TOP':top,'TRI_ORACLE_PHYSICAL_STAGE':stage,
      'TRI_ORACLE_PHYSICAL_ENTRY':entry,'TRI_ORACLE_PHYSICAL_MARKER':marker,
      'TRI_ORACLE_PHYSICAL_OUTPUT':str(output/produced),
      'TRI_ORACLE_PHYSICAL_ANON_GIB':'18','TRI_ORACLE_PHYSICAL_SECONDS':'7200'
    })
    print('Launching guarded feed-forward physical stage: '+stage,flush=True)
    os.execvpe('bash',['bash','syn/run_tri_oracle_guarded_physical.sh'],os.environ)
PY_CHECK
