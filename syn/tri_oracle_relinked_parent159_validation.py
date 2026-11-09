"""Bind a relinked full parent to its original snapshot and mapped gate proof."""
import datetime
import hashlib
import json
from pathlib import Path

from tri_oracle_artifact_fingerprint import artifact_fingerprint


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def commands(path):
    return [line.strip() for line in Path(path).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def lines(path):
    return sorted(Path(path).read_text().splitlines())


def validate_relinked_parent(output, prepared, expected_sources, expected_generated):
    output, prepared = Path(output), Path(prepared)
    revision = json.loads((output/'input_revision.json').read_text())
    assert revision['source_sha256'] == expected_sources, 'Changed source ledger'
    assert revision['generated_sha256'] == expected_generated, 'Changed pre-launch generated ledger'
    assert set(expected_generated) == {'gated_import.v', 'native_entry.tcl', 'gated_interface.json'}
    assert all(sha(path) == expected for path, expected in expected_sources.items()), 'Changed source input'
    assert all(sha(output/name) == expected for name, expected in expected_generated.items()), 'Changed consumed generated input'
    source_manifest = prepared/'elaborated_checkpoint_manifest.json'
    original = json.loads(source_manifest.read_text())
    assert all(sha(path) == expected for path, expected in original['source_sha256'].items())
    assert all(sha(path) == expected for path, expected in original['native_evidence_sha256'].items())
    assert artifact_fingerprint(prepared/'elaborated.db') == original['checkpoint_fingerprint'] == revision['producer_checkpoint_fingerprint']
    cold = json.loads((output/'cold_restore_validation.json').read_text())
    assert cold['state'] == 'full_parent_cold_restore_wiring_cells_and_constraints_verified'
    assert cold['producer_manifest_sha256'] == sha(source_manifest)
    assert cold['producer_checkpoint_fingerprint'] == original['checkpoint_fingerprint']
    assert cold['source_and_restored_sdc_commands_equal'] and cold['source_and_restored_controller_wiring_and_cell_inventories_equal']
    assert cold['native_evidence_sha256'] and all(sha(path) == expected for path, expected in cold['native_evidence_sha256'].items())
    gate_proof = json.loads(Path(revision['mapped_gate_qualification']).read_text())
    assert str(Path(revision['mapped_gate_qualification'])) in expected_sources
    assert gate_proof['state'] == 'original_gate_controller_mapped_functional_qualified'
    assert gate_proof['cases_passed'] == 31 and gate_proof['projection_requests'] == 38
    assert gate_proof['wrong_mathematical_reference_rejected']
    assert all(sha(path) == expected for path, expected in gate_proof.get('source_sha256', {}).items())
    original_constraints = commands(prepared/'elaborated_constraints.sdc')
    assert commands(output/'restored_constraints.sdc') == original_constraints
    assert commands(output/'relinked_constraints.sdc') == original_constraints, 'Relinking changed clock or IO constraints'
    preserve_command = 'set_dont_touch [get_cells numeric/engine/gated]'
    final_constraints = commands(output/'elaborated_constraints.sdc')
    assert preserve_command not in original_constraints and final_constraints.count(preserve_command) == 1
    assert [line for line in final_constraints if line != preserve_command] == original_constraints, 'Unexpected constraint change'
    for before, after in [('reused_controls_before.tsv.sorted', 'reused_controls_after.tsv.sorted'),
                          ('preserved_banks_before.tsv', 'preserved_banks_after.tsv'),
                          ('mapped_controller_boundaries.tsv', 'retained_controller_boundaries.tsv')]:
        assert lines(prepared/before) == lines(output/after), 'Original parent inventory or wiring changed: '+after
    profile = json.loads((output/'gated_interface.json').read_text())
    assert profile['instance'] == 'numeric/engine/gated'
    assert profile['module'] == 'tri_oracle_fabric_gated_executor_mapped153'
    expected_pins = set()
    for name, shape in profile['ports'].items():
        width = shape['width_bits']
        assert isinstance(width, int) and width > 0 and shape['direction'] in ['input', 'output', 'inout']
        expected_pins.update(profile['instance']+'/'+name+(('['+str(bit)+']') if width > 1 else '') for bit in range(width))
    before, after = lines(output/'gate_boundary_before.tsv'), lines(output/'gate_boundary_after.tsv')
    assert before == after, 'Changed mapped gate boundary'
    rows = [line.split('\t') for line in after]
    assert all(len(row) == 2 and row[1] for row in rows)
    assert len(rows) == len(expected_pins) and {row[0] for row in rows} == expected_pins
    source_cells, parent_cells = lines(output/'gate_source_cells.tsv'), lines(output/'gate_parent_cells.tsv')
    assert source_cells == parent_cells and len(source_cells) >= 1000, 'Changed mapped gate cells'
    cell_rows = [line.split('\t') for line in source_cells]
    assert all(len(row) == 2 and row[1].endswith('BWP12T40P140') for row in cell_rows)
    assert len({row[0] for row in cell_rows}) == len(cell_rows)
    assert lines(output/'gate_preservation.tsv') == [profile['instance']+'\t'+profile['module']+'\ttrue']
    evidence = ['input_revision.json', *expected_generated, 'cold_restore_validation.json', 'restored_constraints.sdc',
                'relinked_constraints.sdc', 'elaborated_constraints.sdc', 'reused_controls_after.tsv.sorted',
                'preserved_banks_after.tsv', 'retained_controller_boundaries.tsv', 'gate_boundary_before.tsv',
                'gate_boundary_after.tsv', 'gate_source_cells.tsv', 'gate_parent_cells.tsv',
                'gate_preservation.tsv', 'relinked_wiring.rpt']
    return dict(state='source_bound_full_parent_mapped_gate_relink_checkpoint_qualified',
                observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                producer_manifest_sha256=sha(source_manifest), producer_checkpoint_fingerprint=original['checkpoint_fingerprint'],
                checkpoint_fingerprint=artifact_fingerprint(output/'elaborated.db'),
                source_sha256=expected_sources, generated_sha256=expected_generated,
                native_evidence_sha256={str(output/name): sha(output/name) for name in evidence},
                mapped_gate_standard_cells=len(source_cells), mapped_gate_boundary_bits=len(expected_pins),
                original_clock_IO_and_parent_wiring_preserved=True,
                scope='Full prepared prediction/feed-forward parent relink checkpoint with functionally checked mapped gate controller. '
                      'Full-parent mapping, mapped simulation, routed timing and paper results remain unqualified.',
                full_paper_results_matched=False, routed_timing_qualified=False)
