"""Independently score the full late-clipping Graph Question Answering run."""

import argparse
from collections import Counter
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path

from tokenizers import Tokenizer

from verify_tri_oracle_full_down_code_score import image_interval, score, verified_rows
from verify_tri_oracle_gqa_accuracy_loss import DATA, ROOT, delta_pair, jsonl, read, sha


PROTOCOL = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
TARGETS = ROOT / "records/paper_result_targets.json"
BASELINE_EVIDENCE = ROOT / "records/wac_gqa_frozen_down_scale_result.json"
PILOT = ROOT / "records/tri_oracle_joint_late_clipping.json"
WORKLOAD = {"rows", "codes", "active_rows", "saturated_codes",
            "retained_corrections", "skipped_saturated_codes"}


def require(condition, context):
    if not condition:
        raise ValueError(context)


def workload_for(rows):
    totals = Counter()
    for row in rows:
        counters = row["workload"]
        require(set(counters) == WORKLOAD and all(type(v) is int and v >= 0 for v in counters.values()),
                f"Invalid workload counters for {row['questionId']}")
        require(counters["rows"] >= counters["active_rows"] > 0, "Invalid active-row count")
        require(counters["codes"] == counters["rows"] * 5632, "Unexpected feed-forward intermediate width")
        require(counters["saturated_codes"] == counters["retained_corrections"] + counters["skipped_saturated_codes"],
                "Clipped codes do not reconcile")
        totals.update(counters)
    return dict(totals)


def reference_scores(folder, labels, tokenizer, budget, protocol, baseline_hashes):
    inputs, predictions, receipt = (DATA / folder / name
                                   for name in ("inputs.json", "predictions.jsonl", "receipt.json"))
    require(all(sha(path) == baseline_hashes[str(path)] for path in (inputs, predictions, receipt)),
            f"Published baseline changed in {folder}")
    config, state = read(inputs), read(receipt)
    require(config.get("checkpoint_revision", config.get("revision")) == protocol["checkpoint_revision"]
            and config["prompt"] == protocol["prompt"]
            and config.get("decoder_max_new_tokens", config.get("max_new_tokens")) == budget,
            f"Reference does not match protocol in {folder}")
    require(sha(inputs) == state["inputs_sha256"] and sha(predictions) == state["predictions_sha256"],
            f"Raw reference receipt changed in {folder}")
    rows = jsonl(predictions)
    require(rows.keys() == labels.keys(), f"Reference question set changed in {folder}")
    correct = score(rows.values(), labels, tokenizer, budget)
    require(sum(correct.values()) == state["exact_matches"], f"Reference scores differ in {folder}")
    return correct, (inputs, predictions, receipt)


def compare(labels, before, after, complete):
    keys = labels.keys()
    a = {key: before[key] for key in keys}
    b = {key: after[key] for key in keys}
    change = delta_pair(a, b)
    result = dict(
        questions=len(labels), images=len({item["imageId"] for item in labels.values()}),
        baseline_correct=sum(a.values()), corrected=sum(b.values()),
        gained=change["gained"], lost=change["lost"],
    )
    require(result["corrected"] - result["baseline_correct"] == change["net_correct"],
            "Inconsistent paired transitions")
    if complete:
        result["image_bootstrap_95pct_pp"] = image_interval(labels, a, b)
    return result


def accuracy_bounds(correct, answered, total, dense, reported):
    remaining = total - answered
    target_percent = Decimal(str(reported["accuracy"]))
    loss_pp = Decimal(str(reported["reported_accuracy_loss"]))
    dense_percent = Decimal(100 * dense) / total
    prescribed_percent = max(target_percent, dense_percent - loss_pp)

    def threshold(percent):
        return int((Decimal(total) * percent / 100).to_integral_value(rounding=ROUND_CEILING))

    return dict(
        questions_remaining=remaining,
        exact_correct_count_bounds=[correct, correct + remaining],
        absolute_paper_score_percent=float(target_percent),
        minimum_correct_to_reach_absolute_paper_score=threshold(target_percent),
        minimum_correct_to_reach_both_targets_if_loss_is_in_percentage_points=threshold(prescribed_percent),
        dense_local_score_percent=float(dense_percent),
        absolute_paper_score_still_possible=(correct + remaining >= threshold(target_percent)),
        both_targets_still_possible_if_loss_is_in_percentage_points=(
            correct + remaining >= threshold(prescribed_percent)),
    )


