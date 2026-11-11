"""Verify that the integrated attention replay used only the owning core's softmax."""

import argparse
import json
from pathlib import Path
import re

from prepare_tri_oracle_wac_softmax_layer import NATIVE, ROOT, read, sha, verify
from replay_mapped_cluster_fixture import BENCH, census, check_markers, expected_types

PREFIX = f"{BENCH}.dut.feedforward.compute.compute.tensor.fabric"
COUNTER = re.compile(
    rf"WAC_ROW_ROUTE {re.escape(PREFIX)}\.clusters\[([0-4])\]\.unit\.selected_bank([0-4])\.block_instance"
    r"\.source_cluster\.implementation\.cores\[([0-3])\]\.compute\.simd\.row_route_probe"
    r" rows=(\d+) scores=(\d+) probabilities=(\d+)"
)


def routes(lines, owner, row_count, total_keys):
    observed = {}
    for line in lines:
        if not line.startswith("WAC_ROW_ROUTE "):
            continue
        match = COUNTER.fullmatch(line)
        assert match, line
        cluster, selected, core, rows, scores, probabilities = map(int, match.groups())
        assert cluster == selected and (cluster, core) not in observed, line
        observed[cluster, core] = rows, scores, probabilities
    expected = {(cluster, core): (0, 0, 0) for cluster in range(5) for core in range(4)}
    assert owner in expected
    expected[owner] = row_count, total_keys, total_keys
    assert observed == expected, (observed, expected)
    return observed


def qualify(case):
    setup_path = case / "receipt.json"
    native_dir = case / "xcelium"
    run_path = native_dir / "receipt.json"
    setup, run = read(setup_path), read(run_path)
    assert setup["softmax"] == "head_owned_core_input_memory" and setup["exercised_head"] == 19
    assert run["state"] == "mapped_clusters_passed_integrated_attention_fixture" and run["mapped_banks"] == []
    assert setup["memory_models"] == "vendor" and len(set(setup["memory_model_paths"])) == 6
    assert run["elaboration"]["native_exit_status"] == run["replay"]["native_exit_status"] == 0
    inputs = run["input_sha256"].copy()
    verify(inputs)
    assert inputs[str(setup_path)] == sha(setup_path)
    bundle = (case / "bundle.sv").read_text()
    assert all(bundle.count(f'`include "{model}"') == 1 for model in setup["memory_model_paths"])
    assert "tri_oracle_proportional_softmax.sv" not in bundle and "tri_oracle_cluster_softmax_control.sv" not in bundle
    console = native_dir / "positive/console.log"
    log = console.read_text()
    assert sha(console) == run["replay"]["log_sha256"] and not re.search(r"\*[EF],", log)
    assert log.count("Simulation complete via $finish(1)") == 1
    lines = log.splitlines()
    groups, counts = census(lines, expected_types(case, setup), [])
    assert groups == {"cluster": 5, "source_core": 20, "memory": 623}
    reference_path = NATIVE / "cluster_core_abstracts/boundary_replay/preparation.json"
    reference = read(reference_path)
    markers, measured, _ = check_markers(lines, [reference["reference_ownership_marker"], reference["reference_marker"]])
    rows_path = Path(setup["fixture"]) / "rows.txt"
    assert inputs[str(rows_path)] == sha(rows_path)
    lengths = [int(line.split()[2]) for line in rows_path.read_text().splitlines()[1:]]
    assert measured == run["measured"] and (len(lengths), sum(lengths)) == (measured["rows"], measured["values"])
    owner = (4, 3)
    activity = routes(lines, owner, len(lengths), sum(lengths))
    for label, key in (("LOCAL_SIZE_BOUNDARY_READS", "expected_reads"),
                       ("LOCAL_MERGE_BOUNDARY_MAPS", "expected_map_handshakes")):
        observed = sorted([int(value) for value in line.split()[1:]] for line in lines if line.startswith(label + " "))
        assert observed == reference[key]
    wrong = [re.sub(r"\.cores\[([23])\]\.", lambda match: f".cores[{5 - int(match[1])}].", line)
             if line.startswith("WAC_ROW_ROUTE ") and ".clusters[4]." in line else line for line in lines]
    try:
        routes(wrong, owner, len(lengths), sum(lengths))
    except AssertionError:
        pass
    else:
        raise AssertionError("Accepted an incorrect softmax owner")
    capacity = ROOT / "records/native_partitioned_memory_capacity_result.json"
    observed_memory = {name: counts[name] for name in counts if name.startswith(("TS5N28", "TS6N28"))}
    by_master = read(capacity)["capacity_by_vendor_master"]
    assert observed_memory == {name: item["instances"] for name, item in by_master.items()}
    total_bytes = sum(observed_memory[name] * item["bytes_per_instance"] for name, item in by_master.items())
    assert total_bytes == 414416
    inputs.update({str(path): sha(path) for path in (Path(__file__), setup_path, run_path, console, reference_path, capacity)})
    verify(inputs)
    return dict(state="twenty_core_layer_replayed_with_head_owned_softmax", simulator="Cadence Xcelium",
                exercised_head=19, softmax_owner={"cluster": owner[0], "core": owner[1]},
                measured=measured, markers=markers, compiled_memory_instances=623, compiled_memory_bytes=total_bytes,
                softmax_activity={f"{cluster}/{core}": list(counts) for (cluster, core), counts in activity.items()},
                source_core_count=20, replay=run["replay"], input_sha256=inputs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    args = parser.parse_args()
    case = args.case.resolve()
    result = qualify(case)
    with (case / "xcelium/wac_layer_qualification.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(result["state"], result["softmax_owner"], result["measured"])
