"""Fit layer-specific sign thresholds on one split and score the other split."""

import argparse
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path

import measure_tri_oracle_packed_thresholds as sweep
from verify_tri_oracle_packed_down_weights import ROOT, sha256


PACKING = ROOT / "records/wac_channel_packing_bound_result.json"
BASELINE = ROOT / "records/wac_packed_predictor_threshold_result.json"
MODES = ("fixed_baseline", "paper_skip_target", "paper_traffic_target", "baseline_layer_error")
SPLITS = ("fit", "held")


def reduction(metrics):
    return 1 - Fraction(metrics["predicted_weight_bytes"] + metrics["sign_bytes"], metrics["dense_bytes"])


def select(results, skip_target, traffic_target, opportunities):
    """Return a threshold per objective using the fit split only."""
    fit = {setting: counts[0] for setting, counts in results.items()}
    baseline_error = fit[sweep.BASELINE]["relative_error_sum"]

    def rank_error(setting):
        return fit[setting]["relative_error_sum"], setting

    skip_fit = [setting for setting, counts in fit.items() if counts["skipped_channels"] >= skip_target * opportunities]
    traffic_fit = [setting for setting, counts in fit.items() if reduction(counts) >= traffic_target]
    comparable = [setting for setting, counts in fit.items() if counts["relative_error_sum"] <= baseline_error]
    best_skip = min(skip_fit, key=rank_error) if skip_fit else min(
        fit, key=lambda setting: (-fit[setting]["skipped_channels"], rank_error(setting)))
    best_traffic = min(traffic_fit, key=rank_error) if traffic_fit else min(
        fit, key=lambda setting: (-reduction(fit[setting]), rank_error(setting)))
    return {
        "fixed_baseline": (sweep.BASELINE, True),
        "paper_skip_target": (best_skip, bool(skip_fit)),
        "paper_traffic_target": (best_traffic, bool(traffic_fit)),
        "baseline_layer_error": (min(comparable, key=lambda setting: (-reduction(fit[setting]), rank_error(setting))), True),
    }


def measure(directory):
    directory.mkdir()
    targets = sweep.read(PACKING)["paper_figure_31_6_5"]
    skip_target = Fraction(targets["predicted_channel_reduction_percent"]["VQAv2"], 100)
    traffic_target = Fraction(targets["gated_feedforward_external_memory_access_reduction_percent"]["VQAv2"], 100)
    channels = 5632
    opportunities = sweep.ROWS * channels
    totals = {mode: [Counter(), Counter()] for mode in MODES}
    layers = []
    original = sweep.layer_sweep

    def capture(*args):
        results = original(*args)
        choices = select(results, skip_target, traffic_target, opportunities)
        selected = {}
        for mode, (thresholds, feasible) in choices.items():
            fit, held = results[thresholds]
            for cumulative, counts in zip(totals[mode], (fit, held), strict=True):
                cumulative.update(counts)
            selected[mode] = {"thresholds": thresholds, "fit_target_reached": feasible,
                              "fit": dict(fit), "held": dict(held)}
        layers.append(selected)
        return results

    sweep.layer_sweep = capture
    try:
        sweep.run(directory / "full_sweep.json")
    finally:
        sweep.layer_sweep = original

    base = sweep.read(BASELINE)
    fresh = sweep.read(directory / "full_sweep.json")
    assert fresh["baseline"] == base["baseline"]
    assert len(layers) == sweep.LAYERS and fresh["rows_per_split"] == sweep.LAYERS * sweep.ROWS
    summary = {}
    for mode, counts in totals.items():
        summary[mode] = {
            "fit_layers_reaching_objective": sum(layer[mode]["fit_target_reached"] for layer in layers),
            **{split: {
                "channel_skip_percent": 100 * values["skipped_channels"] / (len(layers) * opportunities),
                "net_traffic_reduction_percent": float(100 * reduction(values)),
                "mean_relative_output_change": values["relative_error_sum"] / fresh["rows_per_split"],
            } for split, values in zip(SPLITS, counts, strict=True)},
        }
    assert all(totals["fixed_baseline"][index][name] == base["baseline"][split][name]
               for index, split in enumerate(SPLITS) for name in totals["fixed_baseline"][index])
    evidence = (Path(__file__), PACKING, BASELINE, directory / "full_sweep.json")
    report = {
        "state": "layer_specific_sign_thresholds_fit_and_held_scored", "summary": summary, "layers": layers,
        "rows_per_split": fresh["rows_per_split"], "threshold_settings_per_layer": fresh["settings"],
        "evidence_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in evidence},
        "scope": "Fits each layer on eight archived images and scores eight different images. "
                 "The objectives use the paper's Visual Question Answering v2 targets on local samples. "
                 "Projection error compares against the same dense fixed-point output.",
    }
    (directory / "receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(report["state"], summary, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda path: Path(path).resolve())
    measure(parser.parse_args().output)
