"""Measure single versus two-stage rounding of the gated prompt activations."""

import argparse
import json
from pathlib import Path

from safetensors import safe_open
import torch

from measure_tri_oracle_input_equalization import CACHE, GIB, LAYERS, host_available
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize, _requantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


def read(path):
    return json.loads(path.read_text())


def measure_shift_selection(gated, skips, gain, channels, exponents, targets, target_norm, original_shift):
    """Compare down shifts using only the retained [M,K] gated codes."""
    retained = gated.masked_fill(skips, 0)  # [M,K], signed16 intermediates after existing pruning
    maximum = retained.max(dim=1).values  # [M], largest positive retained code
    minimum = retained.min(dim=1).values  # [M], smallest negative retained code
    distortions, output_errors, fits = [], [], []
    for candidate in range(10):
        shift = torch.full_like(original_shift, candidate)  # [M,1] trial shift, target-independent
        codes = _requantize(retained, shift, 8)  # [M,K] candidate signed8 down inputs
        decoded = codes << candidate  # [M,K] reconstructed signed16-scale values
        distortions.append((decoded - retained).square().sum(dim=1))  # [M] squared activation loss
        rounding = (1 << candidate) // 2
        fits.append((maximum <= 128 * (1 << candidate) - rounding - 1)
                    & (minimum >= -(129 * (1 << candidate) - rounding - 1)))  # [M] safe without saturation
        output = torch.ldexp(_dot(codes.to(torch.int8), channels).float(),
                             shift - 8 - gain + exponents.T)  # [M,H] per-channel down output
        output_errors.append((output - targets).norm(dim=1) / target_norm)  # [M] comparison only
    possible = torch.stack(fits, dim=1)  # [M,10] shifts that fit the actual signed range
    assert bool(possible[:, -1].all())
    distortion = torch.stack(distortions, dim=1)  # [M,10], lower is better
    errors = torch.stack(output_errors, dim=1)  # [M,10], held-only evaluation
    fixed = original_shift[:, 0]  # [M], current configured shift
    choices = {
        "range": possible.int().argmax(dim=1),
        "input_distortion": distortion.argmin(dim=1),
        "output_oracle": errors.argmin(dim=1),
    }
    measured = {}
    for name, selected in choices.items():
        values = errors.gather(1, selected[:, None])  # [M,1], error from chosen shifts
        measured[name] = {"per_channel_error": float(values.mean()),
                          "changed_shifts": int((selected != fixed).sum())}
    return measured, float(errors.gather(1, fixed[:, None]).mean())


def measure(reference, down, capture, policy):
    """Compare identical fixed-point [M,H] outputs for the held prompt rows."""
    indices = [i for i in range(128, 256) if i % 16]
    activation, residual, targets = (capture[name][indices].cuda() for name in
                                     ("activation", "residual", "target"))  # [M,H] inputs and target
    original_acc, original_output, stats = evaluate_policy(reference, activation, residual, policy, prune=True)
    activation_codes, _ = _quantize(activation, per_row=True)  # [M,H], original normalization and quantization
    gate_shift = stats["gate_shift"][:, None]  # [M,1], actual frame settings
    up_shift = stats["up_shift"][:, None]  # [M,1], actual frame settings
    shift = stats["down_shift"][:, None]  # [M,1], actual frame settings
    gain = stats["up_gain_bits"][:, None]  # [M,1], actual frame settings
    gate = _requantize(_dot(activation_codes, reference.gate), gate_shift, 16)  # [M,K] signed gate codes
    up = _requantize(_dot(activation_codes, reference.up), up_shift, 16)  # [M,K] signed up codes
    product = reference.silu_response[gate + 32768] * up  # [M,K] full-width signed product
    before_limit = _requantize(product, torch.full_like(shift, 8), 32)  # [M,K] first round with widened range
    first_stage = before_limit.clamp(-32768, 32767)  # [M,K] existing signed16 output
    staged = _requantize(first_stage, shift, 8).to(torch.int8)  # [M,K] existing down codes
    widened = _requantize(before_limit, shift, 8).to(torch.int8)  # [M,K] no intermediate clipping control
    assert bool((shift <= 54).all())
    once = _requantize(product, shift + 8, 8).to(torch.int8)  # [M,K] one round and one signed8 saturation

    norm = stats["norm_codes"]  # [M,H], unchanged three-sigma predictor inputs
    outliers = norm.abs() > 768  # [M,H], exact threshold
    signs = (torch.where(norm < 0, -1, 1) * outliers).to(torch.int8)  # [M,H], sign only on outliers
    skips = (outliers.any(dim=1, keepdim=True) & (_dot(signs, reference.gate_sign) <= 0)
             & (_dot(signs, reference.up_sign) == 0))  # [M,K], same mask for all variants
    assert torch.equal(skips.sum(dim=1), stats["skip_count"])
    original_input = staged.masked_fill(skips, 0)  # [M,K] after existing mask
    physical_exponent = shift - 8 - gain  # [M,1] common scale before weight exponent
    assert torch.equal(_dot(original_input, reference.down), original_acc)
    assert torch.equal(torch.ldexp(original_acc.float(), physical_exponent + reference.down_exponent), original_output)

    channels, channel_exponents = _quantize(down, per_row=True)  # [H,K] codes and [H,1] exponents
    target_norm = targets.norm(dim=1).clamp_min(1e-20)  # [M], reference layer output magnitude
    estimates = {}
    for name, codes in (("baseline", staged), ("wide_intermediate", widened), ("one_round", once)):
        pruned = codes.masked_fill(skips, 0)  # [M,K] with identical prediction
        scalar_values = torch.ldexp(_dot(pruned, reference.down).float(),
                                   physical_exponent + reference.down_exponent)  # [M,H]
        channel_values = torch.ldexp(_dot(pruned, channels).float(),
                                    physical_exponent + channel_exponents.T)  # [M,H]
        estimates[name] = {
            "scalar_error": float(((scalar_values - targets).norm(dim=1) / target_norm).mean()),
            "per_channel_error": float(((channel_values - targets).norm(dim=1) / target_norm).mean()),
            "changed_input_codes": int((pruned != original_input).sum()),
        }
    zero_shift_rows = shift[:, 0] == 0  # [M] rows with no second shift
    assert torch.equal(once[zero_shift_rows], staged[zero_shift_rows])
    shift_estimates, fixed_error = measure_shift_selection(
        first_stage, skips, gain, channels, channel_exponents, targets, target_norm, shift
    )
    assert abs(fixed_error - estimates["baseline"]["per_channel_error"]) < 1e-7
    return {"rows": len(indices), "input_codes": staged.numel(),
            "intermediate_clipped_codes": int((first_stage != before_limit).sum()),
            "minimum_final_shift": int(shift.min()), "maximum_final_shift": int(shift.max()),
            "estimates": estimates, "shift_selection": shift_estimates}


