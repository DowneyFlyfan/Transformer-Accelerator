"""Independently re-score the wider sign threshold on the pinned visual holdout."""

from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from verify_tri_oracle_channel_scaled_down import ROOT, REFERENCE, load_official_sources, read, score_cases, sha


MODES = ("channel_scaled_down", "channel_scaled_down_pruned")
CASE = REFERENCE / "paper_skip_target_holdout"


def verify():
    native_path, threshold_path = CASE / "receipt.json", CASE / "threshold_receipt.json"
    status, log = CASE.with_suffix(".exit_status"), CASE.with_suffix(".log")
    raw, trial = read(native_path), read(threshold_path)
    assert status.read_text().strip() == "0"
    assert raw["state"] == "scaled_down_and_pruned_local_benchmark_scored"
    assert trial["state"] == "paper_rate_sign_threshold_scored_on_local_visual_question_benchmark"
    assert raw["questions"] == raw["reproduced_control_cases"] == trial["questions"] == 256
    for pins in (trial["evidence_sha256"], raw["source_sha256"]):
        assert all(sha(ROOT / path) == digest for path, digest in pins.items())
    assert len(trial["threshold_evaluations_by_layer"]) == raw["decoder_layers"] == 22
    assert min(trial["threshold_evaluations_by_layer"]) > 0

    manifest = REFERENCE / "grouped_precision_holdout/manifest.json"
    samples = read(manifest)["samples"]
    order = [(sample["question_id"], sample["image_id"]) for sample in samples]
    assert len({image for _, image in order}) == len({question for question, _ in order}) == 256
    native_order = [tuple(map(int, row.split()[1:])) for row in log.read_text().splitlines()
                    if row.startswith("FF_SCALED_PRUNE_CASE ")]
    assert native_order == list(enumerate((question for question, _ in order), 1))
    assert set(raw["answers"]) == set(MODES)
    for answers in raw["answers"].values():
        assert [(row["question_id"], row["image_id"]) for row in answers] == order

    archived_path = REFERENCE / "ff_channel_scaled_pruned/receipt.json"
    old_proof = ROOT / "records/ff_channel_scaled_pruning_result.json"
    assert read(old_proof)["evidence_sha256"][str(archived_path.relative_to(ROOT))] == sha(archived_path)
    archived = read(archived_path)
    assert archived["checkpoint_revision"] == raw["checkpoint_revision"]
    assert archived["answers"][MODES[0]] == raw["answers"][MODES[0]]
    scorer, normalizer, sources = load_official_sources(ROOT)
    assert all(raw["source_sha256"][path] == digest for path, digest in sources.items())
    scores = {mode: score_cases(samples, raw["answers"][mode], scorer, normalizer) for mode in MODES}
    for score in scores.values():
        score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert scores == raw["scores"]
    percents = {mode: score["official_vqa_consensus_percent"] for mode, score in scores.items()}
    assert percents == raw["scores_percent"] == trial["scores_percent"]
    dense, pruned = (scores[mode]["per_question_score"] for mode in MODES)
    paired = Counter((pruned[key] > value) - (pruned[key] < value) for key, value in dense.items())
    assert raw["paired_question_scores"] == {"improved": paired[1], "declined": paired[-1], "unchanged": paired[0]}
    change = float(Decimal(str(percents[MODES[1]])) - Decimal(str(percents[MODES[0]])))
    assert change == raw["change_percentage_points"]

    assert raw["work"] == trial["work"]
    work = {}
    for phase in ("prefill", "decode"):
        rows = raw["answers"][MODES[1]]
        skipped = sum(row[phase + "_skipped"] for row in rows)
        opportunities = 5632 * sum(row[phase + "_rows"] for row in rows)
        assert (skipped, opportunities) == (trial["work"][phase]["skipped_channels"],
                                             trial["work"][phase]["channel_opportunities"])
        work[phase] = {"skipped_channels": skipped, "channel_opportunities": opportunities,
                       "skip_percent": 100 * skipped / opportunities}
    sweep_path = REFERENCE / "layer_thresholds_v1/full_sweep.json"
    sweep = read(sweep_path)
    opportunities = sweep["rows_per_split"] * 5632
    choices = [item for item in sweep["grid"] if item["thresholds"][1] == -item["thresholds"][2]]
    chosen = min(choices, key=lambda item: (abs(item["fit"]["skipped_channels"] * 100 - 58 * opportunities),
                                            item["fit"]["mean_relative_output_change"], item["thresholds"]))
    assert chosen["thresholds"] == trial["thresholds"] == [0, -4, 4]
    paths = (native_path, threshold_path, status, log, manifest, archived_path, old_proof, sweep_path,
             Path(__file__).resolve(), ROOT / "syn/evaluate_tri_oracle_skip_target.py")
    return {
        "state": "paper_rate_sign_threshold_local_holdout_independently_rescored",
        "checkpoint_revision": raw["checkpoint_revision"], "questions": len(order), "thresholds": trial["thresholds"],
        "scores_percent": percents, "previous_zero_window_score_percent": archived["scores_percent"][MODES[1]],
        "change_percentage_points": change, "paired_question_scores": raw["paired_question_scores"], "work": work,
        "scope": "Fixed local 256-question Visual Question Answering v2 holdout. The paper's exact prompt and split "
                 "remain unverified. The wider window was selected on separate archived activation rows.",
        "native_seconds": trial["elapsed_seconds"], "peak_gpu_bytes": trial["peak_gpu_bytes"],
        "evidence_sha256": {str(path.relative_to(ROOT)): sha(path) for path in paths},
    }


if __name__ == "__main__":
    result = verify()
    output = ROOT / "records/wac_paper_skip_threshold_vqav2_result.json"
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result["state"], result["scores_percent"], result["work"], flush=True)
