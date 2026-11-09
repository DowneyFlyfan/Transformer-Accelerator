"""Mandatory historical-input attestation for the exact completed 191 run.

The raw 191 result alone is not qualified. This verifier accepts only that
immutable run, not fresh results or freshly rebased manifests. A future run
must enforce historical anchors and shard membership before launching.
No tensors are evaluated and no hardware or dataset-accuracy claim is made.
"""
import hashlib
import json
from pathlib import Path


ANCHORS = {
    'full_layer_quantization_error_audit': '97e6b3383a2e15fa0a03c8b90782f851204a7d31952395720414c49c320fea75',
    'model_reference_pruning_validation': 'fdfdd7cbeb5a86c0df41b51a5aa06d3b9fc8d1f82ad3781556e138ccf06f0ae6',
    'model_reference_candidate': 'd462cb1574fc26edea3b17e06e1f3567c395f579f06d5cc087443e475167e9d5',
    'real_frame190_preparation_qualification': 'c13f4d8a43754d8de905fd4a7fe6f22bee224d1aca026e542d6e2d301289d096',
    'folded_scale191_guard': '1e15a665a977fe329bc51683d584b379b3bf978bc502ea78491933ef547fec2c',
    'folded_scale191_gpu_result': 'f3dbaa4dc4433c2bbef47eb1282fe3606e0994cbd8c40913f8d2c357c42601ad',
}
LOAD_SUFFIXES = ('mlp.gate_proj.weight', 'mlp.up_proj.weight',
                 'mlp.down_proj.weight', 'post_attention_layernorm.weight')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require_loaded_shards(folder, index, verified):
    """Resolve the exact four keys used by the source-bound 191 load function."""
    consumed = {}
    for suffix in LOAD_SUFFIXES:
        key = 'language_model.model.layers.0.' + suffix
        shard = (folder / index[key]).resolve()
        assert shard in verified, 'Index points outside independently verified shards'
        consumed[key] = str(shard)
    return consumed


def main():
    root = Path(__file__).resolve().parents[1]
    evidence = {}
    records = {}
    for name, expected in ANCHORS.items():
        path = root / 'records' / (name + '.json')
        assert sha(path) == expected, 'Historical proof or completed run changed: ' + name
        evidence[str(path)] = expected
        records[name] = json.loads(path.read_text())
    result = records['folded_scale191_gpu_result']
    guard = records['folded_scale191_guard']
    audit = records['full_layer_quantization_error_audit']
    candidate = records['model_reference_candidate']
    pruning = records['model_reference_pruning_validation']
    prepared = records['real_frame190_preparation_qualification']
    assert guard['state'] == 'bounded_gpu_reference_completed' and guard['native_exit_status'] == 0
    assert guard['result_sha256'] == ANCHORS['folded_scale191_gpu_result']
    assert result['state'] == 'paired_folded_scale_diagnostic_completed'
    identities = dict(result['source_sha256'])
    for path, digest in guard['source_sha256'].items():
        assert path not in identities or identities[path] == digest
        identities[path] = digest
    assert all(sha(path) == digest for path, digest in identities.items()), 'Consumed input changed'
    evidence.update(identities)
    log = root / 'records/folded_scale191_gpu_native.log'
    assert sha(log) == guard['native_console_sha256']
    assert '\nFOLDED_SCALE191_DIAGNOSTIC_COMPLETE ' in '\n' + log.read_text()
    evidence[str(log)] = sha(log)
    folder = root / '.cache/model_reference/tiny_llava_v1'
    config = folder / 'config.json'
    index_path = folder / 'model.safetensors.index.json'
    assert sha(config) == candidate['config_sha256']
    assert sha(index_path) == audit['weight_index_sha256']
    verified = {(root / item['path']).resolve(): item for item in candidate['verified_weights']}
    consumed = require_loaded_shards(folder, json.loads(index_path.read_text())['weight_map'], verified)
    for path in set(consumed.values()):
        item = verified[Path(path)]
        assert identities[path] == item['sha256'] and Path(path).stat().st_size == item['bytes']
    full = root / '.cache/model_reference/full_layer_fixture'
    partial = root / '.cache/model_reference/feedforward_pruning_fixture'
    assert sha(full / 'manifest.json') == audit['baseline_fixture_manifest_sha256'] == prepared['archived_manifest_sha256']
    full_manifest = json.loads((full / 'manifest.json').read_text())
    cases = {case['token']: case for case in audit['cases']}
    assert sha(full / 'prediction_source.json') == cases['token11']['source_sha256'] == full_manifest['files']['prediction_source.json']
    assert sha(partial / 'prediction_source.json') == cases['token0']['source_sha256'] == pruning['files']['prediction_source.json']
    assert sha(full / 'expected.hex') == full_manifest['files']['expected.hex']
    assert len((full / 'expected.hex').read_text().splitlines()) == 2048
    assert result['checkpoint_revision'] == candidate['revision'] == audit['revision'] == pruning['revision']
    assert result['token_positions'] == [11, 0] and result['token_count'] == 2 and result['layer_index'] == 0
    assert all(value < 1e-6 for value in result['floating_identity_relative_l2'])
    by_case = {(case['policy'], case['prune']): case for case in result['cases']}
    assert len(by_case) == len(result['cases']) == 4
    assert by_case['original', False]['original_archived_2048_output_words_match'] is True
    comparisons = {}
    for prune in (False, True):
        original = by_case['original', prune]['relative_l2_per_token']
        folded = by_case['folded_learned_scale', prune]['relative_l2_per_token']
        assert len(original) == len(folded) == 2 and all(b > a for a, b in zip(original, folded))
        comparisons['predicted' if prune else 'dense'] = dict(original=original, folded=folded)
    assert not result['source_hardware_changed'] and not result['full_model_accuracy_qualified'] and not result['paper_results_matched']
    diagram = root / '.cache/model_reference/folded_scale191_reference_flow.pdf'
    evidence[str(diagram)] = sha(diagram)
    evidence[str(Path(__file__).resolve())] = sha(__file__)
    proof = dict(state='completed191_run_independently_attested', evidence_sha256=evidence,
        loaded_shards=consumed, local_relative_l2=comparisons,
        archived_original_integer_words_matched=2048,
        decision='Retain original learned-scale representation; folding worsened both tested dense errors.',
        raw191_result_requires_this_attestation=True,
        future_fresh_runs_require_prelaunch_historical_anchors_and_shard_membership=True,
        diagram_source_checks=['Quantizer, dot alignment and ties-away saturation checked against integer reference.',
            'Gate/up shifts, gain, SiLU interpolation, product/down rounding and prediction mask checked against reference.',
            'Original/folded input and weight wiring, floating identity and four recorded cases checked against diagnostic.'],
        diagram_visually_inspected=True, source_hardware_changed=False, full_model_accuracy_qualified=False,
        routed_timing_qualified=False, paper_results_matched=False,
        scope='Independent attestation of this exact completed software diagnostic, two archived tokens and one trained layer only. '
              'Historical sources and original expected outputs are independently anchored; every actually loaded shard belongs '
              'to the pinned verified candidate. No fresh execution, hardware arithmetic or task accuracy is qualified.')
    output = root / 'records/folded_scale191_qualification.json'
    assert not output.exists()
    output.write_text(json.dumps(proof, indent=2) + '\n')
    print(proof['state'])


if __name__ == '__main__':
    main()
