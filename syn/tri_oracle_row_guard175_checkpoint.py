"""Synchronously bind the prepared full parent before generic synthesis starts."""
import json
import os
from pathlib import Path
import sys

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_row_guard173_variants import sha


def commands(path):
    return [line.strip() for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def main():
    output, prepared, isolated = map(Path, sys.argv[1:])
    revision_path = output/'input_revision.json'
    assert sha(revision_path) == os.environ['TRI_ORACLE_ROW175_INPUT_REVISION_SHA256']
    revision = json.loads(revision_path.read_text())
    identities = dict(revision['source_sha256'])
    assert all(sha(p) == h for p, h in identities.items()), 'Changed static or generated consumed input'
    assert (output/'compiled_cluster_sources.sv').read_text() == revision['compiled_bundle']
    expected = commands(prepared/'elaborated_constraints.sdc')
    observed = commands(output/'elaborated_constraints.sdc')
    extra = 'set_dont_touch [get_cells numeric/engine/gated/implementation]'
    assert observed.count(extra) == 1
    assert [line for line in observed if line != extra] == expected, 'Original constraints changed'
    for name in ['reused_controls_before.tsv.sorted', 'preserved_banks_before.tsv', 'mapped_controller_boundaries.tsv']:
        assert sorted((output/name).read_text().splitlines()) == sorted((prepared/name).read_text().splitlines()), name+' changed'
    cells = (output/'gate_cells_before.tsv').read_text().splitlines()
    assert len(cells) == 151275 and sorted(cells) == sorted(isolated.read_text().splitlines())
    boundary = (output/'gate_boundary_before.tsv').read_text().splitlines()
    assert len(boundary) == len(set(boundary)) == 21012
    assert all(len(line.split('\t')) == 2 and all(line.split('\t')) for line in boundary)
    assert (output/'gate_preservation_before.tsv').read_text().strip() == (
        'numeric/engine/gated/implementation\ttri_oracle_fabric_gated_executor_mapped153\ttrue')
    evidence = ['compiled_cluster_sources.sv', 'elaboration_wiring.rpt',
        'reused_controls_before.tsv.sorted', 'preserved_banks_before.tsv',
        'mapped_controller_boundaries.tsv', 'gate_cells_before.tsv',
        'gate_boundary_before.tsv', 'gate_preservation_before.tsv',
        'elaborated_constraints.sdc', 'flow_settings.rpt']
    identities[str(revision_path)] = sha(revision_path)
    checkpoint = dict(state='source_bound_reduced_guard_full_parent_checkpoint_qualified',
        source_sha256=identities, checkpoint_fingerprint=artifact_fingerprint(output/'elaborated.db'),
        native_evidence_sha256={str(output/name): sha(output/name) for name in evidence},
        compiled_bundle_sha256=sha(output/'compiled_cluster_sources.sv'), preserved_mapped_controllers=26,
        mapped_gate_cells=151275, mapped_gate_boundary_bits=21012,
        original_clock_and_io_constraints_unchanged=True,
        full_paper_results_matched=False, routed_timing_qualified=False)
    path = output/'elaborated_checkpoint_manifest.json'
    assert not path.exists()
    path.write_text(json.dumps(checkpoint, indent=2)+'\n')
    print('TRI_ORACLE_FRAME175_CHECKPOINT_MANIFEST_CREATED', flush=True)


if __name__ == '__main__':
    main()
