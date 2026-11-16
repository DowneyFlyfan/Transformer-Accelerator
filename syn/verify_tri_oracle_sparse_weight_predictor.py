"""Rescore sparse-predictor answers and verify modeled coefficient-read counts."""

import argparse
from collections import Counter
import json
from pathlib import Path

from tokenizers import Tokenizer

from verify_tri_oracle_late_down_precision import ARCHIVE, DATA, REPORT, ROOT, digest, read, records


def verify(work):
    receipt_path = work / "receipt.json"
    config_path = work / "inputs.json"
    predictions = work / "predictions.jsonl"
    config, receipt = read(config_path), read(receipt_path)
    assert digest(config_path) == receipt["inputs_sha256"]
    assert digest(predictions) == receipt["predictions_sha256"]
    assert receipt["state"] == "sparse_weight_predictor_held_panel_completed"
    archive = ARCHIVE
    old = DATA / "prompt_mask_rate_trials"
    old_report = ROOT / "records/tri_oracle_prompt_mask_rates.json"
    archive_report = REPORT
    questions = DATA / "testdev_balanced_questions.json"
    tokenizer_path = DATA.parent / "tiny_llava_v1/tokenizer.json"
    runner = ROOT / "syn/evaluate_tri_oracle_sparse_weight_predictor.py"
    for path in (archive, old / "predictions.jsonl", old / "inputs.json", old_report, archive_report, questions, tokenizer_path, runner):
        assert digest(path) == config["input_sha256"][str(path)], path
    assert digest(archive) == read(archive_report)["evidence_sha256"][str(archive.relative_to(ROOT))]
    for name in ("inputs.json", "predictions.jsonl"):
        assert digest(old / name) == read(old_report)["evidence_sha256"][str((old / name).relative_to(ROOT))]

    archived = {row["questionId"]: row for row in records(archive)}
    assert len(archived) == 12578
    prior = read(old / "inputs.json")
    assert prior["questions"] == config["questions"]
    assert prior["calibration_uses_labels"] is False
    labels = read(questions)
    held_images = {labels[key]["imageId"] for key in prior["questions"]}
    fit_images = {labels[key]["imageId"] for key in prior["fit_questions"]}
    assert len(held_images) == 67 and len(fit_images) == 16 and held_images.isdisjoint(fit_images)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    protocol = read(ROOT / "records/wac_gqa_accuracy_protocol_result.json")
    assert config["checkpoint_revision"] == protocol["checkpoint_revision"] and config["prompt"] == protocol["prompt"]
    assert config["high_rate_percent_for_nonfirst_prompt_rows"] == 58


    def correct(record, key):
        assert record["questionId"] == key
        tokens = record["tokens"]
        max_tokens = protocol["decoder_max_new_tokens"]
        assert tokens and len(tokens) <= max_tokens and (tokens[-1] == 2 or len(tokens) == max_tokens)
        assert all(type(token) is int and tokenizer.id_to_token(token) is not None for token in tokens)
        prediction = tokenizer.decode(tokens, skip_special_tokens=True).strip().rstrip(".").lower()
        assert prediction == record["prediction"]
        return prediction == labels[key]["answer"]


    magnitude = "high_rate_magnitude"
    top_counts = {"sparse_top64": 64, "sparse_top512": 512}
    assert config["fixed_top_k"] == top_counts
    modes = (magnitude, "sparse_three_sigma", *top_counts)
    assert tuple(config["modes"]) == modes
    counts = {mode: Counter() for mode in modes}
    totals = {mode: Counter() for mode in modes}
    fields = ("budget", "used", "opportunities", "high_budget_rows", "changed_selections",
              "probe_feature_events", "probe_bytes", "followup_bytes_with_per_row_reuse",
              "followup_bytes_without_per_row_reuse", "dense_reference_bytes")
    hidden, intermediate = 2048, 5632
    skip = intermediate * 58 // 100
    kept = intermediate - skip
    assert 67 == receipt["questions"] == receipt["baseline_outputs_reproduced"] == receipt["magnitude_outputs_reproduced"]
    for key, record, previous in zip(config["questions"], records(predictions), records(old / "predictions.jsonl"), strict=True):
        assert key == record["questionId"] == previous["questionId"]
        baseline = record["baseline"]
        assert {name: baseline[name] for name in archived[key]} == archived[key]
        assert record["candidates"].keys() == counts.keys()
        expected = previous["candidates"][magnitude]
        assert {name: record["candidates"][magnitude][name] for name in expected} == expected
        old_correct = correct(baseline, key)
        for mode, row in record["candidates"].items():
            correct_now = correct(row, key)
            counts[mode].update(baseline=int(old_correct), candidate=int(correct_now),
                                gained=int(correct_now and not old_correct), lost=int(old_correct and not correct_now),
                                first_token_changed=int(row["tokens"][0] != baseline["tokens"][0]))
            ordinary = row["high_budget_rows"]
            assert row["opportunities"] == (ordinary + 22) * intermediate
            assert ordinary * skip <= row["used"] == row["budget"] <= ordinary * skip + 22 * intermediate
            if mode != magnitude:
                features = row["probe_feature_events"]
                assert 0 <= features <= ordinary * hidden
                if mode in top_counts:
                    assert features == ordinary * top_counts[mode]
                assert row["probe_bytes"] == 2 * intermediate * features
                assert row["dense_reference_bytes"] == ordinary * intermediate * 3 * hidden
                followup = ordinary * kept * 3 * hidden
                assert row["followup_bytes_without_per_row_reuse"] == followup
                assert row["followup_bytes_with_per_row_reuse"] == followup - 2 * kept * features
            totals[mode].update({name: row[name] for name in fields})
    assert counts == receipt["comparisons"] and totals == receipt["work"]
    results = {}
    for mode, value in totals.items():
        result = dict(counts[mode])
        if mode != magnitude:
            dense = value["dense_reference_bytes"]
            for reuse in ("with", "without"):
                reads = value["probe_bytes"] + value[f"followup_bytes_{reuse}_per_row_reuse"]
                result[f"modeled_reduction_percent_{reuse}_reuse"] = round(100 * (dense - reads) / dense, 2)
        results[mode] = result
    return {
        "questions": len(held_images),
        "device": receipt["device"],
        "elapsed_seconds": receipt["elapsed_seconds"],
        "results": results,
        "state": "sparse_weight_predictors_independently_rescored",
        "scope": "Held-out software stress test at a fixed 58% ordinary prompt-row skip rate. The paper reports accuracy at mean reduction settings. The modeled coefficient reads exclude layout and bus overhead, so they do not establish physical weight traffic.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in
                            (runner, config_path, receipt_path, predictions, Path(__file__).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=lambda name: Path(name).resolve())
    args = parser.parse_args()
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").exists()
    print(json.dumps(verify(args.work), indent=2, sort_keys=True))
