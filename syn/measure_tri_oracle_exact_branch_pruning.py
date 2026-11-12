"""Measure feed-forward pruning when the gate and up values are known exactly."""

import argparse
from collections import Counter
import json
from pathlib import Path

import measure_tri_oracle_packed_thresholds as sweep
from measure_tri_oracle_packed_workload_traffic import group_traffic, reconstruct
from tri_oracle_format335_policy import evaluate_policy
from tri_oracle_integer_reference import _dot, _quantize, _requantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


PACKING = ROOT / "records/wac_channel_packing_bound_result.json"
BASELINE = ROOT / "records/wac_packed_predictor_threshold_result.json"
MODES = ("exact_branch_intersection", "exact_product", "exact_quantized_zeros", "wide_sign_predictor")
SPLITS = ("fit", "held")


def evaluate_layer(activation, residual, reference, down, policy, target):
    """Select thresholds on the first half of the rows and score the second half."""
    torch = sweep.torch
    _, _, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
    codes, _, _, dense, _, _ = reconstruct(reference, activation, stats)  # [R,H] inputs, [R,K] down inputs.
    gate = _requantize(_dot(codes, reference.gate), stats["gate_shift"][:, None], 16)  # [R,K].
    up = _requantize(_dot(codes, reference.up), stats["up_shift"][:, None], 16)  # [R,K] with compensated gain.
    gate_response = reference.silu_response[gate + 32768]  # [R,K] exact nonlinear gate response.
    gated = _requantize(gate_response * up, torch.full_like(stats["down_shift"][:, None], 8), 16)
    assert torch.equal(dense, _requantize(gated, stats["down_shift"][:, None], 8).to(torch.int8))
    gate_magnitude = gate_response.abs().float()  # [R,K], magnitude in fixed-point code units.
    up_magnitude = torch.ldexp(up.abs().float(), -stats["up_gain_bits"][:, None])  # [R,K], undo per-row gain.
    scaled, exponent = _quantize(down, per_row=True)  # [H,K] weights, [H,1] exponents.
    scale = exponent.T + stats["down_shift"][:, None] - 8 - stats["up_gain_bits"][:, None]  # [R,H].
    output = torch.ldexp(_dot(dense, scaled).float(), scale)  # [R,H] dense reference.
    norms = output.double().norm(dim=1).clamp_min(1e-20)  # [R].
    fit = slice(0, sweep.ROWS)
    parts = (fit, slice(sweep.ROWS, 2 * sweep.ROWS))
    rank = (target * dense[fit].numel() + 99) // 100

    def effect(part, mask):
        removed = dense[part].masked_fill(~mask, 0)  # [rows,K], suppressed down inputs.
        delta = torch.ldexp(_dot(removed, scaled).float(), scale[part])  # [rows,H].
        return float((delta.double().norm(dim=1) / norms[part]).sum())

    gate_normalizer = gate_magnitude[fit].median().clamp_min(1)
    up_normalizer = up_magnitude[fit].median().clamp_min(1)
    normalized_gate = gate_magnitude / gate_normalizer  # [R,K].
    normalized_up = up_magnitude / up_normalizer  # [R,K].
    best = None
    for power in range(-6, 7):
        # The max threshold is exactly the intersection of two magnitude windows.
        score = torch.maximum(normalized_gate, normalized_up * 2.0**power)  # [R,K].
        cutoff = torch.kthvalue(score[fit].flatten(), rank).values
        mask = score.le(cutoff)  # [R,K], include all ties at the selected cutoff.
        skipped = int(mask[fit].sum())
        assert skipped >= rank
        key = effect(fit, mask[fit]), skipped, power
        if best is None or key < best[0]:
            best = key, mask
    assert best is not None

    product = gate_magnitude * up_magnitude  # [R,K] before final integer rounding.
    product_mask = product.le(torch.kthvalue(product[fit].flatten(), rank).values)
    norm_codes = stats["norm_codes"]  # [R,H], pre-scale root-mean-square-normalized activation.
    outliers = norm_codes.abs().gt(768)
    signs = (torch.where(norm_codes < 0, -1, 1) * outliers).to(torch.int8)  # [R,H].
    signed_mask = outliers.any(dim=1, keepdim=True) & _dot(signs, reference.gate_sign).le(0)
    signed_mask &= _dot(signs, reference.up_sign).abs().le(4)  # [R,K] previously verified wide window.
    masks = (best[1], product_mask, dense.eq(0), signed_mask)
    results = {}
    for mode, mask in zip(MODES, masks, strict=True):
        metrics = []
        for part in parts:
            pruned = dense[part].masked_fill(mask[part], 0)
            traffic = group_traffic(codes[part], ~mask[part], dense[part], pruned, sweep.BATCH)
            token_traffic = group_traffic(codes[part], ~mask[part], dense[part], pruned, 1)
            metrics.append(Counter(
                skipped=int(mask[part].sum()), opportunities=mask[part].numel(),
                skipped_exact_zero=int((mask[part] & dense[part].eq(0)).sum()),
                output_change=effect(part, mask[part]), dense_bytes=traffic["no_predictor_gate_up_bytes"] +
                traffic["no_predictor_down_bytes"], kept_bytes=traffic["predictor_gate_up_bytes"] +
                traffic["predictor_down_bytes"], token_dense_bytes=token_traffic["no_predictor_gate_up_bytes"] +
                token_traffic["no_predictor_down_bytes"], token_kept_bytes=token_traffic["predictor_gate_up_bytes"] +
                token_traffic["predictor_down_bytes"],
            ))
        results[mode] = metrics
    assert all(item["output_change"] == 0 for item in results["exact_quantized_zeros"])
    return results, best[0][2]


