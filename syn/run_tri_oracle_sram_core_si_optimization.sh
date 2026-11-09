#!/usr/bin/env bash
# Separate core repair branch; never replace a previously qualified database.
set -euo pipefail
exec 200>.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock
flock -n 200
exec 201<.cache/physical/synthesis/tri_oracle_sram_memory_compute/guard.lock
flock -n -s 201
exec python3 - <<'PY'
import datetime, hashlib, json, os, sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, 'syn')
from tri_oracle_artifact_fingerprint import artifact_fingerprint
def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()
qpath = 'records/sram_core_power_trim_result.json'
q = json.loads(Path(qpath).read_text())
assert q['native_commands_completed'] and q['uncapped_connectivity_report_clean']
assert artifact_fingerprint(q['output_database']) == q['output_database_fingerprint']
assert sha(q['producer_guard']) == q['producer_guard_sha256']
for path, expected in json.loads(Path(q['producer_guard']).with_name(
        'power_trim_02_guard_inputs.json').read_text())['sha256'].items():
    assert sha(path) == expected, path
synth = json.loads(Path('records/sram_memory_compute_synthesis_result.json').read_text())
assets = dict(synth['library_sha256'])
for name in ['records/sram_core_bank_views.json', 'records/sram_activation_cache_bank_views.json']:
    for bank in json.loads(Path(name).read_text())['banks'].values():
        assets.update(bank['sha256'])
for path, item in json.loads(Path('records/memory_physical_flow_preparation.json').read_text())['technology_artifacts'].items():
    assert item['type'] == 'file'
    assets[path] = item['sha256']
for path, expected in assets.items():
    assert sha(path) == expected, path
available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))) * 1024
assert available >= 12 * 1024**3
assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == str(24 * 1024**3)
assert Path('/sys/fs/cgroup/memory.swap.max').read_text().strip() == '0'
root = Path('.cache/physical/pnr/tri_oracle_sram_memory_compute')
assert not (root / 'qualification_si_opt_06').exists()
assert not (root / 'routed_si_opt_06.db').exists()
entry = 'syn/tri_oracle_optimize_sram_core_si.tcl'
Path('records/sram_core_si_optimization_launch.json').write_text(json.dumps({
    'launched_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'entry': entry, 'entry_sha256': sha(entry),
    'input_qualification_sha256': sha(qpath), 'asset_sha256': assets,
    'host_available_bytes_before': available, 'native_workers': 19,
    'combined_anonymous_stop_gib': 14,
    'hypothesis': 'Initial native core route used default-disabled crosstalk slew fixing. '
                  'Enable it and perform concurrent setup/hold/transition optimization.',
    'timing_constraints_changed': False,
    'scope': 'Native repair trial only; fresh complete diagnostics and functional checks required.'
}, indent=2) + '\n')
os.environ.update(
    TRI_ORACLE_TOP='tri_oracle_sram_memory_compute',
    TRI_ORACLE_PHYSICAL_STAGE='si_opt_06', TRI_ORACLE_PHYSICAL_ENTRY=entry,
    TRI_ORACLE_PHYSICAL_MARKER='TRI_ORACLE_SRAM_CORE_SI_OPT_COMMANDS_FINISHED',
    TRI_ORACLE_PHYSICAL_OUTPUT=str(root / 'routed_si_opt_06.db'),
    TRI_ORACLE_PHYSICAL_ANON_GIB='14', TRI_ORACLE_PHYSICAL_SECONDS='7200')
os.execvpe('bash', ['bash', 'syn/run_tri_oracle_guarded_physical.sh'], os.environ)
PY
