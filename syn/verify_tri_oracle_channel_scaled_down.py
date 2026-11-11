"""Independently re-score channel-scaled down projection and verify paired coverage."""

import argparse
from collections import Counter
from decimal import Decimal
from hashlib import file_digest
import json
from pathlib import Path

from score_tri_oracle_format326_vqav2 import load_official_sources, score_cases

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / ".cache/model_reference"
MODES = ("dense_integer", "channel_scaled_down")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def verify(case):
    native_path = case / "native_receipt.json"
    result_path = case / "receipt.json"
    log = case / "console.log"
    native, result = read(native_path), read(result_path)
    assert native["state"] == "native_exit" and native["native_exit_status"] == 0
    assert native["log_sha256"] == sha(log)
    assert result["state"] == "channel_scaled_down_projection_benchmark_scored"
    assert result["questions"] == result["reproduced_dense_integer_cases"] == 256 and result["decoder_layers"] == 22
    pins = result["source_sha256"]
    assert all(sha(Path(name)) == digest for name, digest in pins.items())
    manifest = REFERENCE / "grouped_precision_holdout/manifest.json"
    dense_path = REFERENCE / "dense_integer_holdout/receipt.json"
    diagnostic_path = ROOT / "records/ff_quantization_sources.json"
    assert all(pins[str(path)] == sha(path) for path in (manifest, dense_path, diagnostic_path))
    dense, diagnostic = read(dense_path), read(diagnostic_path)
    assert result["checkpoint_revision"] == dense["checkpoint_revision"] == diagnostic["checkpoint_revision"]
    scales = result["channel_scale_exponent_ranges"]
    assert len(scales) == 22
    assert [min(lo for lo, _ in scales), max(hi for _, hi in scales)] == diagnostic["observed_channel_scale_exponent_range"]
    samples = read(manifest)["samples"]
    questions = [sample["question_id"] for sample in samples]
    lines = log.read_text().splitlines()
    observed = [tuple(map(int, line.split()[1:])) for line in lines if line.startswith("FF_CHANNEL_SCALED_CASE ")]
    assert observed == list(enumerate(questions, 1))
    assert len(set(questions)) == len({sample["image_id"] for sample in samples}) == 256
    answers = result["answers"]
    assert set(answers) == set(MODES)
    for mode, cases in answers.items():
        assert [(row["question_id"], row["image_id"]) for row in cases] == [
            (sample["question_id"], sample["image_id"]) for sample in samples]
        for row in cases:
            expected = 0 if mode == "dense_integer" else row["prefill_rows"] + row["decode_rows"] - 22
            assert row["channel_scaled_rows"] == expected
            assert row["prefill_skipped"] == row["decode_skipped"] == 0
    assert [{key: value for key, value in row.items() if key != "channel_scaled_rows"}
            for row in answers["dense_integer"]] == dense["cases"]
    evaluator, normalizer, scorer = load_official_sources(ROOT)
    assert all(pins[name] == digest for name, digest in scorer.items())
    scores = {mode: score_cases(samples, cases, evaluator, normalizer) for mode, cases in answers.items()}
    for score in scores.values():
        score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert scores == result["scores"] and scores["dense_integer"] == dense["score"]
    percentages = {mode: scores[mode]["official_vqa_consensus_percent"] for mode in MODES}
    baseline, scaled = (scores[mode]["per_question_score"] for mode in MODES)
    assert baseline.keys() == scaled.keys()
    paired = Counter((scaled[key] > value) - (scaled[key] < value) for key, value in baseline.items())
    change = Decimal(str(percentages["channel_scaled_down"])) - Decimal(str(percentages["dense_integer"]))
    paths = (Path(__file__), Path(__file__).with_name("evaluate_tri_oracle_channel_scaled_down.py"),
             native_path, result_path, log, manifest, case / "run_guard.py")
    return dict(state="channel_scaled_down_projection_benchmark_independently_scored", questions=256,
        decoder_layers=22, checkpoint_revision=result["checkpoint_revision"], reproduced_dense_integer_cases=256,
        scores_percent=percentages, change_percentage_points=float(change),
        paired_question_scores=dict(improved=paired[1], declined=paired[-1], unchanged=paired[0]),
        graphics_peak_allocated_bytes=result["graphics_peak_allocated_bytes"], wall_seconds=result["wall_seconds"],
        minimum_host_available_bytes=native["available_min_bytes"],
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in paths},
        scope="Fixed local benchmark. Only later-row down weights and their output scaling differ between modes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    case = parser.parse_args().case.resolve()
    result = verify(case)
    with (case / "verified.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["scores_percent"], result["paired_question_scores"], flush=True)
