#!/usr/bin/env bash
# Actual compiled-memory compute-core physical trial; keep prior branches intact.
set -euo pipefail
exec 200>.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock
flock -n 200
exec 201<.cache/physical/synthesis/tri_oracle_sram_memory_compute/guard.lock
flock -n -s 201
exec python3 - <<'PY'
import datetime, hashlib, json, os
from pathlib import Path
def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()
q = json.loads(Path('records/sram_memory_compute_synthesis_result.json').read_text())
assert q['synthesis_completed'] and q['technology_mapping_passed'] and q['real_macro_count'] == 28
for path, expected in q['source_sha256'].items():
    assert sha(path) == expected, path
for name in ['netlist.v', 'constraints.sdc']:
    path = '.cache/physical/synthesis/tri_oracle_sram_memory_compute/' + name
    assert sha(path) == q['output_sha256'][path], path
mapped = json.loads(Path('records/sram_core_mapped_functional_01_result.json').read_text())
assert mapped['mapped_functional_simulation_passed'] and len(mapped['cases']) == 3
assert sha(mapped['netlist']) == mapped['netlist_sha256']
assets = dict(q['library_sha256'])
for name in ['records/sram_core_bank_views.json', 'records/sram_activation_cache_bank_views.json']:
    for bank in json.loads(Path(name).read_text())['banks'].values():
        assets.update(bank['sha256'])
for path, artifact in json.loads(Path('records/memory_physical_flow_preparation.json').read_text())[
        'technology_artifacts'].items():
    assert artifact['type'] == 'file'
    assets[path] = artifact['sha256']
for path, expected in assets.items():
    assert sha(path) == expected, path
available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))) * 1024
assert available >= 12*1024**3
assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == str(24*1024**3)
assert Path('/sys/fs/cgroup/memory.swap.max').read_text().strip() == '0'
out = Path('.cache/physical/pnr/tri_oracle_sram_memory_compute')
assert not out.exists(), 'Refusing to replace an earlier physical attempt'
entry = 'syn/tri_oracle_implement_sram_core.tcl'
Path('records/sram_core_physical_launch.json').write_text(json.dumps({
    'launched_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'entry': entry, 'entry_sha256': sha(entry),
    'synthesis_qualification_sha256': sha('records/sram_memory_compute_synthesis_result.json'),
    'mapped_functional_qualification_sha256': sha('records/sram_core_mapped_functional_01_result.json'),
    'asset_sha256': assets, 'host_available_bytes_before': available,
    'native_workers': 18, 'combined_anonymous_stop_gib': 14,
    'scope': '28actual macros plus64,640standard cells; local physical floorplan. '
             'Command completion alone will not qualify timing, geometry or paper results.'
}, indent=2) + '\n')
os.environ.update(TRI_ORACLE_TOP='tri_oracle_sram_memory_compute',
    TRI_ORACLE_PHYSICAL_STAGE='implementation_01', TRI_ORACLE_PHYSICAL_ENTRY=entry,
    TRI_ORACLE_PHYSICAL_MARKER='TRI_ORACLE_SRAM_CORE_PHYSICAL_COMMANDS_FINISHED',
    TRI_ORACLE_PHYSICAL_OUTPUT=str(out/'routed_power_checked.db'),
    TRI_ORACLE_PHYSICAL_ANON_GIB='14', TRI_ORACLE_PHYSICAL_SECONDS='7200')
os.execvpe('bash', ['bash', 'syn/run_tri_oracle_guarded_physical.sh'], os.environ)
PY
