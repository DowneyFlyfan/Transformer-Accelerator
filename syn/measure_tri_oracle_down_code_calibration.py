"""Fit at most one signed eight-bit code step per down-projection weight."""

import argparse
import json
from pathlib import Path
import time

from safetensors import safe_open
import torch

from measure_tri_oracle_input_equalization import CACHE, EXPANSION, GIB, HIDDEN, LAYERS, host_available
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize, _requantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


RIDGE_FRACTIONS = (0.03, 0.3, 3.0)
IDENTITY = "original"


def read(path):
    return json.loads(path.read_text())


def reconstruct_input(reference, activation, residual, policy):
    """Recover signed-eight-bit down inputs [M,K] and row scales [M,1].

    M counts archived token rows, H counts hidden features and K counts
    intermediate channels. The input activation and residual are [M,H].
    """
    original_raw, original_values, stats = evaluate_policy(reference, activation, residual, policy, prune=True)
    activation_codes, _ = _quantize(activation, per_row=True)  # [M,H], actual row codes
    gate = _requantize(_dot(activation_codes, reference.gate), stats["gate_shift"][:, None], 16)  # [M,K]
    up = _requantize(_dot(activation_codes, reference.up), stats["up_shift"][:, None], 16)  # [M,K]
    products = reference.silu_response[gate + 32768] * up  # [M,K], signed fixed-point product
    shift = stats["down_shift"][:, None]  # [M,1], frozen format policy
    scaled_products = _requantize(products, torch.full_like(shift, 8), 16)  # [M,K]
    down_input = _requantize(scaled_products, shift, 8).to(torch.int8)  # [M,K]
    norm_codes = stats["norm_codes"]  # [M,H], unchanged prediction path
    outlier = norm_codes.abs() > 768  # [M,H], strict three-sigma condition
    signs = (torch.where(norm_codes < 0, -1, 1) * outlier).to(torch.int8)  # [M,H]
    skip = outlier.any(dim=1, keepdim=True) & (_dot(signs, reference.gate_sign) <= 0)  # [M,K]
    skip &= _dot(signs, reference.up_sign) == 0
    down_input = down_input.masked_fill(skip, 0)  # [M,K], exact hardware mask and codes
    assert torch.equal(skip.sum(dim=1), stats["skip_count"])
    row_exponent = shift - 8 - stats["up_gain_bits"][:, None]  # [M,1], physical input exponent
    actual_raw = _dot(down_input, reference.down)  # [M,H], signed32 accumulators
    assert torch.equal(actual_raw, original_raw)
    assert torch.equal(torch.ldexp(actual_raw.float(), reference.down_exponent + row_exponent), original_values)
    return down_input, row_exponent, original_values


def fit_codebook(down_input, row_exponent, baseline_values, targets, original_codes, output_exponent, fraction):
    """Fit additive physical weights on calibration rows and round to legal signed8 codes.

    Inputs are [M,K], exponents [M,1], outputs and targets [M,H], weights [H,K],
    and the unchanged per-output exponent [1,H]. For normalized design rows X
    and residual R, the ridge solution in weight units is X^T (X X^T + λI)^-1 R.
    """
    denominator = targets.norm(dim=1, keepdim=True).clamp_min(1e-20)  # [M,1]
    design = torch.ldexp(down_input.float(), row_exponent) / denominator  # [M,K]
    residual = (targets - baseline_values) / denominator  # [M,H]
    gram = design @ design.T  # [M,M], dual Gram matrix from calibration only
    ridge = gram.diagonal().mean() * fraction  # scalar in design units
    gram.diagonal().add_(ridge.clamp_min(1e-20))
    dual = torch.linalg.solve(gram, residual)  # [M,H], regularized dual solution
    physical_delta = (design.T @ dual).T  # [H,K], additive floating weight change
    code_delta = torch.ldexp(physical_delta, -output_exponent.T).round().clamp(-1, 1)  # [H,K]
    candidate = (original_codes.to(torch.int16) + code_delta.to(torch.int16)).clamp(-128, 127).to(torch.int8)
    assert bool(torch.isfinite(physical_delta).all())
    assert bool(((candidate.to(torch.int16) - original_codes).abs() <= 1).all())
    return candidate


def score(down_input, row_exponent, targets, weights, output_exponent):
    """Score signed8 [M,K] by [H,K] using the existing signed32 dot path."""
    values = torch.ldexp(_dot(down_input, weights).float(), row_exponent + output_exponent)  # [M,H]
    error = (values - targets).norm(dim=1) / targets.norm(dim=1).clamp_min(1e-20)  # [M]
    assert bool(torch.isfinite(error).all())
    return float(error.mean())


