"""Measure the effect of rounding before the three-sigma outlier test in Figure 31.6.5."""

import argparse
from collections import Counter
from itertools import product
import json
from pathlib import Path
import time

import measure_tri_oracle_packed_thresholds as sweep
from tri_oracle_integer_reference import _dot, _quantize
from verify_tri_oracle_packed_down_weights import ROOT, sha256


RULES = ("q8_unit_sigma", "unrounded_unit_sigma", "unrounded_measured_sigma")
GRID = tuple((gate, -window, window) for gate, window in product((-4, 0, 4), (0, 2, 4, 8, 12, 24)))


def measure_layer(activation, residual, reference, down, policy):
    """Use archived activation and residual [R,H], with R prompt rows and H hidden features."""
    torch = sweep.torch
    _, _, stats = sweep.evaluate_policy(reference, activation, residual, policy, prune=False)
    codes, _, default, dense, _, _ = sweep.reconstruct(reference, activation, stats)  # [R,H] activation, [R,K] channels.
    weights, exponent = _quantize(down, per_row=True)  # [H,K] output codes and [H,1] scales.
    shift = exponent.T + stats["down_shift"][:, None] - 8 - stats["up_gain_bits"][:, None]  # [R,H].
    denominator = torch.ldexp(_dot(dense, weights).float(), shift).double().norm(dim=1).clamp_min(1e-20)  # [R].
    codes_q8 = stats["norm_codes"]  # [R,H] predictor codes before the learned scale.
    wide_residual = residual.double()  # [R,H] widened pre-normalization checkpoint residual.
    rms = (wide_residual.square().mean(dim=1, keepdim=True) + reference.epsilon).sqrt()  # [R,1].
    normalized = wide_residual / rms  # [R,H] unrounded normalization before learned scaling.
    sigma = normalized.std(dim=1, correction=0, keepdim=True)  # [R,1] measured standard deviations.
    default_support = codes_q8.abs().gt(768)  # [R,H] current outlier flags.
    supports = (
        (default_support, codes_q8.lt(0)),
        (normalized.abs().gt(3), normalized.lt(0)),
        (normalized.abs().gt(3 * sigma), normalized.lt(0)),
    )  # Paired [R,H] eligibility and negative-sign tensors.
    parts = (slice(0, sweep.ROWS), slice(sweep.ROWS, 2 * sweep.ROWS))
    for rule, (outlier, negative) in zip(RULES, supports, strict=True):
        signs = (torch.where(negative, -1, 1) * outlier).to(torch.int8)  # [R,H] ternary signs.
        gate = _dot(signs, reference.gate_sign)  # [R,K] gate sign matches minus mismatches.
        up = _dot(signs, reference.up_sign).abs()  # [R,K] magnitude of up sign margin.
        eligible = outlier.any(dim=1, keepdim=True)  # [R,1] nonempty support for each row.
        support_stats = []
        for part in parts:
            words = outlier[part].reshape(sweep.ROWS, sweep.HIDDEN // 2, 2).any(dim=2)  # [R/2,H/2].
            support_stats.append((int(outlier[part].sum()), int(eligible[part].sum()),
                                  int(words.sum()) * (dense.shape[1] // 32) * 16,
                                  int((outlier[part] != default_support[part]).sum())))
        for gate_limit, lower, upper in GRID:
            skip = eligible & gate.le(gate_limit) & up.le(upper)  # [R,K] intersected near-zero mask.
            if rule == RULES[0] and (gate_limit, lower, upper) == sweep.BASELINE:
                assert torch.equal(skip, default)
            removed = dense.masked_fill(~skip, 0)  # [R,K] removed down-projection input.
            effect = torch.ldexp(_dot(removed, weights).float(), shift)  # [R,H] omitted contribution.
            relative = effect.double().norm(dim=1) / denominator  # [R] relative output change.
            counts = []
            for part, (outliers, rows, sign_bytes, changes) in zip(parts, support_stats, strict=True):
                kept = dense[part].masked_fill(skip[part], 0)  # [R/2,K] retained down-projection input.
                traffic = sweep.group_traffic(codes[part], ~skip[part], dense[part], kept, sweep.BATCH)
                counts.append(Counter(
                    dense_bytes=traffic["no_predictor_gate_up_bytes"] + traffic["no_predictor_down_bytes"],
                    predicted_weight_bytes=traffic["predictor_gate_up_bytes"] + traffic["predictor_down_bytes"],
                    sign_bytes=sign_bytes, skipped_channels=int(skip[part].sum()),
                    relative_error_sum=float(relative[part].sum()), outliers=outliers,
                    eligible_rows=rows, support_bit_changes_from_q8=changes,
                ))
            yield rule, (gate_limit, lower, upper), counts


def run(output):
    started = time.monotonic()
    output.mkdir()
    totals = {rule: {setting: (Counter(), Counter()) for setting in GRID} for rule in RULES}
    original, original_grid = sweep.layer_sweep, sweep.GRID

    def capture(*args):
        for rule, setting, pair in measure_layer(*args):
            for total, current in zip(totals[rule][setting], pair, strict=True):
                total.update(current)
        return original(*args)

    control = output / "fixed_threshold_control.json"
    sweep.layer_sweep, sweep.GRID = capture, (sweep.BASELINE,)
    try:
        sweep.run(control)
    finally:
        sweep.layer_sweep, sweep.GRID = original, original_grid

    baseline = sweep.read(control)
    historical = ROOT / "records/wac_packed_predictor_threshold_result.json"
    assert baseline["baseline"] == sweep.read(historical)["baseline"]
    physical = ROOT / "records/wac_channel_packing_bound_result.json"
    skip_target = sweep.read(physical)["paper_figure_31_6_5"]["predicted_channel_reduction_percent"]["VQAv2"]
    traffic_target = baseline["paper_traffic_target_percent"]
    reports = {}
    for rule, entries in totals.items():
        summary = sweep.summarize(entries, traffic_target)
        for item in summary["grid"]:
            for split in ("fit", "held"):
                item[split]["skip_percent"] = 100 * item[split]["skipped_channels"] / (baseline["rows_per_split"] * 5632)
        candidates = [item for item in summary["grid"] if item["fit"]["skip_percent"] >= skip_target]
        reports[rule] = {
            "settings_reaching_fit_skip_target": len(candidates),
            "least_fit_error_reaching_skip_target": min(
                candidates, key=lambda item: item["fit"]["relative_error_sum"], default=None,
            ),
            **summary,
        }
    for split in ("fit", "held"):
        observed = reports[RULES[0]]["baseline"][split]
        assert all(observed[key] == value for key, value in baseline["baseline"][split].items()), split
    paths = (Path(__file__).resolve(), Path(sweep.__file__).resolve(), historical, physical, control)
    result = {
        "state": "normalization_outlier_rounding_measured_on_archived_prompt_rows",
        "rows_per_split": baseline["rows_per_split"], "settings_per_rule": len(GRID),
        "paper_skip_target_percent": skip_target, "paper_traffic_target_percent": traffic_target,
        "rules": reports, "elapsed_seconds": time.monotonic() - started,
        "peak_gpu_bytes": sweep.torch.cuda.max_memory_allocated(),
        "scope": "Figure 31.6.5 places detection before applying the learned normalization weight. "
                 "Trained checkpoint prompt rows from disjoint calibration and held images. "
                 "Output change is relative to dense integer feed-forward output. Traffic uses grouped packed reads.",
        "evidence_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in paths},
    }
    (output / "receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], result["rows_per_split"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
