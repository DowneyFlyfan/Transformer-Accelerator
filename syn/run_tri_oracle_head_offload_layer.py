"""Verify a real head reassignment through scores, softmax and attention output."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

from prepare_tri_oracle_head_offload_layer import BASELINE, read, sha, verify
from run_tri_oracle_cluster_local_scores import REFERENCE, check, replay, routes
from run_tri_oracle_core_local_scores import CLUSTER_ISSUE

CLASSIFICATION = re.compile(r"HEAD_OFFLOAD_REPLAY_CLASSIFICATION retrieval=2 streaming=1 read_beats_per_head=(\d+)")
ROW = "HEAD_OFFLOAD_ROW head=0 cluster_owner=8 core_owner=8"


def expected(case):
    setup = read(case / "receipt.json")
    assert setup["head_placement"] == "retrieval_streaming_offload" and setup["expected_owner"] == 8
    baseline_path = BASELINE / "xcelium/core_local_score_qualification.json"
    assert setup["input_sha256"][str(baseline_path)] == sha(baseline_path)
    baseline = read(baseline_path)
    return setup, baseline, baseline_path


def check_replay(lines, markers, baseline):
    classifiers = [CLASSIFICATION.fullmatch(line) for line in lines if line.startswith("HEAD_OFFLOAD_REPLAY_CLASSIFICATION ")]
    assert len(classifiers) == 1 and classifiers[0]
    extra_beats = 2 * int(classifiers[0][1])
    assert extra_beats > 0
    markers, measured, target = check(lines, markers, baseline["compared"]["attention_reads"] + extra_beats)
    assert lines.count(ROW) == baseline["compared"]["rows"] == measured["rows"]
    return markers, measured, target


def qualify(case):
    setup, baseline, baseline_path = expected(case)
    folder = case / "xcelium"
    result_path = folder / "receipt.json"
    result = read(result_path)
    assert result["state"] == "mapped_clusters_passed_integrated_attention_fixture" and result["mapped_banks"] == []
    assert result["elaboration"]["native_exit_status"] == result["replay"]["native_exit_status"] == 0
    assert result["census_groups"] == {"cluster": 5, "source_core": 20, "memory": 623}
    console = folder / "positive/console.log"
    log = console.read_text()
    assert sha(console) == result["replay"]["log_sha256"]
    assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
    lines = log.splitlines()
    reference = read(REFERENCE)
    _, measured, _ = check_replay(lines, [reference["reference_ownership_marker"], reference["reference_marker"]], baseline)
    assert measured == result["measured"]
    for label, tiles, keys, commands in (
        ("SCORE_CORE_TOTAL", baseline["single_core_tiles"], baseline["single_core_keys"], baseline["single_core_commands"]),
        ("SCORE_CLUSTER_TOTAL", baseline["single_core_tiles"] + baseline["cluster_tiles"],
         measured["values"], baseline["single_core_commands"] + baseline["cluster_commands"]),
    ):
        totals = [line for line in lines if line.startswith(label + " ")]
        assert len(totals) == 1 and totals[0].endswith(f" tiles={tiles} keys={keys} commands={commands}"), totals
    issue = [CLUSTER_ISSUE.fullmatch(line) for line in lines if line.startswith("SCORE_CORE_ISSUE ")]
    assert len(issue) == 5 and all(issue)
    observed = [tuple(map(int, match.groups())) for match in issue]
    assert sorted(observed) == [(cluster, cluster, baseline["single_core_commands"] if cluster == 2 else 0)
                                for cluster in range(5)]
    routes(lines, (2, 0), measured["rows"], measured["values"])
    inputs = result["input_sha256"].copy()
    assert inputs[str(case / "receipt.json")] == sha(case / "receipt.json")
    inputs.update({str(path): sha(path) for path in (Path(__file__), result_path, console, baseline_path, REFERENCE)})
    verify(inputs)
    evidence = dict(state="dynamic_head_offload_replayed_on_twenty_core_layer",
                    head=0, initial_owner=0, reassigned_owner=8, retrieval_heads=2, streaming_heads=1,
                    compared=measured, additional_classification_read_beats=measured["attention_reads"]-baseline["compared"]["attention_reads"],
                    single_core_commands=baseline["single_core_commands"], cluster_commands=baseline["cluster_commands"],
                    replay_seconds=result["replay"]["elapsed_seconds"], input_sha256=inputs,
                    scope="Source layer with the original vendor unit-delay memory models and local retrieval-count offloading policy.")
    with (folder / "head_offload_qualification.json").open("x") as stream:
        json.dump(evidence, stream, indent=2)
        stream.write("\n")
    print(evidence["state"], measured, flush=True)


def run(case):
    setup, baseline, _ = expected(case)
    verify(setup["input_sha256"])
    replay.check_markers = lambda lines, markers: check_replay(lines, markers, baseline)
    sys.argv = [replay.__file__, str(case), "--shared-memory"]
    try:
        replay.main()
        qualify(case)
    finally:
        snapshot = case / "xcelium/xcelium.d"
        if snapshot.is_dir():
            shutil.rmtree(snapshot)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--qualify", action="store_true", help="Check a completed replay without launching Xcelium.")
    args = parser.parse_args()
    (qualify if args.qualify else run)(args.case.resolve())
