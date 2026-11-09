"""Check private cold-restore failures independently of claimed metadata flags."""
import hashlib
import json
from pathlib import Path
import tempfile

from test_tri_oracle_relinked_parent159 import fixture
from tri_oracle_relinked_parent159_validation import validate_relinked_parent
from tri_oracle_private_restore169 import verify_private_restore


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    root = Path(__file__).resolve().parents[1]
    results = {}
    for case in ['matching', 'changed_gate_cell', 'changed_gate_net', 'lost_preservation', 'relaxed_clock', 'changed_source_checkpoint']:
        with tempfile.TemporaryDirectory(prefix='restore169_test_', dir=root/'.cache/physical') as folder:
            folder = Path(folder)
            original, prepared, sources, generated = fixture(folder)
            manifest = validate_relinked_parent(prepared, original, sources, generated)
            manifest['state'] = 'source_bound_full_parent_private_gate_relink_checkpoint_qualified'
            manifest_path = prepared/'elaborated_checkpoint_manifest.json'
            manifest_path.write_text(json.dumps(manifest))
            output = folder/'restored'
            output.mkdir()
            for before, after in [('gate_parent_cells.tsv', 'gate_cells_before.tsv'),
                                  ('gate_boundary_after.tsv', 'gate_boundary_before.tsv'),
                                  ('gate_preservation.tsv', 'gate_preservation_before.tsv'),
                                  ('elaborated_constraints.sdc', 'restored_constraints.sdc')]:
                (output/after).write_bytes((prepared/before).read_bytes())
            if case == 'changed_gate_cell':
                p = output/'gate_cells_before.tsv'
                p.write_text(p.read_text().replace('AND2D1', 'OR2D1', 1))
            elif case == 'changed_gate_net':
                p = output/'gate_boundary_before.tsv'
                p.write_text(p.read_text().replace('\tin_valid', '\twrong'))
            elif case == 'lost_preservation':
                p = output/'gate_preservation_before.tsv'
                p.write_text(p.read_text().replace('true', 'false'))
            elif case == 'relaxed_clock':
                p = output/'restored_constraints.sdc'
                p.write_text(p.read_text().replace('1.72414', '9.0'))
            elif case == 'changed_source_checkpoint':
                (prepared/'elaborated.db').write_bytes(b'changed')
            # Even matching hashes and positive flags cannot hide wrong contents.
            proof = dict(state='full_parent_cold_restore_wiring_cells_and_constraints_verified',
                producer_manifest_sha256=sha(manifest_path), producer_checkpoint_fingerprint=manifest['checkpoint_fingerprint'],
                source_and_restored_sdc_commands_equal=True, source_and_restored_controller_wiring_and_cell_inventories_equal=True,
                native_evidence_sha256={str(path): sha(path) for path in output.iterdir()})
            (output/'cold_restore_validation.json').write_text(json.dumps(proof))
            try:
                verified = verify_private_restore(prepared, output)
            except AssertionError:
                assert case != 'matching', 'Matching cold restore rejected'
                results[case] = 'rejected'
            else:
                assert case == 'matching', case+' was accepted'
                assert verified['state'] == 'full_parent_private_gate_cold_restore_qualified'
                results[case] = 'accepted'
        assert not folder.exists()
    files = [Path(__file__).resolve(), root/'syn/tri_oracle_private_restore169.py']
    result = root/'records/private_restore169_verifier_validation.json'
    assert not result.exists()
    result.write_text(json.dumps(dict(state='private_cold_restore_verifier_controls_passed', cases=results,
        source_sha256={str(path): sha(path) for path in files},
        scope='Synthetic verifier controls only; actual full-parent cold restore remains pending.'), indent=2)+'\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
