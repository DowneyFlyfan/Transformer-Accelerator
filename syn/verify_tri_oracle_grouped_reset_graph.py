"""Compare normalized, sorted native graphs after checking each reset tree."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

import run_tri_oracle_grouped_reset as reset
from tri_oracle_artifact_fingerprint import artifact_fingerprint


RECIPE = reset.ROOT / "syn/tri_oracle_grouped_reset_net_graph.tcl"


def graph_stats(folder, mode):
    metrics = re.findall(
        rf"(?m)^RESET_GRAPH_COMPLETE {mode} (\d+) (\d+) (\d+)$",
        (folder / "console.log").read_text(),
    )
    assert len(metrics) == 1, mode
    count, removed, loads = map(int, metrics[0])
    assert count > 4_000_000 and removed == {"original": 5, "buffered": 3875}[mode] and loads == 92420
    return dict(nets=count, ignored_reset_nets=removed, reset_loads=loads,
                sha256=reset.sha(folder / "graph.tsv"))


def compare(original, buffered):
    before = graph_stats(original, "original")
    after = graph_stats(buffered, "buffered")
    assert before["nets"] == after["nets"], (before, after)
    assert before["sha256"] == after["sha256"], (before, after)
    subprocess.run(["cmp", str(original / "graph.tsv"), str(buffered / "graph.tsv")], check=True)
    return dict(original=before, buffered=after)


def run(placement, trial, plan, output):
    assert __debug__ and Path("/.dockerenv").is_file()
    assert output.is_relative_to(reset.ROOT / ".cache") and shutil.disk_usage(output.parent).free >= 7 * reset.GIB
    baseline = json.loads((placement / "receipt.json").read_text())
    assert baseline["state"] == "concurrent_chip_placed_and_cold_verified"
    repaired = json.loads((trial / "receipt.json").read_text())
    assert repaired["state"] == "native_grouped_reset_trial_placed_and_cold_connectivity_checked"
    planned = json.loads(plan.with_suffix(".json").read_text())
    assert planned["state"] == "placed_grouped_reset_trees_planned_and_pin_loads_checked"
    assert planned["placed_netlist_sha256"] == repaired["original_netlist_sha256"] == reset.sha(placement / "place/placed.v")
    for filename in ("apply/trial.v", "cold/reset_tree.tsv", "cold/console.log"):
        path = trial / filename
        assert reset.sha(path) == repaired["evidence_sha256"][str(path.relative_to(reset.ROOT))]
    output.mkdir()
    reset.RECIPE = RECIPE
    stats = {}
    for mode, checkpoint in (("original", placement / "place/placed.db"),
                             ("buffered", trial / "apply/trial.db")):
        fingerprint = artifact_fingerprint(checkpoint)
        if mode == "original":
            assert fingerprint == baseline["placed_database"]
        for group in range(5):
            path = plan / f"grouped_{group}.tsv"
            assert reset.sha(path) == planned["evidence_sha256"][str(path.relative_to(reset.ROOT))]
        folder = output / mode
        stats[mode] = reset.native(folder, mode, checkpoint, plan)
        assert artifact_fingerprint(checkpoint) == fingerprint
        graph = folder / "graph.tsv"
        subprocess.run(
            ["sort", "-S", "256M", "-T", str(folder), "-o", str(graph), str(graph)],
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"}, check=True,
        )
    result = compare(output / "original", output / "buffered")
    with (output / "proof.json").open("x") as stream:
        json.dump(dict(graphs=result, native=stats), stream, indent=2, sort_keys=True)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("placement", "trial", "plan", "output"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    run(**vars(parser.parse_args()))
