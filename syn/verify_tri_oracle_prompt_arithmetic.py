"""Verify the paired prompt arithmetic and pruning diagnostics from raw tokens."""

import argparse
from collections import Counter
import json
from math import comb
from pathlib import Path

from tokenizers import Tokenizer

from verify_tri_oracle_late_down_precision import ARCHIVE, DATA, REPORT, ROOT, digest, read, records


MODES = ("late_float_down", "late_float_feedforward", "all_float_pruned", "all_float_unpruned")
EDGES = (
    ("baseline", "late_float_down"),
    ("baseline", "late_float_feedforward"),
    ("baseline", "all_float_pruned"),
    ("baseline", "all_float_unpruned"),
    ("late_float_down", "late_float_feedforward"),
    ("late_float_feedforward", "all_float_pruned"),
    ("all_float_pruned", "all_float_unpruned"),
)
LATE = tuple(range(17, 22))


def verify(work):
    result_path, config_path, prediction_path = (work / name for name in ("receipt.json", "inputs.json", "predictions.jsonl"))
    report, config = read(result_path), read(config_path)
    assert report["state"] == "matched_prompt_arithmetic_controls_completed"
    assert digest(config_path) == report["inputs_sha256"]
    assert digest(prediction_path) == report["predictions_sha256"]
    assert tuple(config["modes"]) == MODES and tuple(config["late_prefill_layers"]) == LATE

    prior_path = ROOT / "records/tri_oracle_late_down_precision.json"
    prior = read(prior_path)
    settings, = (ROOT / name for name in prior["evidence_sha256"] if name.endswith("/inputs.json"))
    assert digest(settings) == prior["evidence_sha256"][str(settings.relative_to(ROOT))]
    assert config["questions"] == read(settings)["questions"]

    labels_path = DATA / "testdev_balanced_questions.json"
    tokenizer_path = DATA.parent / "tiny_llava_v1/tokenizer.json"
    protocol_path = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
    run_script = ROOT / "syn/evaluate_tri_oracle_prompt_arithmetic.py"
    pins = config["input_sha256"]
    for path in (ARCHIVE, REPORT, labels_path, tokenizer_path, prior_path, settings, run_script):
        assert digest(path) == pins[str(path)], path
    assert digest(ARCHIVE) == read(REPORT)["evidence_sha256"][str(ARCHIVE.relative_to(ROOT))]
    protocol = read(protocol_path)
    assert config["checkpoint_revision"] == protocol["checkpoint_revision"]
    assert config["prompt"] == protocol["prompt"]
    labels = read(labels_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    archived = {row["questionId"]: row for row in records(ARCHIVE)}
    assert len(archived) == len(labels) == 12578

    def correct(row, key):
        assert row["questionId"] == key
        tokens = row["tokens"]
        assert 1 <= len(tokens) <= protocol["decoder_max_new_tokens"]
        assert tokens[-1] == 2 or len(tokens) == protocol["decoder_max_new_tokens"]
        assert all(type(token) is int and tokenizer.id_to_token(token) is not None for token in tokens)
        normalized = tokenizer.decode(tokens, skip_special_tokens=True).strip().rstrip(".").lower()
        assert row["prediction"] == normalized
        return normalized == labels[key]["answer"]

    images = set()
    totals = Counter()
    contributions = {mode: Counter() for mode in MODES}
    comparisons = {edge: Counter() for edge in EDGES}
    for key, row in zip(config["questions"], records(prediction_path), strict=True):
        image = labels[key]["imageId"]
        assert row["questionId"] == key and image not in images
        images.add(image)
        baseline = row["baseline"]
        assert {part: baseline[part] for part in archived[key]} == archived[key]
        assert baseline["float_rows"] == [0] * 22
        assert row["candidates"].keys() == set(MODES)
        candidates = {"baseline": baseline} | row["candidates"]
        outcome = {mode: correct(value, key) for mode, value in candidates.items()}
        totals.update({mode: int(value) for mode, value in outcome.items()})
        for mode, candidate in row["candidates"].items():
            counts = candidate["float_rows"]
            assert len(counts) == 22
            assert all((count > 0) == (not mode.startswith("late_") or index in LATE)
                       for index, count in enumerate(counts))
            predicted = candidate["diagnostic_predicted_skip"]
            applied = candidate["diagnostic_applied_skip"]
            assert 0 < predicted <= sum(counts) * 5632
            assert applied == (0 if mode == "all_float_unpruned" else predicted)
            contributions[mode].update(prompt_rows=sum(counts), predicted_skip_events=predicted,
                                       applied_skip_events=applied)
        for old, new in EDGES:
            comparisons[old, new].update(baseline=int(outcome[old]), candidate=int(outcome[new]),
                                         gained=int(outcome[new] and not outcome[old]),
                                         lost=int(outcome[old] and not outcome[new]),
                                         first_token_changed=int(candidates[old]["tokens"][0] != candidates[new]["tokens"][0]))

    assert len(images) == report["questions"] == report["baseline_outputs_reproduced"] == 67
    assert {mode: comparisons["baseline", mode] for mode in MODES} == report["comparisons"]
    assert totals["baseline"] == prior["paired_results"]["weight_plane"]["control"] == 34
    paired = {}
    for (old, new), counts in comparisons.items():
        discordant = counts["gained"] + counts["lost"]
        tail = sum(comb(discordant, k) for k in range(1 + min(counts["gained"], counts["lost"])))
        paired[f"{old}_to_{new}"] = dict(counts) | {"paired_exact_two_sided_p_value": min(1, 2 * tail / 2**discordant)}
    return {
        "state": "matched_prompt_arithmetic_controls_independently_rescored",
        "same_held_out_images": len(images), "correct": dict(totals), "paired": paired,
        "substitution_counts": {mode: dict(counts) for mode, counts in contributions.items()},
        "host_gpu": report["device"], "peak_device_bytes": report["peak_device_bytes"],
        "scope": "Diagnostic software arithmetic substitutions on the exact held-out questions from the integer "
                 "precision test. All arms retain the compact attention and answer-generation settings. The "
                 "unpruned arm bypasses the feed-forward predictor mask only during prompt processing. "
                 "Mapped execution and the paper's end-to-end benchmark require separate evidence.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (
            result_path, config_path, prediction_path, labels_path, tokenizer_path, protocol_path,
            prior_path, settings, run_script, Path(__file__).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=lambda name: Path(name).resolve())
    options = parser.parse_args()
    assert Path.cwd() == ROOT and __debug__ and not Path("/.dockerenv").exists()
    print(json.dumps(verify(options.work), indent=2, sort_keys=True))
