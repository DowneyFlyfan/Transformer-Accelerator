"""Re-score the fixed-question first-token and later-token counterfactuals."""

import argparse
from collections import Counter
from decimal import Decimal
from hashlib import file_digest
import json
from pathlib import Path

from score_tri_oracle_format326_vqav2 import load_official_sources, score_cases

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / ".cache/model_reference"
MODES = ("dense_integer", "float_first_token", "float_later_tokens")


def read(path):
    return json.loads(path.read_text())


def sha256(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def verify(case):
    native_path = case / "native_receipt.json"
    outcome_path = case / "receipt.json"
    log = case / "console.log"
    native, outcome = read(native_path), read(outcome_path)
    assert native["state"] == "native_exit" and native["native_exit_status"] == 0
    assert native["log_sha256"] == sha256(log)
    assert outcome["state"] == "feedforward_position_counterfactuals_scored"
    assert outcome["questions"] == outcome["reproduced_dense_integer_cases"] == 256 and outcome["decoder_layers"] == 22
    pins = outcome["source_sha256"].copy()
    assert all(sha256(Path(name)) == digest for name, digest in pins.items())
    manifest = REFERENCE / "grouped_precision_holdout/manifest.json"
    dense_path = REFERENCE / "dense_integer_holdout/receipt.json"
    floating_path = REFERENCE / "attention_precision_holdout/receipt.json"
    assert all(pins[str(path)] == sha256(path) for path in (manifest, dense_path, floating_path))
    samples = read(manifest)["samples"]
    questions = [sample["question_id"] for sample in samples]
    lines = log.read_text().splitlines()
    assert [int(line.split()[-1]) for line in lines if line.startswith("FF_POSITION_CASE ")] == questions
    assert len(set(questions)) == len({sample["image_id"] for sample in samples}) == 256
    cases = outcome["answers"]
    assert set(cases) == set(MODES) and all([row["question_id"] for row in rows] == questions for rows in cases.values())
    dense = read(dense_path)
    assert [{key: value for key, value in row.items() if key != "floating_feedforward_rows"}
            for row in cases["dense_integer"]] == dense["cases"]
    for mode, rows in cases.items():
        for row in rows:
            expected = {"dense_integer": 0, "float_first_token": 22,
                        "float_later_tokens": row["prefill_rows"] + row["decode_rows"] - 22}
            assert row["floating_feedforward_rows"] == expected[mode]
            assert row["prefill_skipped"] == row["decode_skipped"] == 0
    cases["floating_reference"] = read(floating_path)["cases"]["compact_and_streaming"]
    evaluator, normalizer, scorer = load_official_sources(ROOT)
    assert all(pins[name] == digest for name, digest in scorer.items())
    scores = {mode: score_cases(samples, rows, evaluator, normalizer) for mode, rows in cases.items()}
    for score in scores.values():
        score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert scores == outcome["scores"]
    percentages = {mode: score["official_vqa_consensus_percent"] for mode, score in scores.items()}
    before = scores["dense_integer"]["per_question_score"]
    for mode in MODES[1:]:
        after = scores[mode]["per_question_score"]
        assert before.keys() == after.keys()
        paired = Counter((after[key] > value) - (after[key] < value) for key, value in before.items())
        assert outcome["paired_changes"][mode] == dict(improved=paired[1], declined=paired[-1], unchanged=paired[0])
    delta = {mode: float(Decimal(str(percentages[mode])) - Decimal(str(percentages["dense_integer"]))) for mode in MODES[1:]}
    paths = (Path(__file__), native_path, outcome_path, log, manifest)
    return dict(state="feedforward_position_counterfactuals_independently_scored", questions=256,
        decoder_layers=22, reproduced_dense_integer_cases=256, scores_percent=percentages,
        change_from_dense_percentage_points=delta, paired_changes=outcome["paired_changes"],
        peak_graphics_bytes=outcome["peak_graphics_bytes"], minimum_host_available_bytes=native["available_min_bytes"],
        wall_seconds=outcome["wall_seconds"], evidence_sha256={str(path.relative_to(ROOT)): sha256(path) for path in paths},
        scope="Matched software counterfactuals. Floating overrides identify numerical loss by token position.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    case = args.case.resolve()
    result = verify(case)
    with (case / "verified.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["scores_percent"], result["change_from_dense_percentage_points"], flush=True)
