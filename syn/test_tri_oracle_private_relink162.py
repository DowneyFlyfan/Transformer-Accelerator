"""Reject parent copies that agree with each other but differ from isolation."""
import hashlib
import json
from pathlib import Path
import tempfile

from test_tri_oracle_relinked_parent159 import fixture
from tri_oracle_private_relink162_validation import validate_private_relinked_parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_fixture(folder, case):
    prepared, output, sources, generated = fixture(folder)
    isolated = folder/'isolated'
    isolated.mkdir()
    top = 'tri_oracle_fabric_gated_executor_mapped153'
    child = 'tri_oracle_gated160_tri_oracle_silu_gate'
    text = 'module '+top+'(clk,in_valid,out_valid);\ninput clk,in_valid;\noutput out_valid;\n'+child+' activation_unit(.clk(clk),.x(in_valid),.z(out_valid));\nendmodule\n'
    text += 'module '+child+'(clk,x,z);\ninput clk,x;\noutput z;\nXOR2D1BWP12T40P140 g0(.A1(clk),.A2(x),.Z(z));\nendmodule\n'
    (output/'gated_import.v').write_text(text)
    (isolated/'qualified_import.v').write_text(text)
    (isolated/'isolated_cells.tsv').write_text((output/'gate_source_cells.tsv').read_text())
    (output/'preexisting_module_names.txt').write_text('tri_oracle_fabric_gated_executor\ntri_oracle_silu_gate\n')
    (output/'relinked_unresolved.rpt').write_text('unit-test native-report placeholder\n')
    profile = json.loads((output/'gated_interface.json').read_text())
    proof = dict(state='private_gate_import_and_mapped_functional_qualified', output_directory=str(isolated),
        qualified_import_sha256=sha(isolated/'qualified_import.v'), isolated_cell_inventory_sha256=sha(isolated/'isolated_cells.tsv'),
        mapped_gate_standard_cells=1001, cases_passed=31, projection_requests=38,
        wrong_mathematical_reference_rejected=True, exact_quantization_checks=600, interface=profile['ports'],
        attempts={'isolated_import': dict(native_exit_status=0),
                  'positive': dict(native_exit_status=0, temporary_build_removed=True),
                  'wrong_reference': dict(native_exit_status=1, temporary_build_removed=True)},
        module_aliases={'tri_oracle_fabric_gated_executor': top, 'tri_oracle_silu_gate': child},
        exported_module_names=[top, child],
        source_sha256={str(path): sha(path) for path in [isolated/'qualified_import.v', isolated/'isolated_cells.tsv']})
    if case == 'unqualified_isolated_proof':
        proof['state'] = 'failed'
    elif case == 'wrong_isolated_count':
        proof['mapped_gate_standard_cells'] = 1000
    elif case == 'wrong_isolated_interface':
        proof['interface'] = {**proof['interface'], 'extra': dict(direction='input', width_bits=1)}
    proof_path = folder/'private_qualification.json'
    proof_path.write_text(json.dumps(proof))
    sources.update(proof['source_sha256'])
    sources[str(proof_path)] = sha(proof_path)
    if case == 'copied_different_import':
        (output/'gated_import.v').write_text(text+'// Different consumed artifact\n')
    generated = {name: sha(output/name) for name in generated}
    revision = json.loads((output/'input_revision.json').read_text())
    revision.update(source_sha256=sources, generated_sha256=generated, isolated_gate_qualification=str(proof_path))
    (output/'input_revision.json').write_text(json.dumps(revision))
    if case == 'matched_wrong_post_import_cells':
        for name in ['gate_source_cells.tsv', 'gate_parent_cells.tsv']:
            (output/name).write_text((output/name).read_text().replace('AND2D1', 'OR2D1', 1))
    elif case == 'preexisting_alias_collision':
        (output/'preexisting_module_names.txt').write_text('tri_oracle_fabric_gated_executor\n'+child+'\n')
    return prepared, output, sources, generated


def main():
    root = Path(__file__).resolve().parents[1]
    results = {}
    for case in ['matching', 'matched_wrong_post_import_cells', 'preexisting_alias_collision',
                 'copied_different_import', 'unqualified_isolated_proof', 'wrong_isolated_count', 'wrong_isolated_interface']:
        with tempfile.TemporaryDirectory(prefix='relink162_test_', dir=root/'.cache/physical') as folder:
            prepared, output, sources, generated = private_fixture(Path(folder), case)
            try:
                result = validate_private_relinked_parent(output, prepared, sources, generated)
            except AssertionError:
                assert case != 'matching', 'Matching private import fixture rejected'
                results[case] = 'rejected'
            else:
                assert case == 'matching', case+' was accepted'
                assert result['independent_isolated_cell_inventory_matches_parent']
                results[case] = 'accepted'
        assert not Path(folder).exists()
    files = [Path(__file__).resolve(), root/'syn/tri_oracle_private_relink162_validation.py',
             root/'syn/tri_oracle_relinked_parent159_validation.py', root/'syn/test_tri_oracle_relinked_parent159.py']
    path = root/'records/private_relink162_verifier_validation.json'
    assert not path.exists()
    path.write_text(json.dumps(dict(state='private_parent_relink_verifier_controls_passed', cases=results,
        source_sha256={str(path): sha(path) for path in files},
        scope='Synthetic artifact-verifier controls only; no native full-parent integration claim.'), indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
