"""Measure sources of feed-forward layer error on the same archived later rows."""

import argparse
import json
from pathlib import Path

from safetensors import safe_open
import torch
from torch.nn.functional import linear, silu

from audit_tri_oracle_ff_down_input import CACHE, ROOT, digest, read
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize, _requantize


def project(activation, gate, up, down):
    """Normalized activation [rows, hidden], gate/up [channels, hidden], down [hidden, channels]."""
    return linear(silu(linear(activation, gate)) * linear(activation, up), down)  # [rows, hidden]


def measure(activation, residual, target, weights, reference, policy):
    """Input/residual/target [later rows, hidden]; weights retain their full trained shapes."""
    gate, up, down = weights
    codes, exponent = _quantize(activation, per_row=True)  # [rows, hidden], [rows, 1]
    quantized_activation = torch.ldexp(codes.float(), exponent)  # [rows, hidden]
    # Quantized weights have the same shapes as the trained matrices.
    q_gate, q_up, q_down = (matrix.float() * 2.0**scale for matrix, scale in (
        (reference.gate, reference.gate_exponent), (reference.up, reference.up_exponent),
        (reference.down, reference.down_exponent)))
    baseline_raw, baseline, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
    gate_dot = _dot(codes, reference.gate)  # [rows, channels]
    up_dot = _dot(codes, reference.up)  # [rows, channels]
    gate_q8 = _requantize(gate_dot, stats["gate_shift"][:, None], 16)  # [rows, channels]
    up_q8 = _requantize(up_dot, stats["up_shift"][:, None], 16)  # [rows, channels]
    fixed_silu = reference.silu_response[gate_q8 + 32768]  # [rows, channels], signed fixed-point values
    product = fixed_silu * up_q8  # [rows, channels], unrounded integer product of two fixed-point factors
    down_shift = stats["down_shift"][:, None]  # [rows, 1]
    gated = _requantize(product, torch.full_like(down_shift, 8), 16)  # [rows, channels]
    final = _requantize(gated, down_shift, 8).to(torch.int8)  # [rows, channels]
    assert torch.equal(_dot(final, reference.down), baseline_raw)
    channel_codes, channel_exp = _quantize(down, per_row=True)  # [hidden, channels], [hidden, 1]
    channel_dot = _dot(final, channel_codes)  # [rows, hidden], signed32 before output scaling
    channel_scale = channel_exp.T + down_shift - 8 - stats["up_gain_bits"][:, None]  # [rows, hidden]
    channel_scaled_down = torch.ldexp(channel_dot.float(), channel_scale)  # [rows, hidden]
    # Dequantize without product rounding or final clipping. Each row shares one gain.
    product_scale = -16 - stats["up_gain_bits"][:, None]  # [rows, 1]
    exact_product = torch.ldexp(product.float(), product_scale)  # [rows, channels]
    denominator = target.double().norm(dim=1).clamp_min(1e-20)  # [rows]

    outputs = {
        "floating_reconstruction": project(activation, gate, up, down),
        "activation_only": project(quantized_activation, gate, up, down),
        "gate_weight_only": project(activation, q_gate, up, down),
        "up_weight_only": project(activation, gate, q_up, down),
        "down_weight_only": project(activation, gate, up, q_down),
        "all_weights_only": project(activation, q_gate, q_up, q_down),
        "quantized_operands": project(quantized_activation, q_gate, q_up, q_down),
        "operands_and_fixed_gate_up": linear(exact_product, q_down),
        "full_fixed_point": baseline,
        "full_fixed_point_channel_scaled_down": channel_scaled_down,
    }  # Every mode produces [rows, hidden] on the same archived input.
    errors = {mode: float(((value.double() - target.double()).norm(dim=1) / denominator).mean())
              for mode, value in outputs.items()}
    assert errors["floating_reconstruction"] < 1e-5, errors["floating_reconstruction"]
    return errors, (int(channel_exp.min()), int(channel_exp.max()))


@torch.inference_mode()
def run(output):
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision("highest")
    torch.cuda.set_per_process_memory_fraction(0.25)
    prior_path = CACHE / "ff_down_input_attribution/receipt.json"
    prior = read(prior_path)
    assert prior["state"] == "down_input_clipping_and_rounding_attributed_on_archived_rows"
    pins = prior["input_sha256"] | {str(path): digest(path) for path in (prior_path, Path(__file__))}
    assert all(digest(Path(name)) == sha for name, sha in pins.items())
    model = CACHE / "tiny_llava_v1"
    index = read(model / "model.safetensors.index.json")["weight_map"]
    epsilon = read(model / "config.json")["text_config"]["rms_norm_eps"]
    policies = read(CACHE / "format335/layer_policy.json")["layers"]
    archived = torch.load(CACHE / "format320/captured_rows.pt", map_location="cpu", weights_only=True, mmap=True)
    # The later rows from the eight prior diagnostic images, excluding global position zero.
    selected = [row for row in range(128, 256) if row % 16 != 0]
    assert len(archived) == len(prior["layers"]) == len(policies) == 22
    results = []
    for layer, (data, policy, reference_row) in enumerate(zip(archived, policies, prior["layers"], strict=True)):
        weights = []
        for kind in ("gate", "up", "down"):
            name, = (name for name in index if name.endswith(f".layers.{layer}.mlp.{kind}_proj.weight"))
            with safe_open(model / index[name], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(name).to("cuda"))  # [channels, hidden] or [hidden, channels]
        reference = IntegerFeedForwardReference(*weights, epsilon)
        tensors = [data[key][selected].to("cuda") for key in ("activation", "residual", "target")]
        assert all(item.shape == (120, 2048) for item in tensors)
        errors, channel_scale_range = measure(*tensors, weights, reference, policy)
        assert errors["full_fixed_point"] == reference_row["mean_row_relative_error"]["baseline"]
        results.append({"layer": layer, "mean_row_relative_error": errors, "channel_scale_exponent_range": channel_scale_range})
        print("FF_QUANTIZATION_LAYER", layer, errors, flush=True)
    assert all(digest(Path(name)) == sha for name, sha in pins.items())
    result = dict(state="feedforward_quantization_sources_measured_on_archived_rows",
                  checkpoint_revision=prior["checkpoint_revision"], diagnostic_images=8, rows_per_layer=len(selected),
                  layers=results, input_sha256=pins, graphics_peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                  scope="Paired layer-output counterfactuals on frozen later prefill rows, without end-to-end generation.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
