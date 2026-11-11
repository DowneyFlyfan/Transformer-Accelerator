"""Compare sign-prediction thresholds on fixed trained activation rows."""

import argparse
import json
from itertools import product
from pathlib import Path

from safetensors import safe_open
import torch

from audit_tri_oracle_ff_down_input import CACHE, digest, read
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize, _requantize

GRID = tuple(product((-12, -10, -8, -6, -4, -2, 0, 2), (0, 1, 2, 3, 4, 6)))
CHANNELS = 5632
ROWS = 120


def measure(activation, residual, reference, scaled_down, exponent, policy):
    """Archived activation/residual [240 rows, hidden]; down codes [hidden, channels]."""
    _, _, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
    codes, _ = _quantize(activation, per_row=True)  # [rows, hidden]
    gate = _requantize(_dot(codes, reference.gate), stats["gate_shift"][:, None], 16)  # [rows, channels]
    up = _requantize(_dot(codes, reference.up), stats["up_shift"][:, None], 16)  # [rows, channels]
    shift = stats["down_shift"][:, None]  # [rows, 1]
    gated = _requantize(reference.silu_response[gate + 32768] * up, torch.full_like(shift, 8), 16)  # [rows, channels]
    down = _requantize(gated, shift, 8).to(torch.int8)  # [rows, channels], before pruning.
    output_scale = exponent.T + shift - 8 - stats["up_gain_bits"][:, None]  # [rows, hidden]
    dense = torch.ldexp(_dot(down, scaled_down).float(), output_scale)  # [rows, hidden]
    denominator = dense.double().norm(dim=1).clamp_min(1e-20)  # [rows]
    norm = stats["norm_codes"]  # [rows, hidden], normalized before learned scale.
    outliers = norm.abs() > 768  # [rows, hidden], strict three-sigma cutoff.
    signs = (torch.where(norm < 0, -1, 1) * outliers).to(torch.int8)  # [rows, hidden]
    gate_margin = _dot(signs, reference.gate_sign)  # [rows, channels]
    up_margin = _dot(signs, reference.up_sign).abs()  # [rows, channels]
    eligible = stats["outlier_count"][:, None] > 0  # [rows, 1]
    default = eligible & (gate_margin <= 0) & (up_margin == 0)  # [rows, channels]
    assert torch.equal(default.sum(dim=1, dtype=torch.int32), stats["skip_count"])
    results = {}
    for gate_limit, up_limit in GRID:
        mask = eligible & (gate_margin <= gate_limit) & (up_margin <= up_limit)  # [rows, channels]
        removed = down.masked_fill(~mask, 0)  # [rows, channels], signed8 values zeroed by the predictor.
        effect = torch.ldexp(_dot(removed, scaled_down).float(), output_scale)  # [rows, hidden]
        error = effect.double().norm(dim=1) / denominator  # [rows]
        results[gate_limit, up_limit] = [
            (int(mask[part].sum()), int((mask[part] & (down[part] != 0)).sum()), float(error[part].sum()))
            for part in (slice(0, ROWS), slice(ROWS, 2 * ROWS))]
    return results


@torch.inference_mode()
def run(output):
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(0.25)
    anchor = CACHE / "ff_quantization_sources_channel_scaled/receipt.json"
    prior = read(anchor)
    assert prior["state"] == "feedforward_quantization_sources_measured_on_archived_rows"
    pins = prior["input_sha256"] | {str(path): digest(path) for path in (anchor, Path(__file__))}
    assert all(digest(Path(name)) == sha for name, sha in pins.items())
    model = CACHE / "tiny_llava_v1"
    index = read(model / "model.safetensors.index.json")["weight_map"]
    epsilon = read(model / "config.json")["text_config"]["rms_norm_eps"]
    archived = torch.load(CACHE / "format320/captured_rows.pt", map_location="cpu", weights_only=True, mmap=True)
    policies = read(CACHE / "format335/layer_policy.json")["layers"]
    assert len(archived) == len(policies) == 22
    # Each split contains eight archived images. Exclude the first token of each image.
    selected = [row for row in range(256) if row % 16 != 0]
    assert len(selected) == 2 * ROWS
    totals = {key: [[0, 0, 0.0], [0, 0, 0.0]] for key in GRID}
    for layer, (data, policy) in enumerate(zip(archived, policies, strict=True)):
        weights = []
        for kind in ("gate", "up", "down"):
            name, = (name for name in index if name.endswith(f".layers.{layer}.mlp.{kind}_proj.weight"))
            with safe_open(model / index[name], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(name).to("cuda"))  # [channels, hidden] or [hidden, channels]
        reference = IntegerFeedForwardReference(*weights, epsilon)
        scaled_down, exp = _quantize(weights[-1], per_row=True)  # [hidden, channels], [hidden, 1]
        assert [int(exp.min()), int(exp.max())] == prior["layers"][layer]["channel_scale_exponent_range"]
        activation, residual = (data[key][selected].to("cuda") for key in ("activation", "residual"))
        assert activation.shape == residual.shape == (2 * ROWS, 2048)
        results = measure(activation, residual, reference, scaled_down, exp, policy)
        for key, values in results.items():
            for part, totals_part in enumerate(totals[key]):
                for index_value, value in enumerate(values[part]):
                    totals_part[index_value] += value
        print("PRUNE_THRESHOLD_LAYER", layer, results[0, 0], flush=True)
    assert all(digest(Path(name)) == sha for name, sha in pins.items())
    rows_per_split = len(archived) * ROWS
    opportunities = rows_per_split * CHANNELS
    grid = []
    for (gate, up), values in totals.items():
        item = dict(gate_threshold=gate, up_window=up)
        for part, (skipped, nonzero, error) in zip(("fit", "held"), values, strict=True):
            item[part] = dict(skipped_channels=skipped, skipped_nonzero=nonzero, skipped_fraction=skipped / opportunities,
                              mean_relative_pruning_error=error / rows_per_split)
        grid.append(item)
    baseline, = (item for item in grid if item["gate_threshold"] == item["up_window"] == 0)
    eligible = [item for item in grid if item["fit"]["skipped_channels"] >= baseline["fit"]["skipped_channels"]]
    selected_policy = min(eligible, key=lambda item: item["fit"]["mean_relative_pruning_error"])
    result = dict(state="pruning_threshold_grid_scored_on_archived_trained_rows", baseline=baseline, selected=selected_policy,
                  selection="Lowest fit output perturbation among policies that skip at least as many fit channels as baseline.",
                  rows_per_split=rows_per_split, channel_opportunities_per_split=opportunities, grid=grid, input_sha256=pins,
                  graphics_peak_bytes=torch.cuda.max_memory_allocated(),
                  scope="Fixed archived fit and diagnostic images. Error measures the change from the dense fixed-point layer output.")
    with (output / "receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("PRUNE_THRESHOLD_GRID", baseline, selected_policy, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output.resolve())
