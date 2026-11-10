"""Prepare trained all-layer shift tests for the unchanged source hardware.

Use one fixed captured row from the first reused diagnostic image, not task
answers. H=2048 input features, D=5632 original intermediate channels, S=64
selected channels in groups0/175, O=35 original outputs2013..2047. Preserve
the full down-matrix stride. These slices qualify number-format interfaces;
they do not qualify all channels, compiled memories, normalization hardware,
whole-model accuracy, whole-chip integration or any paper performance metric.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('HF_HUB_OFFLINE', '1')
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import torch
import torch.nn.functional as functional
from safetensors import safe_open
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize, _requantize
from tri_oracle_cached_feedforward_model_validation import scalar_outputs


def sha(path):
    """Scalar source path -> streamed scalar digest; no tensor/model allocation."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def hardware_shifts(activation_exponent, gate_exponent, up_exponent, gain_cap, down_offset):
    """Caller supplies five Python integer format scalars, no tensor dimensions.
    Return nonnegative six-bit hardware fields plus signed software gain.
    Negative gain attenuates up values with additional right shifts.
    """
    gate_shift = -(activation_exponent + gate_exponent + 8)
    original_up_shift = -(activation_exponent + up_exponent + 8)
    gain = min(original_up_shift, gain_cap)
    up_shift = original_up_shift - gain
    down_shift = max(0, gain + down_offset)
    if any(value < 0 or value > 63 for value in (gate_shift, up_shift, down_shift)):
        raise ValueError('Number format does not fit unsigned six-bit hardware shifts')
    return dict(gate_shift=gate_shift, up_shift=up_shift, down_shift=down_shift, gain=gain)


def write_hex(path, values, bits):
    """Scalar output path/width and caller signed integer list[L] -> L hex lines.
    Mask is representational two's complement; arithmetic values stay unchanged.
    """
    with path.open('x') as stream:
        stream.writelines(f'{value & ((1 << bits)-1):0{bits//4}x}\n' for value in values)


