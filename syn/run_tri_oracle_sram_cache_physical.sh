#!/usr/bin/env bash
# Run from the project in the Cadence Docker login environment.
set -euo pipefail
exec 200>.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock
flock -n 200
exec 201<.cache/physical/synthesis/tri_oracle_sram_activation_cache/guard.lock
flock -n -s 201
exec python3 - <<'PY'
import datetime, hashlib, json, os
from pathlib import Path
def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()
def require(condition, message):
    if not condition:
        raise ValueError(message)
root = Path.cwd()
synthesis = json.loads(Path('records/sram_activation_cache_synthesis_result.json').read_text())
functional = json.loads(Path('records/sram_activation_cache_mapped_functional_validation.json').read_text())
require(synthesis['synthesis_completed'] and synthesis['technology_mapping_passed'], 'Unqualified synthesis')
require(functional['mapped_functional_simulation_passed'], 'Mapped cache not tested')
require(functional['synthesis_qualification_sha256'] == sha(functional['synthesis_qualification']), 'Changed synthesis qualification')
inputs = dict(synthesis['source_sha256'])
for name in ['netlist.v', 'constraints.sdc']:
    path = '.cache/physical/synthesis/tri_oracle_sram_activation_cache/' + name
    inputs[path] = synthesis['sha256'][path]
views = json.loads(Path('records/sram_activation_cache_bank_views.json').read_text())
for bank in views['banks'].values():
    inputs.update(bank['sha256'])
technology = json.loads(Path('records/memory_physical_flow_preparation.json').read_text())['technology_artifacts']
for path, artifact in technology.items():
    require(artifact['type'] == 'file', 'Unexpected technology artifact type')
    inputs[path] = artifact['sha256']
for path, expected in inputs.items():
    require(sha(path) == expected, 'Changed qualified input: ' + path)
available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))) * 1024
require(available >= 12 * 1024**3, 'Insufficient physical-run startup memory')
require(Path('/sys/fs/cgroup/memory.max').read_text().strip() == str(24*1024**3), 'Unexpected container memory limit')
require(Path('/sys/fs/cgroup/memory.swap.max').read_text().strip() == '0', 'Unexpected container swap')
require(Path('/sys/fs/cgroup/cpu.max').read_text().strip() == '2000000 100000', 'Unexpected processor quota')
out = Path('.cache/physical/pnr/tri_oracle_sram_activation_cache')
require(not out.exists(), 'This initial physical run must not replace an existing result')
for path in ['syn/tri_oracle_sram_cache_mmmc.tcl', 'syn/tri_oracle_implement_sram_cache.tcl', 'syn/run_tri_oracle_sram_cache_physical.sh', 'syn/run_tri_oracle_guarded_physical.sh']:
    inputs[path] = sha(path)
Path('records/sram_activation_cache_physical_launch.json').write_text(json.dumps({
    'launched_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'input_sha256': inputs, 'host_available_bytes_before': available,
    'anonymous_stop_gib': 8, 'runtime_limit_seconds': 3600,
    'scope': 'Actual two-macro cache physical trial; native commands and reports must still be qualified.'
}, indent=2) + '\n')
os.environ.update(TRI_ORACLE_TOP='tri_oracle_sram_activation_cache',
    TRI_ORACLE_PHYSICAL_STAGE='implementation_01',
    TRI_ORACLE_PHYSICAL_ENTRY='syn/tri_oracle_implement_sram_cache.tcl',
    TRI_ORACLE_PHYSICAL_MARKER='TRI_ORACLE_SRAM_CACHE_PHYSICAL_COMMANDS_FINISHED',
    TRI_ORACLE_PHYSICAL_OUTPUT=str(out/'routed.db'),
    TRI_ORACLE_PHYSICAL_ANON_GIB='8', TRI_ORACLE_PHYSICAL_SECONDS='3600')
os.execvpe('bash', ['bash', 'syn/run_tri_oracle_guarded_physical.sh'], os.environ)
PY