@torch.inference_mode()
def run(output, export_codes=False):
    assert __debug__ and Path("/.dockerenv").is_file()
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 3 * GIB and host_available() >= 10 * GIB
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    torch.cuda.set_per_process_memory_fraction(0.125)
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    earlier_path = CACHE / "gqa_testdev/activation_range_per_row/receipt.json"
    earlier = read(earlier_path)
    evidence = {name: checksum for name, checksum in earlier["evidence_sha256"].items()}
    for path in (earlier_path, Path(__file__).resolve()):
        evidence[str(path)] = sha256(path)
    assert all(sha256(Path(name)) == checksum for name, checksum in evidence.items())
    model = CACHE / "tiny_llava_v1"
    mapping = read(model / "model.safetensors.index.json")["weight_map"]
    epsilon = read(model / "config.json")["text_config"]["rms_norm_eps"]
    archive = torch.load(CACHE / "format320/captured_rows.pt", map_location="cpu", weights_only=True, mmap=True)
    policies = read(CACHE / "format335/layer_policy.json")["layers"]
    # Each image has 16 saved positions. Hold out position zero in every split.
    indices = [row for row in range(256) if row % 16]
    fit, validation, calibration, hold = slice(0, 60), slice(60, 120), slice(0, 120), slice(120, 240)
    layers = []
    codes_path = output / "codes"
    output.mkdir()
    if export_codes:
        codes_path.mkdir()
    assert len(archive) == len(policies) == LAYERS
    for layer, (capture, policy) in enumerate(zip(archive, policies, strict=True)):
        assert host_available() >= 8 * GIB
        matrices = []
        for role in ("gate", "up", "down"):
            key, = (name for name in mapping if name.endswith(f".layers.{layer}.mlp.{role}_proj.weight"))
            with safe_open(model / mapping[key], framework="pt", device="cpu") as shard:
                matrices.append(shard.get_tensor(key).to(device="cuda", dtype=torch.float32))
        gate, up, down = matrices  # frozen [K,H], [K,H], [H,K]
        assert gate.shape == up.shape == (EXPANSION, HIDDEN) and down.shape == (HIDDEN, EXPANSION)
        reference = IntegerFeedForwardReference(gate, up, down, epsilon)
        original, scales = _quantize(down, per_row=True)  # signed8 [H,K], [H,1]
        reference.down, reference.down_exponent = original, scales.T  # [H,K], [1,H]
        activation, residual, targets = (capture[name][indices].to(device="cuda", dtype=torch.float32)
                                         for name in ("activation", "residual", "target"))  # [240,H]
        down_input, row_exponent, baseline_values = reconstruct_input(reference, activation, residual, policy)

        def fitted(rows, fraction):
            return fit_codebook(down_input[rows], row_exponent[rows], baseline_values[rows], targets[rows],
                                original, scales.T, fraction)

        def evaluate(rows, weights):
            return score(down_input[rows], row_exponent[rows], targets[rows], weights, scales.T)

        validation_scores = {IDENTITY: evaluate(validation, original)}
        for fraction in RIDGE_FRACTIONS:
            validation_scores[str(fraction)] = evaluate(validation, fitted(fit, fraction))
        choice = min(validation_scores, key=validation_scores.__getitem__)
        selected = original if choice == IDENTITY else fitted(calibration, float(choice))  # [H,K]
        baseline_error, selected_error = evaluate(hold, original), evaluate(hold, selected)
        old_score = earlier["layers"][layer]["held"]["0"]["mean_relative_output_error"]
        assert abs(baseline_error - old_score) < 1e-7
        row = dict(layer=layer, validation=validation_scores, selected=choice,
                   held_original_error=baseline_error, held_selected_error=selected_error,
                   changed_codes=int(selected.ne(original).sum()))
        if export_codes:
            artifact = codes_path / f"down_{layer:02d}.pt"
            with artifact.open("xb") as stream:
                torch.save({"codes": selected.cpu(), "scale": scales.cpu()}, stream)
            row["codebook_sha256"] = sha256(artifact)
        layers.append(row)
        print("DOWN_CODE_CALIBRATION_LAYER", layer, row, flush=True)
    assert all(sha256(Path(name)) == checksum for name, checksum in evidence.items())
    result = dict(state="bounded_down_weight_code_calibration_heldout_measured", layers=layers,
                  checkpoint_revision=earlier["checkpoint_revision"], fit_images=4, validation_images=4,
                  held_images=8, held_rows_per_layer=120,
                  held_mean_original_error=sum(row["held_original_error"] for row in layers) / LAYERS,
                  held_mean_selected_error=sum(row["held_selected_error"] for row in layers) / LAYERS,
                  gpu_bytes=torch.cuda.max_memory_allocated(), device=torch.cuda.get_device_name(),
                  wall_seconds=time.monotonic()-started, evidence_sha256=evidence,
                  scope="Frozen activation rows, existing signed eight-bit down-projection interface and unchanged mask. "
                        "The held rows are used only for evaluation. Model answers, prediction traffic and hardware timing are separate.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--export-codes", action="store_true")
    args = parser.parse_args()
    run(args.output, args.export_codes)