@torch.inference_mode()
def run(output):
    assert Path("/.dockerenv").is_file() and __debug__
    assert int(Path("/sys/fs/cgroup/memory.max").read_text()) <= 2 * GIB
    assert host_available() >= 10 * GIB and torch.cuda.mem_get_info()[0] >= 3 * GIB
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(0.10)
    model = CACHE / "tiny_llava_v1"
    mapping_path = model / "model.safetensors.index.json"
    config = model / "config.json"
    capture_path = CACHE / "format320/captured_rows.pt"
    policy_path = CACHE / "format335/layer_policy.json"
    control = CACHE / "gqa_testdev/activation_range_per_row/receipt.json"
    fields = read(mapping_path)["weight_map"]
    epsilon = read(config)["text_config"]["rms_norm_eps"]
    archive = torch.load(capture_path, map_location="cpu", weights_only=True, mmap=True)
    policies = read(policy_path)["layers"]
    baseline = read(control)
    paths = {mapping_path, config, capture_path, policy_path, control, Path(__file__).resolve()}
    paths.update(model / filename for name, filename in fields.items() if ".mlp." in name)
    evidence = {str(path.relative_to(ROOT)): sha256(path) for path in sorted(paths)}
    layers = []
    for index, (capture, policy) in enumerate(zip(archive, policies, strict=True)):
        assert host_available() >= 8.5 * GIB
        weights = []
        for role in ("gate", "up", "down"):
            key, = (name for name in fields if name.endswith(f".layers.{index}.mlp.{role}_proj.weight"))
            with safe_open(model / fields[key], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(key).cuda())  # [K,H], [K,H], [H,K] from the checkpoint
        reference = IntegerFeedForwardReference(*weights, epsilon)
        row = measure(reference, weights[-1], capture, policy)
        previous = baseline["layers"][index]["held"]["0"]["mean_relative_output_error"]
        assert abs(row["estimates"]["baseline"]["per_channel_error"] - previous) < 1e-7
        layers.append({"layer": index, **row})
        print("GATED_ROUNDING_HELD_LAYER", index, row["shift_selection"], flush=True)
    assert len(layers) == LAYERS and all(sha256(ROOT / path) == value for path, value in evidence.items())
    output.mkdir()
    with (output / "receipt.json").open("x") as stream:
        json.dump({"state": "gated_rounding_counterfactual_measured",
                   "layers": layers, "evidence_sha256": evidence,
                   "peak_gpu_bytes": torch.cuda.max_memory_allocated(),
                   "scope": "Held ordinary prompt rows with existing weight prediction and trained signed-eight-bit weights. "
                            "Rounding and shift selection are measured separately. Output-aware shifts are diagnostic. "
                            "Answer accuracy and hardware timing were not measured."}, stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
