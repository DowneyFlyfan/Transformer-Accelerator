#!/usr/bin/env bash
# Run in tri-oracle-eda. Freeze qualified core output under its guard lock.
set -euo pipefail
command -v genus >/dev/null || { echo 'Genus is not on PATH; use the Cadence login shell.' >&2; exit 127; }
cd /home/downeyflyfan/Research_Projects/Hardware/Attention_Accelerator
# Keep the same execution lock as large core routing and Icarus profiles. Bash
# descriptor200 remains open through the exec chain into the synthesis guard.
exec 200>.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock
if ! flock -n 200; then
    echo 'A large physical or gate-simulation job is active; synthesis must wait.' >&2
    exit 75
fi
exec python3 - <<'PY_CHECK'
from pathlib import Path
import fcntl
import hashlib
import json
import os
import shutil
import tempfile

def digest(path):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):
            checksum.update(chunk)
    return checksum.hexdigest()
qualified=Path('records/feedforward_synthesis_result.json')
if qualified.exists() and json.loads(qualified.read_text()).get('synthesis_completed'):
    raise SystemExit('Qualified feed-forward synthesis already exists; preserve/archive that run before resynthesis.')
core=Path('.cache/physical/synthesis/tri_oracle_memory_compute')
if not (core/'guard.lock').is_file():
    raise SystemExit('Core qualification requires its guard lock file.')
with (core/'guard.lock').open('r') as lock:
    try:
        fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Core guard is active; do not qualify or import mutable output.')
    status=core/'guard_result.json'
    if not status.exists() or json.loads(status.read_text())['exit_status']!=0:
        raise SystemExit('Core synthesis is not qualified: completed positive guard result required.')
    if 'TRI_ORACLE_SYNTHESIS_PASS tri_oracle_memory_compute' not in (core/'console.log').read_text():
        raise SystemExit('Core synthesis is not qualified: positive pass marker missing.')
    netlist=core/'netlist.v'
    if not netlist.is_file() or netlist.stat().st_size==0:
        raise SystemExit('Core synthesis is not qualified: mapped netlist missing.')
    revision=json.loads((core/'input_revision.json').read_text())
    for source in ['tri_oracle_memory_compute.sv','tri_oracle_word_bank.sv','tri_oracle_pe_array.sv']:
        path='verilog/'+source
        if digest(path)!=revision['candidate_rtl_inventory'][path]:
            raise SystemExit('Core synthesis is stale for '+path)
    pe=revision.get('mapped_processing_array_dependency')
    if not pe or digest(pe['path'])!=pe['sha256']:
        raise SystemExit('Core lacks a matching mapped processing-array dependency.')
    imports=Path('.cache/physical/imports'); imports.mkdir(parents=True,exist_ok=True)
    snapshot=Path(tempfile.mkdtemp(prefix='feedforward_core_',dir=imports))
    imported=snapshot/'netlist.v'
    shutil.copyfile(netlist,imported)
    manifest={'source_path':str(netlist),'mapped_core_sha256':digest(imported),
              'core_input_revision':revision,'core_guard_result':json.loads(status.read_text()),
              'scope':'immutable qualified synthesis input; functional/physical checks retain their own gates'}
    (snapshot/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    shutil.copyfile(core/'constraints.sdc',snapshot/'core_constraints.sdc')
os.environ.update({
 'TRI_ORACLE_TOP':'tri_oracle_feedforward_core',
 'TRI_ORACLE_LIBS':'.cache/physical/library/tcbn28hpcplusbwp12t40p140ssg0p9v125c.lib',
 'TRI_ORACLE_SYNTH_ENTRY':'syn/tri_oracle_synthesize_feedforward_core.tcl',
 'TRI_ORACLE_IMPORTED_CORE_NETLIST':str(imported),
 'TRI_ORACLE_GUARD_ANON_GIB':'16','TRI_ORACLE_GUARD_SECONDS':'3600'
})
print('Qualified core snapshotted for import: '+str(imported),flush=True)
os.execvpe('bash',['bash','syn/run_tri_oracle_guarded_synthesis.sh'],os.environ)
PY_CHECK
