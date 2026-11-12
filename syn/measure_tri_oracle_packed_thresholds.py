"""Sweep the gate and both up thresholds against the actual packed fetch rules."""

import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path
import time

from safetensors import safe_open
import torch

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from measure_tri_oracle_input_equalization import CACHE, GIB, HIDDEN, LAYERS, host_available, read
from measure_tri_oracle_packed_workload_traffic import group_traffic, reconstruct
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


ROWS = 120
BATCH = 15  # Each image supplies 15 archived ordinary rows after excluding its protected first row.
GATE = (-8, -4, 0, 4, 8, 12, 16, 24, 32)
UP = ((0, 0), (-2, 2), (-4, 4), (-8, 8), (-12, 12), (-16, 16), (-24, 24), (-32, 32),
      (-8, 2), (-2, 8), (-16, 4), (-4, 16), (-24, 8), (-8, 24), (-2048, 2048))
GRID = tuple((gate, low, high) for gate, (low, high) in product(GATE, UP)) + ((2048, -2048, 2048),)
BASELINE = (0, 0, 0)


def layer_sweep(activation, residual, reference, down, policy):
    """Measure projection error and transfer bytes on paired prompt rows [240,H]."""
    _, _, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
    codes, _, default, dense, _, _ = reconstruct(reference, activation, stats)  # Codes [240,H]; masks and down [240,K].
    scaled_down, exponents = _quantize(down, per_row=True)  # [H,K] signed8 weights and [H,1] exponents.
    scale = exponents.T + stats["down_shift"][:, None] - 8 - stats["up_gain_bits"][:, None]  # [240,H].
    output = torch.ldexp(_dot(dense, scaled_down).float(), scale)  # [240,H], dense integer output.
    denominator = output.double().norm(dim=1).clamp_min(1e-20)  # [240], one output norm per row.
    norms = stats["norm_codes"]  # [240,H], raw residual after prediction normalization.
    outlier = norms.abs().gt(768)  # [240,H], predictor input support.
    signs = (torch.where(norms < 0, -1, 1) * outlier).to(torch.int8)  # [240,H], signed outlier indicators.
    gate = _dot(signs, reference.gate_sign)  # [240,K], gate sign margins.
    up = _dot(signs, reference.up_sign)  # [240,K], up sign margins.
    eligible = outlier.any(dim=1, keepdim=True)  # [240,1], whether the row has outliers.
    assert torch.equal(default, eligible & gate.le(0) & up.eq(0))
    splits = (slice(0, ROWS), slice(ROWS, 2 * ROWS))
    sign_bytes = [int(outlier[part].reshape(ROWS, HIDDEN // 2, 2).any(dim=2).sum()) * (dense.shape[1] // 32) * 16
                  for part in splits]
    results = {}
    for gate_limit, low, high in GRID:
        mask = eligible & gate.le(gate_limit) & up.ge(low) & up.le(high)  # [240,K], predicted zero channels.
        pruned = dense.masked_fill(mask, 0)  # [240,K], masked down input.
        removed = dense.masked_fill(~mask, 0)  # [240,K], contribution suppressed by prediction.
        effect = torch.ldexp(_dot(removed, scaled_down).float(), scale)  # [240,H], exact suppressed output.
        relative = effect.double().norm(dim=1) / denominator  # [240], row relative changes.
        pair = []
        for part, signs_read in zip(splits, sign_bytes, strict=True):
            traffic = group_traffic(codes[part], ~mask[part], dense[part], pruned[part], BATCH)
            pair.append(Counter(
                dense_bytes=traffic["no_predictor_gate_up_bytes"] + traffic["no_predictor_down_bytes"],
                predicted_weight_bytes=traffic["predictor_gate_up_bytes"] + traffic["predictor_down_bytes"],
                sign_bytes=signs_read, skipped_channels=int(mask[part].sum()), relative_error_sum=float(relative[part].sum()),
            ))
        results[gate_limit, low, high] = pair
    return results


def summarize(totals, target):
    rows = LAYERS * ROWS
    grid = []
    for thresholds, parts in totals.items():
        item = {"thresholds": thresholds}
        for split, part in zip(("fit", "held"), parts, strict=True):
            traffic = part["predicted_weight_bytes"] + part["sign_bytes"]
            item[split] = {**dict(part), "traffic_bytes": traffic,
                           "net_reduction_percent": 100 * (1 - traffic / part["dense_bytes"]),
                           "mean_relative_output_change": part["relative_error_sum"] / rows}
        grid.append(item)
    baseline, = (item for item in grid if item["thresholds"] == BASELINE)
    no_more_error = [item for item in grid if item["fit"]["relative_error_sum"] <= baseline["fit"]["relative_error_sum"]]
    at_target = [item for item in grid if item["fit"]["net_reduction_percent"] >= target]
    return {"grid": grid, "baseline": baseline,
            "best_traffic_at_baseline_fit_error": max(no_more_error, key=lambda item: item["fit"]["net_reduction_percent"]),
            "least_error_at_paper_fit_traffic_target": min(at_target, key=lambda item: item["fit"]["relative_error_sum"], default=None),
            "fit_settings_reaching_traffic_target": len(at_target),
            "fit_settings_reaching_traffic_target_at_baseline_error": sum(item in at_target for item in no_more_error)}


@torch.inference_mode()
def run(output):
    started = time.monotonic()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    assert host_available() >= 16 * GIB and torch.cuda.mem_get_info()[0] >= 8 * GIB
    torch.cuda.set_per_process_memory_fraction(0.125)
    torch.cuda.reset_peak_memory_stats()
    old_record = ROOT / "records/ff_pruning_threshold_grid_result.json"
    old = read(old_record)
    assert old["state"] == "pruning_threshold_grid_scored_on_archived_trained_rows"
    prior_file = CACHE / "ff_pruning_threshold_grid/receipt.json"
    assert sha256(prior_file) == old["evidence_sha256"][str(prior_file.relative_to(ROOT))]
    prior = read(prior_file)
    metadata = ROOT / "records/format320_multi_image_range_audit.json"
    cases = read(metadata)["inputs"]
    assert [item["split"] for item in cases] == ["calibration"] * 8 + ["held"] * 8
    assert len({item["image_pixel_sha256"] for item in cases}) == 16
    assert all(len(item["selected_token_positions"]) == BATCH + 1 and item["selected_token_positions"][0] == 0
               for item in cases)
    paper = ROOT / PAPER_RELATIVE
    assert sha256(paper) == PAPER_SHA256
    targets = ROOT / "records/paper_result_targets.json"
    target = read(targets)["disclosed_method_gains"]["feed_forward_external_memory_access_reduction_percent"]
    model = CACHE / "tiny_llava_v1"
    index = read(model / "model.safetensors.index.json")["weight_map"]
    epsilon = read(model / "config.json")["text_config"]["rms_norm_eps"]
    rows = CACHE / "format320/captured_rows.pt"
    policies = read(CACHE / "format335/layer_policy.json")["layers"]
    pins = prior["input_sha256"].copy()
    for file in (old_record, prior_file, paper, targets, metadata, Path(__file__).resolve(),
                 Path(reconstruct.__code__.co_filename).resolve(), ROOT / "verilog/tri_oracle_strip_predictor.sv"):
        digest = sha256(file)
        assert pins.setdefault(str(file), digest) == digest
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    archived = torch.load(rows, map_location="cpu", weights_only=True, mmap=True)  # Per-layer [256,H] captures.
    selected = [row for row in range(256) if row % (BATCH + 1)]
    assert len(archived) == len(policies) == LAYERS and len(selected) == 2 * ROWS
    totals = {setting: [Counter(), Counter()] for setting in GRID}
    for layer, (data, policy) in enumerate(zip(archived, policies, strict=True)):
        assert host_available() >= 15 * GIB
        weights = []
        for projection in ("gate", "up", "down"):
            key, = (name for name in index if name.endswith(f".layers.{layer}.mlp.{projection}_proj.weight"))
            with safe_open(model / index[key], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(key).to("cuda"))  # Trained gate/up [K,H] or down [H,K].
        reference = IntegerFeedForwardReference(*weights, epsilon)
        activation, residual = (data[name][selected].to("cuda") for name in ("activation", "residual"))  # [240,H].
        assert activation.shape == residual.shape == (2 * ROWS, HIDDEN)
        for setting, parts in layer_sweep(activation, residual, reference, weights[-1], policy).items():
            for cumulative, part in zip(totals[setting], parts, strict=True):
                cumulative.update(part)
        print("PACKED_THRESHOLD_LAYER", layer, flush=True)
    result = summarize(totals, target)
    for split in ("fit", "held"):
        measured = result["baseline"][split]
        assert measured["skipped_channels"] == prior["baseline"][split]["skipped_channels"]
        assert abs(measured["mean_relative_output_change"] - prior["baseline"][split]["mean_relative_pruning_error"]) < 1e-9
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    result.update(state="packed_predictor_thresholds_measured_on_fit_and_held_rows", settings=len(GRID),
                  rows_per_split=LAYERS * ROWS, paper_traffic_target_percent=target, native_seconds=time.monotonic() - started,
                  peak_gpu_bytes=torch.cuda.max_memory_allocated(), input_sha256=pins,
                  scope="Fixed archived prompt rows grouped by image. Output changes compare against the same dense integer arithmetic.")
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["state"], result["best_traffic_at_baseline_fit_error"], result["least_error_at_paper_fit_traffic_target"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
