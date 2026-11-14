"""Verify all other cold checkpoint connections after grouped_active buffering."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import run_tri_oracle_grouped_reset as native
from tri_oracle_artifact_fingerprint import artifact_fingerprint


ROOT = native.ROOT
RECIPE = ROOT / "syn/tri_oracle_grouped_active_net_graph.tcl"


def verify(parent, candidate, record, plan, output):
    assert __debug__ and Path("/.dockerenv").is_file()
    assert output.is_relative_to(ROOT / ".cache")
    assert shutil.disk_usage(output.parent).free >= 7 * native.GIB
    proof = json.loads(record.read_text())
    assert proof["state"] == "grouped_active_placed_cold_connected_and_pin_loads_verified"
    ledger = candidate.parent / "cold_exact/drivers.tsv"
    for path in (ledger, plan):
        assert native.sha(path) == proof["evidence_sha256"][str(path.relative_to(ROOT))]
    assert native.sha(parent / "trial.v") == proof["parent_netlist_sha256"]
    assert native.sha(candidate / "active.v") == proof["candidate_netlist_sha256"]
    assert native.sha(candidate / "active.def") == proof["placed_design_exchange_sha256"]
    output.mkdir()
    os.environ["TRI_ACTIVE_DRIVER_LEDGER"] = str(ledger)
    native.RECIPE = RECIPE
    results = {}
    checkpoints = {"parent": parent / "trial.db", "candidate": candidate / "active.db"}
    for mode, checkpoint in checkpoints.items():
        folder = output / mode
        fingerprint = artifact_fingerprint(checkpoint)
        stats = native.native(folder, mode, checkpoint, plan)
        assert artifact_fingerprint(checkpoint) == fingerprint
        log = folder / "console.log"
        metrics = re.findall(
            rf"(?m)^GROUPED_ACTIVE_GRAPH_COMPLETE {mode} (\d+) (\d+) (\d+)$", log.read_text()
        )
        count, ignored, sinks = map(int, metrics[0]) if len(metrics) == 1 else (0, 0, 0)
        assert count >= 4_000_000 and ignored == (1 if mode == "parent" else 713) and sinks == 17013
        graph = folder / "graph.tsv"
        subprocess.run(
            ["sort", "-S", "256M", "-T", str(folder), "-o", str(graph), str(graph)],
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"}, check=True,
        )
        digest = native.sha(graph)
        results[mode] = dict(
            **stats, nets=count, ignored_active_nets=ignored, active_loads=sinks,
            graph_sha256=digest, log_sha256=native.sha(log),
        )
        print(f"GROUPED_ACTIVE_GRAPH_SORTED {mode} {count} {digest}", flush=True)
    before, after = results["parent"], results["candidate"]
    assert before["nets"] == after["nets"] and before["graph_sha256"] == after["graph_sha256"]
    subprocess.run(["cmp", str(output / "parent/graph.tsv"), str(output / "candidate/graph.tsv")], check=True)
    receipt = dict(
        state="whole_chip_native_endpoint_graph_preserved_across_grouped_active_buffering",
        parent_netlist_sha256=proof["parent_netlist_sha256"],
        candidate_netlist_sha256=proof["candidate_netlist_sha256"],
        original_loads=17013, inserted_buffers=712, other_nets=before["nets"],
        native=results,
        evidence_sha256={str(path.relative_to(ROOT)): native.sha(path) for path in
                         (record, plan, ledger, RECIPE, Path(__file__).resolve())},
        scope="Cold native signal connectivity, top-level ports and direct pin constants. "
              "The checked noninverting tree replaces only grouped_active. Timing and functional replay are separate checks.",
    )
    with (output / "proof.json").open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print("GROUPED_ACTIVE_GRAPH_EQUIVALENT", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent", "candidate", "record", "plan", "output"):
        parser.add_argument(name, type=lambda path: Path(path).resolve())
    verify(**vars(parser.parse_args()))
