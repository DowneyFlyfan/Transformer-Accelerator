"""Run the upstream LLaVA converter and GQA Test-Dev evaluator on archived tokens."""

from collections import Counter
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from tokenizers import Tokenizer

from check_tri_oracle_paper300_gate import PAPER_RELATIVE, PAPER_SHA256
from verify_tri_oracle_gqa_accuracy_loss import DATA, ROOT, jsonl, read, sha


UPSTREAM = DATA / "official_scorer"
PROTOCOL = ROOT / "records/wac_gqa_accuracy_protocol_result.json"
TARGETS = ROOT / "records/paper_result_targets.json"
CONVERTER = "https://raw.githubusercontent.com/haotian-liu/LLaVA/ce1aa08d129bd7df931a7067bcb79cf3cb3a1af5/scripts/convert_gqa_for_eval.py"
EVALUATOR = "https://gist.githubusercontent.com/haotian-liu/db6eddc2a984b4cbcc8a7f26fd523187/raw/1ac7a1aab0c631845c645722082789977850ace0/1_eval.py"
CONVERTER_SHA256 = "016cea68c91cbc141c276e9e7568420e2f5db5aba90c4f594701663c72929932"
EVALUATOR_SHA256 = "787ca40d8c06d09e4e4a053259f84a4ca3ca431a6fdd8d6fb3003109f013fbdf"
RUNS = {
    "dense_reference": "gqa_testdev_dense_reference_result",
    "pruned_reference": "wac_gqa_frozen_down_scale_result",
    "down_scale_full": "wac_gqa_frozen_down_scale_result",
    "full_down_code": "tri_oracle_full_down_code_accuracy",
    "full_joint_late_clip": "tri_oracle_full_joint_late_clip_accuracy",
    "full_calibrated_clip": "tri_oracle_full_calibrated_clipped_accuracy",
}


def prediction_hash(record, path):
    hashes = record.get("evidence_sha256", record.get("input_sha256"))
    for name in (str(path), str(path.relative_to(ROOT))):
        if name in hashes:
            return hashes[name]
    assert path.parent.name == "full_down_code"
    receipt = path.with_name("receipt.json")
    short = str(receipt.relative_to(ROOT))
    assert hashes.get(str(receipt), hashes.get(short)) == sha(receipt)
    return read(receipt)["predictions_sha256"]


def convert_and_score(questions, labels, tokenizer, rows, token_limit, converter, evaluator):
    with TemporaryDirectory(dir=UPSTREAM, prefix="evaluation_") as directory:
        text_file = Path(directory) / "decoded.jsonl"
        converted_file = Path(directory) / "submission.json"
        with text_file.open("w") as stream:
            for key, row in rows.items():
                tokens = row["tokens"]
                assert 1 <= len(tokens) <= token_limit and (tokens[-1] == 2 or len(tokens) == token_limit)
                assert all(type(token) is int and tokenizer.id_to_token(token) is not None for token in tokens)
                # The upstream model evaluation strips outer whitespace before writing its answer file.
                decoded = tokenizer.decode(tokens, skip_special_tokens=True).strip()
                assert decoded.rstrip(".").lower() == row["prediction"], key
                stream.write(json.dumps({"question_id": key, "text": decoded}) + "\n")
        subprocess.run([sys.executable, str(converter), "--src", str(text_file), "--dst", str(converted_file)],
                       cwd=ROOT, check=True, timeout=30)
        submission = read(converted_file)
        correct = 0
        for (key, row), item in zip(rows.items(), submission, strict=True):
            assert item == {"questionId": key, "prediction": row["prediction"]}
            correct += item["prediction"] == labels[key]["answer"]
        native = subprocess.run([sys.executable, str(evaluator), "--tier", "testdev", "--questions", str(questions),
                                 "--predictions", str(converted_file)], cwd=ROOT, check=True,
                                capture_output=True, text=True, timeout=30)
        score = re.search(r"(?m)^Accuracy: (\d+\.\d+)%$", native.stdout)[1]
    percent = Decimal(100 * correct) / len(rows)
    assert f"{percent:.2f}" == score
    return {"exact_matches": correct, "evaluator_display_percent": score, "accuracy_percent": float(percent)}


