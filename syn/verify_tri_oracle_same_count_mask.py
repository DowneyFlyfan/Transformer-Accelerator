"""Rescore paired same-count mask predictions and verify frozen fit separation."""

import argparse
from collections import Counter
import json
from math import comb
from pathlib import Path

from tokenizers import Tokenizer

from verify_tri_oracle_late_down_precision import ARCHIVE, DATA, REPORT, ROOT, digest, read, records


MODES = ("activation_oracle", "calibrated_sign_rank", "high_rate_magnitude")
ACTIVITY = ("budget", "used", "changed_selections", "opportunities", "high_budget_rows")


def verify(work):
    result_path, config_path, ranking_path, predictions = (
        work / name for name in ("receipt.json", "inputs.json", "sign_rank_table.json", "predictions.jsonl"))
    receipt, config, ranking = map(read, (result_path, config_path, ranking_path))
    assert receipt["state"] == "same_count_prompt_masks_host_panel_completed"
    for path, name in ((config_path, "inputs"), (ranking_path, "rank_table"), (predictions, "predictions")):
        assert digest(path) == receipt[f"{name}_sha256"]
    assert tuple(config["modes"]) == MODES and config["calibration_uses_labels"] is False
    assert config["high_rate_percent_for_nonfirst_prompt_rows"] == 58
    ranks, samples = ranking["rank_by_layer_and_bin"], ranking["samples"]
    assert len(ranks) == len(samples) == 22
    assert all(sorted(values) == list(range(81)) for values in ranks)
    assert all(len(values) == 81 and min(values) >= 0 for values in samples)
    assert sum(map(sum, samples)) == receipt["calibration_entries"] > 0

    protocol_path = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
    prior_path = ROOT / "records/tri_oracle_prompt_arithmetic.json"
    prior = read(prior_path)
    parent_config, = (ROOT / name for name in prior["evidence_sha256"]
                       if name.endswith("/matched_prompt_arithmetic/inputs.json"))
    assert digest(parent_config) == prior["evidence_sha256"][str(parent_config.relative_to(ROOT))]
    assert config["questions"] == read(parent_config)["questions"]
    labels_path = DATA / "testdev_balanced_questions.json"
    tokenizer_path = DATA.parent / "tiny_llava_v1/tokenizer.json"
    runner = ROOT / "syn/evaluate_tri_oracle_same_count_mask.py"
    pins = config["input_sha256"]
    for path in (ARCHIVE, REPORT, prior_path, parent_config, labels_path, tokenizer_path, runner):
        assert digest(path) == pins[str(path)], path
    assert digest(ARCHIVE) == read(REPORT)["evidence_sha256"][str(ARCHIVE.relative_to(ROOT))]
    protocol = read(protocol_path)
    assert config["checkpoint_revision"] == protocol["checkpoint_revision"]
    assert config["prompt"] == protocol["prompt"]
    labels = read(labels_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    archived = {row["questionId"]: row for row in records(ARCHIVE)}
    assert len(archived) == len(labels) == 12578
    held_images = {labels[key]["imageId"] for key in config["questions"]}
    fit_images = {labels[key]["imageId"] for key in config["fit_questions"]}
    assert len(fit_images) == len(config["fit_questions"]) == receipt["calibration_images"] == 16
    assert not held_images & fit_images

    def correct(row, key):
        assert row["questionId"] == key
        tokens = row["tokens"]
        assert 1 <= len(tokens) <= protocol["decoder_max_new_tokens"]
        assert tokens[-1] == 2 or len(tokens) == protocol["decoder_max_new_tokens"]
        assert all(type(token) is int and tokenizer.id_to_token(token) is not None for token in tokens)
        answer = tokenizer.decode(tokens, skip_special_tokens=True).strip().rstrip(".").lower()
        assert answer == row["prediction"]
        return answer == labels[key]["answer"]

    totals = {mode: Counter() for mode in MODES}
    activity = {mode: Counter() for mode in MODES}
    observed = []
    for key, row in zip(config["questions"], records(predictions), strict=True):
        assert row["questionId"] == key
        observed.append(key)
        baseline = row["baseline"]
        assert {part: baseline[part] for part in archived[key]} == archived[key]
        assert row["candidates"].keys() == set(MODES)
        previous = correct(baseline, key)
        for mode, candidate in row["candidates"].items():
            assert candidate["used"] == candidate["budget"] > 0
            assert 0 <= candidate["changed_selections"] <= candidate["used"] <= candidate["opportunities"]
            rows, remainder = divmod(candidate["opportunities"], 5632)
            assert remainder == 0
            if mode == "high_rate_magnitude":
                assert candidate["high_budget_rows"] == rows - 22
                fixed = (rows - 22) * (5632 * 58 // 100)
                assert fixed <= candidate["used"] <= fixed + 22 * 5632
            else:
                assert candidate["high_budget_rows"] == 0
            new = correct(candidate, key)
            totals[mode].update(baseline=int(previous), candidate=int(new), gained=int(new and not previous),
                                lost=int(previous and not new), first_token_changed=int(
                                    baseline["tokens"][0] != candidate["tokens"][0]))
            activity[mode].update({name: candidate[name] for name in ACTIVITY})

    assert len(observed) == len(held_images) == receipt["questions"] == receipt["baseline_outputs_reproduced"] == 67
    assert totals == receipt["comparisons"] and activity == receipt["activity"]
    assert all(counts["baseline"] == prior["correct"]["baseline"] == 34 for counts in totals.values())
    paired = {}
    for mode, counts in totals.items():
        discordant = counts["gained"] + counts["lost"]
        tail = sum(comb(discordant, k) for k in range(1 + min(counts["gained"], counts["lost"])))
        entries = activity[mode]
        paired[mode] = dict(counts) | {
            "paired_exact_two_sided_p_value": min(1, 2 * tail / 2**discordant),
            "prompt_skip_percent": 100 * entries["used"] / entries["opportunities"],
            "fraction_of_selections_changed_percent": 100 * entries["changed_selections"] / entries["used"],
        }
    return {
        "state": "same_count_prompt_masks_independently_rescored",
        "held_out_questions": len(observed), "label_free_calibration_images": len(fit_images),
        "calibration_entries": receipt["calibration_entries"],
        "paired": paired, "activity": {mode: dict(counts) for mode, counts in activity.items()},
        "device": receipt["device"], "peak_device_bytes": receipt["peak_device_bytes"],
        "high_rate_percent_for_nonfirst_prompt_rows": config["high_rate_percent_for_nonfirst_prompt_rows"],
        "scope": "The same-count candidates retain the archived skip count for each prompt row they process. "
                 "The high-rate diagnostic keeps the first row's count and uses a fixed fraction for the "
                 "remaining rows. The magnitude trials use computed gate and up products. The sign-rank "
                 "candidate uses a frozen calibration table and software row ranking. Hardware ranking cost, "
                 "memory traffic, full accuracy and paper protocol remain open.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (
            result_path, config_path, ranking_path, predictions, labels_path, tokenizer_path, protocol_path,
            prior_path, parent_config, runner, Path(__file__).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=lambda name: Path(name).resolve())
    options = parser.parse_args()
    assert Path.cwd() == ROOT and __debug__ and not Path("/.dockerenv").exists()
    print(json.dumps(verify(options.work), indent=2, sort_keys=True))
