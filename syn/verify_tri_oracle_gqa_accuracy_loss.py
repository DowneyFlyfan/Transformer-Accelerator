"""Rescore frozen GQA results on the host, preserving paired questions and images."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_CEILING
from hashlib import file_digest
import json
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".cache/model_reference/gqa_testdev"
FULL = {
    "dense": "dense_reference",
    "pruned": "pruned_reference",
    "down_scale": "down_scale_full",
}
ABLATIONS = (
    "dense_float32",
    "token_merging",
    "streaming_heads",
    "integer_feedforward",
    "weight_skipping",
)


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def jsonl(path):
    rows = {}
    with path.open() as stream:
        for line in stream:
            row = json.loads(line)
            key = row["questionId"]
            assert key not in rows
            rows[key] = row
    return rows


def matched(row, gold, tokenizer, budget):
    tokens = row["tokens"]
    assert 1 <= len(tokens) <= budget and (tokens[-1] == 2 or len(tokens) == budget)
    assert all(
        type(token) is int and tokenizer.id_to_token(token) is not None
        for token in tokens
    )
    response = (
        tokenizer.decode(tokens, skip_special_tokens=True).strip().rstrip(".").lower()
    )
    assert response == row["prediction"]
    return response == gold


def delta_pair(before, after):
    assert before.keys() == after.keys()
    lost = sum(before[key] and not after[key] for key in before)
    gained = sum(after[key] and not before[key] for key in before)
    return dict(lost=lost, gained=gained, net_correct=gained - lost)


def main():
    assert __debug__ and not Path("/.dockerenv").exists()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DATA / "accuracy_loss_audit_host.json")
    args = parser.parse_args()
    protocol_path = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
    proof_path = ROOT / "records/wac_gqa_frozen_down_scale_result.json"
    targets_path = ROOT / "records/paper_result_targets.json"
    protocol, proof, targets = map(read, (protocol_path, proof_path, targets_path))
    labels_path, tokenizer_path = (
        DATA / "testdev_balanced_questions.json",
        DATA.parent / "tiny_llava_v1/tokenizer.json",
    )
    inputs = {}

    def pin(path, expected=None):
        actual = sha(path)
        assert expected is None or expected == actual, path
        inputs[str(path.relative_to(ROOT))] = actual

    for path in (protocol_path, proof_path, Path(__file__).resolve()):
        pin(path)
    for path in (labels_path, tokenizer_path, targets_path, ROOT / targets["source"]):
        pin(path, protocol["input_sha256"][str(path)])
    labels = read(labels_path)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    assert len(labels) == protocol["questions"] == 12578 and all(
        row["isBalanced"] for row in labels.values()
    )
    types = Counter(row["types"]["structural"] for row in labels.values())
    counts = Counter(row["imageId"] for row in labels.values())
    assert len(counts) == 398
    scores = {}
    budget = protocol["decoder_max_new_tokens"]
    for name, folder in FULL.items():
        pred, receipt, manifest = (
            DATA / folder / key
            for key in ("predictions.jsonl", "receipt.json", "inputs.json")
        )
        for path in (pred, receipt, manifest):
            pin(path, proof["input_sha256"][str(path)])
        rows = jsonl(pred)
        assert rows.keys() == labels.keys()
        native = read(manifest)
        assert native["prompt"] == protocol["prompt"]
        assert (
            native.get("checkpoint_revision", native.get("revision"))
            == protocol["checkpoint_revision"]
        )
        scores[name] = {
            key: matched(row, labels[key]["answer"], tokenizer, budget)
            for key, row in rows.items()
        }
        assert sum(scores[name].values()) == read(receipt)["exact_matches"]
    assert {name: sum(values.values()) for name, values in scores.items()} == dict(
        dense=7163, pruned=5975, down_scale=5960
    )
    dense_by_type = defaultdict(int)
    pruned_by_type = defaultdict(int)
    lost_by_type = Counter()
    gained_by_type = Counter()
    change_by_image = defaultdict(int)
    calibration_change_by_image = defaultdict(int)
    for key, label in labels.items():
        group = label["types"]["structural"]
        d, p, c = (scores[name][key] for name in FULL)
        dense_by_type[group] += d
        pruned_by_type[group] += p
        lost_by_type[group] += d and not p
        gained_by_type[group] += p and not d
        change_by_image[label["imageId"]] += p - d
        calibration_change_by_image[label["imageId"]] += c - p
    by_type = {
        key: dict(
            questions=types[key],
            dense_correct=dense_by_type[key],
            pruned_correct=pruned_by_type[key],
            pruned_loss=lost_by_type[key],
            pruned_gain=gained_by_type[key],
        )
        for key in sorted(types)
    }
    full_delta = delta_pair(scores["dense"], scores["pruned"])
    assert (
        sum(gained_by_type.values()) == full_delta["gained"]
        and sum(lost_by_type.values()) == full_delta["lost"]
    )
    image_ids = sorted(counts)
    draws = np.random.default_rng(20261114).multinomial(
        len(image_ids), [1 / len(image_ids)] * len(image_ids), size=4096
    )
    sampled_questions = draws @ np.array([counts[i] for i in image_ids])

    def interval(values):
        samples = (
            100 * (draws @ np.array([values[i] for i in image_ids])) / sampled_questions
        )
        return [round(float(v), 3) for v in np.quantile(samples, [0.025, 0.975])]

    ablation_path = DATA / "paired_ablation"
    ablation_receipt_path = ablation_path / "independent_receipt.json"
    ablation_receipt = read(ablation_receipt_path)
    ablation_pred = ablation_path / "predictions.jsonl"
    pin(ablation_receipt_path)
    pin(ablation_pred, ablation_receipt["evidence_sha256"][str(ablation_pred)])
    rows = jsonl(ablation_pred)
    assert len(rows) == 160 and rows.keys() <= labels.keys()
    stages = {
        name: {
            key: matched(row["modes"][name], labels[key]["answer"], tokenizer, budget)
            for key, row in rows.items()
        }
        for name in ABLATIONS
    }
    attained = {name: sum(cases.values()) for name, cases in stages.items()}
    assert attained == ablation_receipt["matches"]
    transitions = {
        stage: delta_pair(stages[previous], stages[stage])
        for previous, stage in zip(ABLATIONS, ABLATIONS[1:])
    }
    assert all(
        {k: v for k, v in measure.items() if k != "net_correct"}
        == ablation_receipt["transitions"][stage]
        for stage, measure in transitions.items()
    )
    reference = Decimal(
        str(targets["accuracy_and_energy"]["TinyLLaVA-v1"]["GQA"]["accuracy"])
    )
    needed = (Decimal(len(labels)) * reference / 100).to_integral_value(
        rounding=ROUND_CEILING
    )
    assert int(needed) - 5975 == 948
    result = dict(
        state="paired_gqa_accuracy_loss_by_structure_and_component_rechecked",
        questions=len(labels),
        images=len(counts),
        checkpoint_revision=protocol["checkpoint_revision"],
        full_pruned_minus_dense=full_delta,
        full_down_scale_minus_pruned=delta_pair(scores["pruned"], scores["down_scale"]),
        image_cluster_bootstrap_replicates=4096,
        image_cluster_interval_level=0.95,
        pruned_minus_dense_interval_percentage_points=interval(change_by_image),
        down_scale_minus_pruned_interval_percentage_points=interval(
            calibration_change_by_image
        ),
        by_question_type=by_type,
        controlled_ablation_counts=attained,
        controlled_ablation_transitions=transitions,
        extra_correct_needed_to_reach_reported_score_on_local_split=int(needed) - 5975,
        scope="Local software comparisons on balanced GQA Test-Dev. The full runs pair every identical question and use image-cluster resampling. The component ablation covers a separate 160-question panel and informs experiment selection. The paper's exact prompts and split and mapped hardware accuracy remain unverified.",
        input_sha256=inputs,
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "input_sha256"},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
