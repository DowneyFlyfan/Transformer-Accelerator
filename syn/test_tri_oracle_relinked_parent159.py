"""Reject altered wiring, constraints, cells and provenance after parent relinking."""
import hashlib
import json
from pathlib import Path
import tempfile

from tri_oracle_artifact_fingerprint import artifact_fingerprint
from tri_oracle_relinked_parent159_validation import validate_relinked_parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture(folder):
    prepared, output = folder/'prepared', folder/'output'
    prepared.mkdir()
    output.mkdir()
    baseline = {
        'elaborated_constraints.sdc': 'create_clock -name core_clock -period 1.72414 [get_ports clk]\n',
        'reused_controls_before.tsv.sorted': 'original/control/cell\tAND2D1BWP12T40P140\n',
        'preserved_banks_before.tsv': 'instance\tmaster\tarea_um2\tpreserve\ncore\tcore_model\t1\ttrue\n',
        'mapped_controller_boundaries.tsv': 'instance\thpin\thnet\noriginal\toriginal/clk\tclk\n',
    }
    for name, text in baseline.items():
        (prepared/name).write_text(text)
    (prepared/'elaborated.db').write_bytes(b'unit-test original checkpoint')
    manifest = dict(source_sha256={}, native_evidence_sha256={str(prepared/name): sha(prepared/name) for name in baseline},
                    checkpoint_fingerprint=artifact_fingerprint(prepared/'elaborated.db'))
    source_manifest = prepared/'elaborated_checkpoint_manifest.json'
    source_manifest.write_text(json.dumps(manifest))
    for source, destination in [('elaborated_constraints.sdc', 'restored_constraints.sdc'),
                                ('elaborated_constraints.sdc', 'relinked_constraints.sdc'),
                                ('reused_controls_before.tsv.sorted', 'reused_controls_after.tsv.sorted'),
                                ('preserved_banks_before.tsv', 'preserved_banks_after.tsv'),
                                ('mapped_controller_boundaries.tsv', 'retained_controller_boundaries.tsv')]:
        (output/destination).write_text(baseline[source])
    (output/'elaborated_constraints.sdc').write_text(baseline['elaborated_constraints.sdc']+'set_dont_touch [get_cells numeric/engine/gated]\n')
    profile = dict(module='tri_oracle_fabric_gated_executor_mapped153', instance='numeric/engine/gated',
                   ports={name: dict(direction=direction, width_bits=1) for name, direction in
                          [('clk', 'input'), ('in_valid', 'input'), ('out_valid', 'output')]})
    (output/'gated_interface.json').write_text(json.dumps(profile))
    boundary = ''.join('numeric/engine/gated/'+name+'\t'+name+'\n' for name in profile['ports'])
    for suffix in ['before', 'after']:
        (output/('gate_boundary_'+suffix+'.tsv')).write_text(boundary)
    cells = ''.join('g'+str(i)+'\tAND2D1BWP12T40P140\n' for i in range(1001))
    for kind in ['source', 'parent']:
        (output/('gate_'+kind+'_cells.tsv')).write_text(cells)
    (output/'gate_preservation.tsv').write_text(profile['instance']+'\t'+profile['module']+'\ttrue\n')
    (output/'elaborated.db').write_bytes(b'unit-test relinked checkpoint')
    (output/'relinked_wiring.rpt').write_text('unit-test wiring report\n')
    (output/'cold_restore_validation.json').write_text(json.dumps(dict(
        state='full_parent_cold_restore_wiring_cells_and_constraints_verified',
        producer_manifest_sha256=sha(source_manifest), producer_checkpoint_fingerprint=manifest['checkpoint_fingerprint'],
        source_and_restored_sdc_commands_equal=True, source_and_restored_controller_wiring_and_cell_inventories_equal=True,
        native_evidence_sha256={str(output/'restored_constraints.sdc'): sha(output/'restored_constraints.sdc')})))
    (output/'gated_import.v').write_text('unit-test generated netlist bytes\n')
    (output/'native_entry.tcl').write_text('unit-test generated native entry\n')
    qualification = folder/'gated_qualification.json'
    qualification.write_text(json.dumps(dict(state='original_gate_controller_mapped_functional_qualified',
        cases_passed=31, projection_requests=38, wrong_mathematical_reference_rejected=True)))
    sources = {str(qualification): sha(qualification)}
    generated = {name: sha(output/name) for name in ['gated_import.v', 'native_entry.tcl', 'gated_interface.json']}
    revision = dict(source_sha256=sources, generated_sha256=generated, mapped_gate_qualification=str(qualification),
                    producer_checkpoint_fingerprint=manifest['checkpoint_fingerprint'])
    (output/'input_revision.json').write_text(json.dumps(revision))
    return prepared, output, sources, generated


def main():
    root = Path(__file__).resolve().parents[1]
    mutations = {
        'matching': None,
        'relaxed_clock': lambda p: (p/'relinked_constraints.sdc').write_text('create_clock -period 9 [get_ports clk]\n'),
        'extra_false_path': lambda p: (p/'elaborated_constraints.sdc').write_text((p/'elaborated_constraints.sdc').read_text()+'set_false_path -to [all_outputs]\n'),
        'changed_boundary': lambda p: (p/'gate_boundary_after.tsv').write_text((p/'gate_boundary_after.tsv').read_text().replace('\tin_valid', '\twrong_net')),
        'changed_gate_cell': lambda p: (p/'gate_parent_cells.tsv').write_text((p/'gate_parent_cells.tsv').read_text().replace('AND2D1', 'OR2D1', 1)),
        'changed_original_cell': lambda p: (p/'reused_controls_after.tsv.sorted').write_text('wrong\tOR2D1BWP12T40P140\n'),
        'lost_preservation': lambda p: (p/'gate_preservation.tsv').write_text((p/'gate_preservation.tsv').read_text().replace('true', 'false')),
        'changed_generated_netlist': lambda p: (p/'gated_import.v').write_text('changed\n'),
        'changed_original_checkpoint': lambda p: (p.parent/'prepared/elaborated.db').write_bytes(b'changed'),
    }
    results = {}
    for name, mutate in mutations.items():
        with tempfile.TemporaryDirectory(prefix='relink159_test_', dir=root/'.cache/physical') as folder:
            prepared, output, sources, generated = fixture(Path(folder))
            if mutate:
                mutate(output)
            try:
                result = validate_relinked_parent(output, prepared, sources, generated)
            except AssertionError:
                assert mutate is not None, 'Matching fixture rejected'
                results[name] = 'rejected'
            else:
                assert mutate is None, name+' mutation accepted'
                assert result['mapped_gate_standard_cells'] == 1001
                results[name] = 'accepted'
        assert not Path(folder).exists()
    path = root/'records/relinked159_verifier_validation.json'
    assert not path.exists()
    path.write_text(json.dumps(dict(state='relinked_parent_verifier_controls_passed', cases=results,
        source_sha256={str(p): sha(p) for p in [Path(__file__).resolve(), root/'syn/tri_oracle_relinked_parent159_validation.py']},
        scope='Synthetic verifier controls only; no native accelerator integration claim.'), indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
