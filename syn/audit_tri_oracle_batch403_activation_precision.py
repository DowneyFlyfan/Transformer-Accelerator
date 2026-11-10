"""Measure the existing fixed-point learned normalization on the trained layer."""

import json
import math
from pathlib import Path

import torch
from safetensors import safe_open

from run_tri_oracle_batch396_masks import GIB, check_memory, sha256
from tri_oracle_format345_first_token import evaluate_protected
from tri_oracle_integer_reference import IntegerFeedForwardReference, _quantize


ROOT = Path(__file__).resolve().parents[1]
TOKENS, FEATURES = 16, 2048


def rounded(values):
    return values.sign() * torch.floor(values.abs() + 0.5)


def scalar_codes(raw, learned, shifts, epsilon):
    """Round each [token,feature] from exact integer ratios."""
    norm_rows, activation_rows = [], []
    for row, shift in zip(raw, shifts):
        denominator = sum(value * value for value in row) * 65536 + FEATURES * epsilon
        assert denominator > 0 and shift > 0
        norm_row, activation_row = [], []
        for residual, gamma in zip(row, learned):
            numerator = residual * residual * FEATURES * 2**32
            norm = math.isqrt(numerator // denominator)
            norm += 4 * numerator >= (2 * norm + 1)**2 * denominator
            norm = -norm if residual < 0 else norm
            product = norm * gamma
            activation = (abs(product) + 2**(shift - 1)) >> shift
            activation = -activation if product < 0 else activation
            norm_row.append(norm)
            activation_row.append(max(-128, min(127, activation)))
        norm_rows.append(norm_row)
        activation_rows.append(activation_row)
    return norm_rows, activation_rows


@torch.inference_mode()
def main():
    """All activations use [token,feature], and learned coefficients [feature].

    Weight matrices retain their complete original [channel,feature] axes.
    The protected policy stays frozen. Reconstructed trained output has
    [token,feature] shape, with no task scoring or training in this run.
    """
    check_memory(12 * GIB)
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    assert torch.cuda.mem_get_info()[0] > 10 * GIB
    torch.cuda.set_per_process_memory_fraction(0.50)
    torch.cuda.reset_peak_memory_stats()
    model_cache = ROOT / ".cache/model_reference"
    model = model_cache / "tiny_llava_v1"
    reference_path = ROOT / "records/batch389_fixture_preparation.json"
    residual_path = ROOT / "records/batch396_mask_fixture.json"
    reference = json.loads(reference_path.read_text())
    residual_fixture = json.loads(residual_path.read_text())
    assert reference["state"] == "complete_trained_layer_fixture_scalar_cuda_equal"
    assert residual_fixture["state"] == "trained_residuals_and_weight_signs_match_archived_masks"
    assert residual_fixture["source_sha256"][str(reference_path)] == sha256(reference_path)
    epsilon_q16 = residual_fixture["epsilon_q16"]
    captured = model_cache / "format320/captured_rows.pt"
    config = model / "config.json"
    index_path = model / "model.safetensors.index.json"
    index = json.loads(index_path.read_text())["weight_map"]
    epsilon = json.loads(config.read_text())["text_config"]["rms_norm_eps"]
    first_path = model_cache / "format322/layer_policy.json"
    ordinary_path = model_cache / "format335/layer_policy.json"
    first = json.loads(first_path.read_text())["layers"][0]
    ordinary = json.loads(ordinary_path.read_text())["layers"][0]
    activation_hex = Path(reference["fixture"]) / "activation.hex"
    output_hex = Path(reference["fixture"]) / "expected.hex"
    raw_hex = Path(residual_fixture["fixture"]) / "raw.hex"
    keys = {}
    for name, suffix in (
        ("gamma", "post_attention_layernorm.weight"), ("gate", "mlp.gate_proj.weight"),
        ("up", "mlp.up_proj.weight"), ("down", "mlp.down_proj.weight"),
    ):
        keys[name], = (key for key in index if key.endswith(f".layers.0.{suffix}"))
    shards = {model / index[key] for key in keys.values()}
    paths = (reference_path, residual_path, captured, config, index_path, first_path, ordinary_path,
             activation_hex, output_hex, raw_hex, Path(__file__), *sorted(shards),
             ROOT / "syn/tri_oracle_integer_reference.py", ROOT / "syn/tri_oracle_format345_first_token.py",
             ROOT / "syn/tri_oracle_model_reference.py", ROOT / "syn/run_tri_oracle_batch396_masks.py")
    inputs = {str(path): sha256(path) for path in paths}
    archived = reference["source_sha256"] | reference["files_sha256"] | residual_fixture["files_sha256"]
    assert all(inputs[path] == archived[path] for path in inputs if path in archived)

    tensors = {}
    for name, key in keys.items():
        with safe_open(model / index[key], framework="pt", device="cpu") as shard:
            tensors[name] = shard.get_tensor(key).to("cuda")
    captured_layer = torch.load(captured, map_location="cpu", weights_only=True)[0]
    activation, residual = (captured_layer[name][:TOKENS].to("cuda") for name in ("activation", "residual"))
    assert activation.shape == residual.shape == (TOKENS, FEATURES)
    assert activation.dtype == residual.dtype == torch.float32
    gamma = tensors["gamma"].double()
    assert gamma.shape == (FEATURES,)

    baseline, exponents = _quantize(activation, per_row=True)
    activation_archive = torch.tensor([int(line, 16) for line in activation_hex.read_text().splitlines()],
        dtype=torch.uint8, device="cuda").view(torch.int8).reshape(TOKENS, FEATURES)
    assert torch.equal(baseline, activation_archive)
    float_norm = residual * torch.rsqrt(residual.square().mean(dim=1, keepdim=True) + epsilon)
    float_codes, float_exponents = _quantize(float_norm * gamma.float(), per_row=True)
    assert torch.equal(float_codes, baseline) and torch.equal(float_exponents, exponents)

    raw = rounded(residual.double() * 8192).to(torch.int64)
    assert raw.min() >= -32768 and raw.max() <= 32767
    packed_raw = [sum((value & 65535) << (16 * lane) for lane, value in enumerate(strip))
                  for strip in raw.reshape(-1, 8).cpu().tolist()]
    assert packed_raw == [int(line, 16) for line in raw_hex.read_text().splitlines()]
    learned = rounded(gamma * 32768).to(torch.int64)
    assert learned.min() >= -32768 and learned.max() <= 32767
    shifts = (exponents + 23).flatten()
    assert bool(((shifts > 0) & (shifts <= 63)).all())
    norm_rows, activation_rows = scalar_codes(
        raw.cpu().tolist(), learned.cpu().tolist(), shifts.cpu().tolist(), epsilon_q16)
    independent_norm = torch.tensor(norm_rows, dtype=torch.int64, device="cuda")
    fixed_codes = torch.tensor(activation_rows, dtype=torch.int8, device="cuda")
    denominator = (raw.double().square().mean(dim=1, keepdim=True) + epsilon_q16 / 65536).sqrt()
    parallel_norm = rounded(raw.double() * 256 / denominator).to(torch.int64)
    parallel_codes = rounded(torch.ldexp((parallel_norm * learned).double(), -shifts[:, None]))
    assert torch.equal(independent_norm, parallel_norm)
    assert torch.equal(fixed_codes, parallel_codes.clamp(-128, 127).to(torch.int8))
    float_outliers = rounded(
        residual.double() * 256 / (residual.double().square().mean(dim=1, keepdim=True) + epsilon).sqrt()
    )
    assert torch.equal(independent_norm.abs() > 768, float_outliers.abs() > 768)
    assert torch.equal(independent_norm[independent_norm.abs() > 768].sign(),
                       float_outliers[float_outliers.abs() > 768].sign().to(torch.int64))

    weight_reference = IntegerFeedForwardReference(tensors["gate"], tensors["up"], tensors["down"], epsilon)
    old_raw, old_values, old_stats = evaluate_protected(weight_reference, activation, residual, ordinary, first, 0, prune=True)
    assert (old_raw.to(torch.int64) & 0xffffffff).flatten().cpu().tolist() == [
        int(line, 16) for line in output_hex.read_text().splitlines()
    ]
    learned_activation = torch.ldexp(fixed_codes.float(), exponents)
    reconstructed, new_exponents = _quantize(learned_activation, per_row=True)
    assert torch.equal(reconstructed, fixed_codes) and torch.equal(new_exponents, exponents)
    new_raw, new_values, new_stats = evaluate_protected(
        weight_reference, learned_activation, residual, ordinary, first, 0, prune=True)
    for key in ("outlier_count", "skip_count", "gate_shift", "up_shift", "down_shift"):
        assert torch.equal(old_stats[key], new_stats[key]), key
    input_difference = (fixed_codes.short() - baseline.short()).abs()
    output_difference = new_raw.to(torch.int64) - old_raw.to(torch.int64)
    assert int(input_difference.max()) == 1 and int((input_difference != 0).sum()) == 318
    check_memory(8 * GIB)
    assert all(sha256(Path(path)) == digest for path, digest in inputs.items())

    directory = model_cache / "batch403"
    output = ROOT / "records/batch403_activation_precision.json"
    assert not output.exists()
    directory.mkdir()
    data = {
        "gamma": (learned.cpu().tolist(), 16),
        "norm": (independent_norm.flatten().cpu().tolist(), 16),
        "activation": (fixed_codes.flatten().cpu().tolist(), 8),
        "shifts": (shifts.cpu().tolist(), 8),
        "expected": (new_raw.flatten().cpu().tolist(), 32),
    }
    for name, (words, bits) in data.items():
        with (directory / f"{name}.hex").open("x") as stream:
            stream.writelines(f"{value & (2**bits-1):0{bits//4}x}\n" for value in words)
    record = {
        "state": "trained_fixed_normalization_and_output_effect_characterized",
        "scope": __doc__,
        "tokens": TOKENS,
        "features": FEATURES,
        "raw_fraction_bits": 13,
        "normalized_fraction_bits": 8,
        "coefficient_fraction_bits": 15,
        "epsilon_q16": epsilon_q16,
        "activation_comparisons": TOKENS * FEATURES,
        "activation_codes_changed": int((input_difference != 0).sum()),
        "maximum_activation_code_change": int(input_difference.max()),
        "predictor_outlier_and_sign_drift": 0,
        "baseline_output_archive_matches": TOKENS * FEATURES,
        "output_codes_changed": int((output_difference != 0).sum()),
        "maximum_output_code_change": int(output_difference.abs().max()),
        "output_value_relative_l2_change": float((new_values.double() - old_values.double()).norm() / old_values.double().norm()),
        "scalar_and_cuda_activations_equal": True,
        "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
        "source_sha256": inputs,
        "fixture": str(directory),
        "files_sha256": {str(path): sha256(path) for path in sorted(directory.glob("*.hex"))},
        "native_activation_verified": False,
        "full_paper_results_matched": False,
    }
    output.write_text(json.dumps(record, indent=2) + "\n")
    print(f"BATCH403_ACTIVATION_AUDITED changed_inputs=318 changed_outputs={record['output_codes_changed']}", flush=True)


if __name__ == "__main__":
    main()
