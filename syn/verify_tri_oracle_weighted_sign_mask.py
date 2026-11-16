"""Independently score sign predictors against the previous high-rate replay."""

import argparse
from collections import Counter
import json
from math import comb
from pathlib import Path

from tokenizers import Tokenizer

from verify_tri_oracle_late_down_precision import ARCHIVE, DATA, REPORT, ROOT, digest, read, records


PARENT = ROOT / "records/tri_oracle_prompt_mask_rates.json"
DRIVER = ROOT / "syn/evaluate_tri_oracle_weighted_sign_mask.py"
MODES = ("high_rate_magnitude", "high_rate_calibrated_sign", "high_rate_weighted_sign")
ACTIVITY = ("budget", "used", "changed_selections", "opportunities", "high_budget_rows")


def verify(work):
    receipt_path, config_path, table_path, predictions, generated = (
        work / name for name in ("receipt.json", "inputs.json", "sign_rank_table.json",
                                  "predictions.jsonl", "paired_runner.py"))
    receipt, config, table = map(read, (receipt_path, config_path, table_path))
    assert receipt["state"] == "high_rate_weighted_sign_host_panel_completed"
    assert tuple(config["modes"]) == MODES and config["calibration_uses_labels"] is False
    assert config["high_rate_percent_for_nonfirst_prompt_rows"] == 58
    for path, name in ((config_path, "inputs"), (table_path, "rank_table"), (predictions, "predictions")):
        assert digest(path) == receipt[f"{name}_sha256"]

    parent = read(PARENT)

    def parent_input(name):
        (path,) = (ROOT / path for path in parent["evidence_sha256"]
                   if path.endswith(f"/prompt_mask_rate_trials/{name}"))
        assert digest(path) == parent["evidence_sha256"][str(path.relative_to(ROOT))]
        return path

    old_predictions = parent_input("predictions.jsonl")
    old_manifest = parent_input("inputs.json")
    old_table = parent_input("sign_rank_table.json")
    previous = read(old_manifest)
    assert all(config[key] == previous[key] for key in ("questions", "fit_questions", "checkpoint_revision", "prompt"))
    control = read(old_table)
    assert len(table["rank_by_layer_and_bin"]) == len(table["samples"]) == 2
    assert all(table[key][0] == control[key] for key in ("rank_by_layer_and_bin", "samples"))
    for ranks, samples in zip(table["rank_by_layer_and_bin"], table["samples"], strict=True):
        assert len(ranks) == len(samples) == 22
        assert all(sorted(values) == list(range(81)) for values in ranks)
        assert all(len(values) == 81 and min(values) >= 0 for values in samples)
        assert sum(map(sum, samples)) == parent["calibration_entries"]
    assert receipt["calibration_entries"] == [parent["calibration_entries"]] * 2

    labels_path = DATA / "testdev_balanced_questions.json"
    tokenizer_path = DATA.parent / "tiny_llava_v1/tokenizer.json"
    protocol_path = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
    for path in (ARCHIVE, REPORT, labels_path, tokenizer_path, generated):
        assert digest(path) == config["input_sha256"][str(path)]
    assert digest(ARCHIVE) == read(REPORT)["evidence_sha256"][str(ARCHIVE.relative_to(ROOT))]
    protocol = read(protocol_path)
    assert config["checkpoint_revision"] == protocol["checkpoint_revision"] and config["prompt"] == protocol["prompt"]
    labels = read(labels_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    held_images = {labels[key]["imageId"] for key in config["questions"]}
    fit_images = {labels[key]["imageId"] for key in config["fit_questions"]}
    assert len(fit_images) == receipt["calibration_images"] == 16
    assert not fit_images & held_images

    def correct(row, key):
        tokens = row["tokens"]
        limit = protocol["decoder_max_new_tokens"]
        assert row["questionId"] == key and 1 <= len(tokens) <= limit
        assert tokens[-1] == 2 or len(tokens) == limit
        assert all(type(token) is int and tokenizer.id_to_token(token) is not None for token in tokens)
        answer = tokenizer.decode(tokens, skip_special_tokens=True).strip().rstrip(".").lower()
        assert answer == row["prediction"]
        return answer == labels[key]["answer"]

    paired = {mode: Counter() for mode in MODES}
    activity = {mode: Counter() for mode in MODES}
    answer_lengths = {mode: Counter() for mode in ("baseline", *MODES)}
    direct = Counter()
    for key, old, row in zip(config["questions"], records(old_predictions), records(predictions), strict=True):
        assert key == row["questionId"] == old["questionId"]
        baseline = row["baseline"]
        assert baseline == old["baseline"]
        assert row["candidates"]["high_rate_magnitude"] == old["candidates"]["high_rate_magnitude"]
        assert row["candidates"].keys() == set(MODES)
        reference = correct(baseline, key)
        answer_lengths["baseline"].update(tokens=len(baseline["tokens"]),
                                           at_limit=int(len(baseline["tokens"]) == protocol["decoder_max_new_tokens"]))
        outcomes = {}
        for mode, candidate in row["candidates"].items():
            rows, remainder = divmod(candidate["opportunities"], 5632)
            assert remainder == 0 and candidate["high_budget_rows"] == rows - 22
            fixed = (rows - 22) * (5632 * 58 // 100)
            assert fixed <= candidate["budget"] == candidate["used"] <= fixed + 22 * 5632
            outcome = correct(candidate, key)
            outcomes[mode] = outcome
            answer_lengths[mode].update(tokens=len(candidate["tokens"]),
                                        at_limit=int(len(candidate["tokens"]) == protocol["decoder_max_new_tokens"]))
            paired[mode].update(baseline=int(reference), candidate=int(outcome),
                                gained=int(outcome and not reference), lost=int(reference and not outcome),
                                first_token_changed=int(baseline["tokens"][0] != candidate["tokens"][0]))
            activity[mode].update({name: candidate[name] for name in ACTIVITY})
        a, b = (outcomes[mode] for mode in MODES[1:])
        unweighted, weighted = (row["candidates"][mode]["tokens"] for mode in MODES[1:])
        direct.update(gained=int(b and not a), lost=int(a and not b),
                      different_token_sequences=int(unweighted != weighted))

    assert paired == receipt["comparisons"] and activity == receipt["activity"]
    assert len(held_images) == receipt["questions"] == receipt["baseline_outputs_reproduced"] == 67
    summary = {}
    for mode, counts in paired.items():
        discordant = counts["gained"] + counts["lost"]
        tail = sum(comb(discordant, k) for k in range(1 + min(counts["gained"], counts["lost"])))
        summary[mode] = dict(counts) | {
            "paired_exact_two_sided_p_value": min(1, 2 * tail / 2**discordant),
            "prompt_skip_percent": 100 * activity[mode]["used"] / activity[mode]["opportunities"],
        }
    return {
        "state": "high_rate_weighted_sign_independently_rescored",
        "held_out_questions": len(held_images), "label_free_calibration_images": len(fit_images),
        "calibration_entries_per_predictor": parent["calibration_entries"],
        "paired": summary, "weighted_vs_unweighted_on_same_questions": dict(direct),
        "answer_generation": {mode: dict(counts) for mode, counts in answer_lengths.items()},
        "two_bit_outlier_levels": [0, 1, 2, 3],
        "device": receipt["device"], "peak_device_bytes": receipt["peak_device_bytes"],
        "scope": "The sign-based scores use weight signs independently of the full gate and up products. "
                 "The weighted mode adds two-bit residual magnitudes for outliers. The software replay "
                 "applies each predicted mask and keeps the first prompt row's archived skip count. Mapped predictor cost, "
                 "memory traffic, full-benchmark accuracy and paper protocol remain open.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (
            receipt_path, config_path, table_path, predictions, generated, PARENT, DRIVER,
            old_predictions, old_manifest, old_table, labels_path, tokenizer_path, protocol_path,
            Path(__file__).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=lambda name: Path(name).resolve())
    options = parser.parse_args()
    assert __debug__ and not Path("/.dockerenv").exists() and Path.cwd() == ROOT
    print(json.dumps(verify(options.work), indent=2, sort_keys=True))
