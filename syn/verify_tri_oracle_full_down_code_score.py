"""Independently rescore the frozen down-code run against its paired control."""

import argparse
from collections import Counter
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

from verify_tri_oracle_gqa_accuracy_loss import DATA, ROOT, delta_pair, matched, read, sha


def verified_rows(path, ordered, *, allow_prefix=False):
    data = path.read_bytes()
    lines = data.splitlines()
    if allow_prefix and not data.endswith(b"\n"):
        lines = lines[:-1]
    assert lines and len(lines) <= len(ordered), path
    if not allow_prefix:
        assert len(lines) == len(ordered) and data.endswith(b"\n"), path
    rows = [json.loads(line) for line in lines]
    assert [row["questionId"] for row in rows] == ordered[:len(rows)], path
    assert all(type(row["skipped_channels"]) is int and row["skipped_channels"] > 0
               for row in rows), path
    return rows


def score(rows, labels, tokenizer, budget):
    return {row["questionId"]: matched(row, labels[row["questionId"]]["answer"], tokenizer, budget)
            for row in rows}


def image_interval(labels, before, after):
    """Resample whole images because questions sharing an image are dependent."""
    assert before.keys() == after.keys() == labels.keys()
    sizes = Counter(label["imageId"] for label in labels.values())
    net = Counter()
    for key, label in labels.items():
        net[label["imageId"]] += int(after[key]) - int(before[key])
    images = sorted(sizes)
    draws = np.random.default_rng(20261115).multinomial(
        len(images), np.full(len(images), 1 / len(images)), size=4096
    )
    denominators = draws @ np.array([sizes[image] for image in images])
    deltas = 100 * (draws @ np.array([net[image] for image in images])) / denominators
    return [float(value) for value in np.quantile(deltas, (0.025, 0.975))]


def verify(prefix=False):
    assert __debug__ and Path("/.dockerenv").is_file()
    protocol_path = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
    prior = ROOT / "records/wac_gqa_frozen_down_scale_result.json"
    paper_path = ROOT / "records/paper_result_targets.json"
    protocol, targets = read(protocol_path), read(paper_path)
    labels_path = DATA / "testdev_balanced_questions.json"
    tokenizer_path = DATA.parent / "tiny_llava_v1/tokenizer.json"
    paths = [labels_path, tokenizer_path, ROOT / targets["source"]]
    assert all(sha(path) == protocol["input_sha256"][str(path)] for path in paths)
    labels = read(labels_path)
    assert len(labels) == protocol["questions"] == 12578
    assert all(label["isBalanced"] is True for label in labels.values())
    assert len({row["imageId"] for row in labels.values()}) == protocol["images"] == 398
    ordered = sorted(labels)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    budget = protocol["decoder_max_new_tokens"]
    reference, candidate = DATA / "pruned_reference", DATA / "full_down_code"
    old_manifest, old_predictions, old_receipt = (reference / name for name in
        ("inputs.json", "predictions.jsonl", "receipt.json"))
    old_pins = read(prior)["input_sha256"]
    assert all(sha(path) == old_pins[str(path)] for path in (old_manifest, old_predictions, old_receipt))
    new_manifest, new_predictions, new_receipt = (candidate / path.name for path in
        (old_manifest, old_predictions, old_receipt))
    a, b = read(old_manifest), read(new_manifest)
    assert a["checkpoint_revision"] == b["checkpoint_revision"] == protocol["checkpoint_revision"]
    assert a["prompt"] == b["prompt"] == protocol["prompt"]
    assert a["decoder_max_new_tokens"] == b["maximum_new_tokens"] == budget
    assert b["questions"] == len(labels)
    for path in (labels_path, tokenizer_path, DATA / "testdev_balanced_images.parquet"):
        assert a["input_sha256"][str(path)] == b["input_sha256"][str(path)] == protocol["input_sha256"][str(path)]
    original = verified_rows(old_predictions, ordered)
    old_scores = score(original, labels, tokenizer, budget)
    assert sum(old_scores.values()) == read(old_receipt)["exact_matches"] == 5975
    current = verified_rows(new_predictions, ordered, allow_prefix=prefix)
    new_scores = score(current, labels, tokenizer, budget)
    before = {key: old_scores[key] for key in new_scores}
    changes = delta_pair(before, new_scores)
    paired = dict(baseline=sum(before.values()), calibrated=sum(new_scores.values()),
                  gained=changes["gained"], lost=changes["lost"],
                  changed=sum(old["prediction"] != new["prediction"] for old, new in zip(original, current)))
    if prefix:
        return dict(state="in_progress_prefix_rescored", questions=len(current),
                    first_question=ordered[0], last_question=ordered[len(current)-1], paired_counts=paired)

    native = read(new_receipt)
    assert native["state"] == "full_balanced_testdev_bounded_down_codes_completed"
    assert native["questions"] == len(labels) and paired == native["paired_counts"]
    assert sha(new_manifest) == native["inputs_sha256"] and sha(new_predictions) == native["predictions_sha256"]
    assert all(sha(Path(name)) == expected for name, expected in b["input_sha256"].items())
    accuracy = 100 * paired["calibrated"] / len(labels)
    assert accuracy == native["accuracy_percent"]
    paper = Decimal(str(targets["accuracy_and_energy"]["TinyLLaVA-v1"]["GQA"]["accuracy"]))
    required = int((paper * len(labels) / 100).to_integral_value(rounding=ROUND_CEILING))
    evidence = (*paths, protocol_path, prior, paper_path, old_manifest, old_predictions, old_receipt,
                new_manifest, new_predictions, new_receipt, Path(__file__).resolve())
    return dict(state="paired_full_down_code_software_accuracy_independently_rescored",
                questions=len(labels), images=protocol["images"], paired_counts=paired,
                accuracy_percent=accuracy, paper_accuracy_percent=float(paper),
                additional_correct_to_reach_paper_score_on_local_split=max(0, required-paired["calibrated"]),
                image_cluster_interval_percentage_points=image_interval(labels, before, new_scores),
                image_cluster_bootstrap_replicates=4096,
                scope="Software accuracy under the pinned local balanced test split and prompt. "
                      "The paper's exact evaluation protocol and mapped hardware accuracy remain unverified.",
                evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in evidence})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(prefix=args.prefix), indent=2, sort_keys=True))
