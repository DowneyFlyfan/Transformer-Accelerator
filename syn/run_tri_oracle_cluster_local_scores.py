"""Replay the complete layer and check cluster-local attention score execution."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

from prepare_tri_oracle_wac_softmax_layer import NATIVE, ROOT, read, sha, verify
from verify_tri_oracle_wac_softmax_layer import routes
import replay_mapped_cluster_fixture as replay

BASELINE = ROOT / ".cache/physical/wac_layer_owned19/xcelium/wac_layer_qualification.json"
REFERENCE = NATIVE / "cluster_core_abstracts/boundary_replay/preparation.json"
CHECK_MARKERS = replay.check_markers


def expected(case):
    setup = read(case / "receipt.json")
    assert setup["score_tiles"] == "one_head_cluster" and setup["exercised_head"] == 19
    fixture = Path(setup["fixture"]) / "rows.txt"
    assert sha(fixture) == setup["input_sha256"][str(fixture)]
    lengths = [int(line.split()[2]) for line in fixture.read_text().splitlines()[1:]]
    assert len(lengths) == 4 and sum(lengths) == 1023
    old_tiles = sum((length + 159) // 160 for length in lengths)
    new_tiles = sum((length + 31) // 32 for length in lengths)
    # The fixture counts eight-byte beats. Each added tile reloads the
    # 64-byte query, one two-beat request for each of the four cores.
    added_reads = 8 * (new_tiles - old_tiles)
    old = read(BASELINE)["measured"]
    assert old["rows"] == len(lengths) and old["values"] == sum(lengths)
    return setup, new_tiles, sum(lengths), old["attention_reads"] + added_reads


def check(lines, markers, reads):
    owner, summary = markers
    adjusted = re.sub(r"\battention_reads=\d+\b", f"attention_reads={reads}", summary)
    return CHECK_MARKERS(lines, [owner, adjusted])


def qualify(case):
    setup, tiles, keys, reads = expected(case)
    folder = case / "xcelium"
    build_path = folder / "elaborate/native_receipt.json"
    run_path = folder / "positive/native_receipt.json"
    build, result = read(build_path), read(run_path)
    assert build["native_exit_status"] == result["native_exit_status"] == 0
    assert build["state"] == result["state"] == "native_exit"
    build_console, console = (path.with_name("console.log") for path in (build_path, run_path))
    assert sha(build_console) == build["log_sha256"] and sha(console) == result["log_sha256"]
    hierarchy = folder / "hierarchy.sv"
    build_text = build_console.read_text()
    assert all(text in build_text for text in (str(case / "bundle.sv"), str(hierarchy), "Writing initial simulation snapshot:"))
    log = console.read_text()
    assert log.count("Simulation complete via $finish(1)") == 1 and not re.search(r"\*[EF],", log)
    lines = log.splitlines()
    groups, _ = replay.census(lines, replay.expected_types(case, setup), [])
    assert groups == {"cluster": 5, "source_core": 20, "memory": 623}
    reference = read(REFERENCE)
    _, measured, _ = check(lines, [reference["reference_ownership_marker"], reference["reference_marker"]], reads)
    for label, key in (("LOCAL_SIZE_BOUNDARY_READS", "expected_reads"),
                       ("LOCAL_MERGE_BOUNDARY_MAPS", "expected_map_handshakes")):
        observed = sorted([int(value) for value in line.split()[1:]] for line in lines if line.startswith(label + " "))
        assert observed == reference[key], (key, observed)
    commands = 2 * tiles
    totals = [line for line in lines if line.startswith("SCORE_CLUSTER_TOTAL ")]
    assert len(totals) == 1 and totals[0].endswith(f" tiles={tiles} keys={keys} commands={commands}"), totals
    routes(lines, (4, 3), measured["rows"], keys)
    inputs = setup["input_sha256"].copy()
    inputs.update({str(path): sha(path) for path in (
        Path(__file__), case / "receipt.json", build_path, run_path, hierarchy, build_console, console, BASELINE, REFERENCE,
    )})
    verify(inputs)
    evidence = dict(state="cluster_local_score_execution_replayed_with_core_local_softmax",
                    selected_cluster_zero_based=4, score_tiles=tiles, score_keys=keys, local_commands=commands,
                    compared=measured, replay_seconds=result["elapsed_seconds"], input_sha256=inputs,
                    scope="Twenty-core source replay with one score cluster per head and vendor unit-delay memory models.")
    with (folder / "cluster_local_score_qualification.json").open("x") as stream:
        json.dump(evidence, stream, indent=2)
        stream.write("\n")
    print(evidence["state"], tiles, keys, commands, measured, flush=True)


def run(case):
    setup, _, _, reads = expected(case)
    verify(setup["input_sha256"])
    replay.check_markers = lambda lines, markers: check(lines, markers, reads)
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
