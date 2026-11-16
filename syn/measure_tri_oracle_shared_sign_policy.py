"""Evaluate early sign-based shared masks on frozen feed-forward activations."""
import argparse
from collections import Counter
from pathlib import Path
import json
from time import monotonic

import numpy as np
from safetensors import safe_open
import torch

from audit_tri_oracle_ff_down_input import CACHE, ROOT, digest, read
from evaluate_tri_oracle_same_count_mask import BINS, CELLS, bin_index, exact_budget_mask
from measure_tri_oracle_input_equalization import GIB, host_available
from measure_tri_oracle_packed_thresholds import BATCH, HIDDEN, ROWS, group_traffic, reconstruct
from measure_tri_oracle_packed_workload_traffic import CHANNELS, WORD_BYTES, verify_traffic_control
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import IntegerFeedForwardReference, _dot, _quantize

REFERENCE = CACHE / "ff_batch_shared_magnitude/receipt.json"
PARENT = ROOT / "records/tri_oracle_shared_word_pruning_traffic.json"
CAPTURE = ROOT / "records/format320_multi_image_range_audit.json"
SPLITS = {"fit": slice(0, ROWS), "held": slice(ROWS, ROWS * 2)}
RATES = (56, 58)
LAYERS_RATES = tuple(sorted(set(range(0, 101, 10)) | set(RATES)))


def skipped_words(rate):
    return CHANNELS // WORD_BYTES * rate // 100


