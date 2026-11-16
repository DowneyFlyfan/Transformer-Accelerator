"""Independently score both precision trials from the held-out host replay."""

import argparse
from collections import Counter
from hashlib import file_digest
import json
from math import comb
from pathlib import Path

from tokenizers import Tokenizer


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".cache/model_reference/gqa_testdev"
ARCHIVE = DATA / "full_calibrated_clip/predictions.jsonl"
REPORT = ROOT / "records/tri_oracle_full_calibrated_clipped_accuracy.json"
MODES = ("weight_plane", "exact_gated")


def digest(path):
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def records(path):
    with path.open() as stream:
        yield from map(json.loads, stream)


def verify(work):
    receipt_path, config_path, predictions = (work / name for name in ("receipt.json", "inputs.json", "predictions.jsonl"))
    receipt, config = read(receipt_path), read(config_path)
    assert receipt["state"] == "late_down_precision_host_panel_completed"
    assert digest(config_path) == receipt["inputs_sha256"]
    assert digest(predictions) == receipt["predictions_sha256"]
    assert tuple(config["modes"]) == MODES
    assert config["refined_prefill_layers"] == list(range(17, 22))
    assert config["residual_weight_fractional_bits"] == 6
    evidence = read(REPORT)["evidence_sha256"]
    assert digest(ARCHIVE) == evidence[str(ARCHIVE.relative_to(ROOT))]
    archived = {row["questionId"]: row for row in records(ARCHIVE)}
    assert len(archived) == 12578

    questions = DATA / "testdev_balanced_questions.json"
    tokenizer_path = DATA.parent / "tiny_llava_v1/tokenizer.json"
    runner = ROOT / "syn/evaluate_tri_oracle_late_down_precision.py"
    pins = config["input_sha256"]
    for path in (questions, tokenizer_path, ARCHIVE, REPORT, runner):
        assert digest(path) == pins[str(path)], path
    labels = read(questions)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    protocol = read(ROOT / "records/wac_gqa_accuracy_protocol_result.json")
    assert config["checkpoint_revision"] == protocol["checkpoint_revision"] and config["prompt"] == protocol["prompt"]
    excluded_images = set()
    for folder in ("joint_late_clip", "down_code_calibration_panel"):
        source = DATA / folder / "predictions.jsonl"
        assert digest(source) == pins[str(source)]
        excluded_images.update(labels[row["questionId"]]["imageId"] for row in records(source))

    def correct(row, key):
        assert row["questionId"] == key and row["skipped_channels"] > 0
        tokens = row["tokens"]
        budget = protocol["decoder_max_new_tokens"]
        assert 1 <= len(tokens) <= budget and (tokens[-1] == 2 or len(tokens) == budget)
        assert all(type(token) is int and tokenizer.id_to_token(token) is not None for token in tokens)
        response = tokenizer.decode(tokens, skip_special_tokens=True).strip().rstrip(".").lower()
        assert response == row["prediction"]
        return response == labels[key]["answer"]

    counts = {mode: Counter() for mode in MODES}
    cost = Counter()
    largest = Counter()
    images = set()
    seen = []
    for key, row in zip(config["questions"], records(predictions), strict=True):
        assert key == row["questionId"] and key not in seen
        seen.append(key)
        image = labels[key]["imageId"]
        assert image not in images and image not in excluded_images
        images.add(image)
        baseline = row["baseline"]
        assert {name: baseline[name] for name in archived[key]} == archived[key]
        assert row["candidates"].keys() == counts.keys()
        reference = correct(baseline, key)
        for mode, candidate in row["candidates"].items():
            result = correct(candidate, key)
            counts[mode].update(control=int(reference), refined=int(result),
                                gained=int(result and not reference), lost=int(reference and not result),
                                first_token_changed=int(baseline["tokens"][0] != candidate["tokens"][0]))
            cost[mode] += candidate["extra_rows"]
            largest[mode] = max(largest[mode], candidate["maximum_aligned_sum"])

    assert len(seen) == len(images) == receipt["questions"] == receipt["baseline_outputs_reproduced"] == 67
    assert counts == receipt["comparisons"] and cost == receipt["additional_signed8_dot_rows"]
    assert largest == receipt["largest_absolute_aligned_sum"]
    matrix_bytes = len(config["refined_prefill_layers"]) * 2048 * 5632
    assert receipt["extra_weight_code_bytes"] == {"exact_gated": 0, "weight_plane": matrix_bytes}
    for value in range(-32768, 32768):
        low = (value + 128) % 256 - 128
        upper = (value - low) // 256
        high = min(127, upper)
        carry = upper - high
        assert -128 <= low <= 127 and -128 <= high <= 127 and carry in (0, 1)
        assert low + 256 * (high + carry) == value

    summary = {}
    for mode, counts_by_mode in counts.items():
        discordant = counts_by_mode["gained"] + counts_by_mode["lost"]
        probability = sum(comb(discordant, k) for k in range(1 + min(counts_by_mode["gained"], counts_by_mode["lost"])))
        summary[mode] = dict(counts_by_mode) | {
            "net_change_percentage_points": 100 * (counts_by_mode["refined"] - counts_by_mode["control"]) / len(seen),
            "paired_exact_two_sided_p_value": min(1, 2 * probability / 2**discordant),
        }
    return {
        "state": "late_down_precision_host_panel_independently_rescored",
        "questions": len(seen), "distinct_held_out_images": len(images),
        "baseline_outputs_reproduced": len(seen),
        "late_prefill_layers": config["refined_prefill_layers"],
        "verified_signed16_input_codes": 65536,
        "paired_results": summary,
        "additional_signed8_dot_rows": dict(cost),
        "extra_weight_code_bytes": receipt["extra_weight_code_bytes"],
        "device": receipt["device"], "peak_device_bytes": receipt["peak_device_bytes"],
        "scope": "Paired software evaluation on one question per held-out image. Both variants retain the "
                 "archived pruning policy. Counts measure activity in this panel. Published dataset "
                 "protocol, full-benchmark improvement and mapped hardware execution remain unverified.",
        "evidence_sha256": {str(path.relative_to(ROOT)): digest(path) for path in
                            (receipt_path, config_path, predictions, REPORT, questions, tokenizer_path,
                             runner, Path(__file__).resolve())},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=lambda name: Path(name).resolve())
    args = parser.parse_args()
    assert Path.cwd() == ROOT and not Path("/.dockerenv").exists() and __debug__
    print(json.dumps(verify(args.work), indent=2, sort_keys=True))
