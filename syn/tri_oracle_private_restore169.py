"""Verify the mapped gate as well as the legacy parent after a cold restore."""
import hashlib
import json
from pathlib import Path
import sys

from tri_oracle_artifact_fingerprint import artifact_fingerprint


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def commands(path):
    return [line.strip() for line in Path(path).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def verify_private_restore(prepared, output):
    prepared, output = Path(prepared), Path(output)
    manifest_path = prepared/'elaborated_checkpoint_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['state'] == 'source_bound_full_parent_private_gate_relink_checkpoint_qualified'
    assert all(sha(path) == digest for path, digest in manifest['source_sha256'].items())
    assert all(sha(path) == digest for path, digest in manifest['native_evidence_sha256'].items())
    assert artifact_fingerprint(prepared/'elaborated.db') == manifest['checkpoint_fingerprint']
    previous = json.loads((prepared/'cold_restore_validation.json').read_text())
    assert all(sha(path) == digest for path, digest in previous['native_evidence_sha256'].items())
    legacy = json.loads((output/'cold_restore_validation.json').read_text())
    assert legacy['state'] == 'full_parent_cold_restore_wiring_cells_and_constraints_verified'
    assert legacy['producer_manifest_sha256'] == sha(manifest_path)
    assert legacy['producer_checkpoint_fingerprint'] == manifest['checkpoint_fingerprint']
    assert legacy['source_and_restored_sdc_commands_equal'] and legacy['source_and_restored_controller_wiring_and_cell_inventories_equal']
    assert all(sha(path) == digest for path, digest in legacy['native_evidence_sha256'].items())
    assert commands(prepared/'elaborated_constraints.sdc') == commands(output/'restored_constraints.sdc')
    for before, after in [('gate_parent_cells.tsv', 'gate_cells_before.tsv'),
                          ('gate_boundary_after.tsv', 'gate_boundary_before.tsv'),
                          ('gate_preservation.tsv', 'gate_preservation_before.tsv')]:
        assert sorted((prepared/before).read_text().splitlines()) == sorted((output/after).read_text().splitlines()), 'Private gate restore changed '+after
    evidence = ['cold_restore_validation.json', 'restored_constraints.sdc', 'gate_cells_before.tsv',
                'gate_boundary_before.tsv', 'gate_preservation_before.tsv']
    return dict(state='full_parent_private_gate_cold_restore_qualified',
                source_manifest_sha256=sha(manifest_path), source_checkpoint_fingerprint=manifest['checkpoint_fingerprint'],
                native_evidence_sha256={str(output/name): sha(output/name) for name in evidence},
                scope='Cold-restored full prepared parent and preserved mapped gate. No full-parent mapping, functional gate simulation, routed timing or paper metric claim.',
                full_paper_results_matched=False, routed_timing_qualified=False)


if __name__ == '__main__':
    prepared, output = map(Path, sys.argv[1:])
    result = output/'private_cold_restore_validation.json'
    assert not result.exists()
    result.write_text(json.dumps(verify_private_restore(prepared, output), indent=2)+'\n')
    print('TRI_ORACLE_FRAME169_PRIVATE_GATE_COLD_RESTORE_VERIFIED', flush=True)
