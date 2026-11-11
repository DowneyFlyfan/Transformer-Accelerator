"""Verify the paired pruned benchmark and independently count skipped channels."""

import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from verify_tri_oracle_channel_scaled_down import ROOT, REFERENCE, load_official_sources, read, score_cases, sha

MODES = ("channel_scaled_down", "channel_scaled_down_pruned")
CHANNELS = 5632


def verify(case):
    receipt, native_path, log = (case / name for name in ("receipt.json", "native_receipt.json", "console.log"))
    result, native = read(receipt), read(native_path)
    assert result["state"] == "scaled_down_and_pruned_local_benchmark_scored"
    assert native["state"] == "native_exit" and native["native_exit_status"] == 0 and native["log_sha256"] == sha(log)
    assert result["questions"] == result["reproduced_control_cases"] == 256 and result["decoder_layers"] == 22
    pins = result["source_sha256"]
    assert all(sha(Path(name)) == digest for name, digest in pins.items())
    manifest = REFERENCE / "grouped_precision_holdout/manifest.json"
    prior_path = REFERENCE / "ff_channel_scaled_down_holdout/receipt.json"
    assert all(pins[str(path)] == sha(path) for path in (manifest, prior_path))
    prior, samples = read(prior_path), read(manifest)["samples"]
    assert result["checkpoint_revision"] == prior["checkpoint_revision"]
    order = [(sample["question_id"], sample["image_id"]) for sample in samples]
    assert len(order) == len({item[0] for item in order}) == len({item[1] for item in order}) == 256
    observed = [tuple(map(int, line.split()[1:])) for line in log.read_text().splitlines()
                if line.startswith("FF_SCALED_PRUNE_CASE ")]
    assert observed == [(index, question) for index, (question, _) in enumerate(order, 1)]
    answers = result["answers"]
    assert set(answers) == set(MODES) and answers[MODES[0]] == prior["answers"][MODES[0]]
    work = {}
    for mode, rows in answers.items():
        assert [(row["question_id"], row["image_id"]) for row in rows] == order
        for row in rows:
            assert row["channel_scaled_rows"] == row["prefill_rows"] + row["decode_rows"] - 22
            for phase in ("prefill", "decode"):
                assert row[f"{phase}_skipped"] == (row[f"{phase}_predicted"] if mode == MODES[1] else 0)
                assert 0 <= row[f"{phase}_predicted"] <= CHANNELS * row[f"{phase}_rows"]
    for phase in ("prefill", "decode"):
        rows = sum(row[f"{phase}_rows"] for row in answers[MODES[1]])
        skipped = sum(row[f"{phase}_skipped"] for row in answers[MODES[1]])
        work[phase] = dict(rows=rows, skipped_channels=skipped, channel_opportunities=rows * CHANNELS)
    assert work == result["work"]
    evaluator, normalizer, sources = load_official_sources(ROOT)
    assert all(pins[name] == digest for name, digest in sources.items())
    scores = {mode: score_cases(samples, rows, evaluator, normalizer) for mode, rows in answers.items()}
    for score in scores.values():
        score["official_vqa_consensus_percent"] = score.pop("official_vqa_consensus_percent_on64")
    assert scores == result["scores"] and scores[MODES[0]] == prior["scores"][MODES[0]]
    baseline, pruned = (scores[mode]["per_question_score"] for mode in MODES)
    assert baseline.keys() == pruned.keys()
    paired = Counter((pruned[key] > value) - (pruned[key] < value) for key, value in baseline.items())
    percents = {mode: scores[mode]["official_vqa_consensus_percent"] for mode in MODES}
    delta = Decimal(str(percents[MODES[1]])) - Decimal(str(percents[MODES[0]]))
    assert percents == result["scores_percent"] and float(delta) == result["change_percentage_points"]
    assert result["paired_question_scores"] == dict(improved=paired[1], declined=paired[-1], unchanged=paired[0])
    evidence = (Path(__file__), Path(__file__).with_name("evaluate_tri_oracle_channel_scaled_pruning.py"),
                receipt, native_path, log, manifest, case / "run_guard.py")
    return dict(state="scaled_down_and_pruned_local_benchmark_independently_scored", questions=256,
        reproduced_control_cases=256, decoder_layers=22, checkpoint_revision=result["checkpoint_revision"],
        scores_percent=percents, change_percentage_points=float(delta), paired_question_scores=result["paired_question_scores"],
        work=work, skipped_fraction={phase: item["skipped_channels"] / item["channel_opportunities"] for phase, item in work.items()},
        wall_seconds=result["wall_seconds"], graphics_peak_bytes=result["graphics_peak_bytes"],
        minimum_host_available_bytes=native["available_min_bytes"],
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in evidence}, scope=result["scope"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    case = parser.parse_args().case.resolve()
    result = verify(case)
    with (case / "verified.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["scores_percent"], result["skipped_fraction"], flush=True)