def shared_mask(score, rate):
    # [R,K] -> [I,B,W,C] for images, token rows, words, and eight channels.
    groups = score.reshape(-1, BATCH, CHANNELS // WORD_BYTES, WORD_BYTES)
    utility = groups.sum(dim=(1, 3))  # [I,W] cost proxy per common word.
    target = torch.full((len(utility), 1), skipped_words(rate), dtype=torch.int64,
                        device=score.device)  # [I,1], exact word budget.
    words = exact_budget_mask(utility, target)  # [I,W], where true means skip.
    return words[:, None, :, None].expand_as(groups).reshape_as(score)  # [R,K] shared channel mask.


def fit_scores(energy, bins):
    # energy [R,K] is a frozen dense per-channel contribution proxy.
    # bins [R,K] depend only on activation and weight sign bits.
    channel = energy[SPLITS["fit"]].mean(0)  # [K], per-layer calibration prior.
    fit_bins = bins[SPLITS["fit"]].flatten()  # [F*K] calibration only.
    actual = torch.zeros(CELLS, dtype=torch.float64, device=energy.device)  # [Q], Q=BINS**2.
    expected = torch.zeros_like(actual)  # [Q], static prior summed over bin assignments.
    actual.scatter_add_(0, fit_bins, energy[SPLITS["fit"]].flatten())
    expected.scatter_add_(0, fit_bins, channel.expand(ROWS, -1).flatten())
    assert abs(float(actual.sum() - expected.sum())) < 1e-7 * float(actual.sum())
    # Shrink bins toward the channel prior using one training row worth of energy.
    pseudoweight = channel.sum() / CELLS
    multiplier = ((actual + pseudoweight) / (expected + pseudoweight)).clamp(0.25, 4.0)
    assert multiplier.shape == (BINS * BINS,) and bool(torch.isfinite(multiplier).all())
    return channel.expand_as(energy), channel * multiplier[bins]  # [R,K] static and sign-adjusted.


def analyze(activation, residual, reference, down_weights, policy):
    # [R,H] frozen activations and unnormalized residuals for R=240.
    _, _, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
    codes, _, baseline, dense, _, _ = reconstruct(reference, activation, stats)  # [R,H], [R,K] masks and codes.
    down, exp = _quantize(down_weights, per_row=True)  # [H,K] signed8 weights, [H,1] scale exponents.
    row_exp = stats["down_shift"] - 8 - stats["up_gain_bits"]  # [R] shared down input exponents.
    powers = exp.T + row_exp[:, None]  # [R,H], physical output scales.
    norm = torch.ldexp(_dot(dense, down).double(), powers).norm(dim=1).clamp_min(1e-20)  # [R].
    column_size = torch.ldexp(down.double(), exp).norm(dim=0)  # [K], calibrated down-column norms.
    energy = (torch.ldexp(dense.double(), row_exp[:, None]) * column_size / norm[:, None]).square()  # [R,K].
    normalized = stats["norm_codes"]  # [R,H], pre-scale activations for the paper's outlier test.
    outliers = normalized.abs().gt(768)  # [R,H], selected three-sigma outliers.
    signs = (torch.where(normalized < 0, -1, 1) * outliers).to(torch.int8)  # [R,H], signed support.
    gate = _dot(signs, reference.gate_sign)  # [R,K], gate sign margins.
    up = _dot(signs, reference.up_sign).abs()  # [R,K], absolute up margins.
    bins = bin_index(gate, up, outliers.sum(1)).long()  # [R,K], joint table indices.
    assert torch.equal(baseline, (outliers.any(1, keepdim=True) & gate.le(0) & up.eq(0)))
    channel, calibrated = fit_scores(energy, bins)
    masks = {"archived": baseline, "dense": torch.zeros_like(baseline)}
    for rate in RATES:
        masks[f"magnitude_{rate}"] = shared_mask(energy, rate)
        masks[f"prior_{rate}"] = shared_mask(channel, rate)
    for rate in LAYERS_RATES:
        masks[f"sign_{rate}"] = shared_mask(calibrated, rate)
    for mode, skip in masks.items():
        removed = dense.masked_fill(~skip, 0)  # [R,K], signed8 activations suppressed by the mask.
        suppressed = _dot(removed, down)  # [R,H], output lost to suppression.
        assert torch.equal(suppressed[:2, :16], (removed[:2].double() @ down[:16].double().T).int())
        error = torch.ldexp(suppressed.double(), powers).norm(dim=1) / norm  # [R], exact output error ratio.
        for part, rows in SPLITS.items():
            before = codes[rows]
            keep = ~skip[rows]
            complete = dense[rows]
            after = complete.masked_fill(~keep, 0)
            amounts = group_traffic(before, keep, complete, after, BATCH)
            signs_present = outliers[rows].reshape(-1, BATCH, HIDDEN // 2, 2).any(3)  # [I,B,H/2].
            if mode == "archived" or mode.startswith("sign_"):
                per_token = int(signs_present.sum()) * (CHANNELS // 32) * 2 * 8
                shared_signs = int(signs_present.any(1).sum()) * (CHANNELS // 32) * 2 * 8
            else:
                per_token = shared_signs = 0
            if mode.startswith("magnitude_"):
                # Dense gate/up must be known before the shared magnitude mask can be scored.
                amounts["predictor_gate_up_bytes"] = amounts["no_predictor_gate_up_bytes"]
            yield mode, part, Counter(
                relative_error_sum=float(error[rows].sum()), skipped=int((~keep).sum()),
                sign_bytes_without_reuse=per_token, sign_bytes_with_reuse=shared_signs, **amounts,
            )


def allocate(curves, target_words):
    """Find the least calibration error at an exact total skip-word budget."""
    totals = np.full(target_words + 1, np.inf)
    totals[0] = 0
    choices = []
    for curve in curves:
        updated = np.full_like(totals, np.inf)
        selection = np.full(len(totals), -1, dtype=np.int16)
        for rate, measurements in sorted(curve.items()):
            count = skipped_words(rate)
            if count > target_words:
                continue
            addition = totals[: len(totals) - count] + measurements["relative_error_sum"]
            better = addition < updated[count:]
            updated[count:][better] = addition[better]
            selection[count:][better] = rate
        totals = updated
        choices.append(selection)
    best_cost = totals[target_words]
    assert np.isfinite(best_cost)
    remainder = target_words
    rates = []
    for selection in reversed(choices):
        rate = int(selection[remainder])
        assert rate >= 0
        rates.append(rate)
        remainder -= skipped_words(rate)
    assert remainder == 0
    return rates[::-1], float(best_cost)


def adaptive_results(curves, uniform):
    schedules = {}
    for rate in RATES:
        target = len(curves["fit"]) * skipped_words(rate)
        chosen, fit_cost = allocate(curves["fit"], target)
        assert sum(skipped_words(item) for item in chosen) == target
        assert fit_cost <= uniform[f"sign_{rate}"]["fit"]["relative_error_sum"] + 1e-8
        parts = {}
        for part, layers in curves.items():
            merged = sum((layer[item] for layer, item in zip(layers, chosen, strict=True)), Counter())
            parts[part] = merged
        assert abs(parts["fit"]["relative_error_sum"] - fit_cost) < 1e-8
        schedules[rate] = chosen
        uniform[f"adaptive_sign_{rate}"] = parts
    return schedules


@torch.inference_mode()
def run(out):
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists() and __debug__
    assert host_available() >= 10 * GIB and torch.cuda.mem_get_info()[0] >= 10 * GIB
    torch.set_num_threads(3)
    torch.cuda.set_per_process_memory_fraction(0.3)
    torch.cuda.reset_peak_memory_stats()
    started = monotonic()
    control = verify_traffic_control()
    prior = read(PARENT)
    assert digest(REFERENCE) == prior["evidence_sha256"][str(REFERENCE.relative_to(ROOT))]
    baseline = read(REFERENCE)
    metadata = read(CAPTURE)
    assert metadata["labels_used"] is False
    assert [row["split"] for row in metadata["inputs"]] == ["calibration"] * 8 + ["held"] * 8
    assert len({row["image_pixel_sha256"] for row in metadata["inputs"]}) == 16
    captured = CACHE / "format320/captured_rows.pt"
    policies_path = CACHE / "format335/layer_policy.json"
    model = CACHE / "tiny_llava_v1"
    config = model / "config.json"
    index_path = model / "model.safetensors.index.json"
    index = read(index_path)["weight_map"]
    weight_files = sorted({model / name for name in index.values()})
    pinned = {str(path.relative_to(ROOT)): digest(path) for path in
              (captured, policies_path, config, index_path, *weight_files)}
    for path, sha in pinned.items():
        assert baseline["input_sha256"][str(ROOT / path)] == sha
    data = torch.load(captured, map_location="cpu", weights_only=True, mmap=True)
    policies = read(policies_path)["layers"]
    epsilon = read(config)["text_config"]["rms_norm_eps"]
    selected = [i for i in range(256) if i % (BATCH + 1)]
    assert len(selected) == ROWS * 2 and len(data) == len(policies) == 22
    totals = {}
    curves = {part: [{} for _ in data] for part in SPLITS}
    for layer, (sample, policy) in enumerate(zip(data, policies, strict=True)):
        assert host_available() >= 9 * GIB
        weights = []
        for branch in ("gate", "up", "down"):
            key, = (key for key in index if key.endswith(f".layers.{layer}.mlp.{branch}_proj.weight"))
            with safe_open(model / index[key], framework="pt", device="cpu") as shard:
                weights.append(shard.get_tensor(key).to("cuda"))
        reference = IntegerFeedForwardReference(*weights, epsilon)
        activation, residual = (sample[name][selected].to("cuda") for name in ("activation", "residual"))
        assert activation.shape == residual.shape == (ROWS * 2, HIDDEN)
        for mode, part, amounts in analyze(activation, residual, reference, weights[-1], policy):
            totals.setdefault(mode, {}).setdefault(part, Counter()).update(amounts)
            if mode.startswith("sign_"):
                curves[part][layer][int(mode.split("_", 1)[1])] = amounts
        print("SHARED_SIGN_LAYER", layer + 1, flush=True)
    row_count = len(data) * ROWS
    for part, original in totals["archived"].items():
        old = baseline["result"]["predictor_control"][part]
        assert original["skipped"] == old["total_skipped"]
        assert abs(original["relative_error_sum"] / row_count - old["mean_relative_output_perturbation"]) < 1e-7
        for key in ("predictor_gate_up_bytes", "predictor_down_bytes",
                    "no_predictor_gate_up_bytes", "no_predictor_down_bytes"):
            assert original[key] == old[key]
    schedules = adaptive_results(curves, totals)
    for mode, parts in totals.items():
        for part, result in parts.items():
            dense = result["no_predictor_gate_up_bytes"] + result["no_predictor_down_bytes"]
            weights = result["predictor_gate_up_bytes"] + result["predictor_down_bytes"]
            result["mean_relative_error"] = result["relative_error_sum"] / row_count
            result["skipped_percent"] = 100 * result["skipped"] / (row_count * CHANNELS)
            result["byte_reduction_percent_with_shared_signs"] = 100 * (
                dense - weights - result["sign_bytes_with_reuse"]) / dense
            result["byte_reduction_percent_without_shared_signs"] = 100 * (
                dense - weights - result["sign_bytes_without_reuse"]) / dense
            if mode not in ("archived", "dense"):
                rate = int(mode.rsplit("_", 1)[1])
                assert result["skipped"] == row_count * WORD_BYTES * skipped_words(rate)
    report = {
        "state": "shared_early_sign_masks_measured", "rows_per_split": row_count, "results": totals,
        "calibration_selected_rates_by_layer": schedules,
        "layer_rate_grid": LAYERS_RATES,
        "device": torch.cuda.get_device_name(), "peak_bytes": torch.cuda.max_memory_allocated(),
        "elapsed_seconds": monotonic() - started,
        "input_sha256": pinned | {str(p.relative_to(ROOT)): digest(p) for p in (
            REFERENCE, PARENT, CAPTURE, control, Path(__file__).resolve(),
            Path(group_traffic.__code__.co_filename), Path(bin_index.__code__.co_filename))},
    }
    with (out / "receipt.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("SHARED_SIGN_COMPLETE", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=lambda name: Path(name).resolve())
    args = parser.parse_args()
    assert args.out.is_relative_to(ROOT / ".cache")
    args.out.mkdir(parents=True, exist_ok=True)
    run(args.out)
