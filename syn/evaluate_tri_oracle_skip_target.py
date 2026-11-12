"""Score a paper-rate symmetric threshold on the fixed visual question benchmark."""

import argparse
import json
from pathlib import Path
import sys

# The calibrated reference uses PyTorch scaled dot-product attention.
sys.modules["kernels"] = None
import evaluate_tri_oracle_channel_scaled_pruning as benchmark


def run(output):
    root = benchmark.ROOT
    threshold_record = root / "records/wac_layer_predictor_threshold_result.json"
    packing = root / "records/wac_channel_packing_bound_result.json"
    verified = benchmark.read(threshold_record)
    target = benchmark.read(packing)["paper_figure_31_6_5"]["predicted_channel_reduction_percent"]["VQAv2"]
    sweep_path = benchmark.REFERENCE / "layer_thresholds_v1/full_sweep.json"
    digest = benchmark.sha256(sweep_path)
    assert verified["evidence_sha256"][str(sweep_path.relative_to(root))] == digest
    sweep = benchmark.read(sweep_path)
    opportunities = sweep["rows_per_split"] * benchmark.CHANNELS
    symmetric = [item for item in sweep["grid"] if item["thresholds"][1] == -item["thresholds"][2]]
    selected = min(symmetric, key=lambda item: (
        abs(100 * item["fit"]["skipped_channels"] - target * opportunities),
        item["fit"]["mean_relative_output_change"], item["thresholds"],
    ))
    gate, _, up = selected["thresholds"]
    calls = [0] * verified["layers"]
    source_install = benchmark.install_channel_scaling

    def install(replacement, layer, weight, context):
        scales = source_install(replacement, layer, weight, context)
        evaluate = replacement.reference.evaluate

        def with_threshold(activation, residual, **settings):
            # Both inputs are retained rows by hidden features. Protect the
            # first token exactly as the reference channel-scaling policy does.
            first = replacement.decoder.prefill_active and context["calls"][layer] == 0
            if settings["prune"] and not first:
                assert settings["gate_threshold"] == settings["up_window"] == 0
                settings.update(gate_threshold=gate, up_window=up)
                calls[layer] += 1
            return evaluate(activation, residual, **settings)

        replacement.reference.evaluate = with_threshold
        return scales

    output.mkdir()
    benchmark.install_channel_scaling = install
    try:
        benchmark.run(output)
    finally:
        benchmark.install_channel_scaling = source_install
    assert len(calls) == 22 and min(calls) > 0
    native = output / "receipt.json"
    result = benchmark.read(native)
    assert result["questions"] == result["reproduced_control_cases"] == 256
    assert benchmark.sha256(sweep_path) == digest
    paths = (Path(__file__).resolve(), threshold_record, packing, sweep_path, native)
    report = {
        "state": "paper_rate_sign_threshold_scored_on_local_visual_question_benchmark",
        "thresholds": selected["thresholds"], "fit_skip_target_percent": target,
        "archived_fit_skip_percent": 100 * selected["fit"]["skipped_channels"] / opportunities,
        "archived_held_skip_percent": 100 * selected["held"]["skipped_channels"] / opportunities,
        "threshold_evaluations_by_layer": calls, "questions": result["questions"],
        "scores_percent": result["scores_percent"], "work": result["work"],
        "elapsed_seconds": result["wall_seconds"], "peak_gpu_bytes": result["graphics_peak_bytes"],
        "evidence_sha256": {str(path.relative_to(root)): benchmark.sha256(path) for path in paths},
    }
    with (output / "threshold_receipt.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(report["state"], report["thresholds"], report["scores_percent"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=lambda value: Path(value).resolve())
    run(parser.parse_args().output)
