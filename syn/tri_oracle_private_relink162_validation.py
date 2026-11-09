"""Anchor a parent relink to a separately imported and simulated mapped circuit."""
import json
from pathlib import Path
import re

from tri_oracle_namespace_mapped160 import masked_code
from tri_oracle_relinked_parent159_validation import validate_relinked_parent, sha, lines


def validate_private_relinked_parent(output, prepared, expected_sources, expected_generated):
    output = Path(output)
    result = validate_relinked_parent(output, prepared, expected_sources, expected_generated)
    revision = json.loads((output/'input_revision.json').read_text())
    proof_path = Path(revision['isolated_gate_qualification'])
    assert str(proof_path) in expected_sources
    proof = json.loads(proof_path.read_text())
    assert proof['state'] == 'private_gate_import_and_mapped_functional_qualified'
    assert proof['cases_passed'] == 31 and proof['projection_requests'] == 38
    assert proof['wrong_mathematical_reference_rejected'] and proof['exact_quantization_checks'] >= 500
    attempts = proof['attempts']
    assert attempts['isolated_import']['native_exit_status'] == attempts['positive']['native_exit_status'] == 0
    assert attempts['wrong_reference']['native_exit_status'] != 0
    assert attempts['positive']['temporary_build_removed'] and attempts['wrong_reference']['temporary_build_removed']
    assert proof['source_sha256'] and all(sha(path) == digest for path, digest in proof['source_sha256'].items())
    isolated = Path(proof['output_directory'])
    exported = isolated/'qualified_import.v'
    inventory = isolated/'isolated_cells.tsv'
    assert sha(exported) == proof['qualified_import_sha256'] == sha(output/'gated_import.v')
    assert sha(inventory) == proof['isolated_cell_inventory_sha256']
    assert lines(inventory) == lines(output/'gate_source_cells.tsv') == lines(output/'gate_parent_cells.tsv')
    assert len(lines(inventory)) == proof['mapped_gate_standard_cells'] == result['mapped_gate_standard_cells']
    profile = json.loads((output/'gated_interface.json').read_text())
    assert profile['ports'] == proof['interface']
    declarations = re.findall(r'^\s*module\s+([A-Za-z_][A-Za-z_0-9$]*)\s*\(',
                              masked_code((output/'gated_import.v').read_text()), re.M)
    assert len(declarations) == len(set(declarations))
    assert set(declarations) == set(proof['exported_module_names'])
    assert set(declarations) <= set(proof['module_aliases'].values())
    assert proof['module_aliases']['tri_oracle_fabric_gated_executor'] == profile['module']
    assert all(name == profile['module'] or name.startswith('tri_oracle_gated160_') for name in declarations)
    preexisting = set((output/'preexisting_module_names.txt').read_text().splitlines())
    assert 'tri_oracle_fabric_gated_executor' in preexisting
    assert not set(declarations) & preexisting, 'Private import overlaps loaded parent modules'
    result.update(state='source_bound_full_parent_private_gate_relink_checkpoint_qualified',
        independent_isolated_cell_inventory_matches_parent=True,
        private_import_module_names_disjoint_from_parent=True,
        isolated_qualification_sha256=sha(proof_path), qualified_import_sha256=sha(exported),
        isolated_cell_inventory_sha256=sha(inventory))
    result['native_evidence_sha256'].update({str(output/name): sha(output/name) for name in
                                           ['preexisting_module_names.txt', 'relinked_unresolved.rpt']})
    return result