@torch.inference_mode()
def main():
    """Read frozen metadata and22 captured CPU dictionaries, each[256,H].
    Per layer load original gate/up[D,H],down[H,D] float32 checkpoint tensors to
    one graphics processor. The unchanged reference quantizes complete matrices
    before slicing, preserving per-tensor exponents. a/r[1,H] select row143;
    full_raw/full_values[1,H] and stats come from the unchanged reference.

    selected[S] fixes original channel IDs. codes[1,H] and exponent[1,1] come
    from activation quantization. gate/up[S,H], down[O,D], normalized[H],
    activation[H], skip[S], shifts[3], expected[O] are CPU archive lists.
    Independent scalar projection/rounding/interpolation computes expected.

    CUDA cross-check: gate_dot/up_dot[1,S],gate_codes/up_codes[1,S],products[1,S],
    gated/down_input[1,S], final_weights[64,S], check[1,64]. The29 padded
    weight rows meet native integer-multiply alignment and are discarded.
    No training, loss, optimizer, model forward or task scoring occurs.
    """
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    output = root/'records/format331_fixture_preparation.json'
    directory = root/'.cache/model_reference/format331'
    assert not output.exists() and not directory.exists()
    qualified_path = root/'records/format327_qualification.json'
    assert sha(qualified_path) == '750d9451f8fe8c83a2c517bc91a41f1e30c17cfade13a41678bb92d7f0ab6a81'
    qualified = json.loads(qualified_path.read_text())
    scoring_path = root/'records/format326_official_scoring.json'
    assert sha(scoring_path) == qualified['scoring_sha256']
    scoring = json.loads(scoring_path.read_text())
    assert scoring['state'] == 'official_pilot_scoring_completed_baselines_reproduced'
    inputs = dict(scoring['source_sha256'])
    for path in (Path(__file__), qualified_path, scoring_path,
                 root/'syn/test_tri_oracle_format331_configuration.py',
                 root/'syn/tri_oracle_cached_feedforward_model_validation.py',
                 root/'records/format329_failure_diagnosis.json'):
        inputs[str(path)] = sha(path)
    assert all(sha(path) == digest for path, digest in inputs.items())
    policy_path = root/'.cache/model_reference/format322/layer_policy.json'
    assert sha(policy_path) == qualified['published_policy_sha256']
    policy = json.loads(policy_path.read_text())
    assert policy['state'] == 'extended_local_fixed_layer_policy' and len(policy['layers']) == 22
    loader = json.loads((root/'records/format320_loader_metadata.json').read_text())
    model_directory = root/'.cache/model_reference/tiny_llava_v1'
    assert {path.name for path in model_directory.iterdir() if path.is_file()} == set(loader['snapshot_file_names'])
    index = json.loads((model_directory/'model.safetensors.index.json').read_text())
    config = json.loads((model_directory/'config.json').read_text())
    captured = torch.load(root/'.cache/model_reference/format320/captured_rows.pt',
                          map_location='cpu', weights_only=True)
    assert len(captured) == 22
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    assert torch.cuda.mem_get_info()[0] > 10*1024**3
    torch.cuda.set_per_process_memory_fraction(.84)
    torch.cuda.reset_peak_memory_stats()
    selected = torch.tensor([*range(32), *range(5600, 5632)], dtype=torch.int64, device='cuda')  # [S]
    directory.mkdir()
    started = time.monotonic()
    record = dict(state='preparing', started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  source_sha256=inputs, capture_row=143, capture_source='First held-image final selected token',
                  checkpoint_revision=policy['checkpoint_revision'], layers=[], scope=__doc__,
                  source_hardware_verified=False, compiled_memory_verified=False,
                  hardware_full_model_configuration_verified=False, full_paper_results_matched=False)

    def save():
        record['elapsed_seconds'] = time.monotonic()-started
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2)+'\n')
        temporary.replace(output)

    save()
    for layer, row_data in enumerate(captured):
        assert all(row_data[name].shape == (256, 2048) for name in ('activation', 'residual', 'target'))
        matrices = {}  # Original float32 gate/up[D,H],down[H,D], from pinned shards.
        for kind in ('gate', 'up', 'down'):
            names = [name for name in index['weight_map'] if name.endswith(f'.layers.{layer}.mlp.{kind}_proj.weight')]
            assert len(names) == 1
            with safe_open(model_directory/index['weight_map'][names[0]], framework='pt', device='cpu') as shard:
                matrices[kind] = shard.get_tensor(names[0]).to('cuda')
        assert matrices['gate'].shape == matrices['up'].shape == (5632, 2048)
        assert matrices['down'].shape == (2048, 5632)
        reference = IntegerFeedForwardReference(matrices['gate'], matrices['up'], matrices['down'],
                                               config['text_config']['rms_norm_eps'])
        a = row_data['activation'][143:144].to('cuda')  # [1,H], original floating activation.
        r = row_data['residual'][143:144].to('cuda')  # [1,H], original pre-scale residual.
        setting = policy['layers'][layer]
        full_raw, full_values, stats = reference.evaluate(a, r, prune=True,
            maximum_up_gain_bits=setting['maximum_up_gain_bits'], down_shift_offset=setting['down_shift_offset'])
        assert full_raw.shape == full_values.shape == (1, 2048)
        codes, exponent = _quantize(a, per_row=True)  # [1,H] / [1,1].
        fields = hardware_shifts(int(exponent.item()), reference.gate_exponent, reference.up_exponent,
                                 setting['maximum_up_gain_bits'], setting['down_shift_offset'])
        assert all(int(stats[key].item()) == fields[key] for key in ('gate_shift', 'up_shift', 'down_shift'))
        assert int(stats['up_gain_bits'].item()) == fields['gain']
        shifts = [fields[key] for key in ('gate_shift', 'up_shift', 'down_shift')]
        activation = codes[0].cpu().tolist()  # [H] signed8 source.
        normalized = stats['norm_codes'][0].cpu().tolist()  # [H] signed16 pre-scale codes.
        gate = reference.gate.index_select(0, selected).cpu().reshape(-1).tolist()  # [S*H].
        up = reference.up.index_select(0, selected).cpu().reshape(-1).tolist()  # [S*H].
        down = reference.down[2013:2048].cpu().reshape(-1).tolist()  # [O*D].
        outliers = [(position, -1 if value < 0 else 1) for position, value in enumerate(normalized) if abs(value) > 768]
        skip = []  # [S], exact CPU sign-margin branch intersection.
        for channel in range(64):
            gm = sum(sign*(-1 if gate[channel*2048+feature] < 0 else 1) for feature, sign in outliers)
            um = sum(sign*(-1 if up[channel*2048+feature] < 0 else 1) for feature, sign in outliers)
            skip.append(bool(outliers) and gm <= 0 and um == 0)
        expected = scalar_outputs(activation, gate, up, down, selected.cpu().tolist(), skip, shifts)  # [O].
        gate_dot = _dot(codes, reference.gate.index_select(0, selected))  # [1,S].
        up_dot = _dot(codes, reference.up.index_select(0, selected))  # [1,S].
        gate_codes = _requantize(gate_dot, stats['gate_shift'][:, None], 16)  # [1,S].
        up_codes = _requantize(up_dot, stats['up_shift'][:, None], 16)  # [1,S].
        products = reference.silu_response[gate_codes+32768]*up_codes  # [1,S].
        gated = _requantize(products, torch.full_like(stats['down_shift'][:, None], 8), 16)  # [1,S].
        down_input = _requantize(gated, stats['down_shift'][:, None], 8).to(torch.int8)  # [1,S].
        down_input.masked_fill_(torch.tensor(skip, dtype=torch.bool, device='cuda')[None, :], 0)
        final_weights = functional.pad(reference.down[2013:2048].index_select(1, selected), (0, 0, 0, 29))  # [64,S].
        check = _dot(down_input, final_weights)  # [1,64], firstO independently cross-check scalar sums.
        assert check[0, :35].cpu().tolist() == expected
        fixture = directory/f'layer{layer:02d}'
        fixture.mkdir()
        for name, values, bits in [('activation', activation, 8), ('norm', normalized, 16),
                                  ('gate', gate, 8), ('up', up, 8), ('down', down, 8),
                                  ('skip', [int(value) for value in skip], 8), ('expected', expected, 32),
                                  ('groups', [0, 175], 16), ('configuration', [*shifts, 2013, 35], 32)]:
            write_hex(fixture/(name+'.hex'), values, bits)
        entry = dict(layer=layer, fixture=str(fixture), policy=setting, fields=fields,
                     selected_channels=selected.cpu().tolist(), expected_outputs=35,
                     nonzero_outputs=sum(value != 0 for value in expected), skipped_channels=sum(skip),
                     outlier_features=len(outliers), scalar_and_cuda_outputs_identical=True,
                     files_sha256={str(path): sha(path) for path in sorted(fixture.iterdir())})
        if layer == 2:
            for key, position in [('wrong_up_shift', 1), ('wrong_down_shift', 2)]:
                changed = shifts.copy()
                changed[position] += 1
                wrong = scalar_outputs(activation, gate, up, down, selected.cpu().tolist(), skip, changed)
                differences = sum(left != right for left, right in zip(expected, wrong))
                assert differences > 0, 'Chosen fixed layer2 row cannot detect an incorrect shift'
                entry[key] = dict(changed_shift=changed[position], different_output_sums=differences)
        record['layers'].append(entry)
        save()
        print('FORMAT331_FIXTURE_READY', layer, fields, 'nonzero_outputs', entry['nonzero_outputs'], flush=True)
        del matrices, reference, full_raw, full_values, gate_dot, up_dot, gate_codes, up_codes, products, gated, down_input, final_weights, check
    assert all(sha(path) == digest for path, digest in inputs.items())
    assert {path.name for path in model_directory.iterdir() if path.is_file()} == set(loader['snapshot_file_names'])
    assert len(record['layers']) == 22
    record.update(state='all22_trained_format_fixtures_prepared_scalar_cuda_equal',
                  graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                  graphics_peak_reserved_bytes=torch.cuda.max_memory_reserved())
    save()
    print('FORMAT331_PREPARATION_COMPLETED', flush=True)


if __name__ == '__main__':
    main()
