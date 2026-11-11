"""Check both score-execution modes in the native twenty-core layer replay."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

from run_tri_oracle_cluster_local_scores import REFERENCE, ROOT, check, read, replay, routes, sha, verify

BASELINE = ROOT / ".cache/physical/wac_cluster_local_scores/xcelium/cluster_local_score_qualification.json"
CLUSTER_ISSUE = re.compile(
    r"SCORE_CORE_ISSUE .*\.clusters\[([0-4])\]\.unit\.selected_bank([0-4])\.block_instance"
    r"\.source_cluster\.implementation\.score_issue_probe commands=(\d+)"
)


def expected(case):
    setup_path = case / "receipt.json"
    setup = read(setup_path)
    assert setup["score_tiles"] == "single_core_or_head_cluster" and setup["exercised_head"] == 19
    assert setup["input_sha256"][str(BASELINE)] == sha(BASELINE)
    baseline = read(BASELINE)
    fixture = Path(setup["fixture"]) / "rows.txt"
    assert sha(fixture) == setup["input_sha256"][str(fixture)]
    lengths = [int(line.split()[2]) for line in fixture.read_text().splitlines()[1:]]
    assert len(lengths) == baseline["compared"]["rows"] and sum(lengths) == baseline["score_keys"]
    core_lengths = [length for length in lengths if length <= 32]
    assert core_lengths and len(core_lengths) < len(lengths)
    return setup, baseline, core_lengths


def qualify(case):
    setup, baseline, core_lengths = expected(case)
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
    _, measured, _ = check(lines, [reference["reference_ownership_marker"], reference["reference_marker"]],
                           baseline["compared"]["attention_reads"])
    assert measured == result["measured"]
    core_tiles = len(core_lengths)
    core_commands = 8 * core_tiles
    total_commands = baseline["local_commands"] + 6 * core_tiles
    for label, tiles, keys, commands in (
        ("SCORE_CORE_TOTAL", core_tiles, sum(core_lengths), core_commands),
        ("SCORE_CLUSTER_TOTAL", baseline["score_tiles"], baseline["score_keys"], total_commands),
    ):
        totals = [line for line in lines if line.startswith(label + " ")]
        assert len(totals) == 1 and totals[0].endswith(f" tiles={tiles} keys={keys} commands={commands}"), totals
    issue = [CLUSTER_ISSUE.fullmatch(line) for line in lines if line.startswith("SCORE_CORE_ISSUE ")]
    assert len(issue) == 5 and all(issue)
    observed = [tuple(map(int, match.groups())) for match in issue]
    assert sorted(observed) == [(cluster, cluster, core_commands if cluster == 4 else 0) for cluster in range(5)]
    routes(lines, (4, 3), measured["rows"], baseline["score_keys"])
    inputs = result["input_sha256"].copy()
    assert inputs[str(case / "receipt.json")] == sha(case / "receipt.json")
    inputs.update({str(path): sha(path) for path in (Path(__file__), result_path, console, BASELINE, REFERENCE)})
    verify(inputs)
    evidence = dict(state="single_core_and_cluster_score_execution_replayed",
                    local_capacity_keys=32, single_core_tiles=core_tiles, single_core_keys=sum(core_lengths),
                    single_core_commands=core_commands, cluster_tiles=baseline["score_tiles"]-core_tiles,
                    cluster_commands=total_commands-core_commands, compared=measured,
                    replay_seconds=result["replay"]["elapsed_seconds"], input_sha256=inputs,
                    scope="Source replay with 32-key local-fit policy and original vendor unit-delay memory models.")
    with (folder / "core_local_score_qualification.json").open("x") as stream:
        json.dump(evidence, stream, indent=2)
        stream.write("\n")
    print(evidence["state"], core_tiles, total_commands, measured, flush=True)


def run(case):
    setup, baseline, _ = expected(case)
    verify(setup["input_sha256"])
    replay.check_markers = lambda lines, markers: check(lines, markers, baseline["compared"]["attention_reads"])
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
    parser.add_argument("--qualify", action="store_true")
    args = parser.parse_args()
    (qualify if args.qualify else run)(args.case.resolve())