def verify():
    evidence = {}

    def pin(path, expected=None):
        actual = sha(path)
        assert expected is None or actual == expected, path
        assert evidence.setdefault(str(path.relative_to(ROOT)), actual) == actual
        return path

    protocol, targets = (read(pin(path)) for path in (PROTOCOL, TARGETS))
    pin(ROOT / PAPER_RELATIVE, PAPER_SHA256)
    converter = pin(UPSTREAM / "convert.py", CONVERTER_SHA256)
    evaluator = pin(UPSTREAM / "testdev_eval.py", EVALUATOR_SHA256)
    questions = DATA / "testdev_balanced_questions.json"
    vocabulary = DATA.parent / "tiny_llava_v1/tokenizer.json"
    for path in (questions, vocabulary):
        pin(path, protocol["input_sha256"][str(path)])
    labels = read(questions)
    tokenizer = Tokenizer.from_file(str(vocabulary))
    assert len(labels) == protocol["questions"] == 12578 and all(row["isBalanced"] is True for row in labels.values())
    images = Counter(row["imageId"] for row in labels.values())
    assert len(images) == protocol["images"] == 398

    results = {}
    for run, name in RUNS.items():
        receipt = ROOT / "records" / f"{name}.json"
        proof = read(pin(receipt))
        path = DATA / run / "predictions.jsonl"
        manifest = pin(path.with_name("inputs.json"))
        config = read(manifest)
        assert config.get("checkpoint_revision", config.get("revision")) == protocol["checkpoint_revision"]
        assert config["prompt"] == protocol["prompt"]
        token_limit = protocol["decoder_max_new_tokens"]
        assert any(config.get(field) == token_limit for field in ("decoder_max_new_tokens", "max_new_tokens", "maximum_new_tokens"))
        rows = jsonl(pin(path, prediction_hash(proof, path)))
        assert rows.keys() == labels.keys()
        results[run] = convert_and_score(questions, labels, tokenizer, rows, token_limit, converter, evaluator)

    paper = targets["accuracy_and_energy"]["TinyLLaVA-v1"]["GQA"]
    absolute, allowed_drop = (Decimal(str(paper[key])) for key in ("accuracy", "reported_accuracy_loss"))
    assert absolute == Decimal(str(protocol["paper_reported_accuracy_percent"]))
    size = len(labels)
    dense = Decimal(100 * results["dense_reference"]["exact_matches"]) / size
    minimum = (max(dense - allowed_drop, absolute) * size / 100).to_integral_value(rounding=ROUND_CEILING)
    alternatives = (name for name in RUNS if name != "dense_reference")
    best_name = max(alternatives, key=lambda name: results[name]["exact_matches"])
    best = results[best_name]
    best_percent = Decimal(100 * best["exact_matches"]) / size
    pin(Path(__file__).resolve())
    return {
        "state": "upstream_gqa_evaluator_rescored_local_full_runs",
        "questions": size, "images": len(images), "checkpoint_revision": protocol["checkpoint_revision"],
        "upstream_converter": CONVERTER, "upstream_evaluator": EVALUATOR,
        "results": results, "best_pruned_run": best_name,
        "paper_accuracy_percent": float(absolute), "paper_accuracy_loss": float(allowed_drop),
        "best_pruned_shortfall_percentage_points": float(absolute - best_percent),
        "best_pruned_loss_against_local_dense_percentage_points": float(dense - best_percent),
        "questions_short_of_both_targets_if_loss_means_percentage_points": int(minimum) - best["exact_matches"],
        "scope": "Exact-match accuracy of the archived software answers on the balanced Test-Dev split. "
                 "The LLaVA converter reproduced each saved prediction from its token IDs and its GQA evaluator "
                 "agreed with the independent exact counts. Tri-Oracle's checkpoint revision, prompt, labeled split "
                 "and execution of the benchmark on the mapped accelerator remain unconfirmed.",
        "evidence_sha256": evidence,
    }


if __name__ == "__main__":
    assert __debug__ and Path.cwd() == ROOT and not Path("/.dockerenv").is_file()
    print(json.dumps(verify(), indent=2, sort_keys=True))
