"""Test sign thresholds scaled by a token's outlier count."""

import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path


GRID = tuple(product((-16, -8, -4, 0, 4, 8, 12, 16, 24, 32),
                     (0, 1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 32)))
BASELINE = (0, 0)


def outlier_limits(count, gate_numerator, up_numerator):
    """Return integer cutoffs for margins divided by the positive outlier count."""
    return count * gate_numerator // 32, count * up_numerator // 32


def measure_layer(activation, residual, reference, down, policy):
    """Measure archived prompt rows [R,H] with H hidden features and K feed-forward channels."""
    from measure_tri_oracle_packed_thresholds import BATCH, HIDDEN, ROWS, group_traffic, reconstruct, torch
    from tri_oracle_format335_policy import evaluate_policy
    from tri_oracle_integer_reference import _dot, _quantize

    _, _, stats = evaluate_policy(reference, activation, residual, policy, prune=False)
    codes, _, default, dense, _, _ = reconstruct(reference, activation, stats)  # Input [R,H], mask and down [R,K].
    norm = stats["norm_codes"]  # [R,H], normalization before the learned scale.
    support = norm.abs().gt(768)  # [R,H], active outlier features.
    signs = (torch.where(norm < 0, -1, 1) * support).to(torch.int8)  # [R,H], ternary signs.
    count = stats["outlier_count"][:, None]  # [R,1], outliers per row, broadcast across K.
    assert torch.equal(count[:, 0], support.sum(dim=1))
    gate = _dot(signs, reference.gate_sign)  # [R,K], gate sign sums.
    up = _dot(signs, reference.up_sign).abs()  # [R,K], absolute up sign sums.
    down_weights, exponents = _quantize(down, per_row=True)  # [H,K] integer weights, [H,1] powers.
    scale = exponents.T + stats["down_shift"][:, None] - 8 - stats["up_gain_bits"][:, None]  # [R,H].
    output = torch.ldexp(_dot(dense, down_weights).float(), scale)  # [R,H], dense integer output.
    denominator = output.double().norm(dim=1).clamp_min(1e-20)  # [R], output norm for each row.
    parts = (slice(0, ROWS), slice(ROWS, 2 * ROWS))
    sign_bytes = [
        int(support[part].reshape(ROWS, HIDDEN // 2, 2).any(dim=2).sum()) * (dense.shape[1] // 32) * 16
        for part in parts
    ]

    for setting in GRID:
        gate_limit, up_limit = outlier_limits(count, *setting)  # Two [R,1] signed integer cutoffs.
        skip = (count > 0) & gate.le(gate_limit) & up.le(up_limit)  # [R,K], conjunction of both branch tests.
        if setting == BASELINE:
            assert torch.equal(skip, default)
        pruned = dense.masked_fill(skip, 0)  # [R,K], down inputs retained.
        removed = dense.masked_fill(~skip, 0)  # [R,K], down inputs suppressed.
        change = torch.ldexp(_dot(removed, down_weights).float(), scale)  # [R,H], suppressed projection.
        relative = change.double().norm(dim=1) / denominator  # [R], relative projection change.
        counts = []
        for part, signs_read in zip(parts, sign_bytes, strict=True):
            traffic = group_traffic(codes[part], ~skip[part], dense[part], pruned[part], BATCH)
            counts.append(Counter(
                dense_bytes=traffic["no_predictor_gate_up_bytes"] + traffic["no_predictor_down_bytes"],
                predicted_weight_bytes=traffic["predictor_gate_up_bytes"] + traffic["predictor_down_bytes"],
                sign_bytes=signs_read, skipped_channels=int(skip[part].sum()),
                relative_error_sum=float(relative[part].sum()),
            ))
        yield setting, counts


def run(output):
    import measure_tri_oracle_packed_thresholds as sweep
    from verify_tri_oracle_packed_down_weights import ROOT, sha256

    output.mkdir()
    totals = {setting: (Counter(), Counter()) for setting in GRID}
    original = sweep.layer_sweep

    def capture(*args):
        for setting, counts in measure_layer(*args):
            for cumulative, part in zip(totals[setting], counts, strict=True):
                cumulative.update(part)
        return original(*args)

    control = output / "fixed_threshold_control.json"
    sweep.layer_sweep = capture
    try:
        sweep.run(control)
    finally:
        sweep.layer_sweep = original
    raw = sweep.read(control)
    reference = ROOT / "records/wac_packed_predictor_threshold_result.json"
    verified = sweep.read(reference)
    assert raw["baseline"] == verified["baseline"]
    for counts, split in zip(totals[BASELINE], ("fit", "held"), strict=True):
        assert all(counts[key] == raw["baseline"][split][key] for key in counts), split

    packing = ROOT / "records/wac_channel_packing_bound_result.json"
    figure = sweep.read(packing)["paper_figure_31_6_5"]
    skip_target = figure["predicted_channel_reduction_percent"]["VQAv2"]
    traffic_target = figure["gated_feedforward_external_memory_access_reduction_percent"]["VQAv2"]
    report = sweep.summarize({(gate, -up, up): counts for (gate, up), counts in totals.items()}, traffic_target)
    for item in report["grid"]:
        for split in ("fit", "held"):
            item[split]["skip_percent"] = 100 * item[split]["skipped_channels"] / (raw["rows_per_split"] * 5632)
    fit_skip = [item for item in report["grid"] if item["fit"]["skip_percent"] >= skip_target]
    rank = min(fit_skip, key=lambda item: (item["fit"]["relative_error_sum"], item["thresholds"]), default=None)
    pins = (Path(__file__).resolve(), Path(sweep.__file__).resolve(), reference, packing, control)
    result = {
        "state": "outlier_scaled_sign_thresholds_measured_on_archived_prompt_rows",
        "cutoff_denominator": 32, "settings": len(GRID), "rows_per_split": raw["rows_per_split"],
        "fit_skip_target_percent": skip_target, "fit_traffic_target_percent": traffic_target,
        "fit_settings_reaching_skip_target": len(fit_skip), "least_error_at_fit_skip_target": rank,
        "scope": "Local visual prompt activation rows in independent fit and held image splits. "
                 "Output changes are relative to dense integer projection. Traffic uses the existing packed fetch model.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in pins},
        **report,
    }
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], "settings", len(GRID), "passing both traffic and error",
          report["fit_settings_reaching_traffic_target_at_baseline_error"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    run(parser.parse_args().output)