def run(output):
    output.mkdir()
    target = sweep.read(PACKING)["paper_figure_31_6_5"]["predicted_channel_reduction_percent"]["VQAv2"]
    totals = {mode: [Counter(), Counter()] for mode in MODES}
    ratios = []
    original = sweep.layer_sweep

    def capture(*args):
        measurements, power = evaluate_layer(*args, target)
        for mode, parts in measurements.items():
            for cumulative, counts in zip(totals[mode], parts, strict=True):
                cumulative.update(counts)
        ratios.append(power)
        return original(*args)

    sweep.layer_sweep = capture
    try:
        sweep.run(output / "control_sweep.json")
    finally:
        sweep.layer_sweep = original
    control = output / "control_sweep.json"
    fresh = sweep.read(control)
    assert fresh["baseline"] == sweep.read(BASELINE)["baseline"]
    fixed, = (item for item in fresh["grid"] if item["thresholds"] == [0, -4, 4])
    assert len(ratios) == sweep.LAYERS
    for split, metrics in zip(SPLITS, totals["wide_sign_predictor"], strict=True):
        assert metrics["skipped"] == fixed[split]["skipped_channels"]
        assert metrics["output_change"] == fixed[split]["relative_error_sum"]
        assert metrics["kept_bytes"] == fixed[split]["predicted_weight_bytes"]
    rows = fresh["rows_per_split"]
    summary = {mode: {split: dict(metrics) | {
        "channel_skip_percent": 100 * metrics["skipped"] / metrics["opportunities"],
        "mean_relative_output_change": metrics["output_change"] / rows,
        "shared_weight_reduction_percent": 100 * (1 - metrics["kept_bytes"] / metrics["dense_bytes"]),
        "per_token_weight_reduction_percent": 100 * (1 - metrics["token_kept_bytes"] / metrics["token_dense_bytes"]),
    } for split, metrics in zip(SPLITS, values, strict=True)} for mode, values in totals.items()}
    pins = (Path(__file__).resolve(), PACKING, BASELINE, control)
    result = {
        "state": "exact_branch_pruning_compared_with_wide_sign_threshold", "target_skip_percent": target,
        "rows_per_split": rows, "selected_up_to_gate_powers_by_layer": ratios, "summary": summary,
        "scope": "Exact branches and products are diagnostic controls on archived activation rows. "
                 "Weight traffic projections exclude sign reads. Per-token figures use a different baseline.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in pins},
    }
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], {mode: rows["held"] for mode, rows in summary.items()}, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
