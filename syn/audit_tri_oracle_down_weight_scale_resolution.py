"""Compare down-projection weight scales on frozen later prefill rows."""

import argparse
from copy import copy
import json
from pathlib import Path
from statistics import mean
import time

from safetensors import safe_open
import torch

from audit_tri_oracle_ff_down_input import CACHE, ROOT, digest, read
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _quantize


@torch.inference_mode()
def linear_weight_codes(weight):
    """Quantize checkpoint down weights [O,K], outputs by intermediate channels.

    The per-output scale [O,1] comes from checkpoint weights alone. Return
    signed 8-bit codes [O,K] and their positive scale [O,1].
    """
    weight = weight.float()  # [O,K], use floating-point scale arithmetic at full precision.
    maximum = weight.abs().amax(dim=1, keepdim=True)  # [O,1], peak magnitude by output.
    scale = torch.where(maximum > 0, maximum / 127, 1.0)  # [O,1], full-range scale.
    codes = torch.round(weight / scale).clamp(-127, 127).to(torch.int8)  # [O,K], initial codes.
    best_error = ((codes * scale - weight).square()).sum(dim=1, keepdim=True)  # [O,1].
    full_range = codes.contiguous(), scale
    for fraction in (0.85, 0.90, 0.95):
        trial_scale = full_range[1] * fraction  # [O,1], fixed alternate clipping range.
        trial_codes = torch.round(weight / trial_scale).clamp(-127, 127).to(torch.int8)  # [O,K].
        error = ((trial_codes * trial_scale - weight).square()).sum(dim=1, keepdim=True)  # [O,1].
        improves = error < best_error  # [O,1], selected using weight reconstruction alone.
        codes = torch.where(improves, trial_codes, codes)  # [O,K], best codes per output.
        scale = torch.where(improves, trial_scale, scale)  # [O,1], their matching scales.
        best_error = torch.where(improves, error, best_error)  # [O,1], best error.
    return {"linear_absmax": full_range, "linear_weight_error_fit": (codes.contiguous(), scale)}


def measure(activation, residual, target, weights, epsilon, policy):
    """Replay archived [M,H] activations, residuals and targets.

    M counts token rows, H hidden features, K intermediate channels and O
    output features. Checkpoint gate/up weights are [K,H] and down weights [O,K].
    """
    reference = IntegerFeedForwardReference(*weights, epsilon)
    down = weights[2]  # [O,K], original checkpoint down weights.
    reference.down, exponents = _quantize(down, per_row=True)  # [O,K] codes and [O,1] exponents.
    reference.down_exponent = exponents.T  # [1,O], broadcast across token rows.
    _, baseline, baseline_stats = evaluate_policy(reference, activation, residual, policy, prune=False)
    values = {"power_of_two": baseline}  # Each entry is a dequantized output [M,O].
    for name, (codes, scale) in linear_weight_codes(down).items():
        alternative = copy(reference)
        alternative.down = codes  # [O,K], unchanged integer dot operand shape and width.
        alternative.down_exponent = 0  # Weight scale is applied after the integer dot.
        _, output, stats = evaluate_policy(alternative, activation, residual, policy, prune=False)
        assert all(torch.equal(stats[key], baseline_stats[key]) for key in stats)
        values[name] = output * scale.T  # [M,O], output-channel scale [1,O].
    denominator = target.double().norm(dim=1).clamp_min(1e-20)  # [M], target norm per token.
    return {name: float(((value.double() - target.double()).norm(dim=1) / denominator).mean())
            for name, value in values.items()}


@torch.inference_mode()
def run(output):
    started = time.monotonic()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(0.20)
    torch.cuda.reset_peak_memory_stats()
    prior_path = CACHE / "ff_quantization_sources_channel_scaled/receipt.json"
    committed = ROOT / "records/ff_quantization_sources.json"
    record = read(committed)
    assert record["evidence_sha256"][str(prior_path.relative_to(ROOT))] == digest(prior_path)
    prior = read(prior_path)
    assert prior["state"] == "feedforward_quantization_sources_measured_on_archived_rows"
    pins = prior["input_sha256"] | {str(path): digest(path) for path in (prior_path, committed, Path(__file__).resolve())}
    assert all(digest(Path(name)) == expected for name, expected in pins.items())
    model = CACHE / "tiny_llava_v1"
    weight_map = read(model / "model.safetensors.index.json")["weight_map"]
    epsilon = read(model / "config.json")["text_config"]["rms_norm_eps"]
    policies = read(CACHE / "format335/layer_policy.json")["layers"]
    rows = torch.load(CACHE / "format320/captured_rows.pt", map_location="cpu", weights_only=True, mmap=True)
    selected = [index for index in range(128, 256) if index % 16 != 0]
    assert len(rows) == len(policies) == len(prior["layers"]) == 22 and len(selected) == 120
    measurements = []
    for layer, (data, policy, previous) in enumerate(zip(rows, policies, prior["layers"], strict=True)):
        weights = []  # Three checkpoint tensors with shapes [K,H], [K,H], [O,K].
        for projection in ("gate", "up", "down"):
            name, = (name for name in weight_map if name.endswith(f".layers.{layer}.mlp.{projection}_proj.weight"))
            path = model / weight_map[name]
            assert str(path) in pins
            with safe_open(path, framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(name).to("cuda"))
        tensors = [data[key][selected].to("cuda") for key in ("activation", "residual", "target")]  # All [M,H].
        assert all(value.shape == (120, 2048) for value in tensors)
        errors = measure(*tensors, weights, epsilon, policy)
        archived = previous["mean_row_relative_error"]["full_fixed_point_channel_scaled_down"]
        assert abs(errors["power_of_two"] - archived) < 1e-8, (layer, errors, archived)
        measurements.append(errors)
        print("DOWN_SCALE_RESOLUTION", layer, errors, flush=True)
    assert all(digest(Path(name)) == expected for name, expected in pins.items())
    modes = measurements[0]
    result = {
        "state": "down_weight_scale_resolution_measured_on_frozen_prefill_rows",
        "checkpoint_revision": prior["checkpoint_revision"], "layers": len(measurements),
        "rows_per_layer": len(selected), "mean_row_relative_error": {
            mode: mean(row[mode] for row in measurements) for mode in modes},
        "layers_improved": {
            mode: sum(row[mode] < row["power_of_two"] for row in measurements) for mode in modes},
        "per_layer_errors": measurements, "graphics_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "native_elapsed_seconds": time.monotonic() - started, "input_sha256": pins,
        "scope": "Frozen layer outputs with skipping disabled and signed 8-bit dot operands. Linear scales are applied after the dot.",
    }
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["mean_row_relative_error"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
