#!/usr/bin/env bash
# Run in the existing Cadence container; preserve the compiled-memory input views.
set -euo pipefail
exec 200>.cache/physical/pnr/tri_oracle_memory_compute/physical.guard.lock
flock -n 200
exec python3 - <<'PY'
import datetime, hashlib, json, os
from pathlib import Path
def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()
functional = json.loads(Path('records/sram_memory_compute_functional_validation.json').read_text())
assert functional['unit_functional_tests_passed'] and functional['native_fault_controls_rejected'] == 6
for path, expected in functional['source_sha256'].items():
    assert sha(path) == expected, path
libraries = ['.cache/physical/library/tcbn28hpcplusbwp12t40p140tt1v25c.lib']
for record in ['records/sram_core_bank_views.json', 'records/sram_activation_cache_bank_views.json']:
    banks = json.loads(Path(record).read_text())['banks']
    for key, bank in banks.items():
        if key == 'metadata':
            continue
        libraries.append(bank['libraries']['tt1v25c'])
        for path, expected in bank['sha256'].items():
            assert sha(path) == expected, path
technology = json.loads(Path('records/memory_physical_flow_preparation.json').read_text())
for path, artifact in technology['technology_artifacts'].items():
    assert artifact['type'] == 'file' and sha(path) == artifact['sha256'], path
available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                     if line.startswith('MemAvailable:'))) * 1024
assert available >= 12*1024**3
assert Path('/sys/fs/cgroup/memory.max').read_text().strip() == str(24*1024**3)
assert Path('/sys/fs/cgroup/memory.swap.max').read_text().strip() == '0'
top = 'tri_oracle_sram_memory_compute'
output = Path('.cache/physical/synthesis') / top
assert not output.exists(), 'Refusing to replace an earlier synthesis attempt'
entry = 'syn/tri_oracle_synthesize_sram_memory_compute.tcl'
Path('records/sram_core_synthesis_launch.json').write_text(json.dumps({
    'launched_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'top': top, 'entry': entry, 'entry_sha256': sha(entry),
    'functional_qualification_sha256': sha('records/sram_memory_compute_functional_validation.json'),
    'libraries_sha256': {path: sha(path) for path in libraries},
    'host_available_bytes_before': available, 'synthesis_workers': 18,
    'concurrent_native_integration_runs': 2, 'combined_anonymous_stop_gib': 14,
    'scope': 'Actual19KB standalone compute-core mapping; full integration, physical '
             'implementation and all full-chip/paper measurements remain separate.'
}, indent=2) + '\n')
os.environ.update(TRI_ORACLE_TOP=top, TRI_ORACLE_SYNTH_ENTRY=entry,
    TRI_ORACLE_LIBS=' '.join(libraries), TRI_ORACLE_GUARD_ANON_GIB='14',
    TRI_ORACLE_GUARD_SECONDS='7200')
os.execvpe('bash', ['bash', 'syn/run_tri_oracle_guarded_synthesis.sh'], os.environ)
PY