def verify(prefix=False):
    require(__debug__ and Path("/.dockerenv").is_file(), "Use the Cadence container with assertions enabled")
    protocol, targets = read(PROTOCOL), read(TARGETS)
    question_file = DATA / "testdev_balanced_questions.json"
    tokenizer_file = DATA.parent / "tiny_llava_v1/tokenizer.json"
    dataset = (question_file, tokenizer_file, DATA / "testdev_balanced_images.parquet")
    paper = ROOT / targets["source"]
    pins = protocol["input_sha256"]
    require(all(sha(path) == pins[str(path)] for path in (*dataset, paper)), "Dataset, tokenizer, or paper changed")
    labels = read(question_file)
    require(len(labels) == protocol["questions"] == 12578 and all(row["isBalanced"] for row in labels.values()),
            "Wrong balanced test-development split")
    require(len({label["imageId"] for label in labels.values()}) == 398, "Wrong benchmark image inventory")
    tokenizer = Tokenizer.from_file(str(tokenizer_file))
    budget = protocol["decoder_max_new_tokens"]
    hashes = read(BASELINE_EVIDENCE)["input_sha256"]
    dense, dense_files = reference_scores("dense_reference", labels, tokenizer, budget, protocol, hashes)
    pruned, pruned_files = reference_scores("pruned_reference", labels, tokenizer, budget, protocol, hashes)
    require((sum(dense.values()), sum(pruned.values())) == (7163, 5975), "Baseline counts changed")

    finished = DATA / "full_joint_late_clip"
    config_file, predictions, receipt_file = (finished / name
                                              for name in ("inputs.json", "predictions.jsonl", "receipt.json"))
    config = read(config_file)
    require(config["checkpoint_revision"] == protocol["checkpoint_revision"] and config["prompt"] == protocol["prompt"]
            and config["maximum_new_tokens"] == budget and config["questions"] == len(labels),
            "Clipping run does not match the independent local protocol")
    require(config["late_layers"] == list(range(17, 22)), "Wrong clipping layer range")
    require(all(config["input_sha256"][str(path)] == pins[str(path)] for path in dataset),
            "Clipping run has a different data input")
    pilot_predictions = DATA / "joint_late_clip/predictions.jsonl"
    pilot_inputs = DATA / "joint_late_clip/inputs.json"
    pilot_record = read(PILOT)
    require(config["input_sha256"][str(PILOT)] == sha(PILOT), "Wrong pilot source")
    require(all(sha(path) == config["input_sha256"][str(path)] == pilot_record["evidence_sha256"][str(path.relative_to(ROOT))]
                for path in (pilot_predictions, pilot_inputs)), "Pilot evidence changed")
    anchors = jsonl(pilot_predictions)
    require(len(anchors) == pilot_record["questions"] == 160 and anchors.keys() <= labels.keys(),
            "Wrong pilot anchor questions")
    excluded_images = {labels[key]["imageId"] for key in anchors}

    rows = verified_rows(predictions, sorted(labels), allow_prefix=prefix)
    candidate = score(rows, labels, tokenizer, budget)
    totals = workload_for(rows)
    active_labels = {key: labels[key] for key in candidate}
    outside = {key: row for key, row in active_labels.items() if row["imageId"] not in excluded_images}
    matched = 0
    for row in rows:
        key = row["questionId"]
        if key in anchors:
            reference = anchors[key]["corrected"]
            require(row["tokens"] == reference["tokens"] and row["skipped_channels"] == reference["skipped"],
                    f"Clipping anchor changed at {key}")
            matched += 1
    comparisons = dict(full=compare(active_labels, pruned, candidate, not prefix),
                       images_disjoint_from_panel=compare(outside, pruned, candidate, not prefix),
                       matched_panel_controls=matched, workload=totals)
    bounds = accuracy_bounds(sum(candidate.values()), len(rows), len(labels), sum(dense.values()),
                             targets["accuracy_and_energy"]["TinyLLaVA-v1"]["GQA"])
    if prefix:
        return dict(state="in_progress_clipping_prefix_independently_scored",
                    **comparisons, final_accuracy_bounds=bounds)
    native = read(receipt_file)
    require(native["state"] == "full_joint_late_clip_completed", "Missing terminal clipping receipt")
    require(native["inputs_sha256"] == sha(config_file) and native["predictions_sha256"] == sha(predictions),
            "Clipping output changed after generation")
    require(matched == len(anchors) and all(native[key] == value for key, value in comparisons.items()),
            "Independent scores, bootstrap bounds, anchors, or workload disagree with the runner")
    require(all(sha(Path(name)) == digest for name, digest in config["input_sha256"].items()),
            "Clipping inputs changed during the run")
    evidence = (config_file, predictions, receipt_file, pilot_inputs, pilot_predictions, PILOT,
                PROTOCOL, TARGETS, BASELINE_EVIDENCE, *dataset, *dense_files, *pruned_files,
                Path(__file__).resolve(), Path(score.__code__.co_filename).resolve(), paper)
    return dict(
        state="full_joint_late_clip_software_accuracy_independently_verified",
        checkpoint_revision=protocol["checkpoint_revision"],
        **comparisons, final_accuracy_bounds=bounds,
        paper_prompt_and_split_confirmed=protocol["paper_prompt_and_split_confirmed"],
        mapped_execution_accuracy_verified=False,
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in evidence},
        scope="Balanced test-development software evaluation with a pinned local prompt and checkpoint. "
              "An image-disjoint comparison excludes the panel that informed clipping. Mapped integer "
              "execution and agreement with the paper's undisclosed prompt and split require separate evidence.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.prefix), indent=2, sort_keys=True))
